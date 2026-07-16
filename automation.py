import json
import threading
import time
from datetime import datetime, timedelta, timezone

_connect = None
_handler = None
_started = False


def now():
    return datetime.now(timezone.utc).isoformat()


def configure(connect, handler):
    global _connect, _handler
    _connect, _handler = connect, handler


def initialise(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS workflow_config (
        step TEXT PRIMARY KEY, label TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        max_attempts INTEGER NOT NULL DEFAULT 4, settings TEXT NOT NULL DEFAULT '{}')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS automation_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL REFERENCES bookings(id),
        step TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending', attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 4, run_after TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
        idempotency_key TEXT NOT NULL UNIQUE, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS booking_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL REFERENCES bookings(id),
        event TEXT NOT NULL, detail TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'Info', created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cleaner_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL REFERENCES bookings(id),
        cleaner_id INTEGER NOT NULL REFERENCES cleaners(id), token TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'Offered', distance REAL NOT NULL, created_at TEXT NOT NULL,
        responded_at TEXT, UNIQUE(booking_id, cleaner_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL REFERENCES bookings(id),
        recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
        provider_id TEXT, error TEXT, created_at TEXT NOT NULL)""")
    steps = [
        ("send_quote", "Send customer quote"), ("offer_cleaners", "Offer job to suitable cleaners"),
        ("send_confirmations", "Send assignment confirmations"), ("send_reminder", "Send 24-hour reminders"),
        ("send_payment_confirmation", "Send payment confirmation"),
        ("send_abandoned_followup", "Follow up abandoned bookings"),
        ("send_final_invoice", "Send final invoice"), ("send_review", "Send review request")]
    conn.executemany("INSERT OR IGNORE INTO workflow_config(step,label) VALUES (?,?)", steps)


def workflow_to_autopilot_key(step):
    if step in {"offer_cleaners", "send_confirmations"}:
        return "booking_autopilot"
    if step in {"send_reminder"}:
        return "cleaner_operations"
    if step in {"send_payment_confirmation", "send_abandoned_followup", "send_final_invoice", "send_review"}:
        return "customer_payment"
    return "booking_autopilot"


def alert_once(conn, automation_key, title, detail, level="Needs attention"):
    try:
        existing = conn.execute(
            "SELECT id FROM automation_alerts WHERE automation_key=? AND title=? AND resolved_at IS NULL LIMIT 1",
            (automation_key, title),
        ).fetchone()
        if existing:
            return
        conn.execute(
            "INSERT INTO automation_alerts(automation_key,title,detail,level,created_at) VALUES (?,?,?,?,?)",
            (automation_key, title, detail, level, now()),
        )
    except Exception:
        # Autopilot tables may not exist during early startup/migration. Never let
        # alert recording break the proven booking workflow worker.
        pass


def automation_log(conn, automation_key, event, detail, level="Info"):
    try:
        conn.execute(
            "INSERT INTO automation_logs(automation_key,event,detail,level,created_at) VALUES (?,?,?,?,?)",
            (automation_key, event, detail, level, now()),
        )
    except Exception:
        pass


def timeline(booking_id, event, detail, level="Info"):
    with _connect() as conn:
        conn.execute("INSERT INTO booking_timeline(booking_id,event,detail,level,created_at) VALUES (?,?,?,?,?)", (booking_id, event, detail, level, now()))


def enqueue(booking_id, step, payload=None, run_after=None, key=None):
    with _connect() as conn:
        config = conn.execute("SELECT * FROM workflow_config WHERE step=?", (step,)).fetchone()
        if config and not config["enabled"]:
            timeline(booking_id, "Step skipped", f"{config['label']} is disabled", "Warning")
            return None
        when = run_after or now()
        idem = key or f"{booking_id}:{step}"
        conn.execute("""INSERT OR IGNORE INTO automation_jobs
            (booking_id,step,status,attempts,max_attempts,run_after,payload,idempotency_key,created_at,updated_at)
            VALUES (?,?,'Pending',0,?,?,?,?,?,?)""", (booking_id, step, config["max_attempts"] if config else 4, when, json.dumps(payload or {}), idem, now(), now()))
        job = conn.execute("SELECT id FROM automation_jobs WHERE idempotency_key=?", (idem,)).fetchone()
        return job["id"] if job else None


def retry(job_id):
    with _connect() as conn:
        job = conn.execute("SELECT * FROM automation_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            return False
        conn.execute("UPDATE automation_jobs SET status='Pending',attempts=0,last_error=NULL,run_after=?,updated_at=? WHERE id=?", (now(), now(), job_id))
        timeline(job["booking_id"], "Automation retried", f"{job['step']} manually queued")
        return True


def worker_loop():
    while True:
        try:
            with _connect() as conn:
                job = conn.execute("""SELECT * FROM automation_jobs WHERE status IN ('Pending','Retrying')
                    AND run_after<=? ORDER BY run_after,id LIMIT 1""", (now(),)).fetchone()
                if job:
                    conn.execute("UPDATE automation_jobs SET status='Running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), job["id"]))
            if not job:
                time.sleep(2)
                continue
            skipped_label = None
            with _connect() as conn:
                config = conn.execute("SELECT enabled,label FROM workflow_config WHERE step=?", (job["step"],)).fetchone()
                if config and not config["enabled"]:
                    conn.execute("UPDATE automation_jobs SET status='Skipped',last_error=NULL,updated_at=? WHERE id=?", (now(), job["id"]))
                    skipped_label = config["label"]
            if skipped_label:
                timeline(job["booking_id"], "Automation skipped", f"{skipped_label} is paused in Sparkles Autopilot.", "Warning")
                continue
            try:
                _handler(dict(job))
                with _connect() as conn:
                    conn.execute("UPDATE automation_jobs SET status='Completed',last_error=NULL,updated_at=? WHERE id=?", (now(), job["id"]))
            except Exception as error:
                attempts = job["attempts"] + 1
                failed = attempts >= job["max_attempts"]
                delay = min(300, 10 * (2 ** max(0, attempts - 1)))
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                with _connect() as conn:
                    conn.execute("UPDATE automation_jobs SET status=?,last_error=?,run_after=?,updated_at=? WHERE id=?", ("Failed" if failed else "Retrying", str(error), retry_at, now(), job["id"]))
                    if failed:
                        automation_key = workflow_to_autopilot_key(job["step"])
                        booking = conn.execute("SELECT reference FROM bookings WHERE id=?", (job["booking_id"],)).fetchone()
                        reference = booking["reference"] if booking else f"Booking #{job['booking_id']}"
                        detail = (
                            f"{reference}: workflow step '{job['step']}' failed after {attempts} attempt(s). "
                            f"Sparkles already retried it automatically. Last error: {error}. "
                            f"Recommended action: open /admin/bookings and review the booking timeline."
                        )
                        alert_once(conn, automation_key, f"{job['step']} failed after retries", detail)
                        automation_log(conn, automation_key, "Workflow failed after retries", detail, "Error")
                timeline(job["booking_id"], "Automation failed", f"{job['step']}: {error}", "Error")
        except Exception as error:
            print("Automation worker error:", error)
            time.sleep(3)


def start_worker():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=worker_loop, name="sparkles-automation", daemon=True).start()

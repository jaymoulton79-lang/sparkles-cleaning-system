import json
import mimetypes
import os
import sqlite3
import uuid
import math
import base64
import hashlib
import hmac
import time
import urllib.error
import urllib.parse
import urllib.request
import smtplib
import socket
import logging
import sys
import secrets
import re
import html as html_lib
import csv
import io
from email.message import EmailMessage
from email.utils import parseaddr
import automation
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

try:
    import psycopg
except ImportError:  # Local development can continue with SQLite only.
    psycopg = None

DB_ERROR_TYPES = (sqlite3.Error,)
DB_INTEGRITY_ERROR_TYPES = (sqlite3.IntegrityError,)
if psycopg is not None:
    DB_ERROR_TYPES = (sqlite3.Error, psycopg.Error)
    DB_INTEGRITY_ERROR_TYPES = (sqlite3.IntegrityError, psycopg.IntegrityError)

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
DB = DATA / "sparkles.db"
MAX_BODY = 15 * 1024 * 1024
ALLOWED_IMAGES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
ALLOWED_APPLICANT_UPLOADS = {**ALLOWED_IMAGES, "application/pdf": ".pdf"}
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")
META_PAGE_ID = os.environ.get("META_PAGE_ID", "").strip()
META_PAGE_ACCESS_TOKEN = os.environ.get("META_PAGE_ACCESS_TOKEN", "").strip()
META_GRAPH_API_VERSION = os.environ.get("META_GRAPH_API_VERSION", "v25.0").strip() or "v25.0"
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "Sparkles Cleaning Cambridge <bookings@sparkles.local>")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "").strip().lower()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
ADMIN_SETUP_TOKEN = os.environ.get("ADMIN_SETUP_TOKEN", "")
BOOTSTRAP_ADMIN_EMAIL = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "labcontractors@outlook.com").strip().lower()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
SESSION_COOKIE = "sparkles_session"
PASSWORD_ITERATIONS = 260000
SESSION_DAYS = 14
RESET_TOKEN_MINUTES = 60


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname, "message": record.getMessage(), "logger": record.name})


logger = logging.getLogger("sparkles")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.handlers = [handler]

# Approximate district centroids keep the MVP private and dependency-free. Unknown
# Postcode districts use simple fallback coordinates and can be upgraded to a geocoder later.
POSTCODE_CENTRES = {
    "CB1": (52.194, 0.145), "CB2": (52.190, 0.118), "CB3": (52.214, 0.089),
    "CB4": (52.228, 0.128), "CB5": (52.218, 0.176), "CB6": (52.399, 0.262),
    "CB7": (52.350, 0.319), "CB8": (52.242, 0.407), "CB9": (52.083, 0.438),
    "CB10": (52.020, 0.250), "CB11": (52.020, 0.210), "CB21": (52.130, 0.280),
    "CB22": (52.126, 0.120), "CB23": (52.215, -0.018), "CB24": (52.290, 0.083),
    "CB25": (52.260, 0.240)
}

DEFAULT_AI_PRICING = {
    "Regular clean": {"base": 4700, "bedroom_extra": 1000, "bathroom_extra": 1000},
    "Deep clean": {"base": 8700, "bedroom_extra": 2000, "bathroom_extra": 1000},
    "End of tenancy": {"base": 12700, "bedroom_extra": 3000, "bathroom_extra": 2000},
    "One-off clean": {"base": 6700, "bedroom_extra": 2000, "bathroom_extra": 1000}
}
PRICING_VERSION = "2026-launch-competitive-ending-7"
DEFAULT_AI_RESPONSES = {
    "greeting": "Thanks for contacting Sparkles Cleaning Cambridge. I can help with prices, availability and booking details.",
    "booking_prompt": "To prepare an accurate quote, please share your name, phone, email, address, postcode, type of clean, bedrooms, bathrooms, preferred date and preferred time.",
    "handoff": "You can complete the secure booking form online and pay the 25% deposit to confirm."
}
DEFAULT_SERVICE_AREAS = "United Kingdom"
DEFAULT_BUSINESS_HOURS = "Monday to Friday 8am-6pm, Saturday 9am-2pm, closed Sunday"


def utcnow():
    return datetime.now(timezone.utc)


def extract_intro_name(message):
    first_sentence = re.split(r"[.!?]", message or "", 1)[0].strip()
    if not first_sentence:
        return ""
    patterns = [
        r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z-]*)",
        r"\bi\s+am\s+([A-Za-z][A-Za-z-]*)",
        r"\bi['’`´]m\s+([A-Za-z][A-Za-z-]*)",
        r"\bim\s+([A-Za-z][A-Za-z-]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, first_sentence, re.I)
        if match:
            return match.group(1).title()
    intro_words = [
        word for word in re.findall(r"[A-Za-z][A-Za-z-]*", first_sentence)
        if word.lower() not in {"hi", "hello", "hey", "i", "im", "m", "am", "my", "name", "is", "need", "want", "looking", "for"}
    ]
    if intro_words and any(marker in first_sentence.lower() for marker in ("hi", "hello", "i'm", "i’m", "im ", "i am", "my name")):
        return intro_words[-1].title()
    return ""


def normalise_password_input(password):
    return str(password or "").strip()


def normalise_email_input(email):
    return re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", str(email or "")).lower()


def hash_password(password):
    password = normalise_password_input(password)
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        password = normalise_password_input(password)
        algorithm, iterations, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def cleaner_auth_candidates(conn, email):
    email = normalise_email_input(email)
    rows = conn.execute(
        """SELECT id,email,password_hash,active FROM cleaners
        ORDER BY active DESC,
        CASE WHEN password_hash IS NOT NULL AND password_hash<>'' THEN 1 ELSE 0 END DESC,
        id DESC""",
    ).fetchall()
    return [row for row in rows if normalise_email_input(row["email"]) == email]


def find_cleaner_for_credentials(conn, email, password):
    password = normalise_password_input(password)
    for candidate in cleaner_auth_candidates(conn, email):
        if candidate["password_hash"] and verify_password(password, candidate["password_hash"]):
            return candidate
    return None


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_url():
    return runtime_setting("PUBLIC_URL", PUBLIC_URL).rstrip("/")


def email_from_address():
    return (
        runtime_setting("EMAIL_FROM", EMAIL_FROM)
        or runtime_setting("SMTP_FROM", SMTP_FROM)
        or "Sparkles Cleaning Cambridge <bookings@sparkles.local>"
    ).strip()


def smtp_config():
    try:
        port = int(runtime_setting("SMTP_PORT", str(SMTP_PORT)) or "587")
    except ValueError:
        port = 587
    return {
        "host": runtime_setting("SMTP_HOST", SMTP_HOST).strip(),
        "port": port,
        "user": runtime_setting("SMTP_USER", SMTP_USER).strip(),
        "password": runtime_setting("SMTP_PASSWORD", SMTP_PASSWORD),
        "from": email_from_address(),
    }


def smtp_diagnostics():
    config = smtp_config()
    missing = []
    if not config["host"]:
        missing.append("SMTP_HOST")
    if not config["from"]:
        missing.append("SMTP_FROM")
    if config["user"] and not config["password"]:
        missing.append("SMTP_PASSWORD")
    return {
        "configured": not missing and bool(config["host"]),
        "missing": missing,
        "host_present": bool(config["host"]),
        "port": config["port"],
        "user_present": bool(config["user"]),
        "password_present": bool(config["password"]),
        "from": config["from"],
        "mode": "ssl" if config["port"] == 465 else "starttls",
        "network_family": "ipv4",
    }


def email_provider_config():
    provider = runtime_setting("EMAIL_PROVIDER", EMAIL_PROVIDER).strip().lower()
    resend_key = runtime_setting("RESEND_API_KEY", RESEND_API_KEY)
    sendgrid_key = runtime_setting("SENDGRID_API_KEY", SENDGRID_API_KEY)
    if not provider:
        if resend_key:
            provider = "resend"
        elif sendgrid_key:
            provider = "sendgrid"
        else:
            provider = "smtp"
    return {
        "provider": provider,
        "resend_configured": bool(resend_key),
        "sendgrid_configured": bool(sendgrid_key),
        "resend_key": resend_key,
        "sendgrid_key": sendgrid_key,
        "from": email_from_address(),
    }


def email_provider_diagnostics():
    config = email_provider_config()
    return {
        "provider": config["provider"],
        "resend_configured": config["resend_configured"],
        "sendgrid_configured": config["sendgrid_configured"],
        "from": config["from"],
        "smtp": smtp_diagnostics(),
        "notes": "Set EMAIL_PROVIDER=resend with RESEND_API_KEY, or EMAIL_PROVIDER=sendgrid with SENDGRID_API_KEY, if Railway blocks outbound SMTP."
    }


def message_html_body(message):
    for part in message.walk():
        if part.get_content_type() == "text/html":
            return part.get_content()
    return None


def message_text_body(message):
    if not message.is_multipart():
        return message.get_content()
    for part in message.walk():
        if part.get_content_type() == "text/plain":
            return part.get_content()
    return ""


def post_json(url, payload, headers):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, body
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {error.code}: {body}")


def deliver_resend_message(message, config):
    payload = {
        "from": config["from"],
        "to": [message["To"]],
        "subject": message["Subject"],
        "text": message_text_body(message),
    }
    html_body = message_html_body(message)
    if html_body:
        payload["html"] = html_body
    status, body = post_json("https://api.resend.com/emails", payload, {"Authorization": f"Bearer {config['resend_key']}"})
    if status not in (200, 201, 202):
        raise RuntimeError(f"Resend returned HTTP {status}: {body}")
    return body


def deliver_sendgrid_message(message, config):
    from_name, from_email = parseaddr(config["from"])
    content = [{"type": "text/plain", "value": message_text_body(message)}]
    html_body = message_html_body(message)
    if html_body:
        content.append({"type": "text/html", "value": html_body})
    payload = {
        "personalizations": [{"to": [{"email": message["To"]}]}],
        "from": {"email": from_email or config["from"], **({"name": from_name} if from_name else {})},
        "subject": message["Subject"],
        "content": content,
    }
    status, body = post_json("https://api.sendgrid.com/v3/mail/send", payload, {"Authorization": f"Bearer {config['sendgrid_key']}"})
    if status not in (200, 202):
        raise RuntimeError(f"SendGrid returned HTTP {status}: {body}")
    return body


def create_ipv4_socket(host, port, timeout):
    last_error = None
    for family, socktype, proto, _, address in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as error:
            last_error = error
            if sock:
                sock.close()
    if last_error:
        raise last_error
    raise OSError(f"No IPv4 SMTP address found for {host}:{port}")


class IPv4SMTP(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        if self.debuglevel > 0:
            self._print_debug("connect: to", (host, port), self.source_address)
        return create_ipv4_socket(host, port, timeout)


class IPv4SMTPSSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        if self.debuglevel > 0:
            self._print_debug("connect: to", (host, port), self.source_address)
        sock = create_ipv4_socket(host, port, timeout)
        return self.context.wrap_socket(sock, server_hostname=self._host)


def smtp_network_check(host=None, port=None):
    config = smtp_config()
    host = host or config["host"] or "smtp.gmail.com"
    port = int(port or config["port"] or 587)

    def resolve(family):
        try:
            rows = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
            return {
                "ok": True,
                "addresses": sorted({row[4][0] for row in rows}),
                "error": None
            }
        except OSError as error:
            return {"ok": False, "addresses": [], "error": repr(error)}

    def connect_family(family):
        started = time.time()
        try:
            rows = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
            last_error = None
            for row_family, socktype, proto, _, address in rows:
                sock = None
                try:
                    sock = socket.socket(row_family, socktype, proto)
                    sock.settimeout(5)
                    sock.connect(address)
                    sock.close()
                    return {"ok": True, "address": address[0], "elapsed_ms": int((time.time() - started) * 1000), "error": None}
                except OSError as error:
                    last_error = error
                    if sock:
                        sock.close()
            return {"ok": False, "address": None, "elapsed_ms": int((time.time() - started) * 1000), "error": repr(last_error)}
        except OSError as error:
            return {"ok": False, "address": None, "elapsed_ms": int((time.time() - started) * 1000), "error": repr(error)}

    starttls = {"ok": False, "error": None, "elapsed_ms": None}
    started = time.time()
    try:
        with IPv4SMTP(host, port, timeout=10) as smtp:
            code, greeting = smtp.ehlo()
            if code >= 400:
                raise RuntimeError(f"EHLO failed: {code} {greeting!r}")
            code, response = smtp.starttls()
            if code >= 400:
                raise RuntimeError(f"STARTTLS failed: {code} {response!r}")
            code, greeting = smtp.ehlo()
            if code >= 400:
                raise RuntimeError(f"EHLO after STARTTLS failed: {code} {greeting!r}")
        starttls = {"ok": True, "error": None, "elapsed_ms": int((time.time() - started) * 1000)}
    except Exception as error:
        starttls = {"ok": False, "error": repr(error), "elapsed_ms": int((time.time() - started) * 1000)}

    ipv4_connect = connect_family(socket.AF_INET)
    ipv6_connect = connect_family(socket.AF_INET6)
    conclusion = "unknown"
    if not resolve(socket.AF_INET)["ok"] and not resolve(socket.AF_INET6)["ok"]:
        conclusion = "dns_failed"
    elif ipv4_connect["ok"] and starttls["ok"]:
        conclusion = "smtp_587_reachable_starttls_ok"
    elif ipv4_connect["ok"] and not starttls["ok"]:
        conclusion = "smtp_reachable_starttls_failed"
    elif not ipv4_connect["ok"] and ipv6_connect["ok"]:
        conclusion = "ipv4_failed_ipv6_reachable"
    elif not ipv4_connect["ok"] and not ipv6_connect["ok"]:
        conclusion = "smtp_port_unreachable_or_blocked"

    return {
        "host": host,
        "port": port,
        "dns_ipv4": resolve(socket.AF_INET),
        "dns_ipv6": resolve(socket.AF_INET6),
        "tcp_ipv4": ipv4_connect,
        "tcp_ipv6": ipv6_connect,
        "starttls_ipv4": starttls,
        "conclusion": conclusion,
        "blocked_likely": conclusion == "smtp_port_unreachable_or_blocked",
    }


def deliver_email_message(message):
    provider = email_provider_config()
    if provider["provider"] == "resend":
        if not provider["resend_key"]:
            raise RuntimeError("EMAIL_PROVIDER is resend but RESEND_API_KEY is not configured.")
        return deliver_resend_message(message, provider)
    if provider["provider"] == "sendgrid":
        if not provider["sendgrid_key"]:
            raise RuntimeError("EMAIL_PROVIDER is sendgrid but SENDGRID_API_KEY is not configured.")
        return deliver_sendgrid_message(message, provider)
    config = smtp_config()
    if not config["host"]:
        raise RuntimeError("SMTP_HOST is not configured, so email is only stored as a local preview.")
    if config["port"] == 465:
        with IPv4SMTPSSL(config["host"], config["port"], timeout=20) as smtp:
            if config["user"]:
                smtp.login(config["user"], config["password"])
            smtp.send_message(message)
    else:
        with IPv4SMTP(config["host"], config["port"], timeout=20) as smtp:
            smtp.ehlo()
            if config["port"] != 25:
                smtp.starttls()
                smtp.ehlo()
            if config["user"]:
                smtp.login(config["user"], config["password"])
            smtp.send_message(message)
    return "smtp"


def email_delivery_available():
    provider = email_provider_config()
    smtp = smtp_config()
    return (
        (provider["provider"] == "resend" and provider["resend_configured"]) or
        (provider["provider"] == "sendgrid" and provider["sendgrid_configured"]) or
        bool(smtp["host"])
    )


def send_auth_email(recipient, subject, body, html_body=None):
    if not email_delivery_available():
        logger.info(json.dumps({"auth_email_preview": {"recipient": recipient, "subject": subject, "body": body}}))
        return "Preview"
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = email_from_address(), recipient, subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    deliver_email_message(message)
    return "Sent"


def admin_configured():
    return bool(runtime_setting("ADMIN_EMAIL", "") and runtime_setting("ADMIN_PASSWORD_HASH", ""))


def postcode_district(postcode):
    compact = "".join(postcode.upper().split())
    return compact[:-3] if len(compact) > 3 else compact


def distance_miles(from_postcode, to_postcode):
    a = POSTCODE_CENTRES.get(postcode_district(from_postcode), POSTCODE_CENTRES["CB1"])
    b = POSTCODE_CENTRES.get(postcode_district(to_postcode), POSTCODE_CENTRES["CB1"])
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(3958.8 * 2 * math.asin(math.sqrt(h)), 1)


def cleaner_has_conflict(conn, cleaner_id, booking_date, booking_time, exclude_booking=None):
    query = """SELECT id FROM bookings WHERE cleaner_id=? AND preferred_date=?
        AND preferred_time=? AND status NOT IN ('Cancelled','Completed')"""
    params = [cleaner_id, booking_date, booking_time]
    if exclude_booking is not None:
        query += " AND id<>?"
        params.append(exclude_booking)
    return conn.execute(query, params).fetchone() is not None


def quote_pence(clean_type, bedrooms, bathrooms):
    pricing = ai_pricing_rules()
    rule = pricing.get(clean_type) or pricing.get("One-off clean") or {"base": 7500, "bedroom_extra": 1600, "bathroom_extra": 1100}
    raw_total = int(rule.get("base", 7500)) + max(0, int(bedrooms) - 1) * int(rule.get("bedroom_extra", 0)) + max(0, int(bathrooms) - 1) * int(rule.get("bathroom_extra", 0))
    return price_ending_7_pence(raw_total)


def price_ending_7_pence(amount):
    pounds = max(0, math.ceil(int(amount or 0) / 100))
    remainder = pounds % 10
    if remainder <= 7:
        pounds += 7 - remainder
    else:
        pounds += 17 - remainder
    return pounds * 100


def ai_pricing_rules():
    try:
        value = runtime_setting("AI_PRICING_JSON", json.dumps(DEFAULT_AI_PRICING))
        data = json.loads(value)
        return data if isinstance(data, dict) else DEFAULT_AI_PRICING
    except (TypeError, ValueError, json.JSONDecodeError):
        return DEFAULT_AI_PRICING


def ai_settings():
    try:
        responses = json.loads(runtime_setting("AI_RESPONSES_JSON", json.dumps(DEFAULT_AI_RESPONSES)))
    except (TypeError, ValueError, json.JSONDecodeError):
        responses = DEFAULT_AI_RESPONSES
    if not isinstance(responses, dict):
        responses = DEFAULT_AI_RESPONSES
    return {
        "business_hours": runtime_setting("AI_BUSINESS_HOURS", DEFAULT_BUSINESS_HOURS),
        "service_areas": runtime_setting("AI_SERVICE_AREAS", DEFAULT_SERVICE_AREAS),
        "pricing": ai_pricing_rules(),
        "responses": {**DEFAULT_AI_RESPONSES, **responses},
        "booking_url": f"{public_url()}/"
    }


def schedule_booking_reminder(booking):
    try:
        reminder_time = datetime.fromisoformat(booking["preferred_date"]).replace(tzinfo=timezone.utc) - timedelta(days=1) + timedelta(hours=8)
        if reminder_time > datetime.now(timezone.utc):
            automation.enqueue(booking["id"], "send_reminder", run_after=reminder_time.isoformat())
    except (ValueError, TypeError):
        pass


BOOKING_FIELDS = ["name", "phone", "email", "address", "postcode", "clean_type", "bedrooms", "bathrooms", "preferred_date", "preferred_time"]


def create_booking_record(fields, photos=None, source="Website"):
    required = [key for key in BOOKING_FIELDS if not fields.get(key)]
    if required:
        raise ValueError("Missing booking details: " + ", ".join(required))
    reference = f"SPK-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    quote_token = uuid.uuid4().hex
    total = quote_pence(fields["clean_type"], fields["bedrooms"], fields["bathrooms"])
    deposit = round(total * .25)
    with connect() as conn:
        cursor = conn.execute("""
            INSERT INTO bookings (reference,name,phone,email,address,postcode,clean_type,bedrooms,bathrooms,preferred_date,preferred_time,notes,photos,status,created_at,total_amount,deposit_amount,balance_amount,payment_status,quote_token,quote_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'New',?,?,?,?, 'Deposit Due',?,'Pending')
        """, (reference, fields["name"], fields["phone"], fields["email"], fields["address"], fields["postcode"].upper(), fields["clean_type"], int(fields["bedrooms"]), int(fields["bathrooms"]), fields["preferred_date"], fields["preferred_time"], fields.get("notes", ""), json.dumps(photos or []), datetime.now(timezone.utc).isoformat(), total, deposit, total-deposit, quote_token))
        booking_id = cursor.lastrowid
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    automation.timeline(booking_id, "Booking received", f"{source} booking created. Quote calculated automatically: £{total/100:.2f}")
    checkout_url, checkout_session_id, checkout_error = None, None, None
    if stripe_configured():
        try:
            checkout = create_checkout(booking, "deposit")
            checkout_url, checkout_session_id = checkout["url"], checkout["id"]
            with connect() as conn:
                conn.execute("UPDATE bookings SET deposit_checkout_session_id=?, deposit_checkout_url=? WHERE id=?", (checkout_session_id, checkout_url, booking_id))
            automation.timeline(booking_id, "Deposit checkout created", "Stripe Checkout link created for the 25% deposit")
        except ValueError as error:
            checkout_error = str(error)
            automation.timeline(booking_id, "Deposit checkout failed", checkout_error, "Warning")
    else:
        checkout_error = "Stripe is not configured. Add STRIPE_SECRET_KEY before taking online deposits."
        automation.timeline(booking_id, "Deposit checkout not created", checkout_error, "Warning")
    safe_send_booking_confirmation_email(booking_id, False)
    automation.enqueue(booking_id, "send_quote")
    automation.enqueue(booking_id, "send_abandoned_followup", run_after=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
    return {
        "ok": True, "reference": reference, "booking_id": booking_id,
        "total_amount": total, "deposit_amount": deposit, "balance_amount": total-deposit,
        "payment_status": "Deposit Due", "checkout_url": checkout_url,
        "checkout_session_id": checkout_session_id, "checkout_error": checkout_error,
        "quote_status": "Queued"
    }


def stripe_request(path, data=None, method="POST"):
    secret_key = runtime_setting("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY)
    if not secret_key:
        raise ValueError("Stripe test mode is not configured. Add STRIPE_SECRET_KEY to the server environment.")
    encoded = urllib.parse.urlencode(data or {}).encode() if data is not None else None
    auth = base64.b64encode(f"{secret_key}:".encode()).decode()
    request = urllib.request.Request(f"https://api.stripe.com/v1/{path.lstrip('/')}", data=encoded, method=method, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        details = json.loads(error.read() or b"{}")
        raise ValueError(details.get("error", {}).get("message", "Stripe could not process the request."))


def stripe_get(path, params=None):
    secret_key = runtime_setting("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY)
    if not secret_key:
        raise ValueError("Stripe test mode is not configured. Add STRIPE_SECRET_KEY to the server environment.")
    query = urllib.parse.urlencode(params or {})
    url = f"https://api.stripe.com/v1/{path.lstrip('/')}"
    if query:
        url += f"?{query}"
    auth = base64.b64encode(f"{secret_key}:".encode()).decode()
    request = urllib.request.Request(url, method="GET", headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        details = json.loads(error.read() or b"{}")
        raise ValueError(details.get("error", {}).get("message", "Stripe could not process the request."))


def stripe_configured():
    return bool(runtime_setting("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY))


def archived_stripe_session_ids():
    try:
        with connect() as conn:
            return {
                row["session_id"]
                for row in conn.execute("SELECT session_id FROM archived_stripe_sessions").fetchall()
            }
    except Exception:
        return set()


def recovered_stripe_booking_rows(days=45):
    if not stripe_configured():
        return []
    archived_sessions = archived_stripe_session_ids()
    created_gte = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    rows, starting_after = [], None
    while True:
        params = {"limit": 100, "created[gte]": created_gte}
        if starting_after:
            params["starting_after"] = starting_after
        page = stripe_get("checkout/sessions", params)
        sessions = page.get("data", [])
        for session in sessions:
            if session.get("payment_status") != "paid":
                continue
            if session.get("id") in archived_sessions:
                continue
            metadata = session.get("metadata") or {}
            customer = session.get("customer_details") or {}
            booking_id = metadata.get("booking_id") or session.get("client_reference_id") or session.get("id")
            amount = int(session.get("amount_total") or 0)
            created = datetime.fromtimestamp(int(session.get("created", 0)), timezone.utc)
            payment_type = (metadata.get("payment_type") or "deposit").lower()
            deposit_amount = amount if payment_type == "deposit" else 0
            total_amount = deposit_amount * 4 if deposit_amount else amount
            reference = metadata.get("booking_reference") or metadata.get("reference") or f"Stripe {str(booking_id)[-6:]}"
            rows.append({
                "id": booking_id,
                "reference": reference,
                "name": customer.get("name") or customer.get("email") or session.get("customer_email") or "Stripe customer",
                "phone": customer.get("phone") or "",
                "email": customer.get("email") or session.get("customer_email") or "",
                "address": "Original booking details were not found in the active database.",
                "postcode": "",
                "clean_type": "Cleaning booking",
                "bedrooms": 0,
                "bathrooms": 0,
                "preferred_date": created.date().isoformat(),
                "preferred_time": "See Stripe payment",
                "notes": "Recovered from successful Stripe payment because the bookings table is empty.",
                "photos": [],
                "before_photos": [],
                "after_photos": [],
                "status": "Deposit Paid",
                "payment_status": "Deposit Paid",
                "cleaner_id": None,
                "cleaner_name": None,
                "cleaner_phone": None,
                "created_at": created.isoformat(),
                "total_amount": total_amount,
                "deposit_amount": deposit_amount,
                "balance_amount": max(total_amount - deposit_amount, 0),
                "deposit_checkout_session_id": session.get("id"),
                "recovered_session_id": session.get("id"),
                "deposit_checkout_url": "",
                "balance_payment_url": "",
                "accepted_at": None,
                "started_at": None,
                "completed_at": None,
                "cleaner_notes": "",
                "payments": [{
                    "id": session.get("id"),
                    "booking_id": booking_id,
                    "payment_type": payment_type,
                    "amount": amount,
                    "currency": "gbp",
                    "status": "Paid",
                    "provider_payment_id": session.get("payment_intent") or session.get("id"),
                    "created_at": created.isoformat()
                }],
                "_source": "stripe.checkout.sessions"
            })
        if not page.get("has_more") or not sessions:
            break
        starting_after = sessions[-1]["id"]
    return rows


def create_checkout(booking, payment_type):
    amount = booking["deposit_amount"] if payment_type == "deposit" else booking["balance_amount"]
    label = "25% cleaning deposit" if payment_type == "deposit" else "Cleaning invoice balance"
    return stripe_request("checkout/sessions", {
        "mode": "payment", "customer_email": booking["email"],
        "success_url": f"{public_url()}/payment-success?session_id={{CHECKOUT_SESSION_ID}}&booking={booking['id']}",
        "cancel_url": f"{public_url()}/?payment=cancelled&booking={booking['id']}", "client_reference_id": str(booking["id"]),
        "metadata[booking_id]": str(booking["id"]), "metadata[payment_type]": payment_type,
        "line_items[0][price_data][currency]": "gbp", "line_items[0][price_data][unit_amount]": str(amount),
        "line_items[0][price_data][product_data][name]": f"Sparkles Cleaning Cambridge - {label}",
        "line_items[0][price_data][product_data][description]": booking["reference"], "line_items[0][quantity]": "1"
    })


def create_balance_invoice(conn, booking):
    if not runtime_setting("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY) or booking["payment_status"] == "Paid in Full":
        return None
    if booking["payment_status"] == "Balance Due" and booking["balance_payment_url"]:
        return {"id": booking["stripe_invoice_id"] or "", "hosted_invoice_url": booking["balance_payment_url"], "url": booking["balance_payment_url"]}
    checkout = create_checkout(booking, "balance")
    conn.execute(
        "UPDATE bookings SET balance_payment_url=?, stripe_invoice_id=COALESCE(NULLIF(stripe_invoice_id,''), ?), payment_status='Balance Due' WHERE id=?",
        (checkout["url"], checkout["id"], booking["id"]),
    )
    return {"id": checkout["id"], "hosted_invoice_url": checkout["url"], "url": checkout["url"]}


def record_payment(conn, booking_id, payment_type, amount, provider_id, status="Paid"):
    conn.execute("""INSERT OR IGNORE INTO payments
        (booking_id,payment_type,amount,currency,status,provider_payment_id,created_at)
        VALUES (?,?,?,'gbp',?,?,?)""", (booking_id, payment_type, amount, status, provider_id, datetime.now(timezone.utc).isoformat()))
    if payment_type == "deposit":
        conn.execute("UPDATE bookings SET payment_status='Deposit Paid', status=CASE WHEN status='New' THEN 'Deposit Paid' ELSE status END WHERE id=?", (booking_id,))
    elif payment_type == "balance":
        conn.execute("UPDATE bookings SET payment_status='Paid in Full' WHERE id=?", (booking_id,))


def estimated_cleaner_hours(booking):
    bedrooms = int(booking["bedrooms"] or 0)
    bathrooms = int(booking["bathrooms"] or 0)
    clean_type = str(booking["clean_type"] or "").lower()
    hours = 1.5 + bedrooms * 0.45 + bathrooms * 0.35
    if "deep" in clean_type:
        hours += 1.25
    if "end of tenancy" in clean_type:
        hours += 2
    return max(2, round(hours * 2) / 2)


def ensure_cleaner_payout(conn, booking_id):
    booking = conn.execute("""
        SELECT b.*, c.name AS cleaner_name, c.hourly_rate AS cleaner_hourly_rate
        FROM bookings b JOIN cleaners c ON c.id=b.cleaner_id
        WHERE b.id=? AND b.cleaner_id IS NOT NULL
    """, (booking_id,)).fetchone()
    if not booking or booking["status"] != "Completed":
        return None
    hours = estimated_cleaner_hours(booking)
    rate = float(booking["cleaner_hourly_rate"] or 0)
    amount = int(round(hours * rate * 100))
    now = utcnow().isoformat()
    conn.execute("""INSERT OR IGNORE INTO cleaner_payouts
        (booking_id,cleaner_id,amount,currency,status,estimated_hours,hourly_rate,created_at,updated_at)
        VALUES (?,?,?,'gbp','Pending',?,?,?,?)""", (booking_id, booking["cleaner_id"], amount, hours, rate, now, now))
    conn.execute("""UPDATE cleaner_payouts
        SET amount=?, estimated_hours=?, hourly_rate=?, updated_at=?
        WHERE booking_id=? AND status='Pending'""", (amount, hours, rate, now, booking_id))
    return conn.execute("SELECT * FROM cleaner_payouts WHERE booking_id=?", (booking_id,)).fetchone()


def record_invoice_payment(conn, invoice):
    booking_id = int(invoice.get("metadata", {}).get("booking_id") or 0)
    invoice_id = invoice.get("id")
    if not booking_id and invoice_id:
        booking = conn.execute("SELECT id FROM bookings WHERE stripe_invoice_id=?", (invoice_id,)).fetchone()
        booking_id = int(booking["id"]) if booking else 0
    if not booking_id:
        raise ValueError("Booking not found for this Stripe invoice.")
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        raise ValueError("Booking not found for this Stripe invoice.")
    amount = int(invoice.get("amount_paid") or 0)
    if amount <= 0:
        raise ValueError("Stripe invoice has not recorded a paid balance amount yet.")
    if amount < int(booking["balance_amount"] or 0):
        raise ValueError("Stripe invoice paid amount is less than the booking balance.")
    provider_id = invoice.get("payment_intent") or invoice_id
    record_payment(conn, booking_id, "balance", amount, provider_id)
    if invoice_id:
        conn.execute("UPDATE bookings SET stripe_invoice_id=COALESCE(stripe_invoice_id, ?), balance_payment_url=COALESCE(balance_payment_url, ?) WHERE id=?", (invoice_id, invoice.get("hosted_invoice_url"), booking_id))
    return booking_id, amount


def sync_paid_balance_invoices(conn):
    if not stripe_configured():
        return []
    rows = conn.execute("""SELECT id,stripe_invoice_id FROM bookings
        WHERE payment_status='Balance Due' AND stripe_invoice_id IS NOT NULL AND stripe_invoice_id<>''""").fetchall()
    synced = []
    for row in rows:
        try:
            invoice = stripe_request(f"invoices/{row['stripe_invoice_id']}", None, "GET")
            if invoice.get("paid") or invoice.get("status") == "paid":
                booking_id, amount = record_invoice_payment(conn, invoice)
                try:
                    automation.timeline(booking_id, "Final payment synced", f"Stripe invoice already paid: £{amount/100:.2f}")
                    automation.enqueue(booking_id, "send_review")
                except Exception as automation_error:
                    logger.error(json.dumps({"stripe_invoice_sync": "automation_failed", "booking_id": booking_id, "invoice_id": row["stripe_invoice_id"], "error": str(automation_error)}))
                synced.append(booking_id)
        except Exception as exc:
            logger.error(json.dumps({"stripe_invoice_sync": "failed", "booking_id": row["id"], "invoice_id": row["stripe_invoice_id"], "error": str(exc)}))
    return synced


def clean_customer_email_copy(booking_id, recipient, subject, body, html_body=None):
    try:
        with connect() as conn:
            booking = conn.execute("SELECT name,email FROM bookings WHERE id=?", (booking_id,)).fetchone()
    except Exception:
        booking = None
    if not booking or str(recipient or "").strip().lower() != str(booking["email"] or "").strip().lower():
        return subject, body, html_body

    customer_name = display_customer_name(booking["name"])
    replacements = {
        "Sparkles Cleaning Cambridge": "Sparkles Cleaning Cambridge",
        "Sparkles Cleaning Cambridge": "Sparkles Cleaning Cambridge",
        "Â£": "£",
        "â€“": "-",
        "â€™": "'",
    }
    for old, new in replacements.items():
        subject = str(subject or "").replace(old, new)
        body = str(body or "").replace(old, new)
        html_body = html_body.replace(old, new) if html_body else html_body
    body = re.sub(r"Hello\s+[^,\n]+,", f"Hello {customer_name},", body, count=1)
    html_body = re.sub(r"Hello\s+[^,<\n]+,", f"Hello {html_lib.escape(customer_name)},", html_body, count=1) if html_body else html_body
    return subject, body, html_body


def send_workflow_email(booking_id, recipient, subject, body, html_body=None):
    subject, body, html_body = clean_customer_email_copy(booking_id, recipient, subject, body, html_body)
    delivery_status, provider_id, error = "Preview", None, None
    config = smtp_config()
    if config["host"]:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = config["from"], recipient, subject
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")
        try:
            deliver_email_message(message)
            delivery_status, provider_id = "Sent", message["Message-ID"] or uuid.uuid4().hex
        except Exception as exc:
            error = str(exc)
            delivery_status = "Failed"
            logger.error(json.dumps({"email_delivery": "failed", "booking_id": booking_id, "recipient": recipient, "subject": subject, "error": error}))
    else:
        logger.warning(json.dumps({"email_delivery": "preview", "booking_id": booking_id, "recipient": recipient, "subject": subject, "missing": smtp_diagnostics()["missing"]}))
    with connect() as conn:
        conn.execute("INSERT INTO email_log(booking_id,recipient,subject,body,status,provider_id,error,created_at) VALUES (?,?,?,?,?,?,?,?)", (booking_id, recipient, subject, body, delivery_status, provider_id, error, datetime.now(timezone.utc).isoformat()))
    automation.timeline(booking_id, "Email prepared" if delivery_status == "Preview" else "Email sent", f"{subject} → {recipient} ({delivery_status})", "Warning" if delivery_status == "Preview" else "Info")
    if delivery_status == "Sent":
        logger.info(json.dumps({"email_delivery": "sent", "booking_id": booking_id, "recipient": recipient, "subject": subject}))
    if delivery_status == "Failed":
        raise RuntimeError(error)


def money_pounds(pence):
    try:
        return f"£{int(pence or 0) / 100:.2f}"
    except (TypeError, ValueError):
        return "£0.00"


def email_contact_address():
    return (
        runtime_setting("COMPANY_EMAIL", "")
        or runtime_setting("ADMIN_EMAIL", "")
        or runtime_setting("SMTP_FROM", SMTP_FROM)
    )


def public_brand_name():
    company = (runtime_setting("COMPANY_NAME", "") or "").strip()
    if not company or company.lower() in {"sparkles os", "sparkles cleaning cambridge", "sparkles cleaning"}:
        return "Sparkles Cleaning Cambridge"
    return company


def display_customer_name(name):
    cleaned = str(name or "").strip()
    if not cleaned:
        return "there"
    return " ".join(
        "".join(
            piece[:1].upper() + piece[1:].lower() if re.match(r"[A-Za-z]", piece) else piece
            for piece in re.split(r"([\s-]+)", word)
        )
        for word in cleaned.split()
    )


def plain_rows(rows):
    return "\n".join(f"{label}: {value}" for label, value in rows)


def sparkles_email_html(title, intro, rows, cta=None):
    company = html_lib.escape(public_brand_name())
    title_html = html_lib.escape(title)
    intro_html = html_lib.escape(intro).replace("\n", "<br>")
    rows_html = "".join(
        f"""<tr>
            <td style="padding:10px 12px;border-bottom:1px solid #F2D9E7;color:#6B5F6A;font-size:14px;">{html_lib.escape(str(label))}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #F2D9E7;color:#172033;font-size:14px;font-weight:700;">{html_lib.escape(str(value or '—'))}</td>
        </tr>"""
        for label, value in rows
    )
    cta_html = ""
    if cta and cta.get("url"):
        cta_html = f"""<p style="margin:26px 0 10px;">
            <a href="{html_lib.escape(cta['url'])}" style="background:#E91E8F;color:#ffffff;text-decoration:none;padding:13px 18px;border-radius:14px;font-weight:800;display:inline-block;box-shadow:0 10px 24px rgba(233,30,143,.22);">{html_lib.escape(cta.get('label', 'View booking'))}</a>
        </p>"""
    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#FFF8EF;font-family:Inter,Arial,Helvetica,sans-serif;color:#172033;">
    <div style="max-width:640px;margin:0 auto;padding:24px;">
      <div style="background:#E91E8F;color:#ffffff;border-radius:24px 24px 0 0;padding:26px;border-bottom:5px solid #FACC15;">
        <div style="font-size:14px;letter-spacing:.08em;text-transform:uppercase;opacity:.95;font-weight:800;">{company}</div>
        <h1 style="margin:8px 0 0;font-size:26px;line-height:1.2;">{title_html}</h1>
        <p style="margin:8px 0 0;font-size:14px;opacity:.9;">Smiles Come Standard.</p>
      </div>
      <div style="background:#ffffff;border-radius:0 0 24px 24px;padding:24px;box-shadow:0 18px 44px rgba(233,30,143,.10);">
        <p style="font-size:16px;line-height:1.6;margin:0 0 18px;">{intro_html}</p>
        <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;background:#FFF7FB;border:1px solid #F2D9E7;border-radius:18px;overflow:hidden;">
          {rows_html}
        </table>
        {cta_html}
        <p style="font-size:13px;color:#6B5F6A;line-height:1.5;margin:24px 0 0;">Thank you for choosing {company}. Smiles Come Standard. If anything needs changing, please reply to this email.</p>
      </div>
    </div>
  </body>
</html>"""


def owner_alert_recipient():
    return (
        runtime_setting("COMPANY_EMAIL", "")
        or runtime_setting("ADMIN_EMAIL", "")
        or email_contact_address()
    ).strip()


def cleaner_setup_link(token):
    return f"{public_url()}/cleaner/setup?role=cleaner&token={urllib.parse.quote(token)}"


def create_cleaner_invitation(cleaner_id):
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES)
    with connect() as conn:
        cleaner = conn.execute("SELECT * FROM cleaners WHERE id=?", (cleaner_id,)).fetchone()
        if not cleaner:
            raise ValueError("Cleaner not found.")
        conn.execute(
            "UPDATE password_reset_tokens SET used_at=? WHERE role='cleaner' AND subject_id=? AND used_at IS NULL",
            (utcnow().isoformat(), cleaner_id),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens(token_hash,role,subject_id,email,expires_at,created_at) VALUES (?,?,?,?,?,?)",
            (token_hash(token), "cleaner", cleaner_id, cleaner["email"], expires.isoformat(), utcnow().isoformat()),
        )
    return cleaner, cleaner_setup_link(token), expires


def send_cleaner_invitation_email(cleaner_id):
    cleaner, link, expires = create_cleaner_invitation(cleaner_id)
    rows = [
        ("Cleaner", cleaner["name"]),
        ("Portal", "Sparkles Cleaner Portal"),
        ("Expires", expires.strftime("%d %b %Y %H:%M UTC")),
    ]
    intro = f"Hello {display_customer_name(cleaner['name'])}, you have been invited to activate your Sparkles Cleaner Portal account. Create your own password using the secure one-time link below."
    subject = "Activate your Sparkles Cleaner Portal account"
    body = f"{intro}\n\n{plain_rows(rows)}\n\nSetup link:\n{link}\n\nThis link can be used once and will expire automatically."
    html_body = sparkles_email_html(
        "Activate your cleaner account",
        intro,
        rows,
        {"label": "Create cleaner password", "url": link},
    )
    status = send_auth_email(cleaner["email"], subject, body, html_body)
    return {"status": status, "setup_link": link if status == "Preview" else None}


def send_owner_job_alert(booking_id, title, intro, event):
    recipient = owner_alert_recipient()
    if not recipient:
        return
    with connect() as conn:
        row = conn.execute("""SELECT b.*, c.name cleaner_name, c.email cleaner_email
            FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id WHERE b.id=?""", (booking_id,)).fetchone()
    if not row:
        return
    rows = [
        ("Booking reference", row["reference"]),
        ("Customer", row["name"]),
        ("Cleaner", row["cleaner_name"] or "Unassigned"),
        ("Service", row["clean_type"]),
        ("Date", row["preferred_date"]),
        ("Time", row["preferred_time"]),
        ("Status", row["status"]),
    ]
    subject = f"{title} - {row['reference']}"
    body = f"{intro}\n\n{plain_rows(rows)}"
    html_body = sparkles_email_html(title, intro, rows, {"label": "Open Owner Command Centre", "url": f"{public_url()}/admin/bookings"})
    try:
        send_auth_email(recipient, subject, body, html_body)
        automation.timeline(booking_id, event, f"Owner alert sent to {recipient}")
    except Exception as error:
        logger.error(json.dumps({"owner_alert": "failed", "booking_id": booking_id, "error": str(error)}))
        automation.timeline(booking_id, event, f"Owner alert failed: {error}", "Warning")


def booking_email_rows(booking, deposit_paid=None):
    if deposit_paid is None:
        payment_state = str(booking["payment_status"] or booking["status"] or "").strip().lower()
        deposit_paid = payment_state in {"deposit paid", "paid in full"}
    deposit_label = money_pounds(booking["deposit_amount"])
    deposit_row_label = "Deposit paid" if deposit_paid else "Deposit due"
    return [
        ("Booking reference", booking["reference"]),
        ("Date", booking["preferred_date"]),
        ("Time", booking["preferred_time"]),
        ("Address", f"{booking['address']}, {booking['postcode']}"),
        ("Service", booking["clean_type"]),
        (deposit_row_label, deposit_label),
        ("Balance due", money_pounds(booking["balance_amount"])),
    ]


def send_booking_confirmation_email(booking_id, deposit_paid=None, intro=None):
    with connect() as conn:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        return
    deposit_is_paid = bool(deposit_paid) if deposit_paid is not None else None
    rows = booking_email_rows(booking, deposit_is_paid)
    customer_name = display_customer_name(booking["name"])
    if deposit_is_paid:
        subject = f"Booking confirmation – {booking['reference']}"
        heading = "Booking confirmation"
        intro = intro or f"Hello {customer_name}, thanks for booking with Sparkles Cleaning Cambridge. Your deposit has been received and your booking is confirmed. Smiles Come Standard."
    else:
        subject = f"Booking request received – {booking['reference']}"
        heading = "Booking request received"
        intro = intro or f"Hello {customer_name}, thanks for requesting a Sparkles booking. Your clean is not confirmed until the 25% deposit has been paid securely by Stripe. Here are the details."
    body = f"{intro}\n\n{plain_rows(rows)}\n\nSparkles Cleaning Cambridge"
    html_body = sparkles_email_html(heading, intro, rows)
    send_workflow_email(booking_id, booking["email"], subject, body, html_body)
    copy_to = email_contact_address()
    if copy_to and copy_to.lower() != str(booking["email"]).lower():
        send_workflow_email(booking_id, copy_to, f"Copy: {subject}", body, html_body)


def send_cleaner_job_details_email(booking_id):
    with connect() as conn:
        row = conn.execute("""SELECT b.*, c.name cleaner_name, c.email cleaner_email, c.phone cleaner_phone
            FROM bookings b JOIN cleaners c ON c.id=b.cleaner_id WHERE b.id=?""", (booking_id,)).fetchone()
    if not row or not row["cleaner_email"]:
        return
    rows = [
        ("Booking reference", row["reference"]),
        ("Customer", row["name"]),
        ("Customer phone", row["phone"]),
        ("Customer email", row["email"]),
        ("Service", row["clean_type"]),
        ("Date", row["preferred_date"]),
        ("Time", row["preferred_time"]),
        ("Address", f"{row['address']}, {row['postcode']}"),
        ("Notes", row["notes"] or "None"),
    ]
    intro = f"Hello {row['cleaner_name']}, you have been assigned a Sparkles Cleaner Portal job. Please review the details below."
    subject = f"New assigned cleaning job - {row['reference']}"
    portal_url = f"{public_url()}/cleaner/login"
    body = f"{intro}\n\n{plain_rows(rows)}\n\nOpen the Cleaner Portal:\n{portal_url}\n\nSparkles Cleaning Cambridge"
    html_body = sparkles_email_html("New assigned job", intro, rows, {"label": "Open Cleaner Portal", "url": portal_url})
    send_workflow_email(booking_id, row["cleaner_email"], subject, body, html_body)

def send_cleaner_on_way_email(booking_id):
    with connect() as conn:
        row = conn.execute("""SELECT b.*, c.name cleaner_name, c.phone cleaner_phone
            FROM bookings b JOIN cleaners c ON c.id=b.cleaner_id WHERE b.id=?""", (booking_id,)).fetchone()
    if not row or not row["email"]:
        return
    customer_name = display_customer_name(row["name"])
    intro = f"Hello {customer_name}, good news — your Sparkles cleaner is on the way to your property."
    rows = [
        ("Booking reference", row["reference"]),
        ("Cleaner", row["cleaner_name"] or "Your Sparkles cleaner"),
        ("Service", row["clean_type"]),
        ("Date", row["preferred_date"]),
        ("Time", row["preferred_time"]),
        ("Address", f"{row['address']}, {row['postcode']}"),
    ]
    if row["cleaner_phone"]:
        rows.append(("Cleaner phone", row["cleaner_phone"]))
    subject = f"Your Sparkles cleaner is on the way - {row['reference']}"
    body = f"{intro}\n\n{plain_rows(rows)}\n\nSmiles Come Standard.\n\nSparkles Cleaning Cambridge"
    html_body = sparkles_email_html("Your cleaner is on the way", intro, rows)
    send_workflow_email(booking_id, row["email"], subject, body, html_body)


def safe_send_booking_confirmation_email(booking_id, deposit_paid=None, intro=None):
    try:
        send_booking_confirmation_email(booking_id, deposit_paid, intro)
    except RuntimeError as error:
        automation.timeline(booking_id, "Booking confirmation email failed", str(error), "Warning")


def safe_send_cleaner_job_details_email(booking_id):
    try:
        send_cleaner_job_details_email(booking_id)
    except RuntimeError as error:
        automation.timeline(booking_id, "Cleaner job email failed", str(error), "Warning")


def safe_send_cleaner_on_way_email(booking_id):
    try:
        send_cleaner_on_way_email(booking_id)
    except RuntimeError as error:
        automation.timeline(booking_id, "On my way email failed", str(error), "Warning")


def applicant_timeline(applicant_id, event, detail="", level="Info"):
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO cleaner_applicant_timeline(applicant_id,event,detail,level,created_at) VALUES (?,?,?,?,?)",
                (applicant_id, event, detail, level, utcnow().isoformat()),
            )
    except Exception as error:
        logger.warning(json.dumps({"applicant_timeline": "failed", "applicant_id": applicant_id, "event": event, "error": str(error)}))


def send_cleaner_applicant_confirmation(applicant_id):
    with connect() as conn:
        applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
    if not applicant:
        return
    name = display_customer_name(applicant["name"])
    rows = [
        ("Application reference", f"APP-{int(applicant['id']):04d}"),
        ("Name", applicant["name"]),
        ("Postcode", applicant["postcode"]),
        ("Travel radius", f"{applicant['travel_radius']} miles"),
        ("Status", applicant["status"]),
    ]
    intro = f"Hi {name}, thanks for applying to become a Sparkles Cleaner. We have received your application and will review your details shortly."
    subject = "Your Sparkles cleaner application has been received"
    body = f"{intro}\n\n{plain_rows(rows)}\n\nSmiles Come Standard.\nSparkles Cleaning Cambridge"
    html_body = sparkles_email_html("Cleaner application received", intro, rows)
    try:
        status = send_auth_email(applicant["email"], subject, body, html_body)
        applicant_timeline(applicant_id, "Confirmation email sent", f"{subject} → {applicant['email']} ({status})")
    except Exception as error:
        applicant_timeline(applicant_id, "Confirmation email failed", str(error), "Warning")
        raise


def send_owner_applicant_alert(applicant_id):
    recipient = owner_alert_recipient()
    if not recipient:
        applicant_timeline(applicant_id, "Owner notification skipped", "No owner email address configured", "Warning")
        return
    with connect() as conn:
        applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
    if not applicant:
        return
    rows = [
        ("Applicant", applicant["name"]),
        ("Email", applicant["email"]),
        ("Phone", applicant["phone"]),
        ("Postcode", applicant["postcode"]),
        ("Source", applicant["source"]),
        ("Travel", applicant["travel_method"]),
        ("Services", ", ".join(json.loads(applicant["services"] or "[]")) or "Not supplied"),
    ]
    intro = "A new cleaner has applied to join Sparkles Cleaning Cambridge. Review the applicant and approve them when ready."
    subject = f"New cleaner application - {applicant['name']}"
    body = f"{intro}\n\n{plain_rows(rows)}\n\nOpen applicants:\n{public_url()}/admin/cleaner-applicants"
    html_body = sparkles_email_html("New cleaner application", intro, rows, {"label": "Review applicant", "url": f"{public_url()}/admin/cleaner-applicants"})
    try:
        status = send_auth_email(recipient, subject, body, html_body)
        applicant_timeline(applicant_id, "Owner notified", f"{subject} → {recipient} ({status})")
    except Exception as error:
        applicant_timeline(applicant_id, "Owner notification failed", str(error), "Warning")
        raise


def suitable_cleaners(booking):
    weekday = datetime.fromisoformat(booking["preferred_date"]).strftime("%A")
    matches = []
    with connect() as conn:
        declined = {
            int(row["cleaner_id"])
            for row in conn.execute(
                "SELECT cleaner_id FROM cleaner_offers WHERE booking_id=? AND status='Declined'",
                (booking["id"],),
            ).fetchall()
        }
        for row in conn.execute("SELECT * FROM cleaners WHERE active=1 AND password_hash IS NOT NULL AND password_hash<>''").fetchall():
            cleaner = dict(row)
            if int(cleaner["id"]) in declined:
                continue
            if not int(cleaner.get("identity_verified") or 0) or not int(cleaner.get("right_to_work_verified") or 0):
                continue
            if cleaner_self_drives(cleaner) and (
                str(cleaner.get("driving_licence_status") or "").strip().lower() != "verified"
                or not int(cleaner.get("has_own_vehicle") or 0)
            ):
                continue
            distance = distance_miles(booking["postcode"], cleaner["postcode"])
            if (weekday in json.loads(cleaner["availability"]) and booking["clean_type"] in json.loads(cleaner["services"])
                    and distance <= cleaner["travel_radius"] and not cleaner_has_conflict(conn, cleaner["id"], booking["preferred_date"], booking["preferred_time"], booking["id"])):
                cleaner["distance"] = distance
                matches.append(cleaner)
    return sorted(matches, key=lambda item: (item["distance"], item["hourly_rate"]))


def cleaner_verification_payload(data, defaults=None):
    defaults = defaults or {}
    allowed_travel = {"Unknown", "Car", "Car/self-driving", "Owner/company transport", "Public transport", "Bicycle", "Walk/local only"}
    allowed_licence = {"Not provided", "Uploaded", "Verified", "Not held"}
    travel_method = str(data.get("travel_method", defaults.get("travel_method", "Unknown")) or "Unknown").strip()
    licence_status = str(data.get("driving_licence_status", defaults.get("driving_licence_status", "Not provided")) or "Not provided").strip()
    if travel_method not in allowed_travel:
        raise ValueError("Invalid travel method.")
    if licence_status not in allowed_licence:
        raise ValueError("Invalid driving licence status.")
    return {
        "identity_verified": 1 if data.get("identity_verified", defaults.get("identity_verified", False)) else 0,
        "right_to_work_verified": 1 if data.get("right_to_work_verified", defaults.get("right_to_work_verified", False)) else 0,
        "proof_of_address_verified": 1 if data.get("proof_of_address_verified", defaults.get("proof_of_address_verified", False)) else 0,
        "travel_method": travel_method,
        "driving_licence_status": licence_status,
        "has_own_vehicle": 1 if data.get("has_own_vehicle", defaults.get("has_own_vehicle", False)) else 0,
    }


def cleaner_self_drives(cleaner):
    travel_method = str(cleaner.get("travel_method") or "Unknown").strip().lower()
    return travel_method in {"car", "car/self-driving", "self-driving"}


def automation_handler(job):
    step, booking_id = job["step"], job["booking_id"]
    with connect() as conn:
        booking_row = conn.execute("SELECT b.*,c.name cleaner_name,c.email cleaner_email FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id WHERE b.id=?", (booking_id,)).fetchone()
    if not booking_row:
        raise RuntimeError("Booking no longer exists")
    booking = dict(booking_row)
    if step == "send_quote":
        public_url = runtime_setting("PUBLIC_URL", PUBLIC_URL).rstrip("/")
        link = f"{public_url}/quote?token={booking['quote_token']}"
        send_workflow_email(booking_id, booking["email"], f"Your Sparkles quote – {booking['reference']}", f"Hello {booking['name']},\n\nYour cleaning quote is £{booking['total_amount']/100:.2f}. A 25% deposit of £{booking['deposit_amount']/100:.2f} confirms the booking.\n\nReview and accept: {link}\n\nSparkles Cleaning Cambridge")
        with connect() as conn:
            conn.execute("UPDATE bookings SET quote_status='Sent' WHERE id=?", (booking_id,))
        automation.timeline(booking_id, "Quote sent", f"£{booking['total_amount']/100:.2f} quote sent to customer")
    elif step == "send_abandoned_followup":
        if booking["payment_status"] != "Deposit Due":
            automation.timeline(booking_id, "Abandoned follow-up skipped", f"Payment status is {booking['payment_status']}")
            return
        checkout = booking.get("deposit_checkout_url") or f"{public_url()}/quote?token={booking['quote_token']}"
        send_workflow_email(booking_id, booking["email"], f"Complete your Sparkles booking - {booking['reference']}", f"Hello {booking['name']},\n\nWe saved your Sparkles booking request, but the 25% deposit has not been completed yet.\n\nYour quote is £{booking['total_amount']/100:.2f}; the deposit is £{booking['deposit_amount']/100:.2f}.\n\nComplete your booking here: {checkout}\n\nIf you have questions, reply to this email and we will help.")
        automation.timeline(booking_id, "Abandoned booking follow-up sent", "Customer reminded 24 hours after an unpaid booking")
    elif step == "offer_cleaners":
        if booking.get("cleaner_id"):
            automation.timeline(booking_id, "Auto assignment skipped", f"Booking is already assigned to {booking.get('cleaner_name') or 'a cleaner'}.")
            return
        matches = suitable_cleaners(booking)
        if not matches:
            automation.timeline(booking_id, "Owner attention needed", "No eligible cleaners are available for this paid booking.", "Warning")
            send_owner_job_alert(
                booking_id,
                "No eligible cleaner found",
                "Sparkles could not automatically assign this paid booking because no active cleaner currently matches the date, service, availability and travel radius. Please add or adjust a cleaner, then assign manually.",
                "Owner assignment alert",
            )
            return
        cleaner = matches[0]
        with connect() as conn:
            if cleaner_has_conflict(conn, cleaner["id"], booking["preferred_date"], booking["preferred_time"], booking_id):
                automation.timeline(booking_id, "Owner attention needed", f"{cleaner['name']} became unavailable during auto-assignment.", "Warning")
                send_owner_job_alert(
                    booking_id,
                    "Cleaner conflict during auto assignment",
                    f"Sparkles found {cleaner['name']} as the nearest cleaner, but they became unavailable before assignment. Please review the booking.",
                    "Owner assignment alert",
                )
                return
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE bookings SET cleaner_id=?, status='Assigned', assigned_at=? WHERE id=?", (cleaner["id"], now, booking_id))
        automation.timeline(booking_id, "Cleaner auto assigned", f"{cleaner['name']} was auto assigned as the nearest eligible cleaner ({cleaner['distance']} miles away).")
        safe_send_cleaner_job_details_email(booking_id)
        automation.enqueue(booking_id, "send_confirmations")
        with connect() as conn:
            updated = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if updated:
            schedule_booking_reminder(dict(updated))
    elif step == "send_payment_confirmation":
        send_workflow_email(booking_id, booking["email"], f"Deposit received - {booking['reference']}", f"Hello {booking['name']},\n\nThank you. We have received your 25% deposit of £{booking['deposit_amount']/100:.2f} for {booking['clean_type']} on {booking['preferred_date']} ({booking['preferred_time']}).\n\nWe will confirm the assigned cleaner as soon as the job is accepted.\n\nSparkles Cleaning Cambridge")
        automation.timeline(booking_id, "Payment confirmation sent", "Customer notified after deposit payment")
    elif step == "send_confirmations":
        send_workflow_email(booking_id, booking["email"], f"Cleaner confirmed – {booking['reference']}", f"Hello {booking['name']},\n\n{booking['cleaner_name']} is confirmed for {booking['preferred_date']} ({booking['preferred_time']}).")
        send_workflow_email(booking_id, booking["cleaner_email"], f"Job confirmed – {booking['reference']}", f"Hello {booking['cleaner_name']},\n\nYou are confirmed for {booking['address']}, {booking['postcode']} on {booking['preferred_date']} ({booking['preferred_time']}).")
        automation.timeline(booking_id, "Confirmations sent", f"Customer and {booking['cleaner_name']} notified; booking is on the calendar")
    elif step == "send_reminder":
        with connect() as conn:
            already_sent = conn.execute("SELECT 1 FROM booking_timeline WHERE booking_id=? AND event='24-hour reminders sent' LIMIT 1", (booking_id,)).fetchone()
        if already_sent:
            automation.timeline(booking_id, "Reminder skipped", "24-hour reminders were already sent for this booking.")
            return
        send_workflow_email(booking_id, booking["email"], f"Reminder: your clean is tomorrow", f"Your Sparkles clean is tomorrow, {booking['preferred_date']} ({booking['preferred_time']}). Cleaner: {booking['cleaner_name']}.")
        send_workflow_email(booking_id, booking["cleaner_email"], f"Reminder: cleaning job tomorrow", f"Reminder for {booking['address']}, {booking['postcode']} tomorrow ({booking['preferred_time']}).")
        automation.timeline(booking_id, "24-hour reminders sent", "Customer and cleaner reminded")
    elif step == "send_final_invoice":
        with connect() as conn:
            current_booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            invoice = create_balance_invoice(conn, current_booking)
            url = invoice.get("hosted_invoice_url") if invoice else booking["balance_payment_url"]
        if not url:
            raise RuntimeError("Stripe invoice URL is not available")
        with connect() as conn:
            already_sent = conn.execute("SELECT 1 FROM booking_timeline WHERE booking_id=? AND event='Final invoice sent' LIMIT 1", (booking_id,)).fetchone()
        if already_sent:
            automation.timeline(booking_id, "Final invoice skipped", "Final invoice was already sent; Sparkles kept the existing balance payment link.")
            return
        rows = [
            ("Booking reference", booking["reference"]),
            ("Service", booking["clean_type"]),
            ("Date", booking["preferred_date"]),
            ("Total", money_pounds(booking["total_amount"])),
            ("Deposit paid", money_pounds(booking["deposit_amount"])),
            ("Balance due", money_pounds(booking["balance_amount"])),
        ]
        customer_name = display_customer_name(booking["name"])
        intro = f"Hello {customer_name}, thank you for choosing Sparkles Cleaning Cambridge. Your clean is complete and your remaining balance is now ready to pay securely."
        body = f"{intro}\n\n{plain_rows(rows)}\n\nPay your remaining balance securely here: {url}\n\nSparkles Cleaning Cambridge\nSmiles Come Standard."
        html_body = sparkles_email_html(
            "Final balance due",
            intro,
            rows,
            {"url": url, "label": "Pay remaining balance"},
        )
        send_workflow_email(booking_id, booking["email"], f"Final balance due - {booking['reference']}", body, html_body)
        automation.timeline(booking_id, "Final invoice sent", f"Balance £{booking['balance_amount']/100:.2f}")
    elif step == "send_review":
        if booking["payment_status"] != "Paid in Full":
            automation.timeline(booking_id, "Review deferred", f"Payment status is {booking['payment_status']}; waiting for final payment", "Warning")
            raise RuntimeError("Final payment has not been confirmed yet.")
        with connect() as conn:
            already_sent = conn.execute("SELECT 1 FROM booking_timeline WHERE booking_id=? AND event='Review requested' LIMIT 1", (booking_id,)).fetchone()
        if already_sent:
            automation.timeline(booking_id, "Review request skipped", "Review request was already sent for this booking.")
            return
        review_url = runtime_setting("REVIEW_URL", "") or f"{runtime_setting('PUBLIC_URL', PUBLIC_URL).rstrip('/')}/review-thanks?booking={booking_id}"
        customer_name = display_customer_name(booking["name"])
        send_workflow_email(booking_id, booking["email"], "How did we do?", f"Hello {customer_name},\n\nThank you for your payment. We would love your feedback: {review_url}")
        automation.timeline(booking_id, "Review requested", "Review request sent after final payment")
    else:
        raise RuntimeError(f"Unknown automation step: {step}")


POSTGRES_SCHEMES = ("postgres://", "postgresql://")
POSTGRES_ID_TABLES = {
    "bookings", "cleaners", "cleaner_applicants", "customers", "payments",
    "customer_reviews", "ai_conversations", "ai_messages", "automation_jobs",
    "booking_timeline", "cleaner_applicant_timeline", "cleaner_offers", "email_log", "cleaner_payouts",
    "automation_runs", "automation_logs", "automation_alerts", "recruitment_clicks"
}
POSTGRES_RESERVED_TABLES = {"workflow_config", "app_config", "sessions", "password_reset_tokens", "archived_stripe_sessions"}


def database_url():
    return os.environ.get("DATABASE_URL", "").strip()


def using_postgres():
    return database_url().startswith(POSTGRES_SCHEMES)


def normalise_postgres_url(value):
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


class DbRow:
    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = tuple(values)
        self._data = {column: self._values[index] for index, column in enumerate(self._columns)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._data[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._data.keys()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def items(self):
        return self._data.items()


class PgCursor:
    def __init__(self, cursor=None, rows=None, columns=None, lastrowid=None):
        self._cursor = cursor
        self._rows = rows
        self._columns = columns
        self.lastrowid = lastrowid

    def _convert(self, row):
        if row is None:
            return None
        if isinstance(row, DbRow):
            return row
        if isinstance(row, dict):
            return DbRow(row.keys(), row.values())
        columns = self._columns
        if columns is None and self._cursor and self._cursor.description:
            columns = [description.name for description in self._cursor.description]
        return DbRow(columns or [], row)

    def fetchone(self):
        if self._rows is not None:
            if not self._rows:
                return None
            return self._convert(self._rows.pop(0))
        return self._convert(self._cursor.fetchone())

    def fetchall(self):
        if self._rows is not None:
            rows, self._rows = self._rows, []
            return [self._convert(row) for row in rows]
        return [self._convert(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class PostgresConnection:
    def __init__(self, dsn):
        if psycopg is None:
            raise RuntimeError("PostgreSQL is selected with DATABASE_URL, but psycopg is not installed. Add requirements.txt dependencies and redeploy.")
        self._conn = psycopg.connect(normalise_postgres_url(dsn), autocommit=False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()

    def execute(self, sql, params=()):
        return self._execute(sql, params)

    def executemany(self, sql, seq_of_params):
        cursor = None
        for params in seq_of_params:
            cursor = self._execute(sql, params)
        return cursor or PgCursor(rows=[], columns=[])

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def _execute(self, sql, params=()):
        stripped = " ".join(sql.strip().split())
        lower = stripped.lower()

        if lower.startswith("pragma table_info"):
            table_name = re.search(r"pragma\s+table_info\((.+)\)", stripped, re.I).group(1).strip().strip('"')
            return self._postgres_table_info(table_name)

        if "from sqlite_master" in lower:
            return self._sqlite_master_query(stripped, params)

        translated = self._translate_sql(stripped)
        cursor = self._conn.cursor()
        cursor.execute(translated, params)
        lastrowid = None
        if cursor.description:
            rows = cursor.fetchall()
            columns = [description.name for description in cursor.description]
            if columns == ["id"] and rows and self._is_insert_returning_id(translated):
                lastrowid = rows[0][0]
            return PgCursor(rows=rows, columns=columns, lastrowid=lastrowid)
        return PgCursor(cursor=cursor, lastrowid=lastrowid)

    def _postgres_table_info(self, table_name):
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT column_name,data_type,is_nullable,column_default
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
        """, (table_name,))
        rows = []
        for index, (name, data_type, nullable, default) in enumerate(cursor.fetchall()):
            rows.append((index, name, data_type, 0 if nullable == "YES" else 1, default, 1 if default and "nextval" in default else 0))
        return PgCursor(rows=rows, columns=["cid", "name", "type", "notnull", "dflt_value", "pk"])

    def _sqlite_master_query(self, sql, params):
        lower = sql.lower()
        cursor = self._conn.cursor()
        if "select name" in lower:
            cursor.execute("""
                SELECT table_name AS name
                FROM information_schema.tables
                WHERE table_schema='public' AND table_type='BASE TABLE'
                ORDER BY table_name
            """)
            return PgCursor(rows=cursor.fetchall(), columns=["name"])
        if "select 1" in lower:
            table_name = params[0] if params else ""
            cursor.execute("""
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public' AND table_name=%s
                LIMIT 1
            """, (table_name,))
            return PgCursor(rows=cursor.fetchall(), columns=["?column?"])
        return PgCursor(rows=[], columns=[])

    def _translate_sql(self, sql):
        sql = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "SERIAL PRIMARY KEY", sql, flags=re.I)
        sql = re.sub(r"\s+REFERENCES\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)", "", sql, flags=re.I)
        sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.I)
        sql = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", sql, flags=re.I)
        sql = re.sub(r"\bORDER\s+BY\s+rowid\b", "ORDER BY 1", sql, flags=re.I)
        sql = self._append_conflict_clause(sql)
        sql = self._append_returning_id(sql)
        sql = sql.replace("?", "%s")
        return sql

    def _append_conflict_clause(self, sql):
        lower = sql.lower()
        if not lower.startswith("insert into") or " on conflict" in lower:
            return sql
        if "values" not in lower:
            return sql
        # Only add DO NOTHING for SQL that used SQLite's OR IGNORE/OR REPLACE before translation.
        # These known statements all have natural unique keys/primary keys.
        table_match = re.match(r"insert\s+into\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.I)
        table = table_match.group(1) if table_match else ""
        conflict_safe_tables = {"app_config", "workflow_config", "automation_jobs", "cleaner_offers", "payments", "archived_stripe_sessions", "cleaner_payouts"}
        if table in conflict_safe_tables:
            return sql + " ON CONFLICT DO NOTHING"
        return sql

    def _append_returning_id(self, sql):
        lower = sql.lower()
        if not lower.startswith("insert into") or " returning " in lower or " on conflict" in lower:
            return sql
        match = re.match(r"insert\s+into\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.I)
        if match and match.group(1) in POSTGRES_ID_TABLES:
            return sql + " RETURNING id"
        return sql

    def _is_insert_returning_id(self, sql):
        return sql.lower().startswith("insert into") and " returning id" in sql.lower()


def configured_database_path():
    selected, profiles = dashboard_database_profile()
    selected_path = Path(selected["path"]) if selected and selected.get("path") else DB
    selected_counts = selected.get("row_counts", {}) if selected else {}
    selected_total = sum(int(selected_counts.get(table, 0) or 0) for table in ("bookings", "payments", "cleaners"))

    configured_path = None
    for key in ("SPARKLES_DB_PATH", "SQLITE_DB_PATH", "DATABASE_PATH"):
        value = os.environ.get(key, "").strip()
        if value:
            configured_path = Path(value).expanduser()
            break
    database_url_path = sqlite_path_from_url(os.environ.get("DATABASE_URL", "").strip())
    if configured_path is None and database_url_path:
        configured_path = database_url_path
    if configured_path is None:
        for mount_key in ("RAILWAY_VOLUME_MOUNT_PATH", "VOLUME_MOUNT_PATH"):
            mount = os.environ.get(mount_key, "").strip()
            if mount:
                configured_path = Path(mount).expanduser() / "sparkles.db"
                break
    if configured_path is None:
        return selected_path

    try:
        configured_resolved = configured_path.resolve()
    except OSError:
        configured_resolved = configured_path.absolute()
    configured_profile = next((profile for profile in profiles if profile.get("path") == str(configured_resolved)), None)
    configured_counts = configured_profile.get("row_counts", {}) if configured_profile else {}
    configured_total = sum(int(configured_counts.get(table, 0) or 0) for table in ("bookings", "payments", "cleaners"))
    if selected_total > configured_total:
        return selected_path
    return configured_path


def connect():
    if using_postgres():
        return PostgresConnection(database_url())
    path = configured_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def table_exists(conn, table_name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone())


def table_count(conn, table_name, where="", params=()):
    if not table_exists(conn, table_name):
        return 0
    sql = f"SELECT COUNT(*) count FROM {quote_identifier(table_name)}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql, params).fetchone()
    return int(row["count"] or 0) if row else 0


def perform_fresh_launch_reset():
    """Archive old launch-test activity while preserving setup, auth config and payments."""
    now = utcnow().isoformat()
    archive_reason = f"Fresh launch reset on {now}"
    clear_tables = [
        "ai_messages",
        "ai_conversations",
        "automation_jobs",
        "booking_timeline",
        "cleaner_offers",
        "cleaner_applicants",
        "cleaner_applicant_timeline",
        "customer_reviews",
        "email_log",
        "password_reset_tokens",
    ]
    with connect() as conn:
        summary = {
            "database": "PostgreSQL DATABASE_URL" if using_postgres() else str(configured_database_path()),
            "bookings_archived": table_count(conn, "bookings", "archived_at IS NULL"),
            "cleaner_accounts_removed": table_count(conn, "cleaners"),
            "payments_preserved": table_count(conn, "payments"),
            "config_preserved": True,
            "admin_login_preserved": True,
            "stripe_email_config_preserved": True,
            "cleared_tables": {},
        }
        if table_exists(conn, "bookings"):
            conn.execute("""
                UPDATE bookings
                SET archived_at=?, archive_reason=?, is_test=1, cleaner_id=NULL, assigned_at=NULL
                WHERE archived_at IS NULL
            """, (now, archive_reason))
        for table_name in clear_tables:
            if not table_exists(conn, table_name):
                summary["cleared_tables"][table_name] = 0
                continue
            summary["cleared_tables"][table_name] = table_count(conn, table_name)
            conn.execute(f"DELETE FROM {quote_identifier(table_name)}")
        if table_exists(conn, "cleaners"):
            conn.execute("DELETE FROM cleaners")
    return summary


def sqlite_path_from_url(value):
    if not value:
        return None
    if value.startswith("sqlite:///"):
        path = value.removeprefix("sqlite:///")
        if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
            return Path(path)
        return ROOT / path
    if value.startswith("sqlite://"):
        return Path(value.removeprefix("sqlite://"))
    return None


def sqlite_candidate_paths():
    paths = []
    for key in ("SPARKLES_DB_PATH", "SQLITE_DB_PATH", "DATABASE_PATH"):
        value = os.environ.get(key, "").strip()
        if value:
            paths.append(Path(value))
    database_url_path = sqlite_path_from_url(os.environ.get("DATABASE_URL", "").strip())
    if database_url_path:
        paths.append(database_url_path)
    for mount_key in ("RAILWAY_VOLUME_MOUNT_PATH", "VOLUME_MOUNT_PATH"):
        mount = os.environ.get(mount_key, "").strip()
        if mount:
            paths.append(Path(mount) / "sparkles.db")
            paths.extend(Path(mount).glob("*.db") if Path(mount).exists() else [])
    paths.extend([DB, ROOT / "sparkles.db", Path("/data/sparkles.db"), Path("/app/data/sparkles.db"), Path("/app/sparkles.db")])
    for directory in (DATA, ROOT, Path("/data"), Path("/app/data"), Path("/app")):
        if directory.exists():
            paths.extend(directory.glob("*.db"))
            paths.extend(directory.glob("*.sqlite"))
            paths.extend(directory.glob("*.sqlite3"))
    unique = []
    seen = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser().absolute()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def open_sqlite(path, readonly=False):
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_database_profile(path):
    profile = {"path": str(path), "exists": path.exists(), "size_bytes": path.stat().st_size if path.exists() else 0, "tables": [], "row_counts": {}, "error": None}
    if not path.exists():
        return profile
    try:
        with open_sqlite(path, readonly=True) as conn:
            table_names = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
            profile["tables"] = table_names
            for table_name in table_names:
                safe_name = '"' + table_name.replace('"', '""') + '"'
                profile["row_counts"][table_name] = conn.execute(f"SELECT COUNT(*) count FROM {safe_name}").fetchone()["count"]
    except DB_ERROR_TYPES as error:
        profile["error"] = str(error)
    return profile


def dashboard_database_profile():
    profiles = [sqlite_database_profile(path) for path in sqlite_candidate_paths()]
    def score(profile):
        counts = profile.get("row_counts", {})
        core_total = sum(int(counts.get(table, 0) or 0) for table in ("bookings", "payments", "cleaners"))
        core_tables = sum(1 for table in ("bookings", "payments", "cleaners") if table in counts)
        preferred = 1 if profile["path"] == str(DB.resolve()) else 0
        return (1 if core_total > 0 else 0, core_total, core_tables, preferred, profile.get("size_bytes", 0))
    selected = sorted(profiles, key=score, reverse=True)[0] if profiles else sqlite_database_profile(DB)
    if score(selected)[0] == 0:
        selected = next((profile for profile in profiles if profile["path"] == str(DB.resolve())), selected)
    return selected, profiles


def runtime_setting(key, fallback=""):
    environment = os.environ.get(key)
    if environment not in (None, ""):
        return environment
    try:
        with connect() as conn:
            row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else fallback
    except DB_ERROR_TYPES:
        return fallback


AUTOPILOT_AUTOMATIONS = [
    {
        "key": "cleaner_recruitment",
        "name": "Cleaner Recruitment",
        "summary": "Track recruitment links, applications, AI scoring and cleaner invitation readiness.",
        "owner_trigger": "Only notify if applicants need review, follow-up or recruitment goes quiet.",
        "config": {
            "mode": "Dry run",
            "target_applicants_per_week": "10",
            "recruitment_area": "Cambridge and surrounding areas",
            "channels": "Facebook, WhatsApp, Indeed, Google Business Profile",
            "owner_alert_after_days_quiet": "3",
            "facebook_page_posting": "Disabled",
            "facebook_post_mode": "Dry run",
            "facebook_post_frequency": "Manual approval only",
        },
    },
    {
        "key": "booking_autopilot",
        "name": "Booking Autopilot",
        "summary": "Confirm paid bookings, find eligible cleaners and monitor automatic reassignment.",
        "owner_trigger": "Only notify if no eligible cleaner is available or reassignment fails.",
        "config": {
            "mode": "Live",
            "auto_assign_after_deposit": "Yes",
            "exclude_declined_cleaners": "Yes",
            "owner_alert_if_no_cleaner": "Yes",
        },
    },
    {
        "key": "cleaner_operations",
        "name": "Cleaner Operations",
        "summary": "Monitor cleaner reminders, on-my-way updates, rejections and no-show risk.",
        "owner_trigger": "Only notify if a cleaner rejects, misses acceptance or cannot be replaced.",
        "config": {
            "mode": "Live",
            "clean_reminder_hours_before": "24",
            "late_acceptance_warning_hours": "12",
            "owner_alert_on_rejection": "Yes",
        },
    },
    {
        "key": "customer_payment",
        "name": "Customer Payment",
        "summary": "Monitor deposits, final invoices, balance reminders and review requests.",
        "owner_trigger": "Only notify if payment fails, balance is overdue or a payment email fails.",
        "config": {
            "mode": "Live",
            "deposit_follow_up_hours": "24",
            "final_balance_follow_up_days": "2",
            "review_request_after_paid": "Yes",
        },
    },
    {
        "key": "owner_daily_briefing",
        "name": "Owner Daily Briefing",
        "summary": "Prepare a daily owner summary of bookings, payments and cleaner activity.",
        "owner_trigger": "Only notify if there is something needing owner intervention.",
        "config": {
            "mode": "Dry run",
            "briefing_time": "08:00",
            "include_revenue": "Yes",
            "include_attention_items": "Yes",
        },
    },
]

AUTOPILOT_WORKFLOW_STEPS = {
    "booking_autopilot": ("offer_cleaners", "send_confirmations"),
    "cleaner_operations": ("send_reminder",),
    "customer_payment": ("send_payment_confirmation", "send_abandoned_followup", "send_final_invoice", "send_review"),
}

LEGACY_AUTOPILOT_KEYS = {
    "booking_communications": "booking_autopilot",
    "customer_reminders": "cleaner_operations",
}


def autopilot_catalog():
    return {item["key"]: item for item in AUTOPILOT_AUTOMATIONS}


def ensure_autopilot_defaults(conn):
    now = utcnow().isoformat()
    for item in AUTOPILOT_AUTOMATIONS:
        existing = conn.execute("SELECT key FROM automation_settings WHERE key=?", (item["key"],)).fetchone()
        if not existing:
            legacy_key = next((old for old, new in LEGACY_AUTOPILOT_KEYS.items() if new == item["key"]), None)
            legacy = conn.execute("SELECT * FROM automation_settings WHERE key=?", (legacy_key,)).fetchone() if legacy_key else None
            enabled = legacy["enabled"] if legacy else 0
            config = autopilot_config(legacy["config_json"]) if legacy else {}
            config = {**item["config"], **config}
            conn.execute(
                """INSERT INTO automation_settings(key,name,summary,enabled,config_json,owner_trigger,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    item["key"],
                    item["name"],
                    item["summary"],
                    enabled,
                    json.dumps(config),
                    item["owner_trigger"],
                    now,
                    now,
                ),
            )
        else:
            current = dict(conn.execute("SELECT * FROM automation_settings WHERE key=?", (item["key"],)).fetchone())
            config = {**item["config"], **autopilot_config(current.get("config_json"))}
            conn.execute(
                """UPDATE automation_settings
                SET name=?, summary=?, owner_trigger=?, config_json=?, updated_at=?
                WHERE key=?""",
                (item["name"], item["summary"], item["owner_trigger"], json.dumps(config), now, item["key"]),
            )
        steps = autopilot_workflow_step_list(item["key"])
        if steps:
            try:
                placeholders = ",".join("?" for _ in steps)
                rows = conn.execute(f"SELECT enabled FROM workflow_config WHERE step IN ({placeholders})", list(steps)).fetchall()
                if rows:
                    live_enabled = 1 if all(row["enabled"] for row in rows) else 0
                    conn.execute("UPDATE automation_settings SET enabled=?,updated_at=? WHERE key=?", (live_enabled, now, item["key"]))
            except DB_ERROR_TYPES:
                pass


def autopilot_config(config_json):
    try:
        value = json.loads(config_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def autopilot_log(conn, key, event, detail="", level="Info", run_id=None):
    conn.execute(
        "INSERT INTO automation_logs(automation_key,run_id,event,detail,level,created_at) VALUES (?,?,?,?,?,?)",
        (key, run_id, event, detail, level, utcnow().isoformat()),
    )


def autopilot_alert_once(conn, key, title, detail, level="Needs attention"):
    existing = conn.execute(
        "SELECT id FROM automation_alerts WHERE automation_key=? AND title=? AND resolved_at IS NULL LIMIT 1",
        (key, title),
    ).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO automation_alerts(automation_key,title,detail,level,created_at) VALUES (?,?,?,?,?)",
        (key, title, detail, level, utcnow().isoformat()),
    )


def autopilot_workflow_step_list(key):
    return AUTOPILOT_WORKFLOW_STEPS.get(key, ())


def autopilot_workflow_where(key):
    steps = autopilot_workflow_step_list(key)
    if not steps:
        return "", []
    placeholders = ",".join("?" for _ in steps)
    return f"step IN ({placeholders})", list(steps)


def autopilot_count_runs(conn, key, status):
    return conn.execute(
        "SELECT COUNT(*) count FROM automation_runs WHERE automation_key=? AND status=?",
        (key, status),
    ).fetchone()["count"]


def autopilot_count_jobs(conn, key, status):
    where, params = autopilot_workflow_where(key)
    if not where:
        return 0
    return conn.execute(
        f"SELECT COUNT(*) count FROM automation_jobs WHERE {where} AND status=?",
        [*params, status],
    ).fetchone()["count"]


def autopilot_next_run(conn, key):
    where, params = autopilot_workflow_where(key)
    if where:
        row = conn.execute(
            f"""SELECT MIN(run_after) next_run FROM automation_jobs
            WHERE {where} AND status IN ('Pending','Retrying')""",
            params,
        ).fetchone()
        if row and row["next_run"]:
            return row["next_run"]
    if key == "owner_daily_briefing":
        setting = conn.execute("SELECT config_json FROM automation_settings WHERE key=?", (key,)).fetchone()
        config = autopilot_config(setting["config_json"] if setting else "{}")
        return f"Daily at {config.get('briefing_time', '08:00')}"
    return "Runs when triggered"


def autopilot_last_run(conn, key):
    where, params = autopilot_workflow_where(key)
    candidates = []
    run = conn.execute(
        "SELECT MAX(COALESCE(finished_at, started_at)) value FROM automation_runs WHERE automation_key=?",
        (key,),
    ).fetchone()
    if run and run["value"]:
        candidates.append(run["value"])
    if where:
        job = conn.execute(
            f"SELECT MAX(updated_at) value FROM automation_jobs WHERE {where}",
            params,
        ).fetchone()
        if job and job["value"]:
            candidates.append(job["value"])
    return max(candidates) if candidates else ""


def autopilot_attention_count(conn, key):
    return conn.execute(
        "SELECT COUNT(*) count FROM automation_alerts WHERE automation_key=? AND resolved_at IS NULL",
        (key,),
    ).fetchone()["count"]


def autopilot_item_stats(conn, key):
    success = autopilot_count_runs(conn, key, "Completed") + autopilot_count_jobs(conn, key, "Completed")
    failures = autopilot_count_runs(conn, key, "Failed") + autopilot_count_jobs(conn, key, "Failed")
    return {
        "last_run": autopilot_last_run(conn, key),
        "next_run": autopilot_next_run(conn, key),
        "success_count": success,
        "failure_count": failures,
        "needs_attention_count": autopilot_attention_count(conn, key),
    }


RECRUITMENT_CHANNELS = [
    ("facebook", "Facebook"),
    ("whatsapp", "WhatsApp"),
    ("indeed", "Indeed"),
    ("google-business-profile", "Google Business Profile"),
    ("gumtree", "Gumtree"),
    ("referral", "Referral"),
    ("qr-code", "QR code"),
]


def normalise_recruitment_source(value):
    source = re.sub(r"[^a-z0-9\-]+", "-", str(value or "website").strip().lower()).strip("-")
    return source[:80] or "website"


def recruitment_link(source):
    return f"{public_url().rstrip('/')}/r/cleaners/{urllib.parse.quote(normalise_recruitment_source(source))}"


def recruitment_apply_link(source):
    return f"{public_url().rstrip('/')}/become-a-cleaner?source={urllib.parse.quote(normalise_recruitment_source(source))}"


def indeed_applicant_identifier(invite_code):
    compact = re.sub(r"[^A-Za-z0-9]", "", str(invite_code or ""))[:10].upper()
    return f"IND-{compact}"


def indeed_application_link(invite_code):
    query = urllib.parse.urlencode({"source": "indeed", "applicant": str(invite_code or "").strip()})
    return f"{public_url().rstrip('/')}/become-a-cleaner?{query}"


def indeed_invitation_message(name, invite_code):
    display_name = display_customer_name(name) or "there"
    link = indeed_application_link(invite_code)
    return (
        f"Hi {display_name},\n\n"
        "Thanks for your interest in cleaner opportunities with Sparkles Cleaning Cambridge. "
        "To continue, please complete our short Sparkles application using your personal link:\n\n"
        f"{link}\n\n"
        "You can choose your availability, services and travel area. Completing the form does not guarantee approval, "
        "and Sparkles will review your application before any cleaner account is created.\n\n"
        "Smiles Come Standard."
    )


def recruitment_share_text(source="facebook", area="Cambridge and surrounding areas"):
    link = recruitment_link(source)
    return (
        f"Sparkles Cleaning Cambridge is looking for reliable cleaners in {area}.\n\n"
        "Flexible local cleaning work, choose your availability, friendly support and competitive self-employed rates.\n\n"
        f"Apply here:\n{link}\n\n"
        "Smiles Come Standard."
    )


def meta_page_config():
    """Read Meta credentials from the process environment only.

    The Page token must never be saved in app_config or returned to a browser.
    """
    return {
        "page_id": META_PAGE_ID,
        "access_token": META_PAGE_ACCESS_TOKEN,
        "graph_api_version": META_GRAPH_API_VERSION,
    }


def facebook_recruitment_draft(config):
    area = str(config.get("recruitment_area") or "Cambridge and surrounding areas").strip()
    message = recruitment_share_text("facebook", area)
    link = recruitment_link("facebook")
    draft_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return {"message": message, "link": link, "hash": draft_hash}


def facebook_recruitment_state(config):
    meta = meta_page_config()
    draft = facebook_recruitment_draft(config)
    approved = hmac.compare_digest(
        str(config.get("_facebook_approved_draft_hash") or ""),
        draft["hash"],
    )
    published = hmac.compare_digest(
        str(config.get("_facebook_last_published_hash") or ""),
        draft["hash"],
    )
    posting_enabled = str(config.get("facebook_page_posting") or "Disabled").lower() == "enabled"
    mode = str(config.get("facebook_post_mode") or "Dry run")
    return {
        "configured": bool(meta["page_id"] and meta["access_token"]),
        "page_id_configured": bool(meta["page_id"]),
        "token_configured": bool(meta["access_token"]),
        "page_id": meta["page_id"],
        "graph_api_version": meta["graph_api_version"],
        "posting_enabled": posting_enabled,
        "mode": mode,
        "frequency": str(config.get("facebook_post_frequency") or "Manual approval only"),
        "draft": draft,
        "approved": approved,
        "approved_at": config.get("_facebook_approved_at", ""),
        "published": published,
        "last_published_at": config.get("_facebook_last_published_at", ""),
        "last_post_id": config.get("_facebook_last_post_id", ""),
        "publish_state": config.get("_facebook_publish_state", "Draft"),
        "can_publish": bool(posting_enabled and approved and not published),
    }


def safe_meta_error(status, body, access_token=""):
    message = "Meta rejected the request."
    error_type = ""
    code = ""
    try:
        payload = json.loads(body or "{}")
        detail = payload.get("error", {}) if isinstance(payload, dict) else {}
        if isinstance(detail, dict):
            message = str(detail.get("message") or message)
            error_type = str(detail.get("type") or "")
            code = str(detail.get("code") or "")
    except (TypeError, json.JSONDecodeError):
        if body:
            message = str(body)
    if access_token:
        message = message.replace(access_token, "[redacted]")
    return {
        "status": int(status or 0),
        "message": message[:500],
        "type": error_type[:120],
        "code": code[:40],
    }


def facebook_graph_request(method, resource, fields=None):
    config = meta_page_config()
    if not config["page_id"] or not config["access_token"]:
        raise ValueError("Add META_PAGE_ID and META_PAGE_ACCESS_TOKEN in Railway before connecting Facebook.")
    version = re.sub(r"[^a-zA-Z0-9.]", "", config["graph_api_version"]) or "v25.0"
    resource = str(resource or "").strip("/")
    url = f"https://graph.facebook.com/{version}/{resource}"
    values = {str(key): str(value) for key, value in (fields or {}).items()}
    values["access_token"] = config["access_token"]
    encoded = urllib.parse.urlencode(values).encode("utf-8")
    request = urllib.request.Request(
        f"{url}?{encoded.decode('utf-8')}" if method == "GET" else url,
        data=None if method == "GET" else encoded,
        method=method,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            payload = json.loads(body or "{}")
            return payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        detail = safe_meta_error(error.code, body, config["access_token"])
        raise RuntimeError(json.dumps(detail)) from None
    except urllib.error.URLError as error:
        raise RuntimeError(json.dumps({"status": 0, "message": f"Meta connection failed: {error.reason}", "type": "NetworkError", "code": ""})) from None


def facebook_test_page_connection():
    config = meta_page_config()
    payload = facebook_graph_request("GET", config["page_id"], {"fields": "id,name"})
    if str(payload.get("id") or "") != config["page_id"]:
        raise RuntimeError(json.dumps({"status": 0, "message": "Meta returned a different Page than the configured Page ID.", "type": "PageMismatch", "code": ""}))
    return {"id": payload.get("id", ""), "name": payload.get("name", "")}


def facebook_publish_recruitment(draft):
    config = meta_page_config()
    payload = facebook_graph_request("POST", f"{config['page_id']}/feed", {"message": draft["message"]})
    post_id = str(payload.get("id") or "")
    if not post_id:
        raise RuntimeError(json.dumps({"status": 0, "message": "Meta did not return a post ID.", "type": "InvalidResponse", "code": ""}))
    return post_id


def update_autopilot_config_fields(conn, key, updates):
    row = conn.execute("SELECT config_json FROM automation_settings WHERE key=?", (key,)).fetchone()
    if not row:
        raise ValueError("Automation settings were not found.")
    config = autopilot_config(row["config_json"])
    config.update(updates)
    conn.execute(
        "UPDATE automation_settings SET config_json=?,updated_at=? WHERE key=?",
        (json.dumps(config), utcnow().isoformat(), key),
    )
    return config


def autopilot_snapshot(conn, key):
    if key == "cleaner_recruitment":
        applicants = conn.execute("SELECT COUNT(*) count FROM cleaner_applicants").fetchone()["count"]
        new_applicants = conn.execute("SELECT COUNT(*) count FROM cleaner_applicants WHERE status IN ('New','Review','Ready to contact')").fetchone()["count"]
        active_cleaners = conn.execute("SELECT COUNT(*) count FROM cleaners WHERE active=1").fetchone()["count"]
        clicks = table_count(conn, "recruitment_clicks")
        incomplete = conn.execute("""SELECT COUNT(*) count FROM cleaner_applicants
            WHERE status IN ('New','Review','Ready to contact')
            AND (email='' OR phone='' OR postcode='' OR services='' OR availability='')""").fetchone()["count"]
        if new_applicants:
            autopilot_alert_once(
                conn,
                "cleaner_recruitment",
                "Cleaner applicants need review",
                f"{new_applicants} applicant(s) are waiting in the recruitment pipeline. Recommended action: open /admin/cleaner-applicants and review strong applicants.",
            )
        if incomplete:
            autopilot_alert_once(
                conn,
                "cleaner_recruitment",
                "Incomplete cleaner applications need follow-up",
                f"{incomplete} applicant(s) are missing key details. Sparkles has not rejected them automatically. Recommended action: request the missing details.",
            )
        return f"{applicants} applicants tracked, {new_applicants} awaiting review, {incomplete} incomplete, {active_cleaners} active cleaners, {clicks} recruitment link visit(s)."
    if key == "booking_autopilot":
        paid_unassigned = conn.execute("""SELECT COUNT(*) count FROM bookings
            WHERE archived_at IS NULL
            AND cleaner_id IS NULL
            AND status NOT IN ('Completed','Cancelled')
            AND payment_status IN ('Deposit Paid','Balance Due','Paid in Full')""").fetchone()["count"]
        failed_assignments = autopilot_count_jobs(conn, key, "Failed")
        if paid_unassigned:
            autopilot_alert_once(
                conn,
                "booking_autopilot",
                "Paid bookings need cleaner assignment",
                f"{paid_unassigned} paid booking(s) do not yet have a cleaner. Sparkles will use eligible cleaners first; if none are available, assign manually from /admin/bookings.",
            )
        return f"{paid_unassigned} paid booking(s) waiting for assignment, {failed_assignments} failed assignment workflow(s)."
    if key == "cleaner_operations":
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        tomorrow_bookings = conn.execute("SELECT COUNT(*) count FROM bookings WHERE preferred_date=? AND archived_at IS NULL", (tomorrow,)).fetchone()["count"]
        declined = table_count(conn, "cleaner_offers", "status='Declined'")
        in_progress = conn.execute("SELECT COUNT(*) count FROM bookings WHERE status='In Progress' AND archived_at IS NULL").fetchone()["count"]
        return f"{tomorrow_bookings} booking(s) scheduled for tomorrow, {in_progress} in progress, {declined} cleaner rejection record(s)."
    if key == "customer_payment":
        deposit_due = conn.execute("SELECT COUNT(*) count FROM bookings WHERE payment_status='Deposit Due' AND archived_at IS NULL").fetchone()["count"]
        balance_due = conn.execute("SELECT COUNT(*) count FROM bookings WHERE payment_status='Balance Due' AND archived_at IS NULL").fetchone()["count"]
        failed_emails = table_count(conn, "email_log", "status IN ('Failed','Error')")
        failed_payment_jobs = autopilot_count_jobs(conn, key, "Failed")
        if failed_emails:
            autopilot_alert_once(
                conn,
                "customer_payment",
                "Email delivery failure detected",
                f"{failed_emails} failed email record(s) exist. Recommended action: open /admin/diagnostics and check email provider logs.",
            )
        return f"{deposit_due} bookings awaiting deposit, {balance_due} balances due, {failed_emails} failed email records, {failed_payment_jobs} failed payment workflow(s)."
    if key == "owner_daily_briefing":
        today = datetime.now().date().isoformat()
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        today_bookings = conn.execute("SELECT COUNT(*) count FROM bookings WHERE preferred_date=? AND archived_at IS NULL", (today,)).fetchone()["count"]
        tomorrow_bookings = conn.execute("SELECT COUNT(*) count FROM bookings WHERE preferred_date=? AND archived_at IS NULL", (tomorrow,)).fetchone()["count"]
        unassigned = conn.execute("SELECT COUNT(*) count FROM bookings WHERE cleaner_id IS NULL AND archived_at IS NULL AND status NOT IN ('Completed','Cancelled')").fetchone()["count"]
        balances = conn.execute("SELECT COUNT(*) count FROM bookings WHERE payment_status='Balance Due' AND archived_at IS NULL").fetchone()["count"]
        applicants = conn.execute("SELECT COUNT(*) count FROM cleaner_applicants WHERE status IN ('New','Review','Ready to contact')").fetchone()["count"]
        open_attention = conn.execute("SELECT COUNT(*) count FROM automation_alerts WHERE resolved_at IS NULL").fetchone()["count"]
        if not open_attention:
            return f"No urgent action required. {today_bookings} job(s) today, {tomorrow_bookings} tomorrow, {unassigned} unassigned, {balances} outstanding balance(s), {applicants} applicant(s) awaiting review."
        return f"{today_bookings} job(s) today, {tomorrow_bookings} tomorrow, {unassigned} unassigned, {balances} outstanding balance(s), {applicants} applicant(s), {open_attention} attention item(s)."
    return "Dry run completed."


def autopilot_payload():
    with connect() as conn:
        ensure_autopilot_defaults(conn)
        order = {item["key"]: index for index, item in enumerate(AUTOPILOT_AUTOMATIONS)}
        settings = []
        catalog_keys = set(order)
        facebook = {}
        for row in conn.execute("SELECT * FROM automation_settings ORDER BY key").fetchall():
            item = dict(row)
            if item.get("key") not in catalog_keys:
                continue
            item["enabled"] = bool(item.get("enabled"))
            full_config = autopilot_config(item.get("config_json"))
            if item.get("key") == "cleaner_recruitment":
                facebook = facebook_recruitment_state(full_config)
            item["config"] = {key: value for key, value in full_config.items() if not str(key).startswith("_")}
            item["mode"] = full_config.get("mode", "Dry run")
            item.update(autopilot_item_stats(conn, item["key"]))
            item.pop("config_json", None)
            settings.append(item)
        settings.sort(key=lambda item: order.get(item["key"], 999))
        logs = [dict(row) for row in conn.execute("SELECT * FROM automation_logs ORDER BY id DESC LIMIT 80").fetchall()]
        runs = [dict(row) for row in conn.execute("SELECT * FROM automation_runs ORDER BY id DESC LIMIT 20").fetchall()]
        alerts = [dict(row) for row in conn.execute("SELECT * FROM automation_alerts WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 20").fetchall()]
    return {"automations": settings, "logs": logs, "runs": runs, "alerts": alerts, "facebook": facebook}


def initialise():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                address TEXT NOT NULL,
                postcode TEXT NOT NULL,
                clean_type TEXT NOT NULL,
                bedrooms INTEGER NOT NULL,
                bathrooms INTEGER NOT NULL,
                preferred_date TEXT NOT NULL,
                preferred_time TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                photos TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'New',
                created_at TEXT NOT NULL
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(bookings)")}
        if "cleaner_id" not in columns:
            conn.execute("ALTER TABLE bookings ADD COLUMN cleaner_id INTEGER REFERENCES cleaners(id)")
        if "assigned_at" not in columns:
            conn.execute("ALTER TABLE bookings ADD COLUMN assigned_at TEXT")
        payment_columns = {
            "total_amount": "INTEGER NOT NULL DEFAULT 0",
            "deposit_amount": "INTEGER NOT NULL DEFAULT 0",
            "balance_amount": "INTEGER NOT NULL DEFAULT 0",
            "payment_status": "TEXT NOT NULL DEFAULT 'Deposit Due'",
            "stripe_customer_id": "TEXT",
            "stripe_invoice_id": "TEXT",
            "deposit_checkout_session_id": "TEXT",
            "deposit_checkout_url": "TEXT",
            "balance_payment_url": "TEXT",
            "quote_token": "TEXT",
            "quote_status": "TEXT NOT NULL DEFAULT 'Pending'"
        }
        for column, definition in payment_columns.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE bookings ADD COLUMN {column} {definition}")
        if "customer_id" not in columns:
            conn.execute("ALTER TABLE bookings ADD COLUMN customer_id INTEGER REFERENCES customers(id)")
        cleaner_workflow_columns = {
            "accepted_at": "TEXT",
            "on_my_way_at": "TEXT",
            "started_at": "TEXT",
            "completed_at": "TEXT",
            "declined_at": "TEXT",
            "before_photos": "TEXT NOT NULL DEFAULT '[]'",
            "after_photos": "TEXT NOT NULL DEFAULT '[]'",
            "cleaner_notes": "TEXT NOT NULL DEFAULT ''"
        }
        for column, definition in cleaner_workflow_columns.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE bookings ADD COLUMN {column} {definition}")
        cleanup_columns = {
            "is_test": "INTEGER NOT NULL DEFAULT 0",
            "archived_at": "TEXT",
            "archive_reason": "TEXT NOT NULL DEFAULT ''"
        }
        columns = {row[1] for row in conn.execute("PRAGMA table_info(bookings)")}
        for column, definition in cleanup_columns.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE bookings ADD COLUMN {column} {definition}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archived_stripe_sessions (
                session_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL DEFAULT '',
                archived_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cleaners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                postcode TEXT NOT NULL,
                travel_radius REAL NOT NULL,
                hourly_rate REAL NOT NULL,
                availability TEXT NOT NULL,
                services TEXT NOT NULL,
                dbs_status TEXT NOT NULL,
                insurance_status TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        cleaner_columns = {row[1] for row in conn.execute("PRAGMA table_info(cleaners)")}
        if "password_hash" not in cleaner_columns:
            conn.execute("ALTER TABLE cleaners ADD COLUMN password_hash TEXT")
        cleaner_extra_columns = {
            "identity_verified": "INTEGER NOT NULL DEFAULT 0",
            "right_to_work_verified": "INTEGER NOT NULL DEFAULT 0",
            "proof_of_address_verified": "INTEGER NOT NULL DEFAULT 0",
            "travel_method": "TEXT NOT NULL DEFAULT 'Unknown'",
            "driving_licence_status": "TEXT NOT NULL DEFAULT 'Not provided'",
            "has_own_vehicle": "INTEGER NOT NULL DEFAULT 0",
        }
        cleaner_columns = {row[1] for row in conn.execute("PRAGMA table_info(cleaners)")}
        for column, definition in cleaner_extra_columns.items():
            if column not in cleaner_columns:
                conn.execute(f"ALTER TABLE cleaners ADD COLUMN {column} {definition}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cleaner_applicants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                postcode TEXT NOT NULL,
                experience TEXT NOT NULL DEFAULT '',
                travel_radius REAL NOT NULL DEFAULT 5,
                hourly_rate REAL NOT NULL DEFAULT 0,
                availability TEXT NOT NULL DEFAULT '[]',
                services TEXT NOT NULL DEFAULT '[]',
                dbs_status TEXT NOT NULL DEFAULT 'Unknown',
                insurance_status TEXT NOT NULL DEFAULT 'Unknown',
                source TEXT NOT NULL DEFAULT 'Website',
                status TEXT NOT NULL DEFAULT 'New',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_cleaner_id INTEGER REFERENCES cleaners(id)
            )
        """)
        conn.execute("""CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        applicant_extra_columns = {
            "identity_verified": "INTEGER NOT NULL DEFAULT 0",
            "right_to_work_verified": "INTEGER NOT NULL DEFAULT 0",
            "proof_of_address_verified": "INTEGER NOT NULL DEFAULT 0",
            "travel_method": "TEXT NOT NULL DEFAULT 'Unknown'",
            "driving_licence_status": "TEXT NOT NULL DEFAULT 'Not provided'",
            "has_own_vehicle": "INTEGER NOT NULL DEFAULT 0",
            "right_to_work_status": "TEXT NOT NULL DEFAULT 'Not provided'",
            "short_intro": "TEXT NOT NULL DEFAULT ''",
            "id_uploads": "TEXT NOT NULL DEFAULT '[]'",
            "proof_of_address_uploads": "TEXT NOT NULL DEFAULT '[]'",
            "driving_licence_uploads": "TEXT NOT NULL DEFAULT '[]'",
            "external_reference": "TEXT NOT NULL DEFAULT ''",
            "invitation_code": "TEXT",
            "invitation_status": "TEXT NOT NULL DEFAULT 'Not invited'",
            "invitation_count": "INTEGER NOT NULL DEFAULT 0",
            "invitation_created_at": "TEXT",
            "invitation_opened_at": "TEXT",
            "application_completed_at": "TEXT",
            "ai_score": "INTEGER",
            "ai_recommendation": "TEXT",
            "ai_scored_at": "TEXT",
            "interview_status": "TEXT NOT NULL DEFAULT 'Not scheduled'",
            "interview_updated_at": "TEXT",
            "converted_at": "TEXT",
        }
        applicant_columns = {row[1] for row in conn.execute("PRAGMA table_info(cleaner_applicants)")}
        for column, definition in applicant_extra_columns.items():
            if column not in applicant_columns:
                conn.execute(f"ALTER TABLE cleaner_applicants ADD COLUMN {column} {definition}")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_cleaner_applicants_invitation_code
            ON cleaner_applicants(invitation_code)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS cleaner_applicant_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_id INTEGER NOT NULL REFERENCES cleaner_applicants(id),
            event TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            level TEXT NOT NULL DEFAULT 'Info',
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            subject_id INTEGER,
            email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            subject_id INTEGER,
            email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL REFERENCES bookings(id),
            payment_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'gbp',
            status TEXT NOT NULL,
            provider_payment_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS cleaner_payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
            cleaner_id INTEGER NOT NULL REFERENCES cleaners(id),
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'gbp',
            status TEXT NOT NULL DEFAULT 'Pending',
            estimated_hours REAL NOT NULL DEFAULT 0,
            hourly_rate REAL NOT NULL DEFAULT 0,
            paid_at TEXT,
            paid_method TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS customer_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER REFERENCES bookings(id),
            customer_name TEXT NOT NULL DEFAULT '',
            rating INTEGER NOT NULL DEFAULT 5,
            comment TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'Manual',
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '', is_secret INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL DEFAULT '',
            customer_email TEXT NOT NULL DEFAULT '',
            customer_phone TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'AI Active',
            admin_takeover INTEGER NOT NULL DEFAULT 0,
            booking_id INTEGER REFERENCES bookings(id),
            collected_details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id),
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS automation_settings (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 0,
            config_json TEXT NOT NULL DEFAULT '{}',
            owner_trigger TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS automation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            automation_key TEXT NOT NULL,
            status TEXT NOT NULL,
            triggered_by TEXT NOT NULL DEFAULT 'manual',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            summary TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS automation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            automation_key TEXT NOT NULL,
            run_id INTEGER,
            event TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            level TEXT NOT NULL DEFAULT 'Info',
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS automation_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            automation_key TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            level TEXT NOT NULL DEFAULT 'Needs attention',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS recruitment_clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'website',
            landing_url TEXT NOT NULL DEFAULT '',
            referrer TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""")
        defaults = [
            ("COMPANY_NAME", "Sparkles Cleaning Cambridge", 0), ("COMPANY_EMAIL", "", 0),
            ("COMPANY_PHONE", "", 0), ("BUSINESS_ADDRESS", "", 0), ("PUBLIC_URL", PUBLIC_URL, 0),
            ("STRIPE_SECRET_KEY", "", 1), ("STRIPE_WEBHOOK_SECRET", "", 1),
            ("SMTP_HOST", "", 0), ("SMTP_PORT", "587", 0), ("SMTP_USER", "", 0),
            ("SMTP_PASSWORD", "", 1), ("SMTP_FROM", SMTP_FROM, 0), ("EMAIL_FROM", EMAIL_FROM, 0), ("EMAIL_PROVIDER", "", 0),
            ("RESEND_API_KEY", "", 1), ("SENDGRID_API_KEY", "", 1), ("REVIEW_URL", "", 0),
            ("LOGO_URL", "", 0), ("ADMIN_EMAIL", "", 0), ("ADMIN_PASSWORD_HASH", "", 1),
            ("AI_BUSINESS_HOURS", DEFAULT_BUSINESS_HOURS, 0), ("AI_SERVICE_AREAS", DEFAULT_SERVICE_AREAS, 0),
            ("AI_PRICING_JSON", json.dumps(DEFAULT_AI_PRICING), 0), ("PRICING_VERSION", PRICING_VERSION, 0),
            ("AI_RESPONSES_JSON", json.dumps(DEFAULT_AI_RESPONSES), 0)
        ]
        conn.executemany("INSERT OR IGNORE INTO app_config(key,value,is_secret,updated_at) VALUES (?,?,?,?)", [(k,v,s,datetime.now(timezone.utc).isoformat()) for k,v,s in defaults])
        pricing_json = json.dumps(DEFAULT_AI_PRICING)
        pricing_config = conn.execute("SELECT value FROM app_config WHERE key='AI_PRICING_JSON'").fetchone()
        pricing_version = conn.execute("SELECT value FROM app_config WHERE key='PRICING_VERSION'").fetchone()
        if (
            not pricing_config
            or pricing_config["value"] != pricing_json
            or not pricing_version
            or pricing_version["value"] != PRICING_VERSION
        ):
            now = utcnow().isoformat()
            conn.execute("UPDATE app_config SET value=?,updated_at=? WHERE key='AI_PRICING_JSON'", (pricing_json, now))
            conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('PRICING_VERSION',?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (PRICING_VERSION, 0, now))
        admin_email = conn.execute("SELECT value FROM app_config WHERE key='ADMIN_EMAIL'").fetchone()
        admin_hash = conn.execute("SELECT value FROM app_config WHERE key='ADMIN_PASSWORD_HASH'").fetchone()
        if not (admin_email and admin_email["value"]) and not (admin_hash and admin_hash["value"]):
            conn.execute("UPDATE app_config SET value=?,updated_at=? WHERE key='ADMIN_EMAIL'", (BOOTSTRAP_ADMIN_EMAIL, utcnow().isoformat()))
            admin_email = conn.execute("SELECT value FROM app_config WHERE key='ADMIN_EMAIL'").fetchone()
        if BOOTSTRAP_ADMIN_PASSWORD:
            now = utcnow().isoformat()
            conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('ADMIN_EMAIL',?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (BOOTSTRAP_ADMIN_EMAIL, 0, now))
            conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('ADMIN_PASSWORD_HASH',?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (hash_password(BOOTSTRAP_ADMIN_PASSWORD), 1, now))
            conn.execute("DELETE FROM sessions WHERE role='admin'")
            logger.info("Bootstrap admin email and password hash applied from environment")
        ensure_autopilot_defaults(conn)
        automation.initialise(conn)
        existing = conn.execute("SELECT id,clean_type,bedrooms,bathrooms FROM bookings WHERE total_amount=0").fetchall()
        for booking in existing:
            total = quote_pence(booking["clean_type"], booking["bedrooms"], booking["bathrooms"])
            deposit = round(total * .25)
            conn.execute("UPDATE bookings SET total_amount=?,deposit_amount=?,balance_amount=? WHERE id=?", (total, deposit, total-deposit, booking["id"]))


class Handler(BaseHTTPRequestHandler):
    server_version = "Sparkles/1.0"

    def log_message(self, fmt, *args):
        logger.info(json.dumps({"client": self.client_address[0], "request": fmt % args}))

    def setup_authorized(self):
        configured = runtime_setting("ADMIN_SETUP_TOKEN", ADMIN_SETUP_TOKEN)
        supplied = self.headers.get("X-Setup-Token", "") or urllib.parse.parse_qs(urlparse(self.path).query).get("token", [""])[0]
        if configured:
            return hmac.compare_digest(configured, supplied)
        return self.client_address[0] in ("127.0.0.1", "::1")

    def cookies(self):
        values = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                values[key] = urllib.parse.unquote(value)
        return values

    def current_session(self):
        token = self.cookies().get(SESSION_COOKIE, "")
        if not token:
            return None
        with connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?", (token_hash(token), utcnow().isoformat())).fetchone()
        return dict(row) if row else None

    def is_admin(self):
        session = self.current_session()
        return bool(session and session["role"] == "admin")

    def is_cleaner(self):
        session = self.current_session()
        return bool(session and session["role"] == "cleaner")

    def is_customer(self):
        session = self.current_session()
        return bool(session and session["role"] == "customer")

    def require_admin(self):
        if self.is_admin():
            return True
        self.send_json({"error": "Admin login required."}, 401)
        return False

    def create_session(self, role, subject_id, email):
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with connect() as conn:
            conn.execute("INSERT INTO sessions(token_hash,role,subject_id,email,expires_at,created_at) VALUES (?,?,?,?,?,?)", (token_hash(token), role, subject_id, email, (now + timedelta(days=SESSION_DAYS)).isoformat(), now.isoformat()))
        return token

    def clear_session(self):
        token = self.cookies().get(SESSION_COOKIE, "")
        if token:
            with connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))

    def request_is_secure(self):
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
        forwarded = self.headers.get("Forwarded", "").lower()
        return forwarded_proto == "https" or "proto=https" in forwarded or public_url().startswith("https://")

    def cookie_attributes(self):
        attrs = [f"HttpOnly", "SameSite=Lax", "Path=/", f"Max-Age={SESSION_DAYS * 86400}"]
        if self.request_is_secure():
            attrs.append("Secure")
        return "; ".join(attrs)

    def auth_cookie(self, token):
        return f"{SESSION_COOKIE}={urllib.parse.quote(token)}; {self.cookie_attributes()}"

    def expired_cookie(self):
        attrs = ["HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=0"]
        if self.request_is_secure():
            attrs.append("Secure")
        return f"{SESSION_COOKIE}=; {'; '.join(attrs)}"

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def send_json(self, data, status=200, headers=None):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path):
        if not path.is_file():
            return self.send_error(404)
        data = path.read_bytes()
        if path == PUBLIC / "styles.css" and (PUBLIC / "cleaner.css").is_file():
            data += b"\n" + (PUBLIC / "cleaner.css").read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() == ".html":
            text = data.decode("utf-8", "replace")
            if "/sparkles-menu.css" not in text:
                text = text.replace("</head>", '<link rel="stylesheet" href="/sparkles-menu.css"></head>')
            if "/sparkles-menu.js" not in text:
                text = text.replace("</body>", '<script src="/sparkles-menu.js"></script></body>')
            data = text.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            return self.send_json({"status": "ok", "service": "sparkles", "time": datetime.now(timezone.utc).isoformat()})
        if path == "/readyz":
            try:
                with connect() as conn:
                    conn.execute("SELECT 1").fetchone()
                return self.send_json({"status": "ready", "database": "ok"})
            except DB_ERROR_TYPES:
                return self.send_json({"status": "not_ready", "database": "error"}, 503)
        if path in ("/login", "/login/"):
            return self.redirect("/login.html")
        if path == "/api/auth/me":
            session = self.current_session()
            return self.send_json({"authenticated": bool(session), "session": session})
        if path == "/api/config":
            if not (self.is_admin() or self.setup_authorized()):
                return self.send_json({"error": "Setup authorization required."}, 401)
            with connect() as conn:
                rows = conn.execute("SELECT key,value,is_secret,updated_at FROM app_config ORDER BY key").fetchall()
            values = {row["key"]: ("••••••••" if row["is_secret"] and row["value"] else row["value"]) for row in rows}
            values.pop("ADMIN_PASSWORD_HASH", None)
            values["ADMIN_CONFIGURED"] = admin_configured()
            values["SMTP_CONFIGURED"] = bool(runtime_setting("SMTP_HOST", SMTP_HOST))
            provider = email_provider_config()
            values["EMAIL_CONFIGURED"] = (
                (provider["provider"] == "resend" and provider["resend_configured"]) or
                (provider["provider"] == "sendgrid" and provider["sendgrid_configured"]) or
                (provider["provider"] == "smtp" and bool(runtime_setting("SMTP_HOST", SMTP_HOST)))
            )
            values["STRIPE_CONFIGURED"] = bool(runtime_setting("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY))
            return self.send_json(values)
        if path == "/api/ai-office/settings":
            if not self.require_admin():
                return
            return self.send_json(ai_settings())
        if path == "/api/admin/dashboard":
            if not self.require_admin():
                return
            return self.owner_dashboard()
        if path == "/api/admin/autopilot":
            if not self.require_admin():
                return
            return self.send_json(autopilot_payload())
        if path == "/api/admin/launch-console":
            if not self.require_admin():
                return
            return self.launch_console()
        if path == "/api/admin/diagnostics":
            if not self.require_admin():
                return
            return self.admin_diagnostics()
        if path == "/api/admin/email-diagnostics":
            if not self.require_admin():
                return
            return self.admin_email_diagnostics()
        if path == "/api/admin/smtp-network-diagnostics":
            if not self.require_admin():
                return
            return self.send_json({"smtp_network": smtp_network_check("smtp.gmail.com", 587), "email_provider": email_provider_diagnostics()})
        if path == "/api/receptionist/conversations":
            return self.receptionist_conversations()
        if path.startswith("/api/receptionist/conversations/") and path.endswith("/messages"):
            return self.receptionist_public_messages(path)
        if path.startswith("/api/receptionist/conversations/"):
            return self.receptionist_detail(path)
        if path == "/api/payments/verify":
            return self.verify_checkout(urllib.parse.parse_qs(parsed.query).get("session_id", [""])[0])
        if path.startswith("/api/quotes/"):
            return self.get_quote(path.split("/")[3])
        if path.startswith("/api/job-offers/"):
            return self.get_job_offer(path.split("/")[3])
        if path == "/api/automations":
            if not self.require_admin():
                return
            with connect() as conn:
                configs = [dict(row) for row in conn.execute("SELECT * FROM workflow_config ORDER BY rowid").fetchall()]
                jobs = [dict(row) for row in conn.execute("""SELECT j.*,b.reference,b.name customer_name FROM automation_jobs j JOIN bookings b ON b.id=j.booking_id ORDER BY j.id DESC LIMIT 100""").fetchall()]
            return self.send_json({"config": configs, "jobs": jobs})
        if path.startswith("/api/bookings/") and path.endswith("/timeline"):
            if not self.require_admin():
                return
            booking_id = int(path.split("/")[3])
            with connect() as conn:
                events = [dict(row) for row in conn.execute("SELECT * FROM booking_timeline WHERE booking_id=? ORDER BY id DESC", (booking_id,)).fetchall()]
            return self.send_json(events)
        if path == "/api/bookings":
            if not self.require_admin():
                return
            with connect() as conn:
                sync_paid_balance_invoices(conn)
                rows = conn.execute("""SELECT b.*, c.name AS cleaner_name, c.phone AS cleaner_phone
                    FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id
                    WHERE b.archived_at IS NULL
                    ORDER BY b.id DESC""").fetchall()
            bookings = []
            for row in rows:
                item = dict(row)
                item["photos"] = json.loads(item["photos"])
                item["before_photos"] = json.loads(item.get("before_photos") or "[]")
                item["after_photos"] = json.loads(item.get("after_photos") or "[]")
                with connect() as payment_conn:
                    item["payments"] = [dict(payment) for payment in payment_conn.execute("SELECT * FROM payments WHERE booking_id=? ORDER BY id DESC", (item["id"],)).fetchall()]
                bookings.append(item)
            if not bookings:
                try:
                    bookings = recovered_stripe_booking_rows()
                except Exception as error:
                    logger.error(json.dumps({"bookings_recovery": "failed", "error": str(error)}))
            return self.send_json(bookings)
        if path == "/api/cleaners":
            if not self.require_admin():
                return
            with connect() as conn:
                rows = conn.execute("SELECT * FROM cleaners ORDER BY active DESC, name").fetchall()
            cleaners = []
            for row in rows:
                item = dict(row)
                item["activated"] = bool(item.get("password_hash"))
                item.pop("password_hash", None)
                item["availability"] = json.loads(item["availability"])
                item["services"] = json.loads(item["services"])
                cleaners.append(item)
            return self.send_json(cleaners)
        if path == "/api/cleaner-payouts":
            if not self.require_admin():
                return
            return self.list_cleaner_payouts()
        if path.startswith("/api/recruitment/invites/"):
            return self.get_recruitment_invite(path)
        if path == "/api/cleaner-applicants/metrics":
            if not self.require_admin():
                return
            return self.cleaner_applicant_metrics()
        if path == "/api/cleaner-applicants":
            if not self.require_admin():
                return
            with connect() as conn:
                rows = conn.execute("SELECT * FROM cleaner_applicants ORDER BY id DESC").fetchall()
            applicants = []
            for row in rows:
                item = dict(row)
                item["availability"] = json.loads(item.get("availability") or "[]")
                item["services"] = json.loads(item.get("services") or "[]")
                item["id_uploads"] = json.loads(item.get("id_uploads") or "[]")
                item["proof_of_address_uploads"] = json.loads(item.get("proof_of_address_uploads") or "[]")
                item["driving_licence_uploads"] = json.loads(item.get("driving_licence_uploads") or "[]")
                item.update(self.score_cleaner_applicant(item))
                applicants.append(item)
            return self.send_json(applicants)
        if path.startswith("/api/cleaner-applicants/") and path.endswith("/timeline"):
            if not self.require_admin():
                return
            try:
                applicant_id = int(path.split("/")[3])
            except (ValueError, IndexError):
                return self.send_json({"error": "Invalid applicant."}, 400)
            with connect() as conn:
                events = [dict(row) for row in conn.execute("SELECT * FROM cleaner_applicant_timeline WHERE applicant_id=? ORDER BY id DESC", (applicant_id,)).fetchall()]
            return self.send_json(events)
        if path == "/api/ai-recruitment/summary":
            if not self.require_admin():
                return
            return self.ai_recruitment_summary()
        if path == "/api/ai-recruitment/autopilot-status":
            if not self.require_admin():
                return
            return self.ai_recruitment_autopilot_status()
        if path.startswith("/api/bookings/") and path.endswith("/matches"):
            if not self.require_admin():
                return
            try:
                booking_id = int(path.split("/")[3])
                with connect() as conn:
                    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                if not booking:
                    return self.send_json({"error": "Booking not found."}, 404)
                matches = []
                for cleaner in suitable_cleaners(dict(booking)):
                    cleaner = dict(cleaner)
                    cleaner.pop("password_hash", None)
                    cleaner["services"] = json.loads(cleaner.get("services") or "[]")
                    cleaner["availability"] = json.loads(cleaner.get("availability") or "[]")
                    cleaner["is_available"] = True
                    matches.append(cleaner)
                return self.send_json(matches)
            except (ValueError, IndexError):
                return self.send_json({"error": "Invalid booking."}, 400)
        if path == "/api/customer/bookings":
            try:
                session = self.current_session()
                if not session or session["role"] != "customer":
                    return self.send_json({"error": "Customer login required."}, 401)
                with connect() as conn:
                    rows = conn.execute("""SELECT b.*, c.name AS cleaner_name, c.phone AS cleaner_phone
                        FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id
                        WHERE (lower(b.email)=lower(?) OR b.customer_id=?)
                        AND b.archived_at IS NULL AND COALESCE(b.is_test,0)=0
                        ORDER BY b.id DESC""", (session["email"], session["subject_id"])).fetchall()
                    bookings = []
                    for row in rows:
                        item = dict(row)
                        try:
                            item["photos"] = json.loads(item.get("photos") or "[]")
                        except (TypeError, json.JSONDecodeError):
                            item["photos"] = []
                        item["payments"] = [dict(payment) for payment in conn.execute("SELECT * FROM payments WHERE booking_id=? ORDER BY id DESC", (item["id"],)).fetchall()]
                        bookings.append(item)
                return self.send_json(bookings)
            except Exception as error:
                logger.exception(json.dumps({"event": "customer_bookings_failed", "error": str(error)}))
                return self.send_json({"error": "Customer bookings could not be loaded. Please try again."}, 500)
        if path == "/api/cleaner/jobs":
            session = self.current_session()
            if not session or session["role"] != "cleaner":
                return self.send_json({"error": "Cleaner login required."}, 401)
            with connect() as conn:
                rows = conn.execute("""SELECT b.*, c.hourly_rate AS cleaner_hourly_rate
                    FROM bookings b JOIN cleaners c ON c.id=b.cleaner_id
                    WHERE b.cleaner_id=? AND b.archived_at IS NULL
                    ORDER BY b.preferred_date DESC, b.preferred_time DESC""", (session["subject_id"],)).fetchall()
            bookings = []
            for row in rows:
                item = dict(row)
                item["photos"] = json.loads(item["photos"])
                item["before_photos"] = json.loads(item.get("before_photos") or "[]")
                item["after_photos"] = json.loads(item.get("after_photos") or "[]")
                bookings.append(item)
            return self.send_json(bookings)
        if path.startswith("/uploads/"):
            name = Path(unquote(path)).name
            return self.send_file(UPLOADS / name)
        if path in ("/", "/index.html"):
            return self.send_file(PUBLIC / "index.html")
        if path in ("/admin/login", "/admin/login/"):
            return self.send_file(PUBLIC / "admin-login.html")
        if path in ("/admin/emergency-reset", "/admin/emergency-reset/"):
            return self.send_file(PUBLIC / "admin-emergency-reset.html")
        if path in ("/cleaner/login", "/cleaner/login/"):
            return self.send_file(PUBLIC / "cleaner-login.html")
        if path in ("/cleaner/apply", "/cleaner/apply/", "/become-a-cleaner", "/become-a-cleaner/"):
            return self.send_file(PUBLIC / "cleaner-apply.html")
        if path.startswith("/r/cleaners/"):
            return self.track_recruitment_click(path)
        if path in ("/customer", "/customer/", "/customer/login", "/customer/login/"):
            return self.send_file(PUBLIC / "customer.html")
        if path in ("/reset-password", "/reset-password/", "/cleaner/setup", "/cleaner/setup/"):
            return self.send_file(PUBLIC / "reset-password.html")
        if path in ("/admin", "/admin/", "/admin/dashboard", "/admin/dashboard/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "owner-dashboard.html")
        if path in ("/admin/diagnostics", "/admin/diagnostics/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "admin-diagnostics.html")
        if path in ("/admin/launch", "/admin/launch/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "launch-console.html")
        if path in ("/admin/fresh-launch-reset", "/admin/fresh-launch-reset/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "fresh-launch-reset.html")
        if path in ("/admin/bookings", "/admin/bookings/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "admin.html")
        if path in ("/admin/cleaners", "/admin/cleaners/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "cleaners-admin.html")
        if path in ("/admin/cleaner-applicants", "/admin/cleaner-applicants/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "cleaner-applicants-admin.html")
        if path in ("/admin/calendar", "/admin/calendar/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "calendar.html")
        if path in ("/cleaner", "/cleaner/"):
            return self.send_file(PUBLIC / "cleaner-apply.html")
        if path in ("/cleaner/dashboard", "/cleaner/dashboard/"):
            if not self.is_cleaner():
                return self.redirect("/cleaner/login")
            return self.send_file(PUBLIC / "cleaner-dashboard.html")
        if path in ("/payment-success", "/payment-success/"):
            return self.send_file(PUBLIC / "payment-success.html")
        if path in ("/review-thanks", "/review-thanks/"):
            return self.send_file(PUBLIC / "review-thanks.html")
        if path in ("/quote", "/quote/"):
            return self.send_file(PUBLIC / "quote.html")
        if path in ("/job-offer", "/job-offer/"):
            return self.send_file(PUBLIC / "job-offer.html")
        if path in ("/admin/automations", "/admin/automations/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "automations.html")
        if path in ("/admin/autopilot", "/admin/autopilot/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "autopilot.html")
        if path in ("/admin/ai-office", "/admin/ai-office/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "ai-office.html")
        if path in ("/admin/ai-office/settings", "/admin/ai-office/settings/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "ai-office-settings.html")
        if path in ("/admin/receptionist", "/admin/receptionist/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "receptionist-admin.html")
        if path in ("/admin/ai-recruitment", "/admin/ai-recruitment/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "ai-recruitment.html")
        if path in ("/admin/setup", "/admin/setup/"):
            if admin_configured() and not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "setup.html")
        protected_files = {"/owner-dashboard.html", "/admin.html", "/cleaners-admin.html", "/cleaner-applicants-admin.html", "/calendar.html", "/automations.html", "/autopilot.html", "/ai-office.html", "/ai-office-settings.html", "/receptionist-admin.html", "/ai-recruitment.html", "/launch-console.html", "/fresh-launch-reset.html", "/setup.html", "/admin-diagnostics.html"}
        if path in protected_files and not self.is_admin():
            return self.redirect("/admin/login")
        if path == "/cleaner-dashboard.html" and not self.is_cleaner():
            return self.redirect("/cleaner/login")
        candidate = (PUBLIC / path.lstrip("/")).resolve()
        if PUBLIC.resolve() in candidate.parents:
            return self.send_file(candidate)
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/admin/login":
            return self.login_admin()
        if path == "/api/admin/emergency-reset":
            return self.emergency_admin_reset()
        if path == "/api/admin/email-test":
            if not self.require_admin():
                return
            return self.admin_email_test()
        if path == "/api/admin/fresh-launch-reset":
            if not self.require_admin():
                return
            return self.fresh_launch_reset()
        if path == "/api/admin/autopilot/cleaner_recruitment/facebook/draft":
            if not self.require_admin():
                return
            return self.autopilot_facebook_draft()
        if path == "/api/admin/autopilot/cleaner_recruitment/facebook/approve":
            if not self.require_admin():
                return
            return self.autopilot_facebook_approve()
        if path == "/api/admin/autopilot/cleaner_recruitment/facebook/test":
            if not self.require_admin():
                return
            return self.autopilot_facebook_test()
        if path == "/api/admin/autopilot/cleaner_recruitment/facebook/publish":
            if not self.require_admin():
                return
            return self.autopilot_facebook_publish()
        if path.startswith("/api/admin/autopilot/") and path.endswith("/toggle"):
            if not self.require_admin():
                return
            return self.autopilot_toggle(path)
        if path.startswith("/api/admin/autopilot/") and path.endswith("/configure"):
            if not self.require_admin():
                return
            return self.autopilot_configure(path)
        if path.startswith("/api/admin/autopilot/") and path.endswith("/run-now"):
            if not self.require_admin():
                return
            return self.autopilot_run_now(path)
        if path.startswith("/api/admin/autopilot/alerts/") and path.endswith("/resolve"):
            if not self.require_admin():
                return
            return self.autopilot_resolve_alert(path)
        if path == "/api/cleaner/login":
            return self.login_cleaner()
        if path == "/api/customer/register":
            return self.register_customer()
        if path == "/api/customer/login":
            return self.login_customer()
        if path == "/api/auth/logout":
            self.clear_session()
            return self.send_json({"ok": True}, headers={"Set-Cookie": self.expired_cookie()})
        if path == "/api/auth/password-reset/request":
            return self.request_password_reset()
        if path == "/api/auth/password-reset/confirm":
            return self.confirm_password_reset()
        if path == "/api/config":
            return self.save_config()
        if path == "/api/ai-office/settings":
            return self.save_ai_settings()
        if path == "/api/ai-office/respond":
            return self.ai_office_reply()
        if path == "/api/ai-recruitment/campaign-copy":
            if not self.require_admin():
                return
            return self.ai_recruitment_campaign_copy()
        if path == "/api/ai-recruitment/autopilot-plan":
            if not self.require_admin():
                return
            return self.ai_recruitment_autopilot_plan()
        if path.startswith("/api/ai-recruitment/applicants/") and path.endswith("/follow-up"):
            if not self.require_admin():
                return
            return self.ai_recruitment_follow_up(path)
        if path == "/api/receptionist/start":
            return self.receptionist_start()
        if path == "/api/receptionist/message":
            return self.receptionist_message()
        if path.startswith("/api/receptionist/conversations/") and path.endswith("/takeover"):
            return self.receptionist_takeover(path)
        if path.startswith("/api/receptionist/conversations/") and path.endswith("/reply"):
            return self.receptionist_admin_reply(path)
        if path == "/api/stripe/webhook":
            return self.stripe_webhook()
        if path.startswith("/api/quotes/") and path.endswith("/accept"):
            return self.accept_quote(path.split("/")[3])
        if path.startswith("/api/job-offers/") and path.endswith("/accept"):
            return self.accept_offer(path.split("/")[3])
        if path.startswith("/api/job-offers/") and path.endswith("/complete"):
            return self.complete_job(path.split("/")[3])
        if path.startswith("/api/automations/") and path.endswith("/retry"):
            if not self.require_admin():
                return
            job_id = int(path.split("/")[3])
            return self.send_json({"ok": automation.retry(job_id)})
        if path.startswith("/api/cleaners/") and path.endswith("/invite"):
            if not self.require_admin():
                return
            return self.invite_cleaner(path)
        if path == "/api/cleaners":
            if not self.require_admin():
                return
            return self.create_cleaner()
        if path.startswith("/api/cleaner-payouts/") and path.endswith("/mark-paid"):
            if not self.require_admin():
                return
            return self.mark_cleaner_payout_paid(path)
        if path == "/api/cleaner-applicants":
            return self.create_cleaner_applicant()
        if path == "/api/cleaner-applicants/import":
            if not self.require_admin():
                return
            return self.import_cleaner_applicants()
        if path == "/api/cleaner-applicants/indeed-invite":
            if not self.require_admin():
                return
            return self.create_indeed_applicant_invite()
        if path.startswith("/api/cleaner-applicants/") and path.endswith("/invite"):
            if not self.require_admin():
                return
            return self.invite_existing_indeed_applicant(path)
        if path.startswith("/api/cleaner-applicants/") and path.endswith("/approve"):
            if not self.require_admin():
                return
            return self.approve_cleaner_applicant(path)
        if path.startswith("/api/cleaner/jobs/") and path.endswith("/action"):
            return self.cleaner_job_action(path)
        if path.startswith("/api/cleaner/jobs/") and path.endswith("/photos"):
            return self.cleaner_job_photos(path)
        if path.startswith("/api/bookings/") and path.endswith("/checkout"):
            return self.start_checkout(path)
        if path.startswith("/api/bookings/") and path.endswith("/resend-final-invoice"):
            if not self.require_admin():
                return
            return self.resend_final_invoice(path)
        if path.startswith("/api/bookings/") and path.endswith("/assign"):
            if not self.require_admin():
                return
            return self.assign_cleaner(path)
        if path.startswith("/api/bookings/") and path.endswith("/auto-assign"):
            if not self.require_admin():
                return
            return self.auto_assign_cleaner(path)
        if path != "/api/bookings":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            return self.send_json({"error": "Upload is empty or too large (15MB maximum)."}, 413)
        try:
            body = self.rfile.read(length)
            raw = (f"Content-Type: {self.headers.get('Content-Type')}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
            message = BytesParser(policy=default).parsebytes(raw)
            fields, photos = {}, []
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if filename and name == "photos":
                    mime = part.get_content_type()
                    if mime not in ALLOWED_IMAGES or len(payload) > 5 * 1024 * 1024:
                        raise ValueError("Photos must be JPG, PNG or WebP and no larger than 5MB each.")
                    saved = f"{uuid.uuid4().hex}{ALLOWED_IMAGES[mime]}"
                    (UPLOADS / saved).write_bytes(payload)
                    photos.append({"name": Path(filename).name, "url": f"/uploads/{saved}"})
                elif name:
                    fields[name] = payload.decode("utf-8").strip()

            required = ["name", "phone", "email", "address", "postcode", "clean_type", "bedrooms", "bathrooms", "preferred_date", "preferred_time"]
            missing = [key for key in required if not fields.get(key)]
            if missing:
                raise ValueError("Please complete all required fields.")
            reference = f"SPK-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
            quote_token = uuid.uuid4().hex
            total = quote_pence(fields["clean_type"], fields["bedrooms"], fields["bathrooms"])
            deposit = round(total * .25)
            with connect() as conn:
                cursor = conn.execute("""
                    INSERT INTO bookings (reference,name,phone,email,address,postcode,clean_type,bedrooms,bathrooms,preferred_date,preferred_time,notes,photos,status,created_at,total_amount,deposit_amount,balance_amount,payment_status,quote_token,quote_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'New',?,?,?,?, 'Deposit Due',?,'Pending')
                """, (reference, fields["name"], fields["phone"], fields["email"], fields["address"], fields["postcode"].upper(), fields["clean_type"], int(fields["bedrooms"]), int(fields["bathrooms"]), fields["preferred_date"], fields["preferred_time"], fields.get("notes", ""), json.dumps(photos), datetime.now(timezone.utc).isoformat(), total, deposit, total-deposit, quote_token))
                booking_id = cursor.lastrowid
                session = self.current_session()
                if session and session["role"] == "customer" and session["email"].lower() == fields["email"].strip().lower():
                    conn.execute("UPDATE bookings SET customer_id=? WHERE id=?", (session["subject_id"], booking_id))
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            automation.timeline(booking_id, "Booking received", f"Quote calculated automatically: £{total/100:.2f}")
            checkout_url, checkout_session_id, checkout_error = None, None, None
            if stripe_configured():
                try:
                    checkout = create_checkout(booking, "deposit")
                    checkout_url, checkout_session_id = checkout["url"], checkout["id"]
                    with connect() as conn:
                        conn.execute("UPDATE bookings SET deposit_checkout_session_id=?, deposit_checkout_url=? WHERE id=?", (checkout_session_id, checkout_url, booking_id))
                    automation.timeline(booking_id, "Deposit checkout created", "Stripe Checkout link created for the 25% deposit")
                except ValueError as error:
                    checkout_error = str(error)
                    automation.timeline(booking_id, "Deposit checkout failed", checkout_error, "Warning")
            else:
                checkout_error = "Stripe is not configured. Add STRIPE_SECRET_KEY before taking online deposits."
                automation.timeline(booking_id, "Deposit checkout not created", checkout_error, "Warning")
            safe_send_booking_confirmation_email(booking_id, False)
            automation.enqueue(booking_id, "send_quote")
            automation.enqueue(booking_id, "send_abandoned_followup", run_after=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
            result = {
                "ok": True, "reference": reference, "booking_id": booking_id,
                "total_amount": total, "deposit_amount": deposit, "balance_amount": total-deposit,
                "payment_status": "Deposit Due", "checkout_url": checkout_url,
                "checkout_session_id": checkout_session_id, "checkout_error": checkout_error,
                "quote_status": "Queued"
            }
            self.send_json(result, 201)
        except (ValueError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)
        except Exception as error:
            print(error)
            self.send_json({"error": "We couldn't save your booking. Please try again."}, 500)

    def do_PATCH(self):
        path = urlparse(self.path).path
        if path.startswith("/api/workflows/"):
            if not self.require_admin():
                return
            try:
                step = path.split("/")[3]
                data = self.read_json()
                with connect() as conn:
                    conn.execute("UPDATE workflow_config SET enabled=?,max_attempts=? WHERE step=?", (1 if data.get("enabled") else 0, int(data.get("max_attempts", 4)), step))
                return self.send_json({"ok": True})
            except (ValueError, TypeError, json.JSONDecodeError):
                return self.send_json({"error": "Invalid workflow settings."}, 400)
        if path.startswith("/api/recovered-bookings/"):
            if not self.require_admin():
                return
            return self.archive_recovered_booking(path)
        if path.startswith("/api/bookings/"):
            if not self.require_admin():
                return
            return self.update_booking(path)
        if path.startswith("/api/cleaners/"):
            if not self.require_admin():
                return
            return self.update_cleaner(path)
        if path.startswith("/api/cleaner-applicants/"):
            if not self.require_admin():
                return
            return self.update_cleaner_applicant(path)
        self.send_error(404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1024 * 1024:
            raise ValueError("Invalid request.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def autopilot_key_from_path(self, path):
        parts = path.strip("/").split("/")
        try:
            key = parts[3]
        except IndexError:
            raise ValueError("Invalid automation.")
        if key not in autopilot_catalog():
            raise ValueError("Unknown automation.")
        return key

    def autopilot_toggle(self, path):
        try:
            key = self.autopilot_key_from_path(path)
            data = self.read_json()
            enabled = 1 if data.get("enabled") else 0
            now = utcnow().isoformat()
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                conn.execute("UPDATE automation_settings SET enabled=?,updated_at=? WHERE key=?", (enabled, now, key))
                for step in autopilot_workflow_step_list(key):
                    conn.execute("UPDATE workflow_config SET enabled=? WHERE step=?", (enabled, step))
                autopilot_log(conn, key, "Automation enabled" if enabled else "Automation disabled", "Owner changed the Autopilot switch.")
            return self.send_json(autopilot_payload())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def autopilot_configure(self, path):
        try:
            key = self.autopilot_key_from_path(path)
            data = self.read_json()
            config = data.get("config", {})
            if not isinstance(config, dict):
                raise ValueError("Configuration must be a set of fields.")
            clean_config = {str(k): str(v).strip() for k, v in config.items()}
            now = utcnow().isoformat()
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                existing = conn.execute("SELECT config_json FROM automation_settings WHERE key=?", (key,)).fetchone()
                existing_config = autopilot_config(existing["config_json"] if existing else "{}")
                internal_config = {name: value for name, value in existing_config.items() if str(name).startswith("_")}
                clean_config.update(internal_config)
                conn.execute("UPDATE automation_settings SET config_json=?,updated_at=? WHERE key=?", (json.dumps(clean_config), now, key))
                autopilot_log(conn, key, "Configuration saved", "Owner updated the Autopilot configuration.")
            return self.send_json(autopilot_payload())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def autopilot_run_now(self, path):
        try:
            key = self.autopilot_key_from_path(path)
            data = self.read_json()
            dry_run = data.get("dry_run", True)
            started = utcnow().isoformat()
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                cursor = conn.execute(
                    "INSERT INTO automation_runs(automation_key,status,triggered_by,started_at,summary) VALUES (?,?,?,?,?)",
                    (key, "Running", "manual", started, "Manual dry run started."),
                )
                run_id = cursor.lastrowid
                summary = autopilot_snapshot(conn, key)
                detail = "Dry run only. No emails were sent, no bookings changed, no payments touched and no cleaner assignments made."
                if not dry_run:
                    detail = "Live side effects are disabled in Phase 1, so this manual run was safely kept as a dry run."
                autopilot_log(conn, key, "Manual dry run completed", f"{summary} {detail}", "Info", run_id)
                conn.execute(
                    "UPDATE automation_runs SET status='Completed',finished_at=?,summary=? WHERE id=?",
                    (utcnow().isoformat(), f"{summary} {detail}", run_id),
                )
            return self.send_json(autopilot_payload())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)
        except Exception as error:
            logger.exception("Autopilot dry run failed")
            try:
                key = self.autopilot_key_from_path(path)
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO automation_alerts(automation_key,title,detail,level,created_at) VALUES (?,?,?,?,?)",
                        (key, "Autopilot dry run failed", str(error), "Needs attention", utcnow().isoformat()),
                    )
            except Exception:
                pass
            return self.send_json({"error": "Autopilot dry run failed. Check the Needs attention panel."}, 500)

    def autopilot_facebook_draft(self):
        try:
            self.read_json()
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                autopilot_log(conn, "cleaner_recruitment", "Facebook recruitment draft prepared", "A Page-only recruitment draft was prepared. Nothing was published.")
            return self.send_json(autopilot_payload())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def autopilot_facebook_approve(self):
        try:
            self.read_json()
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                row = conn.execute("SELECT config_json FROM automation_settings WHERE key='cleaner_recruitment'").fetchone()
                config = autopilot_config(row["config_json"] if row else "{}")
                draft = facebook_recruitment_draft(config)
                update_autopilot_config_fields(conn, "cleaner_recruitment", {
                    "_facebook_approved_draft_hash": draft["hash"],
                    "_facebook_approved_at": utcnow().isoformat(),
                    "_facebook_publish_state": "Approved",
                })
                autopilot_log(conn, "cleaner_recruitment", "Facebook recruitment draft approved", "The owner approved the exact draft currently shown. Nothing was published.")
            return self.send_json(autopilot_payload())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def autopilot_facebook_test(self):
        try:
            self.read_json()
            page = facebook_test_page_connection()
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                update_autopilot_config_fields(conn, "cleaner_recruitment", {
                    "_facebook_connection_checked_at": utcnow().isoformat(),
                    "_facebook_connection_page_name": str(page.get("name") or ""),
                })
                autopilot_log(conn, "cleaner_recruitment", "Facebook Page connection verified", f"Read-only connection confirmed for {page.get('name') or 'the configured Page'}. No post was created.")
            return self.send_json(autopilot_payload())
        except ValueError as error:
            return self.send_json({"error": str(error)}, 400)
        except RuntimeError as error:
            try:
                detail = json.loads(str(error))
                message = detail.get("message") or "Facebook connection failed."
            except (TypeError, json.JSONDecodeError):
                message = "Facebook connection failed."
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                autopilot_log(conn, "cleaner_recruitment", "Facebook Page connection failed", message, "Warning")
                autopilot_alert_once(conn, "cleaner_recruitment", "Facebook Page connection needs attention", f"What happened: {message} What Sparkles tried: a read-only Page connection check. Recommended action: verify the Railway Meta Page variables, then test again. Open /admin/autopilot.")
            return self.send_json({"error": message}, 502)

    def autopilot_facebook_publish(self):
        try:
            data = self.read_json()
            dry_run_passed = False
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                row = conn.execute("SELECT config_json FROM automation_settings WHERE key='cleaner_recruitment'").fetchone()
                config = autopilot_config(row["config_json"] if row else "{}")
                state = facebook_recruitment_state(config)
                draft = state["draft"]
                if not state["posting_enabled"]:
                    return self.send_json({"error": "Facebook Page posting is disabled. Enable it in Cleaner Recruitment configuration first."}, 409)
                if not state["approved"]:
                    return self.send_json({"error": "Approve the current Facebook draft before publishing."}, 409)
                if state["published"]:
                    return self.send_json({"error": "This exact Facebook draft has already been published."}, 409)
                if config.get("_facebook_publish_state") == "Publishing" and config.get("_facebook_publish_attempt_hash") == draft["hash"]:
                    return self.send_json({"error": "The previous publish result is uncertain. Check the Facebook Page before trying again to avoid a duplicate post."}, 409)
                if state["mode"].lower() != "live":
                    update_autopilot_config_fields(conn, "cleaner_recruitment", {
                        "_facebook_last_dry_run_at": utcnow().isoformat(),
                        "_facebook_publish_state": "Dry run passed",
                    })
                    autopilot_log(conn, "cleaner_recruitment", "Facebook publish dry run passed", "The approved Page post passed safety checks. Nothing was published.")
                    dry_run_passed = True
                elif data.get("confirm") != "PUBLISH APPROVED FACEBOOK DRAFT":
                    return self.send_json({"error": "Live Facebook publishing requires owner confirmation."}, 409)
                elif not state["configured"]:
                    return self.send_json({"error": "Add META_PAGE_ID and META_PAGE_ACCESS_TOKEN in Railway before publishing."}, 409)
                else:
                    update_autopilot_config_fields(conn, "cleaner_recruitment", {
                        "_facebook_publish_state": "Publishing",
                        "_facebook_publish_attempt_hash": draft["hash"],
                        "_facebook_publish_attempted_at": utcnow().isoformat(),
                    })
            if dry_run_passed:
                return self.send_json(autopilot_payload())
            post_id = facebook_publish_recruitment(draft)
            with connect() as conn:
                update_autopilot_config_fields(conn, "cleaner_recruitment", {
                    "_facebook_publish_state": "Published",
                    "_facebook_last_published_hash": draft["hash"],
                    "_facebook_last_published_at": utcnow().isoformat(),
                    "_facebook_last_post_id": post_id,
                    "_facebook_publish_attempt_hash": "",
                })
                autopilot_log(conn, "cleaner_recruitment", "Facebook recruitment post published", f"The approved recruitment draft was published to the configured Facebook Page. Post reference: {post_id}.")
            return self.send_json(autopilot_payload())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)
        except RuntimeError as error:
            try:
                detail = json.loads(str(error))
                message = detail.get("message") or "Facebook publishing failed."
            except (TypeError, json.JSONDecodeError):
                message = "Facebook publishing failed."
            with connect() as conn:
                ensure_autopilot_defaults(conn)
                update_autopilot_config_fields(conn, "cleaner_recruitment", {"_facebook_publish_state": "Needs attention"})
                autopilot_log(conn, "cleaner_recruitment", "Facebook recruitment publish failed", message, "Warning")
                autopilot_alert_once(conn, "cleaner_recruitment", "Facebook recruitment post needs attention", f"What happened: {message} What Sparkles tried: publish the owner-approved Page post once. Recommended action: check the Facebook Page and Railway Meta variables before retrying. Open /admin/autopilot.")
            return self.send_json({"error": message}, 502)

    def autopilot_resolve_alert(self, path):
        try:
            parts = path.strip("/").split("/")
            alert_id = int(parts[4])
            with connect() as conn:
                conn.execute("UPDATE automation_alerts SET resolved_at=? WHERE id=?", (utcnow().isoformat(), alert_id))
            return self.send_json(autopilot_payload())
        except (ValueError, IndexError) as error:
            return self.send_json({"error": str(error) or "Invalid alert."}, 400)

    def fresh_launch_reset(self):
        try:
            data = self.read_json()
            if data.get("confirm") != "RESET FRESH LAUNCH":
                return self.send_json({"error": "Confirmation phrase is required."}, 400)
            summary = perform_fresh_launch_reset()
            return self.send_json({"ok": True, "summary": summary})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)
        except Exception as error:
            logger.exception("Fresh launch reset failed")
            return self.send_json({"error": "Fresh launch reset failed. Check server logs for details."}, 500)

    def track_recruitment_click(self, path):
        raw_source = path.split("/r/cleaners/", 1)[1] if "/r/cleaners/" in path else "website"
        source = normalise_recruitment_source(urllib.parse.unquote(raw_source))
        landing = recruitment_apply_link(source)
        try:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO recruitment_clicks(source,landing_url,referrer,user_agent,created_at) VALUES (?,?,?,?,?)",
                    (
                        source,
                        landing,
                        self.headers.get("Referer", "")[:500],
                        self.headers.get("User-Agent", "")[:500],
                        utcnow().isoformat(),
                    ),
                )
        except Exception as error:
            logger.warning(json.dumps({"recruitment_click": "failed", "source": source, "error": str(error)}))
        return self.redirect(landing)

    def login_admin(self):
        try:
            data = self.read_json()
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            stored_email = runtime_setting("ADMIN_EMAIL", "").strip().lower()
            stored_hash = runtime_setting("ADMIN_PASSWORD_HASH", "")
            if not stored_email:
                return self.send_json({"error": "Admin email is not set up yet. Open setup with your setup token first."}, 409)
            if not stored_hash:
                return self.send_json({"error": "Admin password is not set yet. Use Forgot password to create one for this admin email."}, 409)
            if email != stored_email or not verify_password(password, stored_hash):
                return self.send_json({"error": "Invalid email or password."}, 401)
            token = self.create_session("admin", None, email)
            return self.send_json({"ok": True, "role": "admin"}, headers={"Set-Cookie": self.auth_cookie(token)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def emergency_admin_reset(self):
        if not self.setup_authorized():
            return self.send_json({"error": "ADMIN_SETUP_TOKEN is required."}, 401)
        try:
            data = self.read_json()
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            if email != "labcontractors@outlook.com":
                raise ValueError("Emergency reset is restricted to labcontractors@outlook.com.")
            password_hash = hash_password(password)
            now = utcnow().isoformat()
            with connect() as conn:
                conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('ADMIN_EMAIL',?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (email, 0, now))
                conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('ADMIN_PASSWORD_HASH',?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (password_hash, 1, now))
                conn.execute("DELETE FROM sessions WHERE role='admin'")
            logger.info("Emergency admin password reset completed")
            return self.send_json({"ok": True})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def login_cleaner(self):
        try:
            data = self.read_json()
            email = normalise_email_input(data.get("email", ""))
            password = normalise_password_input(data.get("password", ""))
            with connect() as conn:
                candidates = cleaner_auth_candidates(conn, email)
                cleaner = None
                for candidate in candidates:
                    if candidate["password_hash"] and verify_password(password, candidate["password_hash"]):
                        cleaner = candidate
                        break
            if not cleaner:
                logger.warning(json.dumps({
                    "event": "cleaner_login_failed",
                    "email_supplied": bool(email),
                    "candidate_count": len(candidates),
                    "active_candidates": sum(1 for candidate in candidates if int(candidate["active"] or 0)),
                    "candidates_with_password": sum(1 for candidate in candidates if candidate["password_hash"]),
                    "hash_format_candidates": sum(1 for candidate in candidates if str(candidate["password_hash"] or "").startswith("pbkdf2_sha256$")),
                }))
                return self.send_json({"error": "Invalid email or password."}, 401)
            if not cleaner["active"]:
                return self.send_json({"error": "This cleaner account is not active."}, 403)
            token = self.create_session("cleaner", cleaner["id"], cleaner["email"])
            return self.send_json({"ok": True, "role": "cleaner"}, headers={"Set-Cookie": self.auth_cookie(token)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def register_customer(self):
        try:
            data = self.read_json()
            name = data.get("name", "").strip()
            email = data.get("email", "").strip().lower()
            phone = data.get("phone", "").strip()
            password = data.get("password", "")
            if not name or not email or not password:
                raise ValueError("Please enter your name, email and password.")
            with connect() as conn:
                cursor = conn.execute("INSERT INTO customers(name,phone,email,password_hash,created_at) VALUES (?,?,?,?,?)", (name, phone, email, hash_password(password), utcnow().isoformat()))
                customer_id = cursor.lastrowid
                conn.execute("UPDATE bookings SET customer_id=? WHERE lower(email)=lower(?) AND customer_id IS NULL", (customer_id, email))
            token = self.create_session("customer", customer_id, email)
            return self.send_json({"ok": True, "role": "customer"}, 201, headers={"Set-Cookie": self.auth_cookie(token)})
        except DB_INTEGRITY_ERROR_TYPES:
            return self.send_json({"error": "A customer account already exists for that email."}, 409)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def login_customer(self):
        try:
            data = self.read_json()
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            with connect() as conn:
                customer = conn.execute("SELECT id,email,password_hash FROM customers WHERE lower(email)=lower(?)", (email,)).fetchone()
            if not customer:
                return self.send_json({"error": "No customer account found for that email. Choose 'Create account instead' first, then your bookings will appear."}, 401)
            if not verify_password(password, customer["password_hash"]):
                return self.send_json({"error": "Invalid email or password."}, 401)
            token = self.create_session("customer", customer["id"], customer["email"])
            return self.send_json({"ok": True, "role": "customer"}, headers={"Set-Cookie": self.auth_cookie(token)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def request_password_reset(self):
        try:
            data = self.read_json()
            role = data.get("role", "").strip().lower()
            email = data.get("email", "").strip().lower()
            if role not in {"admin", "cleaner", "customer"} or not email:
                raise ValueError("Choose an account type and enter your email.")
            subject_id = None
            exists = False
            if role == "admin":
                exists = bool(runtime_setting("ADMIN_EMAIL", "").strip().lower() == email)
            elif role == "cleaner":
                with connect() as conn:
                    candidates = cleaner_auth_candidates(conn, email)
                    row = candidates[0] if candidates else None
                exists, subject_id = bool(row), row["id"] if row else None
            else:
                with connect() as conn:
                    row = conn.execute("SELECT id FROM customers WHERE lower(email)=lower(?)", (email,)).fetchone()
                exists, subject_id = bool(row), row["id"] if row else None
            response = {"ok": True, "message": "If that account exists, a reset link has been sent."}
            if exists:
                token = secrets.token_urlsafe(32)
                expires = utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES)
                with connect() as conn:
                    conn.execute("INSERT INTO password_reset_tokens(token_hash,role,subject_id,email,expires_at,created_at) VALUES (?,?,?,?,?,?)", (token_hash(token), role, subject_id, email, expires.isoformat(), utcnow().isoformat()))
                link = f"{public_url()}/reset-password?token={urllib.parse.quote(token)}"
                status = send_auth_email(email, "Reset your Sparkles password", f"Use this secure link within {RESET_TOKEN_MINUTES} minutes to reset your password:\n\n{link}\n\nIf you did not request this, you can ignore this email.")
                if status == "Preview":
                    response["reset_link"] = link
            return self.send_json(response)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def confirm_password_reset(self):
        try:
            data = self.read_json()
            token = data.get("token", "")
            password = normalise_password_input(data.get("password", ""))
            with connect() as conn:
                reset = conn.execute("SELECT * FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?", (token_hash(token), utcnow().isoformat())).fetchone()
                if not reset:
                    return self.send_json({"error": "Reset link is invalid or has expired."}, 400)
                password_hash = hash_password(password)
                if reset["role"] == "admin":
                    conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('ADMIN_PASSWORD_HASH',?,?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (password_hash, 1, utcnow().isoformat()))
                elif reset["role"] == "cleaner":
                    reset_email = normalise_email_input(reset["email"])
                    cleaner = conn.execute("SELECT id,email FROM cleaners WHERE id=?", (reset["subject_id"],)).fetchone()
                    if not cleaner:
                        return self.send_json({"error": "Cleaner account for this setup link was not found. Ask the owner to send a new invite."}, 400)
                    if normalise_email_input(cleaner["email"]) != reset_email:
                        logger.warning(json.dumps({
                            "event": "cleaner_setup_email_mismatch",
                            "cleaner_id": cleaner["id"],
                            "token_email_matches_current": False
                        }))
                    conn.execute("UPDATE cleaners SET password_hash=? WHERE id=?", (password_hash, reset["subject_id"]))
                    updated = conn.execute("SELECT password_hash FROM cleaners WHERE id=?", (reset["subject_id"],)).fetchone()
                    if not updated or not verify_password(password, updated["password_hash"]):
                        return self.send_json({"error": "Cleaner password could not be saved. Ask the owner to send a new invite."}, 500)
                    if not find_cleaner_for_credentials(conn, cleaner["email"], password):
                        return self.send_json({"error": "Cleaner password was saved but login verification failed. Ask the owner to resend the invite."}, 500)
                else:
                    conn.execute("UPDATE customers SET password_hash=? WHERE id=?", (password_hash, reset["subject_id"]))
                conn.execute("UPDATE password_reset_tokens SET used_at=? WHERE token_hash=?", (utcnow().isoformat(), token_hash(token)))
                conn.execute("DELETE FROM sessions WHERE role=? AND email=?", (reset["role"], reset["email"]))
            return self.send_json({"ok": True})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def save_config(self):
        if not (self.is_admin() or self.setup_authorized()):
            return self.send_json({"error": "Setup authorization required."}, 401)
        try:
            data = self.read_json()
            allowed = {"COMPANY_NAME","COMPANY_EMAIL","COMPANY_PHONE","BUSINESS_ADDRESS","PUBLIC_URL","STRIPE_SECRET_KEY","STRIPE_WEBHOOK_SECRET","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASSWORD","SMTP_FROM","EMAIL_FROM","EMAIL_PROVIDER","RESEND_API_KEY","SENDGRID_API_KEY","REVIEW_URL","ADMIN_EMAIL"}
            secret_keys = {"STRIPE_SECRET_KEY","STRIPE_WEBHOOK_SECRET","SMTP_PASSWORD","RESEND_API_KEY","SENDGRID_API_KEY"}
            existing_admin_hash = runtime_setting("ADMIN_PASSWORD_HASH", "")
            admin_email = str(data.get("ADMIN_EMAIL") or runtime_setting("ADMIN_EMAIL", "")).strip().lower()
            admin_password = data.get("ADMIN_PASSWORD", "")
            if not existing_admin_hash and (not admin_email or not admin_password):
                raise ValueError("Please create the first admin account by entering an admin email and password.")
            with connect() as conn:
                for key in allowed:
                    if key not in data or data[key] == "••••••••" or (key in secret_keys and data[key] == ""):
                        continue
                    value = str(data[key]).strip()
                    conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES (?,?,?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (key, value, 1 if key in secret_keys else 0, datetime.now(timezone.utc).isoformat()))
                if admin_password:
                    conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('ADMIN_PASSWORD_HASH',?,?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (hash_password(admin_password), 1, utcnow().isoformat()))
                logo = data.get("LOGO_DATA", "")
                if logo:
                    header, encoded = logo.split(",", 1)
                    mime = header.split(";")[0].split(":")[-1]
                    extension = {"image/png":".png","image/jpeg":".jpg","image/webp":".webp"}.get(mime)
                    content = base64.b64decode(encoded)
                    if not extension or len(content) > 1024 * 1024:
                        raise ValueError("Logo must be PNG, JPG or WebP and under 1MB.")
                    name = f"company-logo{extension}"
                    (UPLOADS / name).write_bytes(content)
                    conn.execute("UPDATE app_config SET value=?,updated_at=? WHERE key='LOGO_URL'", (f"/uploads/{name}", datetime.now(timezone.utc).isoformat()))
            logger.info("Production configuration updated")
            self.send_json({"ok": True})
        except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error) as error:
            self.send_json({"error": str(error)}, 400)

    def save_ai_settings(self):
        if not self.require_admin():
            return
        try:
            data = self.read_json()
            settings = ai_settings()
            business_hours = str(data.get("business_hours", settings["business_hours"])).strip()
            service_areas = str(data.get("service_areas", settings["service_areas"])).strip()
            pricing = data.get("pricing", settings["pricing"])
            responses = data.get("responses", settings["responses"])
            if not business_hours or not service_areas:
                raise ValueError("Business hours and service areas are required.")
            if not isinstance(pricing, dict) or not pricing:
                raise ValueError("Pricing must include at least one service.")
            cleaned_pricing = {}
            for service, rule in pricing.items():
                if not service or not isinstance(rule, dict):
                    continue
                cleaned_pricing[str(service).strip()] = {
                    "base": int(rule.get("base", 0)),
                    "bedroom_extra": int(rule.get("bedroom_extra", 0)),
                    "bathroom_extra": int(rule.get("bathroom_extra", 0))
                }
            if not cleaned_pricing:
                raise ValueError("Pricing must include at least one valid service.")
            if not isinstance(responses, dict):
                raise ValueError("AI responses must be a simple set of response fields.")
            cleaned_responses = {str(k): str(v).strip() for k, v in responses.items() if str(k).strip()}
            now = utcnow().isoformat()
            rows = [
                ("AI_BUSINESS_HOURS", business_hours, 0, now),
                ("AI_SERVICE_AREAS", service_areas, 0, now),
                ("AI_PRICING_JSON", json.dumps(cleaned_pricing), 0, now),
                ("AI_RESPONSES_JSON", json.dumps(cleaned_responses), 0, now)
            ]
            with connect() as conn:
                conn.executemany("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES (?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", rows)
            return self.send_json({"ok": True, "settings": ai_settings()})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def ai_office_reply(self):
        if not self.require_admin():
            return
        try:
            data = self.read_json()
            message = str(data.get("message", "")).strip()
            details = data.get("details") if isinstance(data.get("details"), dict) else {}
            settings = ai_settings()
            service_names = list(settings["pricing"].keys())
            lower = message.lower()
            if "deep" in lower:
                details.setdefault("clean_type", "Deep clean")
            elif "tenancy" in lower or "move" in lower:
                details.setdefault("clean_type", "End of tenancy")
            elif "regular" in lower or "weekly" in lower or "fortnight" in lower:
                details.setdefault("clean_type", "Regular clean")
            elif "one-off" in lower or "one off" in lower:
                details.setdefault("clean_type", "One-off clean")
            for number in range(0, 8):
                if f"{number} bed" in lower or f"{number}-bed" in lower:
                    details.setdefault("bedrooms", number)
                if f"{number} bath" in lower or f"{number}-bath" in lower:
                    details.setdefault("bathrooms", number)
            required = ["name","phone","email","address","postcode","clean_type","bedrooms","bathrooms","preferred_date","preferred_time"]
            missing = [field for field in required if details.get(field) in (None, "")]
            quote = None
            if details.get("clean_type") and details.get("bedrooms") not in (None, "") and details.get("bathrooms") not in (None, ""):
                total = quote_pence(details["clean_type"], details["bedrooms"], details["bathrooms"])
                quote = {"total_amount": total, "deposit_amount": round(total * .25), "balance_amount": total - round(total * .25)}
            if quote:
                opener = f"Based on the details so far, the estimated total is £{quote['total_amount']/100:.2f}. The 25% deposit is £{quote['deposit_amount']/100:.2f}."
            elif any(word in lower for word in ["price", "quote", "cost", "how much"]):
                opener = "I can prepare a quote as soon as I know the type of clean, bedrooms and bathrooms."
            elif any(word in lower for word in ["open", "hour", "available"]):
                opener = f"Our business hours are {settings['business_hours']}."
            elif any(word in lower for word in ["area", "postcode", "cover"]):
                opener = f"We cover {settings['service_areas']}."
            else:
                opener = settings["responses"]["greeting"]
            question_labels = {
                "name": "your full name", "phone": "your phone number", "email": "your email address",
                "address": "the cleaning address", "postcode": "the postcode", "clean_type": f"the type of clean ({', '.join(service_names)})",
                "bedrooms": "the number of bedrooms", "bathrooms": "the number of bathrooms",
                "preferred_date": "your preferred date", "preferred_time": "your preferred time"
            }
            next_questions = [question_labels[field] for field in missing[:4]]
            reply = opener
            if next_questions:
                reply += "\n\nTo finish the booking, please ask for: " + "; ".join(next_questions) + "."
            reply += f"\n\nWhen ready, send the customer to {settings['booking_url']} to complete the booking and pay the secure 25% deposit."
            return self.send_json({"reply": reply, "missing": missing, "quote": quote, "details": details, "booking_url": settings["booking_url"]})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def receptionist_start(self):
        conversation = self.create_receptionist_conversation()
        return self.send_json({"conversation_id": conversation["conversation_id"], "message": conversation["message"]})

    def create_receptionist_conversation(self):
        now = utcnow().isoformat()
        greeting = ai_settings()["responses"]["greeting"] + " I can help you get a quote and book online."
        with connect() as conn:
            cursor = conn.execute("INSERT INTO ai_conversations(status,created_at,updated_at) VALUES ('AI Active',?,?)", (now, now))
            conversation_id = cursor.lastrowid
            conn.execute("INSERT INTO ai_messages(conversation_id,sender,message,created_at) VALUES (?,?,?,?)", (conversation_id, "ai", greeting, now))
        return {"conversation_id": conversation_id, "message": greeting}

    def receptionist_message(self):
        try:
            data = self.read_json()
            conversation_id = int(data.get("conversation_id"))
            message = str(data.get("message", "")).strip()
            if not message:
                raise ValueError("Please enter a message.")
            now = utcnow().isoformat()
            with connect() as conn:
                convo = conn.execute("SELECT * FROM ai_conversations WHERE id=?", (conversation_id,)).fetchone()
                if not convo:
                    conversation = self.create_receptionist_conversation()
                    conversation_id = conversation["conversation_id"]
                    convo = conn.execute("SELECT * FROM ai_conversations WHERE id=?", (conversation_id,)).fetchone()
                conn.execute("INSERT INTO ai_messages(conversation_id,sender,message,created_at) VALUES (?,?,?,?)", (conversation_id, "customer", message, now))
                details = json.loads(convo["collected_details"] or "{}")
                details = self.extract_receptionist_details(message, details)
                if not details.get("name"):
                    intro_name = extract_intro_name(message)
                    if intro_name:
                        details["name"] = intro_name
                if not details.get("name"):
                    first_sentence = re.split(r"[.!?]", message, 1)[0]
                    capitalised = [word for word in re.findall(r"\b[A-Z][a-z]{1,}\b", first_sentence) if word.lower() not in {"hi", "hello", "cambridge", "sparkles"}]
                    if capitalised:
                        details["name"] = capitalised[-1]
                conn.execute("UPDATE ai_conversations SET collected_details=?,customer_name=?,customer_email=?,customer_phone=?,updated_at=? WHERE id=?",
                    (json.dumps(details), details.get("name", convo["customer_name"]), details.get("email", convo["customer_email"]), details.get("phone", convo["customer_phone"]), now, conversation_id))
                if convo["admin_takeover"]:
                    reply = "Thanks — a member of the Sparkles team has joined this chat and will reply here shortly."
                    conn.execute("INSERT INTO ai_messages(conversation_id,sender,message,created_at) VALUES (?,?,?,?)", (conversation_id, "system", "Customer message waiting for admin reply", now))
                    return self.send_json({"reply": reply, "admin_takeover": True, "details": details})
                booking_id = convo["booking_id"]
            reply, quote, booking = self.build_receptionist_reply(conversation_id, details, existing_booking_id=booking_id)
            if not details.get("name"):
                intro_name = extract_intro_name(message)
                if intro_name:
                    details["name"] = intro_name
                    reply = reply.replace("Thanks for getting in touch", f"Hi {details['name']}! Thanks for getting in touch")
                    with connect() as conn:
                        conn.execute("UPDATE ai_conversations SET collected_details=?,customer_name=?,updated_at=? WHERE id=?", (json.dumps(details), details["name"], utcnow().isoformat(), conversation_id))
            with connect() as conn:
                conn.execute("INSERT INTO ai_messages(conversation_id,sender,message,created_at) VALUES (?,?,?,?)", (conversation_id, "ai", reply, utcnow().isoformat()))
                conn.execute("UPDATE ai_conversations SET updated_at=? WHERE id=?", (utcnow().isoformat(), conversation_id))
            return self.send_json({"conversation_id": conversation_id, "reply": reply, "quote": quote, "booking": booking, "details": details})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def extract_receptionist_details(self, message, details):
        lower = message.lower()
        settings = ai_settings()
        if not details.get("name"):
            intro_name = extract_intro_name(message)
            if intro_name:
                details["name"] = intro_name
        if not details.get("name"):
            for marker in ("i'm ", "i’m ", "im ", "i am ", "my name is "):
                if marker in lower:
                    after = message[lower.index(marker) + len(marker):].strip()
                    candidate = re.split(r"[^A-Za-z-]", after, 1)[0]
                    if candidate:
                        details["name"] = candidate.title()
                    break
        if not details.get("name"):
            loose_name = re.search(r"\bi.{0,3}m\s+([A-Za-z-]+)", message, re.I)
            if loose_name:
                details["name"] = loose_name.group(1).strip().title()
        if not details.get("name"):
            first_sentence = re.split(r"[.!?]", message, 1)[0]
            intro_words = [word for word in re.findall(r"[A-Za-z-]+", first_sentence) if word.lower() not in {"hi", "hello", "hey", "i", "im", "m", "am", "my", "name", "is"}]
            if intro_words and any(word in first_sentence.lower() for word in ("hi", "hello", "i", "name")):
                details["name"] = intro_words[-1].title()
        name_match = re.search(r"(?:\bi\s+am\b|\bi['’]?m\b|\bim\b|\bmy name is\b)\s+([a-z][a-z-]*)", lower)
        if name_match and not details.get("name"):
            details["name"] = name_match.group(1).strip().title()
        elif not details.get("name"):
            normalised = re.sub(r"[^a-z\s]", " ", lower)
            fallback = re.search(r"(?:\bi\s+am\b|\bi\s+m\b|\bim\b|\bmy\s+name\s+is\b)\s+([a-z][a-z-]*)", normalised)
            if fallback:
                details["name"] = fallback.group(1).strip().title()
            else:
                hi_fallback = re.search(r"\bhi\s+i\s+m\s+([a-z][a-z-]*)", normalised)
                if hi_fallback:
                    details["name"] = hi_fallback.group(1).strip().title()
        for service in settings["pricing"]:
            if service.lower() in lower:
                details["clean_type"] = service
        if "deep" in lower:
            details.setdefault("clean_type", "Deep clean")
        elif "regular" in lower or "weekly" in lower or "fortnight" in lower:
            details.setdefault("clean_type", "Regular clean")
        elif "tenancy" in lower or "move" in lower:
            details.setdefault("clean_type", "End of tenancy")
        elif "one off" in lower or "one-off" in lower:
            details.setdefault("clean_type", "One-off clean")
        if "cambridge" in lower:
            details.setdefault("location", "your area")
        postcode_match = re.search(r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}\b", message.upper())
        if postcode_match:
            details["postcode"] = postcode_match.group(0).upper()
        email_match = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", message)
        if email_match:
            details["email"] = email_match.group(0).lower()
        phone_match = re.search(r"(\+?\d[\d\s-]{8,}\d)", message)
        if phone_match:
            details["phone"] = phone_match.group(1).strip()
        date_match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", message)
        if date_match:
            details["preferred_date"] = date_match.group(0)
        elif "next friday" in lower:
            today = datetime.now().date()
            days = (4 - today.weekday()) % 7 or 7
            details["preferred_date"] = (today + timedelta(days=days)).isoformat()
        for number in range(0, 8):
            if f"{number} bed" in lower or f"{number}-bed" in lower:
                details["bedrooms"] = number
            if f"{number} bath" in lower or f"{number}-bath" in lower:
                details["bathrooms"] = number
        if "morning" in lower:
            details["preferred_time"] = "Morning (8am–12pm)"
        elif "afternoon" in lower and "late" not in lower:
            details["preferred_time"] = "Afternoon (12pm–4pm)"
        elif "late afternoon" in lower:
            details["preferred_time"] = "Late afternoon (4pm–6pm)"
        elif "flexible" in lower:
            details["preferred_time"] = "Flexible"
        for key in ("name", "address"):
            marker = f"{key}:"
            if marker in lower:
                details[key] = message[lower.index(marker)+len(marker):].strip().split("\n")[0].strip()
        if not details.get("name"):
            first_sentence = re.split(r"[.!?]", message, 1)[0]
            intro_words = [word for word in re.findall(r"[A-Za-z-]+", first_sentence) if word.lower() not in {"hi", "hello", "hey", "i", "im", "m", "am", "my", "name", "is"}]
            if intro_words and any(word in first_sentence.lower() for word in ("hi", "hello", "i", "name")):
                details["name"] = intro_words[-1].title()
        return details

    def build_receptionist_reply(self, conversation_id, details, existing_booking_id=None):
        if not details.get("name"):
            with connect() as conn:
                latest_customer = conn.execute("SELECT message FROM ai_messages WHERE conversation_id=? AND sender='customer' ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()
            if latest_customer:
                intro_name = extract_intro_name(latest_customer["message"])
                if intro_name:
                    details["name"] = intro_name
                    with connect() as conn:
                        conn.execute("UPDATE ai_conversations SET collected_details=?,customer_name=?,updated_at=? WHERE id=?", (json.dumps(details), details["name"], utcnow().isoformat(), conversation_id))
        required = BOOKING_FIELDS
        missing = [field for field in required if details.get(field) in (None, "")]
        quote = None
        if details.get("clean_type") and details.get("bedrooms") not in (None, "") and details.get("bathrooms") not in (None, ""):
            total = quote_pence(details["clean_type"], details["bedrooms"], details["bathrooms"])
            deposit = round(total * .25)
            quote = {"total_amount": total, "deposit_amount": deposit, "balance_amount": total-deposit}
        if not missing and not existing_booking_id:
            booking = create_booking_record(details, [], "AI Receptionist chat")
            with connect() as conn:
                conn.execute("UPDATE ai_conversations SET booking_id=?,status='Booking Created',updated_at=? WHERE id=?", (booking["booking_id"], utcnow().isoformat(), conversation_id))
            pay_line = f" You can pay the 25% deposit here: {booking['checkout_url']}" if booking.get("checkout_url") else f" The booking is saved as Deposit Due. {booking.get('checkout_error') or ''}"
            return f"Lovely, I have created your Sparkles booking {booking['reference']}. The total is £{booking['total_amount']/100:.2f} and the deposit is £{booking['deposit_amount']/100:.2f}.{pay_line}", quote, booking
        if existing_booking_id:
            return "Your booking has already been created. If you need to change anything, the Sparkles team can help from here.", quote, None
        quote_required = ["clean_type", "bedrooms", "bathrooms", "postcode", "email"]
        quote_missing = [field for field in quote_required if details.get(field) in (None, "")]
        if details.get("location") and not details.get("postcode"):
            quote_missing = [field for field in quote_missing if field != "postcode"] + ["postcode"]
        provided_labels = {
            "clean_type": details.get("clean_type"),
            "bedrooms": f"{details.get('bedrooms')} bedroom{'s' if str(details.get('bedrooms')) != '1' else ''}" if details.get("bedrooms") not in (None, "") else None,
            "bathrooms": f"{details.get('bathrooms')} bathroom{'s' if str(details.get('bathrooms')) != '1' else ''}" if details.get("bathrooms") not in (None, "") else None,
            "location": details.get("postcode") or details.get("location"),
            "preferred_date": details.get("preferred_date"),
            "preferred_time": details.get("preferred_time")
        }
        summary = [value for value in provided_labels.values() if value]
        customer_name = details.get("name", "").split(" ")[0]
        greeting = f"Hi {customer_name}! Thanks for getting in touch. I can certainly help." if customer_name else "Thanks for getting in touch — I can certainly help."
        if quote_missing:
            friendly_missing = {
                "clean_type": "Type of clean",
                "bedrooms": "Number of bedrooms",
                "bathrooms": "Number of bathrooms",
                "postcode": "Your postcode",
                "email": "Your email address"
            }
            reply = greeting
            if summary:
                reply += "\n\nBased on what you have told me, I have:\n" + "\n".join(f"✅ {item}" for item in summary)
            reply += "\n\nTo give you an accurate quote I just need:\n" + "\n".join(f"• {friendly_missing[field]}" for field in quote_missing[:5])
            reply += "\n\nOnce I have those I will generate your quote and send you the secure booking link."
            return reply, quote, None
        if quote and any(field in missing for field in ("name", "phone", "address", "preferred_date", "preferred_time")):
            booking_link = ai_settings()["booking_url"]
            remaining = {
                "name": "your full name", "phone": "your phone number", "address": "the full cleaning address",
                "preferred_date": "your preferred date", "preferred_time": "your preferred time"
            }
            ask = [remaining[field] for field in ("name", "phone", "address", "preferred_date", "preferred_time") if field in missing]
            reply = f"{greeting}\n\nYour estimated quote is £{quote['total_amount']/100:.2f}, with a 25% deposit of £{quote['deposit_amount']/100:.2f}."
            reply += f"\n\nYou can also complete the secure booking form here: {booking_link}"
            if ask:
                reply += "\n\nIf you would like me to prepare the booking in chat, I just need " + ", ".join(ask[:3]) + "."
            return reply, quote, None
        question_labels = {
            "name": "your full name", "phone": "your phone number", "email": "your email address",
            "address": "the cleaning address", "postcode": "the postcode", "clean_type": "the type of clean",
            "bedrooms": "how many bedrooms", "bathrooms": "how many bathrooms",
            "preferred_date": "your preferred date", "preferred_time": "your preferred time"
        }
        intro = "Thanks, I can help with that."
        if quote:
            intro = f"Based on that, the estimated total is £{quote['total_amount']/100:.2f}. The 25% deposit would be £{quote['deposit_amount']/100:.2f}."
        return intro + " Could you please tell me " + ", ".join(question_labels[field] for field in missing[:3]) + "?", quote, None

    def owner_dashboard_payload(self):
        business_tz = datetime.now().astimezone().tzinfo or timezone.utc
        today = datetime.now(business_tz).date()
        tomorrow = today + timedelta(days=1)
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        today_s, tomorrow_s = today.isoformat(), tomorrow.isoformat()
        week_start_s, month_start_s = week_start.isoformat(), month_start.isoformat()
        today_start_ts = int(datetime.combine(today, datetime.min.time(), business_tz).astimezone(timezone.utc).timestamp())
        tomorrow_start_ts = int(datetime.combine(tomorrow, datetime.min.time(), business_tz).astimezone(timezone.utc).timestamp())
        week_start_ts = int(datetime.combine(week_start, datetime.min.time(), business_tz).astimezone(timezone.utc).timestamp())
        month_start_ts = int(datetime.combine(month_start, datetime.min.time(), business_tz).astimezone(timezone.utc).timestamp())
        successful_payment_statuses = {"paid", "succeeded", "success", "complete", "completed", "paid in full"}
        converted_booking_statuses = {"deposit paid", "paid in full", "paid", "complete", "completed", "succeeded"}

        def normalise(value):
            return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()

        def quote_identifier(identifier):
            return '"' + str(identifier).replace('"', '""') + '"'

        def normalised_columns(row):
            return {normalise(key): key for key in row.keys()}

        def get_value(row, *aliases, default=None):
            lookup = normalised_columns(row)
            for alias in aliases:
                key = lookup.get(normalise(alias))
                if key is not None:
                    return row.get(key)
            return default

        def int_value(value):
            try:
                if value in (None, ""):
                    return 0
                return int(float(str(value).replace(",", "")))
            except (TypeError, ValueError):
                return 0

        def date_part(value):
            return str(value or "")[:10]

        def datetime_to_ts(value):
            if value in (None, ""):
                return None
            if isinstance(value, (int, float)):
                return int(value)
            text = str(value).strip()
            if text.isdigit():
                return int(text)
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return int(parsed.astimezone(timezone.utc).timestamp())
            except ValueError:
                try:
                    parsed = datetime.fromisoformat(text[:10]).replace(tzinfo=business_tz)
                    return int(parsed.astimezone(timezone.utc).timestamp())
                except ValueError:
                    return None

        def is_active_cleaner(cleaner):
            inactive_values = {"0", "false", "no", "inactive", "disabled", "archived", "suspended", "deleted", "cancelled", "canceled", "pending", "invited"}
            active_values = {"1", "true", "yes", "active", "enabled", "approved", "verified", "available", "onboarded"}
            password_value = get_value(cleaner, "password_hash", default="__missing__")
            if password_value in ("", None):
                return False
            role_value = get_value(cleaner, "role", "user_role", "account_type", "user_type", "type", default=None)
            has_cleaner_role = role_value is not None and "cleaner" in normalise(role_value)
            if role_value is not None and not has_cleaner_role:
                return False
            active_value = get_value(cleaner, "active", "is_active", "enabled", "account_active", default=None)
            if active_value is not None:
                return normalise(active_value) in active_values
            status_value = get_value(cleaner, "status", "account_status", "profile_status", default=None)
            if status_value is not None:
                status = normalise(status_value)
                return status in active_values or (has_cleaner_role and status not in inactive_values)
            cleaner_profile_fields = (
                "travel_radius", "hourly_rate", "availability", "services",
                "services_offered", "dbs_status", "insurance_status"
            )
            has_cleaner_profile = any(get_value(cleaner, field, default=None) not in (None, "") for field in cleaner_profile_fields)
            has_contact = get_value(cleaner, "name", "full_name", "email", "phone", default=None) not in (None, "")
            return has_cleaner_role or (has_cleaner_profile and has_contact)

        def is_converted_booking(booking):
            return normalise(get_value(booking, "payment_status", "stripe_status", "deposit_status", "payment_state")) in converted_booking_statuses

        def truthy_flag(value):
            return normalise(value) in {"1", "true", "yes", "y", "on", "test", "archived"}

        def is_excluded_booking(booking):
            return bool(get_value(booking, "archived_at", "archived", "deleted_at", default=None)) or truthy_flag(get_value(booking, "is_test", "test", "exclude_from_dashboard", default=0))

        def successful_payment_rows(bookings, payments):
            rows = []
            paid_types_by_booking = {}
            for payment in payments:
                if normalise(get_value(payment, "status", "payment_status", "stripe_status", "state")) not in successful_payment_statuses:
                    continue
                booking_id = get_value(payment, "booking_id", "booking", "booking_ref", "booking_reference")
                row = {
                    "booking_id": booking_id,
                    "payment_type": normalise(get_value(payment, "payment_type", "type", "kind", default="payment")) or "payment",
                    "amount": int_value(get_value(payment, "amount", "amount_paid", "total", "value")),
                    "created_at": get_value(payment, "created_at", "paid_at", "payment_date", "created", "timestamp"),
                    "created_ts": datetime_to_ts(get_value(payment, "created_at", "paid_at", "payment_date", "created", "timestamp")),
                    "source": "payments"
                }
                rows.append(row)
                paid_types_by_booking.setdefault(row["booking_id"], set()).add(row["payment_type"])
            for booking in bookings:
                if not is_converted_booking(booking):
                    continue
                booking_id = get_value(booking, "id", "booking_id")
                existing_types = paid_types_by_booking.get(booking_id, set())
                has_full_payment = "full" in existing_types or "paid in full" in existing_types
                paid_at = get_value(booking, "paid_at", "deposit_paid_at", "created_at", "created", "timestamp")
                if not has_full_payment and "deposit" not in existing_types:
                    rows.append({
                        "booking_id": booking_id,
                        "payment_type": "deposit",
                        "amount": int_value(get_value(booking, "deposit_amount", "deposit", "deposit_paid", "deposit_total")),
                        "created_at": paid_at,
                        "created_ts": datetime_to_ts(paid_at),
                        "source": "bookings.payment_status"
                    })
                if normalise(get_value(booking, "payment_status", "stripe_status", "deposit_status", "payment_state")) == "paid in full" and not has_full_payment and "balance" not in existing_types:
                    rows.append({
                        "booking_id": booking_id,
                        "payment_type": "balance",
                        "amount": int_value(get_value(booking, "balance_amount", "balance", "remaining_amount", "remaining_balance")),
                        "created_at": paid_at,
                        "created_ts": datetime_to_ts(paid_at),
                        "source": "bookings.payment_status"
                    })
            return rows

        def stripe_checkout_payment_rows(start_date):
            if not stripe_configured():
                return [], None
            try:
                archived_sessions = archived_stripe_session_ids()
                start = datetime.fromisoformat(start_date).replace(tzinfo=business_tz)
                created_gte = int(start.astimezone(timezone.utc).timestamp())
                rows, starting_after = [], None
                while True:
                    params = {"limit": 100, "created[gte]": created_gte}
                    if starting_after:
                        params["starting_after"] = starting_after
                    page = stripe_get("checkout/sessions", params)
                    sessions = page.get("data", [])
                    for session in sessions:
                        if session.get("payment_status") != "paid":
                            continue
                        if session.get("id") in archived_sessions:
                            continue
                        amount = int(session.get("amount_total") or 0)
                        if amount <= 0:
                            continue
                        metadata = session.get("metadata") or {}
                        created = datetime.fromtimestamp(int(session.get("created", 0)), timezone.utc).astimezone(business_tz)
                        booking_id = metadata.get("booking_id") or session.get("client_reference_id") or session.get("id")
                        rows.append({
                            "booking_id": booking_id,
                            "booking_reference": metadata.get("booking_reference") or metadata.get("reference") or booking_id,
                            "payment_type": normalise(metadata.get("payment_type") or "deposit"),
                            "amount": amount,
                            "created_at": created.date().isoformat(),
                            "created_ts": int(session.get("created", 0)),
                            "source": "stripe.checkout.sessions",
                            "checkout_session_id": session.get("id"),
                            "provider_payment_id": session.get("payment_intent") or session.get("id")
                        })
                    if not page.get("has_more") or not sessions:
                        break
                    starting_after = sessions[-1]["id"]
                return rows, None
            except (ValueError, TypeError, urllib.error.URLError) as error:
                return [], str(error)

        def score_table(columns, kind):
            cols = {normalise(column) for column in columns}
            if kind == "bookings":
                signals = {"preferred_date", "clean_type", "payment_status", "deposit_amount", "total_amount", "postcode", "bathrooms", "bedrooms", "cleaner_id", "assigned_at"}
            elif kind == "payments":
                signals = {"payment_type", "provider_payment_id", "booking_id", "amount", "amount_paid", "payment_status", "stripe_status", "paid_at"}
            elif kind == "cleaners":
                signals = {"travel_radius", "hourly_rate", "availability", "services", "dbs_status", "insurance_status", "postcode", "active", "is_active", "enabled", "account_status", "profile_status", "role", "user_role", "account_type", "user_type"}
            else:
                signals = {"admin_takeover", "collected_details", "conversation_id", "customer_email", "customer_phone", "booking_id"}
            return sum(1 for signal in signals if signal in cols)

        def choose_table(table_meta, preferred, kind):
            candidates = [table for table in table_meta if not table["name"].startswith("sqlite_")]
            ranked = sorted(candidates, key=lambda table: (
                1 if score_table(table["columns"], kind) > 0 and table["row_count"] > 0 else 0,
                1 if table["name"] == preferred and table["row_count"] > 0 else 0,
                score_table(table["columns"], kind),
                table["row_count"],
                1 if table["name"] == preferred else 0
            ), reverse=True)
            return ranked[0]["name"] if ranked and score_table(ranked[0]["columns"], kind) > 0 else preferred

        def read_table(conn, table_name):
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
            if not exists:
                return []
            return [dict(row) for row in conn.execute(f"SELECT * FROM {quote_identifier(table_name)}").fetchall()]

        def money_between(rows, start_date, end_date=None, payment_type=None, start_ts=None, end_ts=None):
            total = 0
            for row in rows:
                if start_ts is not None:
                    paid_ts = row.get("created_ts") or datetime_to_ts(row.get("created_at"))
                    if paid_ts is None or paid_ts < start_ts:
                        continue
                    if end_ts is not None and paid_ts >= end_ts:
                        continue
                else:
                    paid_date = date_part(row.get("created_at"))
                    if paid_date < start_date:
                        continue
                    if end_date and paid_date > end_date:
                        continue
                if payment_type and normalise(row.get("payment_type")) != payment_type:
                    continue
                total += int(row.get("amount") or 0)
            return total

        def booking_identity(booking):
            return get_value(booking, "id", "booking_id", "reference", "booking_reference", "ref")

        def payment_booking_identity(payment):
            return payment.get("booking_id") or payment.get("booking_reference")

        def inferred_booking_total_from_payment(payment):
            amount = int(payment.get("amount") or 0)
            payment_type = normalise(payment.get("payment_type"))
            if payment_type == "deposit":
                return amount * 4
            return amount

        def stripe_booking_rows(payments):
            seen, rows = set(), []
            for payment in payments:
                identity = payment_booking_identity(payment)
                if identity in (None, "") or identity in seen:
                    continue
                seen.add(identity)
                total = inferred_booking_total_from_payment(payment)
                rows.append({
                    "id": identity,
                    "reference": payment.get("booking_reference") or identity,
                    "status": "Deposit Paid",
                    "payment_status": "Deposit Paid",
                    "total_amount": total,
                    "deposit_amount": int(payment.get("amount") or 0) if normalise(payment.get("payment_type")) == "deposit" else 0,
                    "created_at": payment.get("created_at"),
                    "preferred_date": payment.get("created_at"),
                    "_source": "stripe.checkout.sessions"
                })
            return rows

        if using_postgres():
            selected_database = {"path": "PostgreSQL DATABASE_URL", "exists": True, "size_bytes": None, "tables": [], "row_counts": {}, "error": None}
            discovered_databases = [selected_database]
            connector = connect
        else:
            selected_database, discovered_databases = dashboard_database_profile()
            dashboard_db_path = Path(selected_database["path"])
            connector = (lambda: open_sqlite(dashboard_db_path, readonly=True)) if dashboard_db_path.exists() else connect
        with connector() as conn:
            table_names = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
            table_meta = []
            for table_name in table_names:
                columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()]
                count = conn.execute(f"SELECT COUNT(*) count FROM {quote_identifier(table_name)}").fetchone()["count"]
                table_meta.append({"name": table_name, "columns": columns, "row_count": count})
            booking_table = choose_table(table_meta, "bookings", "bookings")
            payment_table = choose_table(table_meta, "payments", "payments")
            # Active cleaner accounts must come from the real cleaners table only.
            # Do not use the generic table picker here: tables such as sessions can
            # contain role/email columns and look "cleaner-like", which causes login
            # sessions to be counted as active cleaner accounts.
            cleaner_table = "cleaners"
            conversation_table = choose_table(table_meta, "ai_conversations", "conversations")
            raw_bookings = read_table(conn, booking_table)
            payments = read_table(conn, payment_table)
            cleaners = read_table(conn, cleaner_table)
            conversations = read_table(conn, conversation_table)
            excluded_booking_identities = {
                str(booking_identity(booking))
                for booking in raw_bookings
                if is_excluded_booking(booking) and booking_identity(booking) not in (None, "")
            }
            bookings = [booking for booking in raw_bookings if not is_excluded_booking(booking)]
            payments = [
                payment for payment in payments
                if str(get_value(payment, "booking_id", "booking", "booking_ref", "booking_reference", default="")) not in excluded_booking_identities
            ]
            latest_ai_senders = {}
            if conversation_table == "ai_conversations" and "ai_messages" in table_names:
                latest_ai_senders = {
                    row["conversation_id"]: row["sender"]
                    for row in conn.execute("""
                        SELECT m.conversation_id,m.sender FROM ai_messages m
                        JOIN (
                            SELECT conversation_id,MAX(id) id FROM ai_messages GROUP BY conversation_id
                        ) latest ON latest.id=m.id
                    """).fetchall()
                }
            stored_payment_rows = successful_payment_rows(bookings, payments)
            stripe_payment_rows, stripe_payment_error = stripe_checkout_payment_rows(month_start_s)
            stripe_payment_rows = [
                payment for payment in stripe_payment_rows
                if str(payment_booking_identity(payment)) not in excluded_booking_identities
            ]
            payment_rows = stripe_payment_rows if stripe_payment_rows else stored_payment_rows
            if not bookings and stripe_payment_rows:
                bookings = stripe_booking_rows(stripe_payment_rows)
            paid_deposit_booking_identities = {
                str(payment_booking_identity(payment))
                for payment in payment_rows
                if payment_booking_identity(payment) not in (None, "")
                and normalise(payment.get("payment_type")) == "deposit"
            }
            paid_balance_booking_identities = {
                str(payment_booking_identity(payment))
                for payment in payment_rows
                if payment_booking_identity(payment) not in (None, "")
                and normalise(payment.get("payment_type")) in {"balance", "final", "remaining balance"}
            }
            revenue_today = money_between(payment_rows, today_s, today_s, start_ts=today_start_ts, end_ts=tomorrow_start_ts)
            revenue_week = money_between(payment_rows, week_start_s, today_s, start_ts=week_start_ts, end_ts=tomorrow_start_ts)
            revenue_month = money_between(payment_rows, month_start_s, today_s, start_ts=month_start_ts, end_ts=tomorrow_start_ts)
            deposits_today = money_between(payment_rows, today_s, today_s, "deposit", start_ts=today_start_ts, end_ts=tomorrow_start_ts)
            today_bookings = sum(1 for booking in bookings if date_part(get_value(booking, "preferred_date", "booking_date", "service_date", "scheduled_date", "clean_date", "date")) == today_s)
            tomorrow_bookings = sum(1 for booking in bookings if date_part(get_value(booking, "preferred_date", "booking_date", "service_date", "scheduled_date", "clean_date", "date")) == tomorrow_s)
            waiting_assignment = sum(
                1 for booking in bookings
                if (
                    str(booking_identity(booking)) in paid_deposit_booking_identities
                    or normalise(get_value(booking, "status", "booking_status")) == "deposit paid"
                    or normalise(get_value(booking, "payment_status", "deposit_status")) == "deposit paid"
                )
                and not get_value(booking, "cleaner_id", "assigned_cleaner_id", "cleaner")
                and normalise(get_value(booking, "status", "booking_status")) not in {"completed", "cancelled", "canceled"}
            )
            in_progress = sum(1 for booking in bookings if normalise(get_value(booking, "status", "booking_status")) == "in progress")
            completed_today = sum(1 for booking in bookings if normalise(get_value(booking, "status", "booking_status")) == "completed" and (date_part(get_value(booking, "completed_at", "completed_date", "finished_at")) == today_s or (not get_value(booking, "completed_at", "completed_date", "finished_at") and date_part(get_value(booking, "preferred_date", "booking_date", "service_date", "scheduled_date", "clean_date", "date")) == today_s)))
            outstanding_balances = sum(
                int_value(get_value(booking, "balance_amount", "balance", "remaining_amount", "remaining_balance"))
                for booking in bookings
                if str(booking_identity(booking)) not in paid_balance_booking_identities
                and normalise(get_value(booking, "payment_status", "payment_state")) != "paid in full"
                and normalise(get_value(booking, "status", "booking_status")) not in {"cancelled", "canceled"}
                and (
                    str(booking_identity(booking)) in paid_deposit_booking_identities
                    or normalise(get_value(booking, "status", "booking_status")) in {"deposit paid", "assigned", "accepted", "in progress", "completed"}
                    or normalise(get_value(booking, "payment_status", "deposit_status")) in {"deposit paid", "balance due"}
                )
            )
            active_cleaners = sum(1 for cleaner in cleaners if is_active_cleaner(cleaner))
            booking_identities = {booking_identity(booking) for booking in bookings if booking_identity(booking) not in (None, "")}
            paid_booking_identities = {payment_booking_identity(payment) for payment in payment_rows if payment_booking_identity(payment) not in (None, "")}
            total_bookings = max(len(bookings), len(booking_identities), len(paid_booking_identities))
            converted_booking_identities = {booking_identity(booking) for booking in bookings if is_converted_booking(booking) and booking_identity(booking) not in (None, "")}
            converted_bookings = max(len(converted_booking_identities), len(paid_booking_identities))
            quoted_totals = [int_value(get_value(booking, "total_amount", "total", "quote_total", "amount_total", "price", "quoted_amount")) for booking in bookings if int_value(get_value(booking, "total_amount", "total", "quote_total", "amount_total", "price", "quoted_amount")) > 0]
            if not quoted_totals and payment_rows:
                quoted_totals = [inferred_booking_total_from_payment(payment) for payment in payment_rows if inferred_booking_total_from_payment(payment) > 0]
            average_job = (sum(quoted_totals) / len(quoted_totals)) if quoted_totals else 0
            ai_waiting = sum(1 for convo in conversations if str(get_value(convo, "admin_takeover", default=0)) in {"1", "true", "True"} or normalise(get_value(convo, "status")) == "admin takeover" or latest_ai_senders.get(get_value(convo, "id", "conversation_id")) == "customer")
            recent_reviews = []
            if "customer_reviews" in table_names and "bookings" in table_names:
                recent_reviews = [dict(row) for row in conn.execute("""SELECT r.*, b.reference booking_reference
                    FROM customer_reviews r LEFT JOIN bookings b ON b.id=r.booking_id
                    ORDER BY r.created_at DESC LIMIT 5""").fetchall()]
            status_counts = {}
            for booking in bookings:
                status = get_value(booking, "status", "booking_status", default="Unknown") or "Unknown"
                status_counts[status] = status_counts.get(status, 0) + 1
            status_rows = [{"status": status, "count": count} for status, count in sorted(status_counts.items(), key=lambda item: item[1], reverse=True)]
            revenue_days = []
            for offset in range(6, -1, -1):
                day = today - timedelta(days=offset)
                day_s = day.isoformat()
                revenue_days.append({
                    "date": day_s,
                    "label": day.strftime("%a"),
                    "amount": money_between(payment_rows, day_s, day_s)
                })
            upcoming_rows = []
            if booking_table == "bookings" and cleaner_table == "cleaners":
                upcoming_rows = [dict(row) for row in conn.execute("""SELECT b.id,b.reference,b.name,b.clean_type,b.preferred_date,b.preferred_time,b.status,c.name cleaner_name
                    FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id
                    WHERE b.preferred_date IN (?,?) AND COALESCE(b.is_test,0)=0 AND b.archived_at IS NULL
                    ORDER BY b.preferred_date,b.preferred_time LIMIT 10""", (today_s, tomorrow_s)).fetchall()]
            database_info = {
                "path": selected_database["path"],
                "write_path": "PostgreSQL DATABASE_URL" if using_postgres() else str(DB),
                "exists": selected_database["exists"],
                "size_bytes": selected_database["size_bytes"],
                "discovered_databases": discovered_databases,
                "tables": table_meta,
                "selected_sources": {
                    "bookings": booking_table,
                    "stripe_payments": payment_table,
                    "cleaners": cleaner_table,
                    "ai_conversations": conversation_table
                },
                "table_counts": {table["name"]: table["row_count"] for table in table_meta} | {
                    "dashboard_bookings_used": len(bookings),
                    "dashboard_bookings_excluded": len(raw_bookings) - len(bookings),
                    "dashboard_payments_used": len(payments),
                    "dashboard_cleaners_used": len(cleaners),
                    "dashboard_ai_conversations_used": len(conversations),
                    "successful_payment_rows_used": len(payment_rows),
                    "stripe_payment_rows_used": len(stripe_payment_rows),
                    "stored_payment_rows_used": len(stored_payment_rows),
                    "paid_booking_identities_used": len(paid_booking_identities),
                    "booking_identities_used": len(booking_identities)
                },
                "stripe_payment_source_error": stripe_payment_error
            }

        conversion_rate = round((converted_bookings / total_bookings) * 100, 1) if total_bookings else 0
        return {
            "as_of": utcnow().isoformat(),
            "database": database_info,
            "cards": {
                "revenue_today": revenue_today,
                "revenue_week": revenue_week,
                "revenue_month": revenue_month,
                "deposits_today": deposits_today,
                "total_bookings": total_bookings,
                "today_bookings": today_bookings,
                "tomorrow_bookings": tomorrow_bookings,
                "waiting_assignment": waiting_assignment,
                "in_progress": in_progress,
                "completed_today": completed_today,
                "active_cleaners": active_cleaners,
                "outstanding_balances": outstanding_balances,
                "ai_waiting_review": ai_waiting,
                "booking_conversion_rate": conversion_rate,
                "average_job_value": int(round(average_job or 0))
            },
            "charts": {
                "revenue_days": revenue_days,
                "booking_statuses": status_rows
            },
            "upcoming": upcoming_rows,
            "reviews": recent_reviews
        }

    def owner_dashboard(self):
        return self.send_json(self.owner_dashboard_payload())

    def launch_console_payload(self):
        dashboard = self.owner_dashboard_payload()
        cards = dashboard.get("cards", {})
        applicant_counts = {"total": 0, "new": 0, "recommended": 0, "needs_review": 0}
        recent_applicants = []
        try:
            with connect() as conn:
                applicant_rows = conn.execute("SELECT * FROM cleaner_applicants ORDER BY id DESC LIMIT 12").fetchall()
            scored = []
            for row in applicant_rows:
                item = dict(row)
                item.update(self.score_cleaner_applicant(item))
                item["availability"] = json.loads(item.get("availability") or "[]") if isinstance(item.get("availability"), str) else item.get("availability") or []
                item["services"] = json.loads(item.get("services") or "[]") if isinstance(item.get("services"), str) else item.get("services") or []
                scored.append(item)
            recent_applicants = scored[:5]
            applicant_counts["total"] = len(scored)
            applicant_counts["new"] = len([item for item in scored if str(item.get("status") or "New").lower() == "new"])
            applicant_counts["recommended"] = len([item for item in scored if item.get("recommendation") in {"Excellent", "Good"}])
            applicant_counts["needs_review"] = len([item for item in scored if item.get("recommendation") in {"Review", "Weak"}])
        except Exception as error:
            logger.warning(json.dumps({"launch_console_applicants": "failed", "error": str(error)}))

        booking_link = public_url().rstrip("/") + "/"
        cleaner_links = {
            "facebook": public_url().rstrip("/") + "/become-a-cleaner?source=facebook",
            "whatsapp": public_url().rstrip("/") + "/become-a-cleaner?source=whatsapp",
            "indeed": public_url().rstrip("/") + "/become-a-cleaner?source=indeed",
            "gumtree": public_url().rstrip("/") + "/become-a-cleaner?source=gumtree",
        }
        cleaner_post = (
            "Self-employed cleaners wanted\n\n"
            "Sparkles Cleaning Cambridge is looking for reliable self-employed domestic cleaners.\n\n"
            "We are building a trusted cleaner network and have cleaning job opportunities available based on your postcode, availability and travel radius.\n\n"
            "You choose:\n\n"
            "- Your availability\n"
            "- Your preferred travel area\n"
            "- The cleaning services you offer\n"
            "- Whether you want one-off, regular, deep clean or end-of-tenancy work\n\n"
            "Ideal for experienced cleaners who are reliable, friendly and professional.\n\n"
            "DBS and public liability insurance preferred, but you can still apply and tell us your current status.\n\n"
            f"Apply here:\n\n{cleaner_links['facebook']}\n\n"
            "Smiles Come Standard."
        )
        customer_post = (
            "Need a reliable cleaner?\n\n"
            "Sparkles Cleaning Cambridge lets you book a professional clean online in under 60 seconds.\n\n"
            "- One-off cleans\n"
            "- Regular cleans\n"
            "- Deep cleans\n"
            "- End-of-tenancy cleans\n"
            "- Secure 25% deposit by Stripe\n"
            "- Clear booking confirmation\n\n"
            f"Book here:\n\n{booking_link}\n\n"
            "Smiles Come Standard."
        )
        actions = [
            {
                "title": "Recruit cleaners",
                "detail": "Copy your cleaner advert/link into safe recruitment channels, then review applicants.",
                "href": "/admin/ai-recruitment",
                "button": "Open Cleaner Recruitment",
                "priority": "Supply"
            },
            {
                "title": "Review applicants",
                "detail": f"{applicant_counts['new']} new applicant(s), {applicant_counts['recommended']} recommended.",
                "href": "/admin/cleaner-applicants",
                "button": "Review applicants",
                "priority": "Supply"
            },
            {
                "title": "Get customer bookings",
                "detail": "Copy the customer advert and send people to your booking link.",
                "href": booking_link,
                "button": "Open booking page",
                "priority": "Demand"
            },
            {
                "title": "Assign paid bookings",
                "detail": f"{cards.get('waiting_assignment', 0)} booking(s) waiting for cleaner assignment.",
                "href": "/admin/bookings",
                "button": "Open bookings",
                "priority": "Operations"
            },
            {
                "title": "Collect balances",
                "detail": f"Outstanding balances: £{(cards.get('outstanding_balances', 0) or 0)/100:.2f}.",
                "href": "/admin/bookings",
                "button": "Check balances",
                "priority": "Cash"
            }
        ]
        return {
            "as_of": utcnow().isoformat(),
            "booking_link": booking_link,
            "cleaner_links": cleaner_links,
            "cards": {
                "applicants_total": applicant_counts["total"],
                "new_applicants": applicant_counts["new"],
                "recommended_applicants": applicant_counts["recommended"],
                "active_cleaners": cards.get("active_cleaners", 0),
                "total_bookings": cards.get("total_bookings", 0),
                "waiting_assignment": cards.get("waiting_assignment", 0),
                "revenue_week": cards.get("revenue_week", 0),
                "outstanding_balances": cards.get("outstanding_balances", 0),
            },
            "copy": {
                "cleaner_facebook": cleaner_post,
                "customer_facebook": customer_post,
                "whatsapp_referral": f"Hi, I'm building a cleaner network for Sparkles Cleaning Cambridge. Do you know any reliable cleaners who might want self-employed cleaning work? They can apply here: {cleaner_links['whatsapp']}",
                "customer_whatsapp": f"I'm now taking cleaning bookings through Sparkles Cleaning Cambridge. You can book online, get your quote and pay the 25% deposit securely by Stripe: {booking_link}"
            },
            "actions": actions,
            "recent_applicants": recent_applicants,
        }

    def launch_console(self):
        return self.send_json(self.launch_console_payload())

    def admin_diagnostics(self):
        def quote_identifier(identifier):
            return '"' + str(identifier).replace('"', '""') + '"'

        def latest_row(conn, table_name):
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
            if not exists:
                return None
            columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()]
            order_column = "id" if "id" in columns else "rowid"
            row = conn.execute(f"SELECT * FROM {quote_identifier(table_name)} ORDER BY {quote_identifier(order_column)} DESC LIMIT 1").fetchone()
            return dict(row) if row else None

        session = self.current_session()
        dashboard_payload = self.owner_dashboard_payload()
        if using_postgres():
            selected_database = {"path": "PostgreSQL DATABASE_URL", "exists": True, "size_bytes": None, "tables": [], "row_counts": {}, "error": None}
            discovered_databases = [selected_database]
            connector = connect
        else:
            selected_database, discovered_databases = dashboard_database_profile()
            diagnostics_db_path = Path(selected_database["path"])
            connector = (lambda: open_sqlite(diagnostics_db_path, readonly=True)) if diagnostics_db_path.exists() else connect
        with connector() as conn:
            table_names = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
            row_counts = {}
            for table_name in table_names:
                row_counts[table_name] = conn.execute(f"SELECT COUNT(*) count FROM {quote_identifier(table_name)}").fetchone()["count"]
            diagnostics = {
                "database_path": selected_database["path"],
                "write_database_path": "PostgreSQL DATABASE_URL" if using_postgres() else str(DB),
                "database_exists": selected_database["exists"],
                "email_provider": email_provider_diagnostics(),
                "smtp_network": smtp_network_check("smtp.gmail.com", 587),
                "discovered_databases": discovered_databases,
                "table_names": table_names,
                "row_counts": row_counts,
                "latest_booking": latest_row(conn, "bookings"),
                "latest_stripe_payment": latest_row(conn, "payments"),
                "latest_cleaner": latest_row(conn, "cleaners"),
                "latest_ai_conversation": latest_row(conn, "ai_conversations"),
                "raw_dashboard_metrics": dashboard_payload,
                "current_admin_email": session["email"] if session else None
            }
        return self.send_json(diagnostics)

    def admin_email_diagnostics(self):
        with connect() as conn:
            recent = [dict(row) for row in conn.execute("""
                SELECT id,booking_id,recipient,subject,status,error,created_at
                FROM email_log ORDER BY id DESC LIMIT 20
            """).fetchall()]
        return self.send_json({
            "email_provider": email_provider_diagnostics(),
            "smtp": smtp_diagnostics(),
            "smtp_network": smtp_network_check("smtp.gmail.com", 587),
            "recent_email_log": recent,
            "required_railway_variables": ["EMAIL_FROM", "SMTP_FROM"],
            "optional_railway_variables": ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_PROVIDER", "RESEND_API_KEY", "SENDGRID_API_KEY"],
            "notes": "If smtp_network.conclusion is smtp_port_unreachable_or_blocked, set EMAIL_PROVIDER=resend with RESEND_API_KEY or EMAIL_PROVIDER=sendgrid with SENDGRID_API_KEY."
        })

    def admin_email_test(self):
        try:
            data = self.read_json()
            recipient = (data.get("email") or runtime_setting("COMPANY_EMAIL", "") or runtime_setting("ADMIN_EMAIL", "")).strip()
            if not recipient:
                raise ValueError("Provide an email address for the test.")
            subject = "Sparkles test email"
            body = "This is a test email from Sparkles Cleaning Cambridge. Smiles Come Standard. If you received it, email delivery is configured correctly."
            config = smtp_config()
            provider = email_provider_config()
            if not config["host"]:
                logger.warning(json.dumps({"email_test": "preview", "recipient": recipient, "missing": smtp_diagnostics()["missing"]}))
                if provider["provider"] == "smtp":
                    return self.send_json({"status": "Preview", "sent": False, "email_provider": email_provider_diagnostics(), "smtp": smtp_diagnostics(), "message": "SMTP_HOST is missing, so no real email was sent."}, 503)
            message = EmailMessage()
            message["From"], message["To"], message["Subject"] = config["from"], recipient, subject
            message.set_content(body)
            message.add_alternative(sparkles_email_html("Test email", "This is a test email from Sparkles Cleaning Cambridge. Smiles Come Standard. If you received it, email delivery is configured correctly.", [
                ("Recipient", recipient),
                ("SMTP host", config["host"]),
                ("SMTP mode", "SSL" if config["port"] == 465 else "STARTTLS"),
            ]), subtype="html")
            deliver_email_message(message)
            logger.info(json.dumps({"email_test": "sent", "recipient": recipient}))
            return self.send_json({"status": "Sent", "sent": True, "recipient": recipient, "email_provider": email_provider_diagnostics(), "smtp": smtp_diagnostics()})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)
        except Exception as error:
            logger.error(json.dumps({"email_test": "failed", "error": str(error)}))
            return self.send_json({"status": "Failed", "sent": False, "error": str(error), "email_provider": email_provider_diagnostics(), "smtp": smtp_diagnostics()}, 502)

    def receptionist_conversations(self):
        if not self.require_admin():
            return
        with connect() as conn:
            rows = conn.execute("""SELECT c.*, b.reference booking_reference FROM ai_conversations c
                LEFT JOIN bookings b ON b.id=c.booking_id ORDER BY c.updated_at DESC LIMIT 100""").fetchall()
        return self.send_json([dict(row) for row in rows])

    def receptionist_public_messages(self, path):
        try:
            conversation_id = int(path.split("/")[4])
            with connect() as conn:
                convo = conn.execute("SELECT id FROM ai_conversations WHERE id=?", (conversation_id,)).fetchone()
                if not convo:
                    conversation = self.create_receptionist_conversation()
                    messages = conn.execute("SELECT id,sender,message,created_at FROM ai_messages WHERE conversation_id=? ORDER BY id", (conversation["conversation_id"],)).fetchall()
                    return self.send_json({"conversation_id": conversation["conversation_id"], "messages": [dict(row) for row in messages]})
                messages = conn.execute("SELECT id,sender,message,created_at FROM ai_messages WHERE conversation_id=? ORDER BY id", (conversation_id,)).fetchall()
            return self.send_json({"conversation_id": conversation_id, "messages": [dict(row) for row in messages]})
        except (ValueError, IndexError):
            conversation = self.create_receptionist_conversation()
            with connect() as conn:
                messages = conn.execute("SELECT id,sender,message,created_at FROM ai_messages WHERE conversation_id=? ORDER BY id", (conversation["conversation_id"],)).fetchall()
            return self.send_json({"conversation_id": conversation["conversation_id"], "messages": [dict(row) for row in messages]})

    def receptionist_detail(self, path):
        if not self.require_admin():
            return
        conversation_id = int(path.split("/")[4])
        with connect() as conn:
            convo = conn.execute("SELECT * FROM ai_conversations WHERE id=?", (conversation_id,)).fetchone()
            messages = conn.execute("SELECT * FROM ai_messages WHERE conversation_id=? ORDER BY id", (conversation_id,)).fetchall()
        if not convo:
            return self.send_json({"error": "Conversation not found."}, 404)
        return self.send_json({"conversation": dict(convo), "messages": [dict(row) for row in messages]})

    def receptionist_takeover(self, path):
        if not self.require_admin():
            return
        conversation_id = int(path.split("/")[4])
        data = self.read_json()
        enabled = 1 if data.get("admin_takeover", True) else 0
        status = "Admin Takeover" if enabled else "AI Active"
        with connect() as conn:
            conn.execute("UPDATE ai_conversations SET admin_takeover=?,status=?,updated_at=? WHERE id=?", (enabled, status, utcnow().isoformat(), conversation_id))
            conn.execute("INSERT INTO ai_messages(conversation_id,sender,message,created_at) VALUES (?,?,?,?)", (conversation_id, "system", f"Admin takeover {'enabled' if enabled else 'disabled'}", utcnow().isoformat()))
        return self.send_json({"ok": True, "admin_takeover": bool(enabled), "status": status})

    def receptionist_admin_reply(self, path):
        if not self.require_admin():
            return
        conversation_id = int(path.split("/")[4])
        data = self.read_json()
        message = str(data.get("message", "")).strip()
        if not message:
            return self.send_json({"error": "Please enter a reply."}, 400)
        with connect() as conn:
            conn.execute("UPDATE ai_conversations SET admin_takeover=1,status='Admin Takeover',updated_at=? WHERE id=?", (utcnow().isoformat(), conversation_id))
            conn.execute("INSERT INTO ai_messages(conversation_id,sender,message,created_at) VALUES (?,?,?,?)", (conversation_id, "admin", message, utcnow().isoformat()))
        return self.send_json({"ok": True})

    def start_checkout(self, path):
        try:
            booking_id = int(path.split("/")[3])
            data = self.read_json()
            payment_type = data.get("payment_type", "deposit")
            if payment_type not in ("deposit", "balance"):
                raise ValueError("Invalid payment type.")
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            if not booking:
                return self.send_json({"error": "Booking not found."}, 404)
            session = self.current_session()
            is_admin = bool(session and session["role"] == "admin")
            is_booking_customer = bool(
                session and session["role"] == "customer" and (
                    int(booking["customer_id"] or 0) == int(session["subject_id"] or 0)
                    or str(booking["email"] or "").strip().lower() == str(session["email"] or "").strip().lower()
                )
            )
            if not is_admin and not is_booking_customer:
                return self.send_json({"error": "Please log in to your customer portal to manage this booking payment."}, 401)
            if payment_type == "deposit" and booking["payment_status"] in ("Deposit Paid", "Paid in Full"):
                return self.send_json({"paid": True, "message": "Deposit has already been paid."})
            if payment_type == "balance" and booking["status"] != "Completed":
                return self.send_json({"error": "The remaining balance is available after the job is completed."}, 409)
            session = create_checkout(booking, payment_type)
            if payment_type == "deposit":
                with connect() as conn:
                    conn.execute("UPDATE bookings SET deposit_checkout_session_id=?, deposit_checkout_url=? WHERE id=?", (session["id"], session["url"], booking_id))
            self.send_json({"url": session["url"], "session_id": session["id"]})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)

    def resend_final_invoice(self, path):
        try:
            booking_id = int(path.split("/")[3])
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            if not booking:
                return self.send_json({"error": "Booking not found."}, 404)
            if booking["status"] != "Completed":
                return self.send_json({"error": "Final balance emails can only be sent after the job is completed."}, 409)
            if booking["payment_status"] == "Paid in Full":
                return self.send_json({"error": "This booking is already paid in full."}, 409)
            if int(booking["balance_amount"] or 0) <= 0:
                return self.send_json({"error": "This booking has no remaining balance to collect."}, 409)
            automation_handler({"step": "send_final_invoice", "booking_id": booking_id})
            automation.timeline(booking_id, "Final balance email resent", "Admin resent the final balance email with a secure Stripe Checkout link")
            return self.send_json({"ok": True, "message": "Final balance email sent."})
        except (ValueError, TypeError) as error:
            self.send_json({"error": str(error) or "Could not resend final balance email."}, 400)
        except Exception as error:
            logger.error(json.dumps({"resend_final_invoice": "failed", "error": str(error)}))
            self.send_json({"error": str(error) or "Could not resend final balance email."}, 500)

    def verify_checkout(self, session_id):
        try:
            if not session_id:
                raise ValueError("Missing Stripe session.")
            session = stripe_request(f"checkout/sessions/{session_id}", None, "GET")
            if session.get("payment_status") != "paid":
                return self.send_json({"paid": False, "error": "Payment has not completed."}, 402)
            booking_id = int(session.get("metadata", {}).get("booking_id") or session.get("client_reference_id"))
            payment_type = session.get("metadata", {}).get("payment_type", "deposit")
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                if not booking:
                    return self.send_json({"error": "Booking not found for this Stripe session."}, 404)
                amount = booking["deposit_amount"] if payment_type == "deposit" else booking["balance_amount"]
                record_payment(conn, booking_id, payment_type, amount, session.get("payment_intent") or session_id)
            automation.timeline(booking_id, "Payment received", f"{payment_type.title()} payment confirmed: £{amount/100:.2f}")
            if payment_type == "deposit":
                safe_send_booking_confirmation_email(booking_id, True, f"Hello {booking['name']}, your Sparkles booking is confirmed and your deposit has been received. Here are the details.")
                automation.enqueue(booking_id, "send_payment_confirmation")
                automation.enqueue(booking_id, "offer_cleaners")
            else:
                automation.enqueue(booking_id, "send_review")
            self.send_json({"paid": True, "booking_id": booking_id, "payment_type": payment_type})
        except (ValueError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)

    def stripe_webhook(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            webhook_secret = runtime_setting("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET)
            if not webhook_secret:
                raise ValueError("Stripe webhook secret is not configured.")
            signature = self.headers.get("Stripe-Signature", "")
            parts = dict(part.split("=", 1) for part in signature.split(",") if "=" in part)
            timestamp, supplied = parts.get("t"), parts.get("v1")
            if not timestamp or not supplied or abs(time.time() - int(timestamp)) > 300:
                raise ValueError("Invalid Stripe signature.")
            expected = hmac.new(webhook_secret.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, supplied):
                raise ValueError("Invalid Stripe signature.")
            event = json.loads(payload)
            if event.get("type") == "checkout.session.completed":
                session = event["data"]["object"]
                booking_id = int(session.get("metadata", {}).get("booking_id") or session.get("client_reference_id"))
                payment_type = session.get("metadata", {}).get("payment_type", "deposit")
                with connect() as conn:
                    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                    if not booking:
                        return self.send_json({"error": "Booking not found for this Stripe event."}, 404)
                    amount = booking["deposit_amount"] if payment_type == "deposit" else booking["balance_amount"]
                    record_payment(conn, booking_id, payment_type, amount, session.get("payment_intent") or session["id"])
                automation.timeline(booking_id, "Payment received", f"{payment_type.title()} payment confirmed by Stripe webhook")
                if payment_type == "deposit":
                    safe_send_booking_confirmation_email(booking_id, True)
                    automation.enqueue(booking_id, "send_payment_confirmation")
                    automation.enqueue(booking_id, "offer_cleaners")
                else:
                    automation.enqueue(booking_id, "send_review")
            elif event.get("type") in ("invoice.paid", "invoice.payment_succeeded"):
                invoice = event["data"]["object"]
                with connect() as conn:
                    booking_id, amount = record_invoice_payment(conn, invoice)
                automation.timeline(booking_id, "Final payment received", f"Stripe invoice paid in full: £{amount/100:.2f}")
                automation.enqueue(booking_id, "send_review")
            self.send_json({"received": True})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)

    def create_cleaner(self):
        try:
            data = self.read_json()
            required = ["name", "phone", "email", "postcode", "travel_radius", "hourly_rate", "availability", "services", "dbs_status", "insurance_status"]
            if any(not data.get(key) for key in required):
                raise ValueError("Please complete all required fields.")
            radius, rate = float(data["travel_radius"]), float(data["hourly_rate"])
            if radius <= 0 or rate <= 0:
                raise ValueError("Travel radius and hourly rate must be greater than zero.")
            availability = data.get("availability")
            services = data.get("services")
            if not isinstance(availability, list) or not availability or not isinstance(services, list) or not services:
                raise ValueError("Choose at least one available day and one service.")
            verification = cleaner_verification_payload(data)
            with connect() as conn:
                cursor = conn.execute("""INSERT INTO cleaners
                    (name,phone,email,postcode,travel_radius,hourly_rate,availability,services,dbs_status,insurance_status,active,created_at,
                     identity_verified,right_to_work_verified,proof_of_address_verified,travel_method,driving_licence_status,has_own_vehicle)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    data["name"].strip(), data["phone"].strip(), data["email"].strip().lower(), data["postcode"].strip().upper(), radius, rate,
                    json.dumps(availability), json.dumps(services), data["dbs_status"], data["insurance_status"],
                    1 if data.get("active", True) else 0, datetime.now(timezone.utc).isoformat(),
                    verification["identity_verified"], verification["right_to_work_verified"], verification["proof_of_address_verified"],
                    verification["travel_method"], verification["driving_licence_status"], verification["has_own_vehicle"]
                ))
                cleaner_id = cursor.lastrowid
            invite = send_cleaner_invitation_email(cleaner_id) if data.get("send_invite", True) else {"status": "Not sent", "setup_link": None}
            self.send_json({"ok": True, "id": cleaner_id, "invite": invite}, 201)
        except DB_INTEGRITY_ERROR_TYPES:
            self.send_json({"error": "An account already exists for that email address."}, 409)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)

    def invite_cleaner(self, path):
        try:
            cleaner_id = int(path.split("/")[3])
            invite = send_cleaner_invitation_email(cleaner_id)
            return self.send_json({"ok": True, "invite": invite})
        except ValueError as error:
            return self.send_json({"error": str(error)}, 404)

    def indeed_invite_payload(self, applicant):
        code = str(applicant.get("invitation_code") or "").strip()
        return {
            "ok": True,
            "applicant_id": applicant["id"],
            "applicant_identifier": indeed_applicant_identifier(code),
            "name": applicant["name"],
            "source": "Indeed",
            "link": indeed_application_link(code),
            "message": indeed_invitation_message(applicant["name"], code),
            "invitation_status": applicant.get("invitation_status") or "Generated",
            "invitation_count": int(applicant.get("invitation_count") or 0),
        }

    def issue_indeed_applicant_invite(self, applicant_id=None, name="", external_reference="", notes=""):
        now = utcnow().isoformat()
        event = "Indeed invitation generated"
        with connect() as conn:
            applicant = None
            if applicant_id:
                applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
            elif external_reference:
                applicant = conn.execute("""SELECT * FROM cleaner_applicants
                    WHERE LOWER(source)='indeed' AND external_reference=?
                    ORDER BY id DESC LIMIT 1""", (external_reference,)).fetchone()
            if applicant:
                applicant = dict(applicant)

            if applicant and applicant["approved_cleaner_id"]:
                raise ValueError("This applicant has already been converted to a cleaner.")
            if applicant and applicant.get("application_completed_at"):
                raise ValueError("This applicant has already completed the Sparkles application.")

            if applicant:
                code = str(applicant.get("invitation_code") or "").strip() or secrets.token_urlsafe(18)
                resolved_name = str(name or applicant["name"] or "Indeed applicant").strip()
                resolved_reference = str(external_reference or applicant.get("external_reference") or "").strip()[:160]
                resolved_notes = str(notes or applicant.get("notes") or "").strip()
                conn.execute("""UPDATE cleaner_applicants
                    SET name=?, source='Indeed', status='Invited', notes=?, external_reference=?,
                        invitation_code=?, invitation_status='Generated', invitation_count=COALESCE(invitation_count,0)+1,
                        invitation_created_at=?, updated_at=?
                    WHERE id=?""", (
                    resolved_name, resolved_notes, resolved_reference, code, now, now, applicant["id"]
                ))
                applicant_id = applicant["id"]
                event = "Indeed invitation regenerated"
            else:
                code = secrets.token_urlsafe(18)
                resolved_name = str(name or "").strip()
                if not resolved_name:
                    raise ValueError("Enter the Indeed applicant's name.")
                cursor = conn.execute("""INSERT INTO cleaner_applicants
                    (name,phone,email,postcode,experience,travel_radius,hourly_rate,availability,services,
                     dbs_status,insurance_status,source,status,notes,created_at,updated_at,external_reference,
                     invitation_code,invitation_status,invitation_count,invitation_created_at,interview_status)
                    VALUES (?,'','','','',5,0,'[]','[]','Unknown','Unknown','Indeed','Invited',?,?,?,?,?,'Generated',1,?,'Not scheduled')""", (
                    resolved_name, str(notes or "").strip(), now, now,
                    str(external_reference or "").strip()[:160], code, now
                ))
                applicant_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
            autopilot_log(conn, "cleaner_recruitment", event, f"{row['name']} received a tracked Indeed application link.")
        applicant_timeline(applicant_id, event, f"Personal tracked link created as {indeed_applicant_identifier(row['invitation_code'])}")
        return self.indeed_invite_payload(dict(row))

    def create_indeed_applicant_invite(self):
        try:
            data = self.read_json()
            result = self.issue_indeed_applicant_invite(
                name=str(data.get("name") or "").strip(),
                external_reference=str(data.get("indeed_reference") or "").strip(),
                notes=str(data.get("notes") or "").strip(),
            )
            return self.send_json(result, 201)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error) or "Could not generate the Indeed invitation."}, 400)

    def invite_existing_indeed_applicant(self, path):
        try:
            applicant_id = int(path.split("/")[3])
            try:
                data = self.read_json()
            except ValueError:
                data = {}
            result = self.issue_indeed_applicant_invite(
                applicant_id=applicant_id,
                external_reference=str(data.get("indeed_reference") or "").strip(),
            )
            return self.send_json(result)
        except (ValueError, TypeError, json.JSONDecodeError, IndexError) as error:
            return self.send_json({"error": str(error) or "Could not generate the Indeed invitation."}, 400)

    def get_recruitment_invite(self, path):
        try:
            code = urllib.parse.unquote(path.split("/")[4]).strip()
            if not code or len(code) > 120:
                raise ValueError("Invalid recruitment invitation.")
            opened_now = False
            with connect() as conn:
                applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE invitation_code=?", (code,)).fetchone()
                if not applicant:
                    return self.send_json({"error": "This recruitment invitation is not valid."}, 404)
                applicant = dict(applicant)
                if not applicant.get("invitation_opened_at"):
                    opened_at = utcnow().isoformat()
                    conn.execute("""UPDATE cleaner_applicants
                        SET invitation_opened_at=?, invitation_status=CASE WHEN application_completed_at IS NULL THEN 'Opened' ELSE invitation_status END,
                            updated_at=? WHERE id=?""", (opened_at, opened_at, applicant["id"]))
                    opened_now = True
                applicant = dict(conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant["id"],)).fetchone())
            if opened_now:
                applicant_timeline(applicant["id"], "Indeed invitation opened", "Applicant opened their personal Sparkles application link")
            return self.send_json({
                "ok": True,
                "applicant_identifier": indeed_applicant_identifier(code),
                "name": applicant["name"],
                "source": "Indeed",
                "completed": bool(applicant.get("application_completed_at")),
            })
        except (ValueError, TypeError, IndexError) as error:
            return self.send_json({"error": str(error) or "Invalid recruitment invitation."}, 400)

    def cleaner_applicant_metrics(self):
        with connect() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM cleaner_applicants ORDER BY id DESC").fetchall()]
        indeed_rows = [row for row in rows if normalise_recruitment_source(row.get("source")) == "indeed"]
        invited = [row for row in indeed_rows if row.get("invitation_code")]
        completed = [row for row in invited if row.get("application_completed_at")]
        scored = [row for row in invited if row.get("ai_scored_at")]
        interviewed = [row for row in invited if str(row.get("interview_status") or "Not scheduled") != "Not scheduled"]
        approved = [row for row in invited if row.get("approved_cleaner_id") or row.get("status") in {"Approved", "Added as Cleaner"}]
        converted = [row for row in invited if row.get("approved_cleaner_id")]
        candidate_total = len(invited)
        return self.send_json({
            "source": "Indeed",
            "indeed_records": len(indeed_rows),
            "invited_candidates": candidate_total,
            "invitations_generated": sum(max(1, int(row.get("invitation_count") or 0)) for row in invited),
            "invitations_opened": len([row for row in invited if row.get("invitation_opened_at")]),
            "applications_completed": len(completed),
            "ai_scored": len(scored),
            "interviewed": len(interviewed),
            "approved": len(approved),
            "converted_to_cleaner": len(converted),
            "application_conversion_rate": round((len(completed) / candidate_total) * 100, 1) if candidate_total else 0,
            "cleaner_conversion_rate": round((len(converted) / candidate_total) * 100, 1) if candidate_total else 0,
        })

    def store_cleaner_applicant_score(self, applicant_id):
        with connect() as conn:
            applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
        if not applicant:
            raise ValueError("Applicant not found.")
        result = self.score_cleaner_applicant(dict(applicant))
        scored_at = utcnow().isoformat()
        with connect() as conn:
            conn.execute("""UPDATE cleaner_applicants
                SET ai_score=?, ai_recommendation=?, ai_scored_at=?, updated_at=? WHERE id=?""", (
                result["score"], result["recommendation"], scored_at, scored_at, applicant_id
            ))
        applicant_timeline(applicant_id, "Sparkles AI score recorded", f"{result['recommendation']} ({result['score']}/100)")
        return result

    def create_cleaner_applicant(self):
        try:
            uploads = {"id_uploads": [], "proof_of_address_uploads": [], "driving_licence_uploads": []}
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type.lower():
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    return self.send_json({"error": "Application upload is empty or too large (15MB maximum)."}, 413)
                body = self.rfile.read(length)
                raw = (f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
                message = BytesParser(policy=default).parsebytes(raw)
                data = {}
                upload_fields = {
                    "id_upload": "id_uploads",
                    "proof_of_address_upload": "proof_of_address_uploads",
                    "driving_licence_upload": "driving_licence_uploads",
                }
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    filename = part.get_filename()
                    payload = part.get_payload(decode=True) or b""
                    if filename and name in upload_fields:
                        mime = part.get_content_type()
                        if mime not in ALLOWED_APPLICANT_UPLOADS or len(payload) > 5 * 1024 * 1024:
                            raise ValueError("Applicant uploads must be JPG, PNG, WebP or PDF and no larger than 5MB each.")
                        saved = f"applicant-{uuid.uuid4().hex}{ALLOWED_APPLICANT_UPLOADS[mime]}"
                        (UPLOADS / saved).write_bytes(payload)
                        uploads[upload_fields[name]].append({"name": Path(filename).name, "url": f"/uploads/{saved}", "uploaded_at": utcnow().isoformat()})
                    elif name:
                        existing = data.get(name)
                        value = payload.decode("utf-8").strip()
                        if existing is None:
                            data[name] = value
                        elif isinstance(existing, list):
                            existing.append(value)
                        else:
                            data[name] = [existing, value]
            else:
                data = self.read_json()
            required = ["name", "phone", "email", "postcode", "availability", "services"]
            if any(not data.get(key) for key in required):
                raise ValueError("Please complete your name, phone, email, postcode, availability and services.")
            if isinstance(data.get("availability"), str):
                data["availability"] = [item.strip() for item in data["availability"].split(",") if item.strip()]
            if isinstance(data.get("services"), str):
                data["services"] = [item.strip() for item in data["services"].split(",") if item.strip()]
            for key in ("has_own_vehicle", "identity_verified", "right_to_work_verified", "proof_of_address_verified"):
                data[key] = str(data.get(key, "")).lower() in {"1", "true", "yes", "on"}
            radius = float(data.get("travel_radius") or 5)
            rate = float(data.get("hourly_rate") or 0)
            source = str(data.get("source") or "Website").strip()[:80] or "Website"
            invitation_code = str(data.get("invite_code") or "").strip()
            verification = cleaner_verification_payload(data)
            now = datetime.now(timezone.utc).isoformat()
            with connect() as conn:
                invited_applicant = None
                if invitation_code:
                    invited_applicant = conn.execute(
                        "SELECT * FROM cleaner_applicants WHERE invitation_code=?", (invitation_code,)
                    ).fetchone()
                    if not invited_applicant:
                        raise ValueError("This Indeed invitation is not valid. Ask Sparkles for a fresh invitation.")
                    invited_applicant = dict(invited_applicant)
                    if invited_applicant.get("application_completed_at"):
                        raise ValueError("This Sparkles application has already been completed.")
                    source = "Indeed"
                    conn.execute("""UPDATE cleaner_applicants SET
                        name=?,phone=?,email=?,postcode=?,experience=?,travel_radius=?,hourly_rate=?,availability=?,services=?,
                        dbs_status=?,insurance_status=?,source='Indeed',status='New',updated_at=?,
                        identity_verified=?,right_to_work_verified=?,proof_of_address_verified=?,travel_method=?,driving_licence_status=?,has_own_vehicle=?,
                        right_to_work_status=?,short_intro=?,id_uploads=?,proof_of_address_uploads=?,driving_licence_uploads=?,
                        invitation_status='Completed',application_completed_at=?
                        WHERE id=?""", (
                        data["name"].strip(), data["phone"].strip(), data["email"].strip().lower(), data["postcode"].strip().upper(),
                        str(data.get("experience") or "").strip(), radius, rate,
                        json.dumps(data.get("availability") or []), json.dumps(data.get("services") or []),
                        str(data.get("dbs_status") or "Unknown").strip(), str(data.get("insurance_status") or "Unknown").strip(), now,
                        verification["identity_verified"], verification["right_to_work_verified"], verification["proof_of_address_verified"],
                        verification["travel_method"], verification["driving_licence_status"], verification["has_own_vehicle"],
                        str(data.get("right_to_work_status") or "Not provided").strip(), str(data.get("short_intro") or "").strip(),
                        json.dumps(uploads["id_uploads"] or data.get("id_uploads") or []),
                        json.dumps(uploads["proof_of_address_uploads"] or data.get("proof_of_address_uploads") or []),
                        json.dumps(uploads["driving_licence_uploads"] or data.get("driving_licence_uploads") or []),
                        now, invited_applicant["id"]
                    ))
                    applicant_id = invited_applicant["id"]
                    event = "Indeed application completed"
                    detail = f"Tracked application completed as {indeed_applicant_identifier(invitation_code)}"
                else:
                    cursor = conn.execute("""INSERT INTO cleaner_applicants
                        (name,phone,email,postcode,experience,travel_radius,hourly_rate,availability,services,dbs_status,insurance_status,source,status,notes,created_at,updated_at,
                         identity_verified,right_to_work_verified,proof_of_address_verified,travel_method,driving_licence_status,has_own_vehicle,
                         right_to_work_status,short_intro,id_uploads,proof_of_address_uploads,driving_licence_uploads,application_completed_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        data["name"].strip(), data["phone"].strip(), data["email"].strip().lower(), data["postcode"].strip().upper(),
                        str(data.get("experience") or "").strip(), radius, rate,
                        json.dumps(data.get("availability") or []), json.dumps(data.get("services") or []),
                        str(data.get("dbs_status") or "Unknown").strip(), str(data.get("insurance_status") or "Unknown").strip(),
                        source, "New", str(data.get("notes") or "").strip(), now, now,
                        verification["identity_verified"], verification["right_to_work_verified"], verification["proof_of_address_verified"],
                        verification["travel_method"], verification["driving_licence_status"], verification["has_own_vehicle"],
                        str(data.get("right_to_work_status") or "Not provided").strip(), str(data.get("short_intro") or "").strip(),
                        json.dumps(uploads["id_uploads"] or data.get("id_uploads") or []),
                        json.dumps(uploads["proof_of_address_uploads"] or data.get("proof_of_address_uploads") or []),
                        json.dumps(uploads["driving_licence_uploads"] or data.get("driving_licence_uploads") or []), now
                    ))
                    applicant_id = cursor.lastrowid
                    event = "Application submitted"
                    detail = f"{source} application received"
                autopilot_log(conn, "cleaner_recruitment", "Cleaner application captured", f"{data['name'].strip()} applied from {source}.")
            applicant_timeline(applicant_id, event, detail)
            score = self.store_cleaner_applicant_score(applicant_id)
            try:
                send_cleaner_applicant_confirmation(applicant_id)
            except Exception as email_error:
                logger.warning(json.dumps({"cleaner_applicant_confirmation": "failed", "applicant_id": applicant_id, "error": str(email_error)}))
            try:
                send_owner_applicant_alert(applicant_id)
            except Exception as owner_error:
                logger.warning(json.dumps({"cleaner_applicant_owner_alert": "failed", "applicant_id": applicant_id, "error": str(owner_error)}))
            return self.send_json({
                "ok": True,
                "id": applicant_id,
                "applicant_identifier": indeed_applicant_identifier(invitation_code) if invitation_code else None,
                "score": score["score"],
                "recommendation": score["recommendation"],
            }, 201)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def score_cleaner_applicant(self, applicant):
        availability = json.loads(applicant.get("availability") or "[]") if isinstance(applicant.get("availability"), str) else applicant.get("availability") or []
        services = json.loads(applicant.get("services") or "[]") if isinstance(applicant.get("services"), str) else applicant.get("services") or []
        dbs = str(applicant.get("dbs_status") or "Unknown").lower()
        insurance = str(applicant.get("insurance_status") or "Unknown").lower()
        right_to_work = str(applicant.get("right_to_work_status") or "").lower()
        travel_method = str(applicant.get("travel_method") or "Unknown").lower()
        licence = str(applicant.get("driving_licence_status") or "").lower()
        experience = str(applicant.get("experience") or "").strip()
        intro = str(applicant.get("short_intro") or "").strip()
        radius = float(applicant.get("travel_radius") or 0)
        rate = float(applicant.get("hourly_rate") or 0)
        score = 0
        reasons = []
        risks = []

        if applicant.get("name") and applicant.get("phone") and applicant.get("email") and applicant.get("postcode"):
            score += 10
            reasons.append("Complete contact details")
        else:
            risks.append("Missing contact details")

        if len(availability) >= 5:
            score += 20
            reasons.append("Strong weekly availability")
        elif len(availability) >= 3:
            score += 14
            reasons.append("Good availability")
        elif availability:
            score += 7
            reasons.append("Some availability")
        else:
            risks.append("No availability supplied")

        if {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}.intersection(set(availability)):
            score += 5

        if len(services) >= 3:
            score += 20
            reasons.append("Covers multiple clean types")
        elif len(services) >= 2:
            score += 14
            reasons.append("Covers more than one service")
        elif services:
            score += 7
            reasons.append("Covers one service")
        else:
            risks.append("No services supplied")

        if "verified" in dbs:
            score += 15
            reasons.append("DBS verified")
        elif "certificate" in dbs or "progress" in dbs or "applied" in dbs:
            score += 9
            reasons.append("DBS available or in progress")
        else:
            risks.append("DBS not verified")

        if "yes" in right_to_work or "verified" in right_to_work or applicant.get("right_to_work_verified"):
            score += 12
            reasons.append("Right to work declared")
        else:
            risks.append("Right to work not confirmed")

        if "owner/company" in travel_method:
            score += 8
            reasons.append("Can use owner/company transport")
        elif "car" in travel_method or "self" in travel_method:
            if "verified" in licence and applicant.get("has_own_vehicle"):
                score += 10
                reasons.append("Self-driving with licence and vehicle")
            else:
                score += 3
                risks.append("Self-driving details need checking")
        elif travel_method and travel_method != "unknown":
            score += 5
            reasons.append("Travel method supplied")
        else:
            risks.append("Travel method missing")

        if radius >= 10:
            score += 8
            reasons.append("Useful travel radius")
        elif radius >= 5:
            score += 5

        if 0 < rate <= 18:
            score += 7
            reasons.append("Competitive hourly rate")
        elif 0 < rate <= 25:
            score += 4
        elif rate <= 0:
            risks.append("No hourly rate supplied")

        if experience:
            score += 10
            reasons.append("Experience notes supplied")
        else:
            risks.append("No experience notes")

        if intro:
            score += 5
            reasons.append("Personal introduction supplied")

        score = max(0, min(100, int(score)))
        if applicant.get("approved_cleaner_id") or applicant.get("status") == "Added as Cleaner":
            recommendation = "Already added"
        elif score >= 80:
            recommendation = "Excellent"
        elif score >= 62:
            recommendation = "Good"
        elif score >= 40:
            recommendation = "Review"
        else:
            recommendation = "Weak"
        return {
            "score": score,
            "recommendation": recommendation,
            "reasons": reasons[:5],
            "risks": risks[:5],
            "availability": availability,
            "services": services,
        }

    def ai_recruitment_summary(self):
        with connect() as conn:
            rows = conn.execute("SELECT * FROM cleaner_applicants ORDER BY id DESC").fetchall()
            active_cleaners = conn.execute("SELECT COUNT(*) AS total FROM cleaners WHERE COALESCE(active,1)=1 AND password_hash IS NOT NULL AND password_hash<>''").fetchone()
        scored = []
        for row in rows:
            item = dict(row)
            score = self.score_cleaner_applicant(item)
            item.update(score)
            item["password_hash"] = None
            scored.append(item)
        counts = {
            "total": len(scored),
            "excellent": len([a for a in scored if a["recommendation"] == "Excellent"]),
            "good": len([a for a in scored if a["recommendation"] == "Good"]),
            "recommended": len([a for a in scored if a["recommendation"] in {"Excellent", "Good"}]),
            "review": len([a for a in scored if a["recommendation"] == "Review"]),
            "weak": len([a for a in scored if a["recommendation"] == "Weak"]),
            "needs_review": len([a for a in scored if a["recommendation"] in {"Review", "Weak"}]),
            "already_added": len([a for a in scored if a["recommendation"] == "Already added"]),
            "active_cleaners": int(active_cleaners["total"] if active_cleaners else 0),
        }
        source_counts = {}
        for applicant in scored:
            source = applicant.get("source") or "Unknown"
            source_counts[source] = source_counts.get(source, 0) + 1
        return self.send_json({"counts": counts, "sources": source_counts, "applicants": scored})

    def ai_recruitment_autopilot_status(self):
        with connect() as conn:
            applicants = [dict(row) for row in conn.execute("SELECT * FROM cleaner_applicants ORDER BY id DESC").fetchall()]
            click_rows = []
            if table_exists(conn, "recruitment_clicks"):
                click_rows = [dict(row) for row in conn.execute("SELECT * FROM recruitment_clicks ORDER BY id DESC LIMIT 500").fetchall()]
            active_cleaners = table_count(conn, "cleaners", "COALESCE(active,1)=1 AND password_hash IS NOT NULL AND password_hash<>''")
        scored = []
        for applicant in applicants:
            applicant.update(self.score_cleaner_applicant(applicant))
            scored.append(applicant)
        sources = {}
        for source, label in RECRUITMENT_CHANNELS:
            sources[source] = {
                "source": source,
                "label": label,
                "tracked_link": recruitment_link(source),
                "apply_link": recruitment_apply_link(source),
                "share_text": recruitment_share_text(source),
                "clicks": 0,
                "applicants": 0,
            }
        for click in click_rows:
            source = normalise_recruitment_source(click.get("source"))
            sources.setdefault(source, {
                "source": source,
                "label": source.replace("-", " ").title(),
                "tracked_link": recruitment_link(source),
                "apply_link": recruitment_apply_link(source),
                "share_text": recruitment_share_text(source),
                "clicks": 0,
                "applicants": 0,
            })
            sources[source]["clicks"] += 1
        for applicant in scored:
            source = normalise_recruitment_source(applicant.get("source"))
            sources.setdefault(source, {
                "source": source,
                "label": source.replace("-", " ").title(),
                "tracked_link": recruitment_link(source),
                "apply_link": recruitment_apply_link(source),
                "share_text": recruitment_share_text(source),
                "clicks": 0,
                "applicants": 0,
            })
            sources[source]["applicants"] += 1
        source_list = []
        for item in sources.values():
            item["conversion_rate"] = round((item["applicants"] / item["clicks"]) * 100, 1) if item["clicks"] else 0
            source_list.append(item)
        source_list.sort(key=lambda item: (item["applicants"], item["clicks"]), reverse=True)
        recommended = [item for item in scored if item.get("recommendation") in {"Excellent", "Good"} and item.get("status") not in {"Added as Cleaner", "Rejected"}]
        new_items = [item for item in scored if str(item.get("status") or "New").lower() == "new"]
        actions = []
        if recommended:
            actions.append({
                "priority": "High",
                "title": "Review recommended applicants",
                "detail": f"{len(recommended)} applicant(s) are rated Excellent or Good.",
                "href": "/admin/cleaner-applicants",
            })
        if active_cleaners < 3:
            actions.append({
                "priority": "High",
                "title": "Grow cleaner supply",
                "detail": f"You currently have {active_cleaners} active cleaner(s). Aim for at least 3 before pushing customer bookings hard.",
                "href": "/admin/ai-recruitment",
            })
        if not click_rows:
            actions.append({
                "priority": "Medium",
                "title": "Start sharing tracked links",
                "detail": "No recruitment link clicks have been recorded yet. Copy and post the Facebook or WhatsApp link first.",
                "href": "/admin/ai-recruitment",
            })
        if new_items and not recommended:
            actions.append({
                "priority": "Medium",
                "title": "Review new applicants",
                "detail": f"{len(new_items)} applicant(s) are waiting for review.",
                "href": "/admin/cleaner-applicants",
            })
        return self.send_json({
            "counts": {
                "clicks": len(click_rows),
                "applicants": len(scored),
                "recommended": len(recommended),
                "new": len(new_items),
                "active_cleaners": active_cleaners,
                "conversion_rate": round((len(scored) / len(click_rows)) * 100, 1) if click_rows else 0,
            },
            "sources": source_list,
            "actions": actions,
            "recommended_applicants": recommended[:8],
            "safe_note": "Sparkles tracks links and applications only. It does not scrape Facebook, Indeed or WhatsApp.",
        })

    def ai_recruitment_campaign_copy(self):
        try:
            data = self.read_json()
            channel = str(data.get("channel") or "Facebook").strip()
            area = str(data.get("area") or "your local area").strip()
            rate = str(data.get("rate") or "competitive rates").strip()
            benefits = str(data.get("benefits") or "choose your availability, travel area and services").strip()
            source = channel.lower().replace(" ", "-")
            apply_link = recruitment_link(source)
            title = "Self-employed Domestic Cleaner"
            if channel.lower() in {"facebook", "whatsapp", "nextdoor"}:
                body = (
                    f"Sparkles Cleaning Cambridge is looking for reliable self-employed cleaners in {area}.\n\n"
                    f"You can {benefits}. Pay: {rate}.\n\n"
                    "Ideal applicants are reliable, friendly, experienced with home cleaning, and able to provide DBS/insurance details where available.\n\n"
                    f"Apply here:\n{apply_link}"
                )
            else:
                body = (
                    f"{title}\n\n"
                    f"Sparkles Cleaning Cambridge is recruiting reliable self-employed domestic cleaners in {area}.\n\n"
                    "You will receive cleaning job opportunities based on your postcode, availability, travel radius and services offered.\n\n"
                    f"Pay: {rate}.\n\n"
                    "Requirements:\n"
                    "- Cleaning experience preferred\n"
                    "- Reliable and professional\n"
                    "- Good communication\n"
                    "- DBS certificate preferred\n"
                    "- Public liability insurance preferred\n\n"
                    f"Apply here:\n{apply_link}"
                )
            short = f"Sparkles Cleaning Cambridge is hiring cleaners in {area}. {benefits}. Apply here: {apply_link}"
            return self.send_json({"title": title, "body": body, "short": short, "apply_link": apply_link, "channel": channel})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error) or "Could not generate recruitment copy."}, 400)

    def ai_recruitment_autopilot_plan(self):
        try:
            data = self.read_json()
            area = str(data.get("area") or "Cambridge and surrounding areas").strip()
            target = int(data.get("target") or 10)
            channels = data.get("channels") or ["Facebook", "Indeed", "WhatsApp", "Gumtree"]
            if isinstance(channels, str):
                channels = [part.strip() for part in channels.split(",") if part.strip()]
            channels = channels[:6] or ["Facebook", "Indeed", "WhatsApp", "Gumtree"]
            daily_target = max(1, round(target / 7))
            apply_links = {
                channel: recruitment_link(channel.lower().replace(" ", "-"))
                for channel in channels
            }
            checklist = [
                "Post the generated advert in 2-3 local cleaning/community groups.",
                "Add the tracked application link to every post.",
                "Check new applicants daily in the Cleaner Recruitment shortlist.",
                "Send follow-up emails to promising applicants within 24 hours.",
                "Approve only applicants with clear contact details, availability and suitable checks.",
                "Keep rejected or incomplete applicants in Needs review until they provide missing details."
            ]
            plan = []
            for index, channel in enumerate(channels, start=1):
                plan.append({
                    "day": index,
                    "channel": channel,
                    "action": f"Publish cleaner recruitment advert for {area}",
                    "goal": f"Attract {daily_target}+ cleaner applicant{'s' if daily_target != 1 else ''}",
                    "apply_link": apply_links[channel],
                    "share_text": f"Sparkles Cleaning Cambridge is hiring reliable cleaners in {area}. Flexible local cleaning work, friendly support and competitive pay. Apply here: {apply_links[channel]}",
                    "safe_note": "Use this link in your own posts or paid adverts. Do not scrape or message private profiles without consent."
                })
            return self.send_json({
                "area": area,
                "target": target,
                "channels": channels,
                "apply_links": apply_links,
                "weekly_plan": plan,
                "checklist": checklist,
                "message": "Autopilot plan generated. Share the tracked links through your own adverts, posts and referrals."
            })
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error) or "Could not generate weekly posting plan."}, 400)

    def ai_recruitment_follow_up(self, path):
        try:
            applicant_id = int(path.split("/")[4])
            data = self.read_json()
            template = str(data.get("template") or "shortlist").strip().lower()
            with connect() as conn:
                applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
                if not applicant:
                    return self.send_json({"error": "Applicant not found."}, 404)
                applicant = dict(applicant)
            name = display_customer_name(applicant["name"])
            apply_source = applicant["source"] or "recruitment campaign"
            portal_link = f"{public_url().rstrip('/')}/become-a-cleaner?source=follow-up"
            if template == "missing":
                subject = "A quick question about your Sparkles cleaner application"
                intro = f"Hi {name}, thanks for applying to work with Sparkles Cleaning Cambridge through {apply_source}. We'd love to review your application properly, but we need a few extra details first."
                rows = [
                    ("What we need", "Your availability, services offered, DBS status, insurance status and preferred travel radius"),
                    ("Update link", portal_link),
                ]
                body = f"{intro}\n\nPlease reply with the missing details or submit the form again here:\n{portal_link}\n\nSmiles Come Standard.\nSparkles Cleaning Cambridge"
            else:
                subject = "Your Sparkles cleaner application"
                intro = f"Hi {name}, thanks for applying to work with Sparkles Cleaning Cambridge. Your application looks promising and we'd like to move you to the next step."
                rows = [
                    ("Next step", "Please reply confirming your availability, preferred areas, DBS status and insurance status."),
                    ("Application source", apply_source),
                ]
                body = f"{intro}\n\nPlease reply confirming your availability, preferred areas, DBS status and insurance status.\n\nSmiles Come Standard.\nSparkles Cleaning Cambridge"
            html_body = sparkles_email_html("Cleaner application", intro, rows)
            message = EmailMessage()
            message["From"] = email_from_address()
            message["To"] = applicant["email"]
            message["Subject"] = subject
            message.set_content(body)
            message.add_alternative(html_body, subtype="html")
            deliver_email_message(message)
            now = datetime.now(timezone.utc).isoformat()
            note = f"{applicant['notes'] or ''}\n[{now}] Cleaner Recruitment follow-up sent: {template}".strip()
            with connect() as conn:
                conn.execute("""
                    UPDATE cleaner_applicants
                    SET status=CASE WHEN status='New' THEN 'Contacted' ELSE status END,
                        notes=?,
                        updated_at=?
                    WHERE id=?
                """, (note, now, applicant_id))
            return self.send_json({"ok": True, "status": "Sent", "recipient": applicant["email"], "subject": subject})
        except (ValueError, TypeError, json.JSONDecodeError, IndexError) as error:
            return self.send_json({"error": str(error) or "Could not send applicant follow-up."}, 400)
        except Exception as error:
            logger.error(json.dumps({"ai_recruitment_follow_up": "failed", "error": str(error)}))
            return self.send_json({"error": str(error) or "Could not send applicant follow-up."}, 502)

    def import_cleaner_applicants(self):
        try:
            data = self.read_json()
            csv_text = str(data.get("csv") or "").strip()
            default_source = str(data.get("source") or "CSV import").strip() or "CSV import"
            if not csv_text:
                raise ValueError("Paste CSV data before importing.")
            reader = csv.DictReader(io.StringIO(csv_text))
            if not reader.fieldnames:
                raise ValueError("CSV needs a header row.")
            imported, skipped = 0, []
            now = datetime.now(timezone.utc).isoformat()
            with connect() as conn:
                for index, row in enumerate(reader, start=2):
                    normalised = {str(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
                    name = normalised.get("name") or normalised.get("full_name")
                    phone = normalised.get("phone") or normalised.get("mobile")
                    email = (normalised.get("email") or normalised.get("email_address") or "").lower()
                    postcode = (normalised.get("postcode") or normalised.get("post_code") or "").upper()
                    if not (name and phone and email and postcode):
                        skipped.append({"row": index, "reason": "Missing name, phone, email or postcode"})
                        continue
                    availability = [part.strip() for part in (normalised.get("availability") or "").replace(";", ",").split(",") if part.strip()]
                    services = [part.strip() for part in (normalised.get("services") or normalised.get("services_offered") or "").replace(";", ",").split(",") if part.strip()]
                    try:
                        verification = cleaner_verification_payload({
                            "identity_verified": normalised.get("identity_verified") in {"1", "yes", "true", "verified"},
                            "right_to_work_verified": normalised.get("right_to_work_verified") in {"1", "yes", "true", "verified"},
                            "proof_of_address_verified": normalised.get("proof_of_address_verified") in {"1", "yes", "true", "verified"},
                            "travel_method": normalised.get("travel_method") or "Unknown",
                            "driving_licence_status": normalised.get("driving_licence_status") or normalised.get("driving_license_status") or "Not provided",
                            "has_own_vehicle": normalised.get("has_own_vehicle") in {"1", "yes", "true"},
                        })
                        conn.execute("""
                            INSERT INTO cleaner_applicants
                            (name,phone,email,postcode,experience,travel_radius,hourly_rate,availability,services,dbs_status,insurance_status,source,status,notes,created_at,updated_at,
                             identity_verified,right_to_work_verified,proof_of_address_verified,travel_method,driving_licence_status,has_own_vehicle)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (
                            name, phone, email, postcode,
                            normalised.get("experience") or "",
                            float(normalised.get("travel_radius") or 5),
                            float(normalised.get("hourly_rate") or 0),
                            json.dumps(availability),
                            json.dumps(services),
                            normalised.get("dbs_status") or "Unknown",
                            normalised.get("insurance_status") or "Unknown",
                            normalised.get("source") or default_source,
                            normalised.get("status") or "New",
                            normalised.get("notes") or "",
                            now,
                            now,
                            verification["identity_verified"],
                            verification["right_to_work_verified"],
                            verification["proof_of_address_verified"],
                            verification["travel_method"],
                            verification["driving_licence_status"],
                            verification["has_own_vehicle"],
                        ))
                        imported += 1
                    except (DB_ERROR_TYPES + (ValueError,)) as error:
                        skipped.append({"row": index, "reason": str(error)})
            return self.send_json({"ok": True, "imported": imported, "skipped": skipped})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def update_cleaner_applicant(self, path):
        try:
            applicant_id = int(path.split("/")[3])
            data = self.read_json()
            allowed_statuses = {"Invited", "New", "Contacted", "Interview", "Approved", "Rejected", "Added as Cleaner"}
            allowed_interview_statuses = {"Not scheduled", "Invited", "Scheduled", "Completed", "No show", "Declined"}
            status = str(data.get("status") or "").strip()
            interview_status = str(data.get("interview_status") or "").strip()
            notes = str(data.get("notes") or "").strip()
            if status and status not in allowed_statuses:
                raise ValueError("Invalid applicant status.")
            if interview_status and interview_status not in allowed_interview_statuses:
                raise ValueError("Invalid interview status.")
            status_changed = False
            interview_changed = False
            with connect() as conn:
                applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
                if not applicant:
                    return self.send_json({"error": "Applicant not found."}, 404)
                applicant = dict(applicant)
                status_changed = bool(status and status != applicant["status"])
                interview_changed = bool(interview_status and interview_status != (applicant.get("interview_status") or "Not scheduled"))
                interview_updated_at = utcnow().isoformat() if interview_changed else applicant.get("interview_updated_at")
                conn.execute("""
                    UPDATE cleaner_applicants
                    SET status=COALESCE(NULLIF(?,''),status), notes=?,
                        interview_status=COALESCE(NULLIF(?,''),interview_status), interview_updated_at=?, updated_at=?
                    WHERE id=?
                """, (status, notes, interview_status, interview_updated_at, datetime.now(timezone.utc).isoformat(), applicant_id))
            if status_changed:
                applicant_timeline(applicant_id, "Applicant status updated", f"Status changed to {status}")
            if interview_changed:
                applicant_timeline(applicant_id, "Interview status updated", f"Interview status changed to {interview_status}")
            return self.send_json({"ok": True})
        except (ValueError, TypeError, json.JSONDecodeError, IndexError) as error:
            return self.send_json({"error": str(error) or "Invalid applicant update."}, 400)

    def approve_cleaner_applicant(self, path):
        try:
            applicant_id = int(path.split("/")[3])
            self.read_json()
            with connect() as conn:
                applicant = conn.execute("SELECT * FROM cleaner_applicants WHERE id=?", (applicant_id,)).fetchone()
                if not applicant:
                    return self.send_json({"error": "Applicant not found."}, 404)
                applicant = dict(applicant)
                if applicant["approved_cleaner_id"]:
                    return self.send_json({"error": "Applicant is already added as a cleaner."}, 409)
                if not all(str(applicant.get(field) or "").strip() for field in ("name", "phone", "email", "postcode")):
                    raise ValueError("The applicant must complete the Sparkles application before approval.")
                if not json.loads(applicant.get("availability") or "[]") or not json.loads(applicant.get("services") or "[]"):
                    raise ValueError("The applicant must provide availability and services before approval.")
                verification = cleaner_verification_payload(dict(applicant))
                cursor = conn.execute("""INSERT INTO cleaners
                    (name,phone,email,postcode,travel_radius,hourly_rate,availability,services,dbs_status,insurance_status,active,created_at,
                     identity_verified,right_to_work_verified,proof_of_address_verified,travel_method,driving_licence_status,has_own_vehicle)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        applicant["name"],
                        applicant["phone"],
                        applicant["email"],
                        applicant["postcode"],
                        float(applicant["travel_radius"] or 5),
                        float(applicant["hourly_rate"] or 0) or 15,
                        applicant["availability"],
                        applicant["services"],
                        applicant["dbs_status"],
                        applicant["insurance_status"],
                        1,
                        datetime.now(timezone.utc).isoformat(),
                        verification["identity_verified"],
                        verification["right_to_work_verified"],
                        verification["proof_of_address_verified"],
                        verification["travel_method"],
                        verification["driving_licence_status"],
                        verification["has_own_vehicle"],
                    ))
                cleaner_id = cursor.lastrowid
                conn.execute("""
                    UPDATE cleaner_applicants
                    SET status='Added as Cleaner',
                        invitation_status=CASE WHEN invitation_code IS NOT NULL THEN 'Converted' ELSE invitation_status END,
                        approved_cleaner_id=?, converted_at=?, updated_at=?
                    WHERE id=?
                """, (cleaner_id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), applicant_id))
            applicant_timeline(applicant_id, "Approved as cleaner", f"Cleaner account #{cleaner_id} created")
            invite = send_cleaner_invitation_email(cleaner_id)
            applicant_timeline(applicant_id, "Cleaner invite sent", "Secure Cleaner Portal setup invitation sent")
            return self.send_json({"ok": True, "cleaner_id": cleaner_id, "invite": invite}, 201)
        except DB_INTEGRITY_ERROR_TYPES:
            return self.send_json({"error": "A cleaner account already exists for that email address."}, 409)
        except (ValueError, TypeError, json.JSONDecodeError, IndexError) as error:
            return self.send_json({"error": str(error)}, 400)

    def get_quote(self, token):
        with connect() as conn:
            booking = conn.execute("SELECT id,reference,name,clean_type,bedrooms,bathrooms,preferred_date,preferred_time,total_amount,deposit_amount,balance_amount,quote_status,payment_status FROM bookings WHERE quote_token=?", (token,)).fetchone()
        self.send_json(dict(booking) if booking else {"error": "Quote not found."}, 200 if booking else 404)

    def accept_quote(self, token):
        try:
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE quote_token=?", (token,)).fetchone()
            if not booking:
                return self.send_json({"error": "Quote not found."}, 404)
            if booking["payment_status"] in ("Deposit Paid", "Paid in Full"):
                return self.send_json({"paid": True})
            session = create_checkout(booking, "deposit")
            with connect() as conn:
                conn.execute("UPDATE bookings SET quote_status='Accepted' WHERE id=?", (booking["id"],))
            automation.timeline(booking["id"], "Quote accepted", "Customer accepted quote and opened deposit checkout")
            self.send_json({"url": session["url"]})
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)

    def get_job_offer(self, token):
        with connect() as conn:
            offer = conn.execute("""SELECT o.*,b.reference,b.clean_type,b.preferred_date,b.preferred_time,b.postcode,b.address,b.status booking_status,c.name cleaner_name
                FROM cleaner_offers o JOIN bookings b ON b.id=o.booking_id JOIN cleaners c ON c.id=o.cleaner_id WHERE o.token=?""", (token,)).fetchone()
        self.send_json(dict(offer) if offer else {"error": "Job offer not found."}, 200 if offer else 404)

    def accept_offer(self, token):
        try:
            with connect() as conn:
                offer = conn.execute("SELECT * FROM cleaner_offers WHERE token=?", (token,)).fetchone()
                if not offer:
                    return self.send_json({"error": "Job offer not found."}, 404)
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (offer["booking_id"],)).fetchone()
                cleaner = conn.execute("SELECT * FROM cleaners WHERE id=?", (offer["cleaner_id"],)).fetchone()
                if booking["cleaner_id"] and booking["cleaner_id"] != cleaner["id"]:
                    return self.send_json({"error": "This job has already been accepted by another cleaner."}, 409)
                if cleaner_has_conflict(conn, cleaner["id"], booking["preferred_date"], booking["preferred_time"], booking["id"]):
                    return self.send_json({"error": "You already have a job at this time."}, 409)
                conn.execute("UPDATE bookings SET cleaner_id=?,status='Assigned',assigned_at=? WHERE id=?", (cleaner["id"], datetime.now(timezone.utc).isoformat(), booking["id"]))
                conn.execute("UPDATE cleaner_offers SET status='Accepted',responded_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), offer["id"]))
                conn.execute("UPDATE cleaner_offers SET status='Expired' WHERE booking_id=? AND id<>? AND status='Offered'", (booking["id"], offer["id"]))
            automation.timeline(booking["id"], "Cleaner accepted", f"{cleaner['name']} accepted and was assigned automatically")
            safe_send_cleaner_job_details_email(booking["id"])
            automation.enqueue(booking["id"], "send_confirmations")
            schedule_reminder = dict(booking)
            schedule_reminder["id"] = booking["id"]
            schedule_booking_reminder(schedule_reminder)
            self.send_json({"ok": True, "booking_id": booking["id"], "status": "Assigned"})
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)

    def complete_job(self, token):
        with connect() as conn:
            offer = conn.execute("SELECT * FROM cleaner_offers WHERE token=? AND status='Accepted'", (token,)).fetchone()
            if not offer:
                return self.send_json({"error": "Assigned job not found."}, 404)
            conn.execute("UPDATE bookings SET status='Completed' WHERE id=? AND cleaner_id=?", (offer["booking_id"], offer["cleaner_id"]))
        automation.timeline(offer["booking_id"], "Job completed", "Cleaner marked the job complete")
        automation.enqueue(offer["booking_id"], "send_final_invoice")
        self.send_json({"ok": True, "status": "Completed"})

    def assign_cleaner(self, path):
        try:
            booking_id = int(path.split("/")[3])
            data = self.read_json()
            cleaner_id = int(data.get("cleaner_id"))
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                cleaner = conn.execute("SELECT * FROM cleaners WHERE id=? AND active=1 AND password_hash IS NOT NULL AND password_hash<>''", (cleaner_id,)).fetchone()
                if not booking or not cleaner:
                    return self.send_json({"error": "Booking or activated cleaner not found."}, 404)
                if cleaner_has_conflict(conn, cleaner_id, booking["preferred_date"], booking["preferred_time"], booking_id):
                    return self.send_json({"error": f"{cleaner['name']} is already booked at that time."}, 409)
                conn.execute("UPDATE bookings SET cleaner_id=?, status='Assigned', assigned_at=? WHERE id=?", (cleaner_id, datetime.now(timezone.utc).isoformat(), booking_id))
                updated = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            automation.timeline(booking_id, "Cleaner assigned", f"{cleaner['name']} assigned by admin")
            safe_send_cleaner_job_details_email(booking_id)
            automation.enqueue(booking_id, "send_confirmations")
            schedule_booking_reminder(dict(updated))
            self.send_json({"ok": True, "status": "Assigned", "cleaner_name": cleaner["name"]})
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Invalid assignment request."}, 400)

    def auto_assign_cleaner(self, path):
        try:
            booking_id = int(path.split("/")[3])
            with connect() as conn:
                booking_row = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            if not booking_row:
                return self.send_json({"error": "Booking not found."}, 404)
            booking = dict(booking_row)
            matches = suitable_cleaners(booking)
            if not matches:
                return self.send_json({"error": "No eligible cleaners found. Add an active cleaner with a completed login setup, matching availability, matching services and travel coverage."}, 404)
            cleaner = matches[0]
            with connect() as conn:
                if cleaner_has_conflict(conn, cleaner["id"], booking["preferred_date"], booking["preferred_time"], booking_id):
                    return self.send_json({"error": f"{cleaner['name']} is already booked at that time."}, 409)
                conn.execute("UPDATE bookings SET cleaner_id=?, status='Assigned', assigned_at=? WHERE id=?", (cleaner["id"], datetime.now(timezone.utc).isoformat(), booking_id))
                updated = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            automation.timeline(booking_id, "Cleaner auto assigned", f"{cleaner['name']} was auto assigned as the nearest eligible cleaner ({cleaner['distance']} miles away).")
            safe_send_cleaner_job_details_email(booking_id)
            automation.enqueue(booking_id, "send_confirmations")
            schedule_booking_reminder(dict(updated))
            self.send_json({"ok": True, "status": "Assigned", "cleaner_id": cleaner["id"], "cleaner_name": cleaner["name"], "distance": cleaner["distance"]})
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Invalid auto assignment request."}, 400)

    def cleaner_job_action(self, path):
        session = self.current_session()
        if not session or session["role"] != "cleaner":
            return self.send_json({"error": "Cleaner login required."}, 401)
        try:
            booking_id = int(path.split("/")[4])
            data = self.read_json()
            action = data.get("action")
            now = utcnow().isoformat()
            cleaner_id = session["subject_id"]
            send_on_way_email = False
            with connect() as conn:
                booking = conn.execute("SELECT b.*, c.name AS cleaner_name FROM bookings b JOIN cleaners c ON c.id=b.cleaner_id WHERE b.id=? AND b.cleaner_id=? AND c.active=1", (booking_id, cleaner_id)).fetchone()
                if not booking:
                    return self.send_json({"error": "Assigned job not found."}, 404)
                cleaner_name = booking["cleaner_name"] or session["email"]
                if action == "accept":
                    if booking["status"] not in ("Assigned", "Accepted"):
                        return self.send_json({"error": "Only assigned jobs can be accepted."}, 409)
                    conn.execute("UPDATE bookings SET status='Accepted', accepted_at=COALESCE(accepted_at, ?) WHERE id=?", (now, booking_id))
                    event, detail, status = "Job accepted", f"{cleaner_name} accepted the assigned job", "Accepted"
                elif action == "decline":
                    if booking["status"] != "Assigned":
                        return self.send_json({"error": "Only assigned jobs can be declined."}, 409)
                    conn.execute("UPDATE bookings SET status='New', cleaner_id=NULL, assigned_at=NULL, declined_at=?, cleaner_notes=CASE WHEN ?<>'' THEN ? ELSE cleaner_notes END WHERE id=?", (now, data.get("notes", "").strip(), data.get("notes", "").strip(), booking_id))
                    conn.execute(
                        "INSERT OR IGNORE INTO cleaner_offers(booking_id,cleaner_id,token,status,distance,created_at) VALUES (?,?,?,'Declined',0,?)",
                        (booking_id, cleaner_id, uuid.uuid4().hex, now),
                    )
                    conn.execute(
                        "UPDATE cleaner_offers SET status='Declined', responded_at=? WHERE booking_id=? AND cleaner_id=?",
                        (now, booking_id, cleaner_id),
                    )
                    event, detail, status = "Job declined", f"{cleaner_name} declined the job; booking returned to New for reassignment", "New"
                elif action == "on_way":
                    if booking["status"] not in ("Accepted", "On My Way"):
                        return self.send_json({"error": "Only accepted jobs can be marked as on the way."}, 409)
                    existing_on_way = conn.execute("SELECT 1 FROM booking_timeline WHERE booking_id=? AND event='Cleaner on the way' LIMIT 1", (booking_id,)).fetchone()
                    send_on_way_email = existing_on_way is None
                    conn.execute("UPDATE bookings SET status='On My Way', on_my_way_at=COALESCE(on_my_way_at, ?) WHERE id=?", (now, booking_id))
                    event, detail, status = "Cleaner on the way", f"{cleaner_name} marked themselves as on the way", "On My Way"
                elif action == "start":
                    if booking["status"] not in ("Accepted", "On My Way", "In Progress"):
                        return self.send_json({"error": "Only accepted jobs can be started."}, 409)
                    conn.execute("UPDATE bookings SET status='In Progress', accepted_at=COALESCE(accepted_at, ?), started_at=COALESCE(started_at, ?) WHERE id=?", (now, now, booking_id))
                    event, detail, status = "Job started", f"{cleaner_name} started the job", "In Progress"
                elif action == "complete":
                    if booking["status"] not in ("In Progress", "Completed"):
                        return self.send_json({"error": "Only jobs in progress can be completed."}, 409)
                    conn.execute("UPDATE bookings SET status='Completed', accepted_at=COALESCE(accepted_at, ?), started_at=COALESCE(started_at, ?), completed_at=COALESCE(completed_at, ?) WHERE id=?", (now, now, now, booking_id))
                    ensure_cleaner_payout(conn, booking_id)
                    event, detail, status = "Job completed", f"{cleaner_name} marked the job complete", "Completed"
                elif action == "notes":
                    notes = data.get("notes", "").strip()
                    conn.execute("UPDATE bookings SET cleaner_notes=? WHERE id=?", (notes, booking_id))
                    event, detail, status = "Cleaner notes updated", f"{cleaner_name} updated job notes", booking["status"]
                else:
                    raise ValueError("Invalid cleaner job action.")
            automation.timeline(booking_id, event, detail)
            if action == "on_way" and send_on_way_email:
                safe_send_cleaner_on_way_email(booking_id)
            if action == "decline":
                automation.enqueue(booking_id, "offer_cleaners", key=f"{booking_id}:offer_cleaners:reassign:{uuid.uuid4().hex}")
                automation.timeline(booking_id, "Automatic reassignment queued", "Sparkles will try the next eligible cleaner before asking the owner to step in.")
            if action == "complete":
                automation.enqueue(booking_id, "send_final_invoice")
                send_owner_job_alert(booking_id, "Cleaner completed job", f"{cleaner_name} marked the job complete. The final invoice workflow can now continue.", "Owner completion alert")
            return self.send_json({"ok": True, "status": status})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error) or "Invalid cleaner job action."}, 400)

    def cleaner_job_photos(self, path):
        session = self.current_session()
        if not session or session["role"] != "cleaner":
            return self.send_json({"error": "Cleaner login required."}, 401)
        try:
            booking_id = int(path.split("/")[4])
            photo_type = urllib.parse.parse_qs(urlparse(self.path).query).get("type", [""])[0]
            if photo_type not in ("before", "after"):
                raise ValueError("Photo type must be before or after.")
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                return self.send_json({"error": "Upload is empty or too large (15MB maximum)."}, 413)
            body = self.rfile.read(length)
            raw = (f"Content-Type: {self.headers.get('Content-Type')}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
            message = BytesParser(policy=default).parsebytes(raw)
            saved_photos = []
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if filename and name == "photos":
                    mime = part.get_content_type()
                    if mime not in ALLOWED_IMAGES or len(payload) > 5 * 1024 * 1024:
                        raise ValueError("Photos must be JPG, PNG or WebP and no larger than 5MB each.")
                    saved = f"{uuid.uuid4().hex}{ALLOWED_IMAGES[mime]}"
                    (UPLOADS / saved).write_bytes(payload)
                    saved_photos.append({"name": Path(filename).name, "url": f"/uploads/{saved}", "uploaded_at": utcnow().isoformat()})
            if not saved_photos:
                raise ValueError("Please choose at least one photo.")
            column = "before_photos" if photo_type == "before" else "after_photos"
            with connect() as conn:
                booking = conn.execute(f"SELECT id,{column} FROM bookings WHERE id=? AND cleaner_id=?", (booking_id, session["subject_id"])).fetchone()
                if not booking:
                    return self.send_json({"error": "Assigned job not found."}, 404)
                existing = json.loads(booking[column] or "[]")
                updated = existing + saved_photos
                conn.execute(f"UPDATE bookings SET {column}=? WHERE id=?", (json.dumps(updated), booking_id))
            automation.timeline(booking_id, f"{photo_type.title()} photos uploaded", f"{len(saved_photos)} {photo_type} photo(s) added by cleaner")
            return self.send_json({"ok": True, "photos": updated})
        except (ValueError, TypeError) as error:
            return self.send_json({"error": str(error) or "Invalid photo upload."}, 400)

    def list_cleaner_payouts(self):
        with connect() as conn:
            completed = conn.execute("""
                SELECT id FROM bookings
                WHERE status='Completed' AND cleaner_id IS NOT NULL AND archived_at IS NULL
            """).fetchall()
            for booking in completed:
                ensure_cleaner_payout(conn, booking["id"])
            rows = conn.execute("""
                SELECT p.*, b.reference, b.name AS customer_name, b.preferred_date, b.preferred_time,
                       b.clean_type, b.payment_status, c.name AS cleaner_name, c.email AS cleaner_email
                FROM cleaner_payouts p
                JOIN bookings b ON b.id=p.booking_id
                JOIN cleaners c ON c.id=p.cleaner_id
                WHERE b.archived_at IS NULL
                ORDER BY CASE WHEN p.status='Pending' THEN 0 ELSE 1 END, b.preferred_date DESC, p.id DESC
            """).fetchall()
        return self.send_json([dict(row) for row in rows])

    def mark_cleaner_payout_paid(self, path):
        try:
            payout_id = int(path.split("/")[3])
            data = self.read_json()
            method = str(data.get("paid_method") or "Manual payment").strip()
            notes = str(data.get("notes") or "").strip()
            paid_at = utcnow().isoformat()
            with connect() as conn:
                payout = conn.execute("""
                    SELECT p.*, b.reference, c.name AS cleaner_name
                    FROM cleaner_payouts p
                    JOIN bookings b ON b.id=p.booking_id
                    JOIN cleaners c ON c.id=p.cleaner_id
                    WHERE p.id=?
                """, (payout_id,)).fetchone()
                if not payout:
                    return self.send_json({"error": "Cleaner payout not found."}, 404)
                conn.execute("""
                    UPDATE cleaner_payouts
                    SET status='Paid', paid_at=?, paid_method=?, notes=?, updated_at=?
                    WHERE id=?
                """, (paid_at, method, notes, paid_at, payout_id))
                booking_id = payout["booking_id"]
            automation.timeline(booking_id, "Cleaner payout marked paid", f"{payout['cleaner_name']} payout marked paid by owner via {method}")
            return self.send_json({"ok": True, "status": "Paid", "paid_at": paid_at})
        except (ValueError, TypeError, json.JSONDecodeError, IndexError):
            return self.send_json({"error": "Invalid cleaner payout update."}, 400)

    def update_booking(self, path):
        try:
            booking_id = int(path.split("/")[3])
            data = self.read_json()
            allowed_statuses = {"New", "Deposit Paid", "Assigned", "Accepted", "On My Way", "In Progress", "Completed", "Cancelled"}
            invoice_url, invoice_error = None, None
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                if not booking:
                    return self.send_json({"error": "Booking not found."}, 404)
                new_date = data.get("preferred_date", booking["preferred_date"])
                new_time = data.get("preferred_time", booking["preferred_time"])
                new_status = data.get("status", booking["status"])
                is_test = 1 if data.get("is_test", booking["is_test"] if "is_test" in booking.keys() else 0) else 0
                archive_requested = bool(data.get("archive"))
                unarchive_requested = bool(data.get("unarchive"))
                archive_reason = str(data.get("archive_reason", "")).strip()
                datetime.fromisoformat(new_date)
                if new_status not in allowed_statuses:
                    raise ValueError("Invalid booking status.")
                if booking["cleaner_id"] and cleaner_has_conflict(conn, booking["cleaner_id"], new_date, new_time, booking_id):
                    cleaner = conn.execute("SELECT name FROM cleaners WHERE id=?", (booking["cleaner_id"],)).fetchone()
                    return self.send_json({"error": f"{cleaner['name']} is already booked at that time."}, 409)
                archived_at = booking["archived_at"] if "archived_at" in booking.keys() else None
                if archive_requested:
                    archived_at = utcnow().isoformat()
                    if not archive_reason:
                        archive_reason = "Archived from admin cleanup"
                    is_test = 1
                elif unarchive_requested:
                    archived_at = None
                    archive_reason = ""
                else:
                    archive_reason = booking["archive_reason"] if "archive_reason" in booking.keys() else archive_reason
                conn.execute("""UPDATE bookings SET preferred_date=?, preferred_time=?, status=?, is_test=?, archived_at=?, archive_reason=?
                    WHERE id=?""", (new_date, new_time, new_status, is_test, archived_at, archive_reason, booking_id))
                if new_status == "Completed" and booking["status"] != "Completed":
                    try:
                        refreshed = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                        ensure_cleaner_payout(conn, booking_id)
                        invoice = create_balance_invoice(conn, refreshed)
                        invoice_url = invoice.get("hosted_invoice_url") if invoice else refreshed["balance_payment_url"]
                    except ValueError as error:
                        invoice_error = str(error)
            if new_status == "Completed" and booking["status"] != "Completed":
                automation.timeline(booking_id, "Job completed", "Booking marked complete from the calendar")
                automation.enqueue(booking_id, "send_final_invoice")
            if archive_requested:
                automation.timeline(booking_id, "Booking archived", archive_reason or "Archived from admin cleanup")
            elif unarchive_requested:
                automation.timeline(booking_id, "Booking restored", "Booking restored to active admin lists")
            self.send_json({"ok": True, "preferred_date": new_date, "preferred_time": new_time, "status": new_status, "is_test": is_test, "archived_at": archived_at, "archive_reason": archive_reason, "invoice_url": invoice_url, "invoice_error": invoice_error})
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Invalid schedule update."}, 400)

    def archive_recovered_booking(self, path):
        try:
            session_id = unquote(path.split("/")[3]).strip()
            if not session_id.startswith("cs_"):
                raise ValueError("Invalid recovered payment.")
            try:
                data = self.read_json()
            except ValueError:
                data = {}
            reason = str(data.get("archive_reason") or "Archived recovered Stripe test booking").strip()
            with connect() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO archived_stripe_sessions(session_id,reason,archived_at)
                    VALUES (?,?,?)
                """, (session_id, reason, utcnow().isoformat()))
            return self.send_json({"ok": True, "session_id": session_id, "archived_at": utcnow().isoformat()})
        except (ValueError, TypeError, json.JSONDecodeError, IndexError):
            return self.send_json({"error": "Invalid recovered booking archive request."}, 400)

    def update_cleaner(self, path):
        try:
            cleaner_id = int(path.split("/")[3])
            data = self.read_json()
            allowed_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
            allowed_services = {"Regular clean", "Deep clean", "End of tenancy", "One-off clean"}
            updates, values = [], []
            if "active" in data:
                updates.append("active=?")
                values.append(1 if data.get("active") else 0)
            if "availability" in data:
                availability = data.get("availability")
                if not isinstance(availability, list) or not availability:
                    raise ValueError("Availability must include at least one day.")
                availability = [str(day).strip() for day in availability if str(day).strip()]
                if any(day not in allowed_days for day in availability):
                    raise ValueError("Invalid availability day.")
                updates.append("availability=?")
                values.append(json.dumps(availability))
            if "services" in data:
                services = data.get("services")
                if not isinstance(services, list) or not services:
                    raise ValueError("Services must include at least one service.")
                services = [str(service).strip() for service in services if str(service).strip()]
                if any(service not in allowed_services for service in services):
                    raise ValueError("Invalid service.")
                updates.append("services=?")
                values.append(json.dumps(services))
            if "password" in data:
                password = str(data.get("password") or "")
                if len(password) < 8:
                    raise ValueError("Password must be at least 8 characters.")
                updates.append("password_hash=?")
                values.append(hash_password(password))
            verification_fields = {
                "identity_verified", "right_to_work_verified", "proof_of_address_verified",
                "travel_method", "driving_licence_status", "has_own_vehicle"
            }
            if verification_fields.intersection(data.keys()):
                verification = cleaner_verification_payload(data)
                for field in (
                    "identity_verified", "right_to_work_verified", "proof_of_address_verified",
                    "travel_method", "driving_licence_status", "has_own_vehicle"
                ):
                    updates.append(f"{field}=?")
                    values.append(verification[field])
            if not updates:
                raise ValueError("No cleaner updates supplied.")
            with connect() as conn:
                cleaner = conn.execute("SELECT * FROM cleaners WHERE id=?", (cleaner_id,)).fetchone()
                if not cleaner:
                    return self.send_json({"error": "Cleaner not found."}, 404)
                values.append(cleaner_id)
                conn.execute(f"UPDATE cleaners SET {', '.join(updates)} WHERE id=?", values)
            return self.send_json({"ok": True, "id": cleaner_id})
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Invalid cleaner update."}, 400)


if __name__ == "__main__":
    initialise()
    automation.configure(connect, automation_handler)
    automation.start_worker()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Sparkles is ready on {host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


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
import logging
import sys
import secrets
import re
from email.message import EmailMessage
import automation
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
DB = DATA / "sparkles.db"
MAX_BODY = 15 * 1024 * 1024
ALLOWED_IMAGES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "Sparkles Cleaning <bookings@sparkles.local>")
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
# CB districts fall back to central Cambridge and can be upgraded to a geocoder later.
POSTCODE_CENTRES = {
    "CB1": (52.194, 0.145), "CB2": (52.190, 0.118), "CB3": (52.214, 0.089),
    "CB4": (52.228, 0.128), "CB5": (52.218, 0.176), "CB6": (52.399, 0.262),
    "CB7": (52.350, 0.319), "CB8": (52.242, 0.407), "CB9": (52.083, 0.438),
    "CB10": (52.020, 0.250), "CB11": (52.020, 0.210), "CB21": (52.130, 0.280),
    "CB22": (52.126, 0.120), "CB23": (52.215, -0.018), "CB24": (52.290, 0.083),
    "CB25": (52.260, 0.240)
}

DEFAULT_AI_PRICING = {
    "Regular clean": {"base": 5500, "bedroom_extra": 1400, "bathroom_extra": 1000},
    "Deep clean": {"base": 9500, "bedroom_extra": 1800, "bathroom_extra": 1300},
    "End of tenancy": {"base": 14500, "bedroom_extra": 2400, "bathroom_extra": 1700},
    "One-off clean": {"base": 7500, "bedroom_extra": 1600, "bathroom_extra": 1100}
}
DEFAULT_AI_RESPONSES = {
    "greeting": "Thanks for contacting Sparkles Cleaning Cambridge. I can help with prices, availability and booking details.",
    "booking_prompt": "To prepare an accurate quote, please share your name, phone, email, address, postcode, type of clean, bedrooms, bathrooms, preferred date and preferred time.",
    "handoff": "You can complete the secure booking form online and pay the 25% deposit to confirm."
}
DEFAULT_SERVICE_AREAS = "Cambridge, CB1, CB2, CB3, CB4, CB5, CB21, CB22, CB23, CB24, CB25"
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


def hash_password(password):
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_url():
    return runtime_setting("PUBLIC_URL", PUBLIC_URL).rstrip("/")


def send_auth_email(recipient, subject, body):
    smtp_host = runtime_setting("SMTP_HOST", SMTP_HOST)
    if not smtp_host:
        logger.info(json.dumps({"auth_email_preview": {"recipient": recipient, "subject": subject, "body": body}}))
        return "Preview"
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = runtime_setting("SMTP_FROM", SMTP_FROM), recipient, subject
    message.set_content(body)
    with smtplib.SMTP(smtp_host, int(runtime_setting("SMTP_PORT", str(SMTP_PORT))), timeout=20) as smtp:
        smtp.starttls()
        smtp_user = runtime_setting("SMTP_USER", SMTP_USER)
        if smtp_user:
            smtp.login(smtp_user, runtime_setting("SMTP_PASSWORD", SMTP_PASSWORD))
        smtp.send_message(message)
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
    return int(rule.get("base", 7500)) + max(0, int(bedrooms) - 1) * int(rule.get("bedroom_extra", 0)) + max(0, int(bathrooms) - 1) * int(rule.get("bathroom_extra", 0))


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


def stripe_configured():
    return bool(runtime_setting("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY))


def create_checkout(booking, payment_type):
    amount = booking["deposit_amount"] if payment_type == "deposit" else booking["balance_amount"]
    label = "25% cleaning deposit" if payment_type == "deposit" else "Cleaning invoice balance"
    return stripe_request("checkout/sessions", {
        "mode": "payment", "customer_email": booking["email"],
        "success_url": f"{public_url()}/payment-success?session_id={{CHECKOUT_SESSION_ID}}&booking={booking['id']}",
        "cancel_url": f"{public_url()}/?payment=cancelled&booking={booking['id']}", "client_reference_id": str(booking["id"]),
        "metadata[booking_id]": str(booking["id"]), "metadata[payment_type]": payment_type,
        "line_items[0][price_data][currency]": "gbp", "line_items[0][price_data][unit_amount]": str(amount),
        "line_items[0][price_data][product_data][name]": f"Sparkles Cleaning – {label}",
        "line_items[0][price_data][product_data][description]": booking["reference"], "line_items[0][quantity]": "1"
    })


def create_balance_invoice(conn, booking):
    if not runtime_setting("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY) or booking["stripe_invoice_id"] or booking["payment_status"] == "Paid in Full":
        return None
    customer_id = booking["stripe_customer_id"]
    if not customer_id:
        customer = stripe_request("customers", {"email": booking["email"], "name": booking["name"], "metadata[booking_id]": str(booking["id"])})
        customer_id = customer["id"]
        conn.execute("UPDATE bookings SET stripe_customer_id=? WHERE id=?", (customer_id, booking["id"]))
    stripe_request("invoiceitems", {"customer": customer_id, "amount": str(booking["balance_amount"]), "currency": "gbp", "description": f"Remaining balance for {booking['reference']}", "metadata[booking_id]": str(booking["id"])})
    invoice = stripe_request("invoices", {"customer": customer_id, "collection_method": "send_invoice", "days_until_due": "7", "auto_advance": "false", "metadata[booking_id]": str(booking["id"]), "description": f"Sparkles Cleaning – {booking['reference']}"})
    finalized = stripe_request(f"invoices/{invoice['id']}/finalize", {"auto_advance": "false"})
    conn.execute("UPDATE bookings SET stripe_invoice_id=?, balance_payment_url=?, payment_status='Balance Due' WHERE id=?", (invoice["id"], finalized.get("hosted_invoice_url"), booking["id"]))
    return finalized


def record_payment(conn, booking_id, payment_type, amount, provider_id, status="Paid"):
    conn.execute("""INSERT OR IGNORE INTO payments
        (booking_id,payment_type,amount,currency,status,provider_payment_id,created_at)
        VALUES (?,?,?,'gbp',?,?,?)""", (booking_id, payment_type, amount, status, provider_id, datetime.now(timezone.utc).isoformat()))
    if payment_type == "deposit":
        conn.execute("UPDATE bookings SET payment_status='Deposit Paid', status=CASE WHEN status='New' THEN 'Deposit Paid' ELSE status END WHERE id=?", (booking_id,))
    elif payment_type == "balance":
        conn.execute("UPDATE bookings SET payment_status='Paid in Full' WHERE id=?", (booking_id,))


def send_workflow_email(booking_id, recipient, subject, body):
    delivery_status, provider_id, error = "Preview", None, None
    smtp_host = runtime_setting("SMTP_HOST", SMTP_HOST)
    if smtp_host:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = runtime_setting("SMTP_FROM", SMTP_FROM), recipient, subject
        message.set_content(body)
        try:
            with smtplib.SMTP(smtp_host, int(runtime_setting("SMTP_PORT", str(SMTP_PORT))), timeout=20) as smtp:
                smtp.starttls()
                smtp_user = runtime_setting("SMTP_USER", SMTP_USER)
                if smtp_user:
                    smtp.login(smtp_user, runtime_setting("SMTP_PASSWORD", SMTP_PASSWORD))
                smtp.send_message(message)
            delivery_status, provider_id = "Sent", message["Message-ID"] or uuid.uuid4().hex
        except Exception as exc:
            error = str(exc)
            delivery_status = "Failed"
    with connect() as conn:
        conn.execute("INSERT INTO email_log(booking_id,recipient,subject,body,status,provider_id,error,created_at) VALUES (?,?,?,?,?,?,?,?)", (booking_id, recipient, subject, body, delivery_status, provider_id, error, datetime.now(timezone.utc).isoformat()))
    automation.timeline(booking_id, "Email prepared" if delivery_status == "Preview" else "Email sent", f"{subject} → {recipient} ({delivery_status})", "Warning" if delivery_status == "Preview" else "Info")
    if delivery_status == "Failed":
        raise RuntimeError(error)


def suitable_cleaners(booking):
    weekday = datetime.fromisoformat(booking["preferred_date"]).strftime("%A")
    matches = []
    with connect() as conn:
        for row in conn.execute("SELECT * FROM cleaners WHERE active=1").fetchall():
            cleaner = dict(row)
            distance = distance_miles(booking["postcode"], cleaner["postcode"])
            if (weekday in json.loads(cleaner["availability"]) and booking["clean_type"] in json.loads(cleaner["services"])
                    and distance <= cleaner["travel_radius"] and not cleaner_has_conflict(conn, cleaner["id"], booking["preferred_date"], booking["preferred_time"], booking["id"])):
                cleaner["distance"] = distance
                matches.append(cleaner)
    return sorted(matches, key=lambda item: (item["distance"], item["hourly_rate"]))


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
        send_workflow_email(booking_id, booking["email"], f"Complete your Sparkles booking - {booking['reference']}", f"Hello {booking['name']},\n\nWe saved your Sparkles Cleaning Cambridge booking request, but the 25% deposit has not been completed yet.\n\nYour quote is £{booking['total_amount']/100:.2f}; the deposit is £{booking['deposit_amount']/100:.2f}.\n\nComplete your booking here: {checkout}\n\nIf you have questions, reply to this email and we will help.")
        automation.timeline(booking_id, "Abandoned booking follow-up sent", "Customer reminded 24 hours after an unpaid booking")
    elif step == "offer_cleaners":
        matches = suitable_cleaners(booking)
        if not matches:
            raise RuntimeError("No suitable cleaners currently available")
        for cleaner in matches:
            token = uuid.uuid4().hex
            with connect() as conn:
                conn.execute("INSERT OR IGNORE INTO cleaner_offers(booking_id,cleaner_id,token,status,distance,created_at) VALUES (?,?,?,'Offered',?,?)", (booking_id, cleaner["id"], token, cleaner["distance"], datetime.now(timezone.utc).isoformat()))
                offer = conn.execute("SELECT token FROM cleaner_offers WHERE booking_id=? AND cleaner_id=?", (booking_id, cleaner["id"])).fetchone()
            link = f"{runtime_setting('PUBLIC_URL', PUBLIC_URL).rstrip('/')}/job-offer?token={offer['token']}"
            send_workflow_email(booking_id, cleaner["email"], f"New cleaning job near {booking['postcode']}", f"Hello {cleaner['name']},\n\nA {booking['clean_type']} is available on {booking['preferred_date']} ({booking['preferred_time']}), {cleaner['distance']} miles away.\n\nView and accept: {link}")
        automation.timeline(booking_id, "Job offered", f"Offered to {len(matches)} suitable cleaner(s), nearest first")
    elif step == "send_payment_confirmation":
        send_workflow_email(booking_id, booking["email"], f"Deposit received - {booking['reference']}", f"Hello {booking['name']},\n\nThank you. We have received your 25% deposit of £{booking['deposit_amount']/100:.2f} for {booking['clean_type']} on {booking['preferred_date']} ({booking['preferred_time']}).\n\nWe will confirm the assigned cleaner as soon as the job is accepted.\n\nSparkles Cleaning Cambridge")
        automation.timeline(booking_id, "Payment confirmation sent", "Customer notified after deposit payment")
    elif step == "send_confirmations":
        send_workflow_email(booking_id, booking["email"], f"Cleaner confirmed – {booking['reference']}", f"Hello {booking['name']},\n\n{booking['cleaner_name']} is confirmed for {booking['preferred_date']} ({booking['preferred_time']}).")
        send_workflow_email(booking_id, booking["cleaner_email"], f"Job confirmed – {booking['reference']}", f"Hello {booking['cleaner_name']},\n\nYou are confirmed for {booking['address']}, {booking['postcode']} on {booking['preferred_date']} ({booking['preferred_time']}).")
        automation.timeline(booking_id, "Confirmations sent", f"Customer and {booking['cleaner_name']} notified; booking is on the calendar")
    elif step == "send_reminder":
        send_workflow_email(booking_id, booking["email"], f"Reminder: your clean is tomorrow", f"Your Sparkles clean is tomorrow, {booking['preferred_date']} ({booking['preferred_time']}). Cleaner: {booking['cleaner_name']}.")
        send_workflow_email(booking_id, booking["cleaner_email"], f"Reminder: cleaning job tomorrow", f"Reminder for {booking['address']}, {booking['postcode']} tomorrow ({booking['preferred_time']}).")
        automation.timeline(booking_id, "24-hour reminders sent", "Customer and cleaner reminded")
    elif step == "send_final_invoice":
        with connect() as conn:
            invoice = create_balance_invoice(conn, conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone())
            url = invoice.get("hosted_invoice_url") if invoice else booking["balance_payment_url"]
        if not url:
            raise RuntimeError("Stripe invoice URL is not available")
        send_workflow_email(booking_id, booking["email"], f"Final invoice – {booking['reference']}", f"Thank you for choosing Sparkles. Your remaining balance is £{booking['balance_amount']/100:.2f}.\n\nPay securely: {url}")
        automation.timeline(booking_id, "Final invoice sent", f"Balance £{booking['balance_amount']/100:.2f}")
    elif step == "send_review":
        review_url = runtime_setting("REVIEW_URL", "") or f"{runtime_setting('PUBLIC_URL', PUBLIC_URL).rstrip('/')}/review-thanks?booking={booking_id}"
        send_workflow_email(booking_id, booking["email"], "How did we do?", f"Hello {booking['name']},\n\nThank you for your payment. We would love your feedback: {review_url}")
        automation.timeline(booking_id, "Review requested", "Review request sent after final payment")
    else:
        raise RuntimeError(f"Unknown automation step: {step}")


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def runtime_setting(key, fallback=""):
    environment = os.environ.get(key)
    if environment not in (None, ""):
        return environment
    try:
        with connect() as conn:
            row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else fallback
    except sqlite3.Error:
        return fallback


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
        conn.execute("""CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
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
        defaults = [
            ("COMPANY_NAME", "Sparkles Cleaning Cambridge", 0), ("COMPANY_EMAIL", "", 0),
            ("COMPANY_PHONE", "", 0), ("BUSINESS_ADDRESS", "", 0), ("PUBLIC_URL", PUBLIC_URL, 0),
            ("STRIPE_SECRET_KEY", "", 1), ("STRIPE_WEBHOOK_SECRET", "", 1),
            ("SMTP_HOST", "", 0), ("SMTP_PORT", "587", 0), ("SMTP_USER", "", 0),
            ("SMTP_PASSWORD", "", 1), ("SMTP_FROM", SMTP_FROM, 0), ("REVIEW_URL", "", 0),
            ("LOGO_URL", "", 0), ("ADMIN_EMAIL", "", 0), ("ADMIN_PASSWORD_HASH", "", 1),
            ("AI_BUSINESS_HOURS", DEFAULT_BUSINESS_HOURS, 0), ("AI_SERVICE_AREAS", DEFAULT_SERVICE_AREAS, 0),
            ("AI_PRICING_JSON", json.dumps(DEFAULT_AI_PRICING), 0), ("AI_RESPONSES_JSON", json.dumps(DEFAULT_AI_RESPONSES), 0)
        ]
        conn.executemany("INSERT OR IGNORE INTO app_config(key,value,is_secret,updated_at) VALUES (?,?,?,?)", [(k,v,s,datetime.now(timezone.utc).isoformat()) for k,v,s in defaults])
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

    def auth_cookie(self, token):
        return f"{SESSION_COOKIE}={urllib.parse.quote(token)}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 86400}"

    def expired_cookie(self):
        return f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"

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
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
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
            except sqlite3.Error:
                return self.send_json({"status": "not_ready", "database": "error"}, 503)
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
                rows = conn.execute("""SELECT b.*, c.name AS cleaner_name, c.phone AS cleaner_phone
                    FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id ORDER BY b.id DESC""").fetchall()
            bookings = []
            for row in rows:
                item = dict(row)
                item["photos"] = json.loads(item["photos"])
                item["before_photos"] = json.loads(item.get("before_photos") or "[]")
                item["after_photos"] = json.loads(item.get("after_photos") or "[]")
                with connect() as payment_conn:
                    item["payments"] = [dict(payment) for payment in payment_conn.execute("SELECT * FROM payments WHERE booking_id=? ORDER BY id DESC", (item["id"],)).fetchall()]
                bookings.append(item)
            return self.send_json(bookings)
        if path == "/api/cleaners":
            if not self.require_admin():
                return
            with connect() as conn:
                rows = conn.execute("SELECT * FROM cleaners ORDER BY active DESC, name").fetchall()
            cleaners = []
            for row in rows:
                item = dict(row)
                item.pop("password_hash", None)
                item["availability"] = json.loads(item["availability"])
                item["services"] = json.loads(item["services"])
                cleaners.append(item)
            return self.send_json(cleaners)
        if path.startswith("/api/bookings/") and path.endswith("/matches"):
            if not self.require_admin():
                return
            try:
                booking_id = int(path.split("/")[3])
                with connect() as conn:
                    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                    cleaners = conn.execute("SELECT * FROM cleaners WHERE active=1").fetchall()
                if not booking:
                    return self.send_json({"error": "Booking not found."}, 404)
                weekday = datetime.fromisoformat(booking["preferred_date"]).strftime("%A")
                matches = []
                for row in cleaners:
                    cleaner = dict(row)
                    cleaner.pop("password_hash", None)
                    services = json.loads(cleaner["services"])
                    availability = json.loads(cleaner["availability"])
                    distance = distance_miles(booking["postcode"], cleaner["postcode"])
                    cleaner["distance"] = distance
                    cleaner["services"] = services
                    cleaner["availability"] = availability
                    with connect() as schedule_conn:
                        conflict = cleaner_has_conflict(schedule_conn, cleaner["id"], booking["preferred_date"], booking["preferred_time"], booking_id)
                    cleaner["is_available"] = weekday in availability and booking["clean_type"] in services and distance <= cleaner["travel_radius"] and not conflict
                    if cleaner["is_available"]:
                        matches.append(cleaner)
                return self.send_json(sorted(matches, key=lambda c: (c["distance"], c["hourly_rate"])))
            except (ValueError, IndexError):
                return self.send_json({"error": "Invalid booking."}, 400)
        if path == "/api/customer/bookings":
            session = self.current_session()
            if not session or session["role"] != "customer":
                return self.send_json({"error": "Customer login required."}, 401)
            with connect() as conn:
                rows = conn.execute("""SELECT b.*, c.name AS cleaner_name, c.phone AS cleaner_phone
                    FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id
                    WHERE lower(b.email)=lower(?) OR b.customer_id=?
                    ORDER BY b.id DESC""", (session["email"], session["subject_id"])).fetchall()
            bookings = []
            for row in rows:
                item = dict(row)
                item["photos"] = json.loads(item["photos"])
                with connect() as payment_conn:
                    item["payments"] = [dict(payment) for payment in payment_conn.execute("SELECT * FROM payments WHERE booking_id=? ORDER BY id DESC", (item["id"],)).fetchall()]
                bookings.append(item)
            return self.send_json(bookings)
        if path == "/api/cleaner/jobs":
            session = self.current_session()
            if not session or session["role"] != "cleaner":
                return self.send_json({"error": "Cleaner login required."}, 401)
            with connect() as conn:
                rows = conn.execute("SELECT * FROM bookings WHERE cleaner_id=? ORDER BY preferred_date DESC, preferred_time DESC", (session["subject_id"],)).fetchall()
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
        if path in ("/customer", "/customer/", "/customer/login", "/customer/login/"):
            return self.send_file(PUBLIC / "customer.html")
        if path in ("/reset-password", "/reset-password/"):
            return self.send_file(PUBLIC / "reset-password.html")
        if path in ("/admin", "/admin/", "/admin/dashboard", "/admin/dashboard/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "owner-dashboard.html")
        if path in ("/admin/bookings", "/admin/bookings/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "admin.html")
        if path in ("/admin/cleaners", "/admin/cleaners/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "cleaners-admin.html")
        if path in ("/admin/calendar", "/admin/calendar/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "calendar.html")
        if path in ("/cleaner", "/cleaner/"):
            return self.send_file(PUBLIC / "cleaner.html")
        if path in ("/cleaner/dashboard", "/cleaner/dashboard/"):
            if not self.is_cleaner():
                return self.redirect("/cleaner/login")
            return self.send_file(PUBLIC / "cleaner-dashboard.html")
        if path in ("/payment-success", "/payment-success/"):
            return self.send_file(PUBLIC / "payment-success.html")
        if path in ("/quote", "/quote/"):
            return self.send_file(PUBLIC / "quote.html")
        if path in ("/job-offer", "/job-offer/"):
            return self.send_file(PUBLIC / "job-offer.html")
        if path in ("/admin/automations", "/admin/automations/"):
            if not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "automations.html")
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
        if path in ("/admin/setup", "/admin/setup/"):
            if admin_configured() and not self.is_admin():
                return self.redirect("/admin/login")
            return self.send_file(PUBLIC / "setup.html")
        protected_files = {"/owner-dashboard.html", "/admin.html", "/cleaners-admin.html", "/calendar.html", "/automations.html", "/ai-office.html", "/ai-office-settings.html", "/receptionist-admin.html", "/setup.html"}
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
        if path == "/api/cleaners":
            return self.create_cleaner()
        if path.startswith("/api/cleaner/jobs/") and path.endswith("/action"):
            return self.cleaner_job_action(path)
        if path.startswith("/api/cleaner/jobs/") and path.endswith("/photos"):
            return self.cleaner_job_photos(path)
        if path.startswith("/api/bookings/") and path.endswith("/checkout"):
            return self.start_checkout(path)
        if path.startswith("/api/bookings/") and path.endswith("/assign"):
            if not self.require_admin():
                return
            return self.assign_cleaner(path)
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
        if path.startswith("/api/bookings/"):
            if not self.require_admin():
                return
            return self.update_booking(path)
        self.send_error(404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1024 * 1024:
            raise ValueError("Invalid request.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

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
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            with connect() as conn:
                cleaner = conn.execute("SELECT id,email,password_hash,active FROM cleaners WHERE lower(email)=lower(?)", (email,)).fetchone()
            if not cleaner or not cleaner["password_hash"] or not verify_password(password, cleaner["password_hash"]):
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
        except sqlite3.IntegrityError:
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
            if not customer or not verify_password(password, customer["password_hash"]):
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
                    row = conn.execute("SELECT id FROM cleaners WHERE lower(email)=lower(?)", (email,)).fetchone()
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
            password = data.get("password", "")
            with connect() as conn:
                reset = conn.execute("SELECT * FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?", (token_hash(token), utcnow().isoformat())).fetchone()
                if not reset:
                    return self.send_json({"error": "Reset link is invalid or has expired."}, 400)
                password_hash = hash_password(password)
                if reset["role"] == "admin":
                    conn.execute("""INSERT INTO app_config(key,value,is_secret,updated_at) VALUES ('ADMIN_PASSWORD_HASH',?,?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,updated_at=excluded.updated_at""", (password_hash, 1, utcnow().isoformat()))
                elif reset["role"] == "cleaner":
                    conn.execute("UPDATE cleaners SET password_hash=? WHERE id=?", (password_hash, reset["subject_id"]))
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
            allowed = {"COMPANY_NAME","COMPANY_EMAIL","COMPANY_PHONE","BUSINESS_ADDRESS","PUBLIC_URL","STRIPE_SECRET_KEY","STRIPE_WEBHOOK_SECRET","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASSWORD","SMTP_FROM","REVIEW_URL","ADMIN_EMAIL"}
            secret_keys = {"STRIPE_SECRET_KEY","STRIPE_WEBHOOK_SECRET","SMTP_PASSWORD"}
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
            details.setdefault("location", "Cambridge")
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

    def owner_dashboard(self):
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        today_s, tomorrow_s = today.isoformat(), tomorrow.isoformat()
        week_start_s, month_start_s = week_start.isoformat(), month_start.isoformat()
        paid_statuses = ("Paid", "Succeeded", "succeeded", "paid")

        def money_between(conn, start_date, end_date=None, payment_type=None):
            clauses = ["status IN (?,?,?,?)", "substr(created_at,1,10) >= ?"]
            params = [*paid_statuses, start_date]
            if end_date:
                clauses.append("substr(created_at,1,10) <= ?")
                params.append(end_date)
            if payment_type:
                clauses.append("payment_type = ?")
                params.append(payment_type)
            row = conn.execute(f"SELECT COALESCE(SUM(amount),0) total FROM payments WHERE {' AND '.join(clauses)}", params).fetchone()
            return int(row["total"] or 0)

        with connect() as conn:
            revenue_today = money_between(conn, today_s, today_s)
            revenue_week = money_between(conn, week_start_s, today_s)
            revenue_month = money_between(conn, month_start_s, today_s)
            deposits_today = money_between(conn, today_s, today_s, "deposit")
            today_bookings = conn.execute("SELECT COUNT(*) count FROM bookings WHERE preferred_date=?", (today_s,)).fetchone()["count"]
            tomorrow_bookings = conn.execute("SELECT COUNT(*) count FROM bookings WHERE preferred_date=?", (tomorrow_s,)).fetchone()["count"]
            waiting_assignment = conn.execute("""SELECT COUNT(*) count FROM bookings
                WHERE cleaner_id IS NULL AND status NOT IN ('Completed','Cancelled')""").fetchone()["count"]
            in_progress = conn.execute("SELECT COUNT(*) count FROM bookings WHERE status='In Progress'").fetchone()["count"]
            completed_today = conn.execute("""SELECT COUNT(*) count FROM bookings
                WHERE status='Completed' AND (substr(COALESCE(completed_at,''),1,10)=? OR (completed_at IS NULL AND preferred_date=?))""", (today_s, today_s)).fetchone()["count"]
            active_cleaners = conn.execute("SELECT COUNT(*) count FROM cleaners WHERE active=1").fetchone()["count"]
            total_bookings = conn.execute("SELECT COUNT(*) count FROM bookings").fetchone()["count"]
            converted_bookings = conn.execute("SELECT COUNT(*) count FROM bookings WHERE payment_status IN ('Deposit Paid','Paid in Full')").fetchone()["count"]
            average_job = conn.execute("SELECT COALESCE(AVG(total_amount),0) value FROM bookings WHERE total_amount > 0").fetchone()["value"] or 0
            ai_waiting = conn.execute("""SELECT COUNT(*) count FROM ai_conversations c
                WHERE c.admin_takeover=1
                   OR c.status='Admin Takeover'
                   OR EXISTS (
                        SELECT 1 FROM ai_messages m
                        WHERE m.conversation_id=c.id
                          AND m.sender='customer'
                          AND m.id=(SELECT MAX(id) FROM ai_messages WHERE conversation_id=c.id)
                   )""").fetchone()["count"]
            recent_reviews = [dict(row) for row in conn.execute("""SELECT r.*, b.reference booking_reference
                FROM customer_reviews r LEFT JOIN bookings b ON b.id=r.booking_id
                ORDER BY r.created_at DESC LIMIT 5""").fetchall()]
            status_rows = [dict(row) for row in conn.execute("SELECT status, COUNT(*) count FROM bookings GROUP BY status ORDER BY count DESC").fetchall()]
            revenue_days = []
            for offset in range(6, -1, -1):
                day = today - timedelta(days=offset)
                day_s = day.isoformat()
                revenue_days.append({
                    "date": day_s,
                    "label": day.strftime("%a"),
                    "amount": money_between(conn, day_s, day_s)
                })
            upcoming_rows = [dict(row) for row in conn.execute("""SELECT b.id,b.reference,b.name,b.clean_type,b.preferred_date,b.preferred_time,b.status,c.name cleaner_name
                FROM bookings b LEFT JOIN cleaners c ON c.id=b.cleaner_id
                WHERE b.preferred_date IN (?,?)
                ORDER BY b.preferred_date,b.preferred_time LIMIT 10""", (today_s, tomorrow_s)).fetchall()]

        conversion_rate = round((converted_bookings / total_bookings) * 100, 1) if total_bookings else 0
        return self.send_json({
            "as_of": utcnow().isoformat(),
            "cards": {
                "revenue_today": revenue_today,
                "revenue_week": revenue_week,
                "revenue_month": revenue_month,
                "deposits_today": deposits_today,
                "today_bookings": today_bookings,
                "tomorrow_bookings": tomorrow_bookings,
                "waiting_assignment": waiting_assignment,
                "in_progress": in_progress,
                "completed_today": completed_today,
                "active_cleaners": active_cleaners,
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
        })

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
                    automation.enqueue(booking_id, "send_payment_confirmation")
                    automation.enqueue(booking_id, "offer_cleaners")
                else:
                    automation.enqueue(booking_id, "send_review")
            elif event.get("type") == "invoice.paid":
                invoice = event["data"]["object"]
                booking_id = int(invoice.get("metadata", {}).get("booking_id", 0))
                if booking_id:
                    with connect() as conn:
                        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                        if not booking:
                            return self.send_json({"error": "Booking not found for this Stripe invoice."}, 404)
                        record_payment(conn, booking_id, "balance", booking["balance_amount"], invoice["id"])
                    automation.timeline(booking_id, "Final payment received", "Stripe invoice paid in full")
                    automation.enqueue(booking_id, "send_review")
            self.send_json({"received": True})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)

    def create_cleaner(self):
        try:
            data = self.read_json()
            required = ["name", "phone", "email", "password", "postcode", "travel_radius", "hourly_rate", "availability", "services", "dbs_status", "insurance_status"]
            if any(not data.get(key) for key in required):
                raise ValueError("Please complete all required fields.")
            radius, rate = float(data["travel_radius"]), float(data["hourly_rate"])
            if radius <= 0 or rate <= 0:
                raise ValueError("Travel radius and hourly rate must be greater than zero.")
            with connect() as conn:
                cursor = conn.execute("""INSERT INTO cleaners
                    (name,phone,email,password_hash,postcode,travel_radius,hourly_rate,availability,services,dbs_status,insurance_status,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (data["name"].strip(), data["phone"].strip(), data["email"].strip().lower(), hash_password(data["password"]), data["postcode"].strip().upper(), radius, rate, json.dumps(data["availability"]), json.dumps(data["services"]), data["dbs_status"], data["insurance_status"], datetime.now(timezone.utc).isoformat()))
            self.send_json({"ok": True, "id": cursor.lastrowid}, 201)
        except sqlite3.IntegrityError:
            self.send_json({"error": "An account already exists for that email address."}, 409)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)

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
                cleaner = conn.execute("SELECT * FROM cleaners WHERE id=? AND active=1", (cleaner_id,)).fetchone()
                if not booking or not cleaner:
                    return self.send_json({"error": "Booking or cleaner not found."}, 404)
                if cleaner_has_conflict(conn, cleaner_id, booking["preferred_date"], booking["preferred_time"], booking_id):
                    return self.send_json({"error": f"{cleaner['name']} is already booked at that time."}, 409)
                conn.execute("UPDATE bookings SET cleaner_id=?, status='Assigned', assigned_at=? WHERE id=?", (cleaner_id, datetime.now(timezone.utc).isoformat(), booking_id))
                updated = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            automation.timeline(booking_id, "Cleaner assigned", f"{cleaner['name']} assigned by admin")
            automation.enqueue(booking_id, "send_confirmations")
            schedule_booking_reminder(dict(updated))
            self.send_json({"ok": True, "status": "Assigned", "cleaner_name": cleaner["name"]})
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Invalid assignment request."}, 400)

    def cleaner_job_action(self, path):
        session = self.current_session()
        if not session or session["role"] != "cleaner":
            return self.send_json({"error": "Cleaner login required."}, 401)
        try:
            booking_id = int(path.split("/")[4])
            data = self.read_json()
            action = data.get("action")
            now = utcnow().isoformat()
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE id=? AND cleaner_id=?", (booking_id, session["subject_id"])).fetchone()
                if not booking:
                    return self.send_json({"error": "Assigned job not found."}, 404)
                if action == "accept":
                    if booking["status"] not in ("Assigned", "Accepted"):
                        return self.send_json({"error": "Only assigned jobs can be accepted."}, 409)
                    conn.execute("UPDATE bookings SET status='Accepted', accepted_at=COALESCE(accepted_at, ?) WHERE id=?", (now, booking_id))
                    event, detail, status = "Job accepted", "Cleaner accepted the assigned job", "Accepted"
                elif action == "decline":
                    if booking["status"] not in ("Assigned", "Accepted"):
                        return self.send_json({"error": "Only assigned jobs can be declined."}, 409)
                    conn.execute("UPDATE bookings SET status='New', cleaner_id=NULL, assigned_at=NULL, declined_at=?, cleaner_notes=CASE WHEN ?<>'' THEN ? ELSE cleaner_notes END WHERE id=?", (now, data.get("notes", "").strip(), data.get("notes", "").strip(), booking_id))
                    event, detail, status = "Job declined", "Cleaner declined the job; booking returned to New", "New"
                elif action == "start":
                    if booking["status"] not in ("Accepted", "Assigned", "In Progress"):
                        return self.send_json({"error": "Only accepted jobs can be started."}, 409)
                    conn.execute("UPDATE bookings SET status='In Progress', accepted_at=COALESCE(accepted_at, ?), started_at=COALESCE(started_at, ?) WHERE id=?", (now, now, booking_id))
                    event, detail, status = "Job started", "Cleaner started the job", "In Progress"
                elif action == "complete":
                    if booking["status"] not in ("In Progress", "Accepted", "Assigned", "Completed"):
                        return self.send_json({"error": "Only active jobs can be completed."}, 409)
                    conn.execute("UPDATE bookings SET status='Completed', accepted_at=COALESCE(accepted_at, ?), started_at=COALESCE(started_at, ?), completed_at=COALESCE(completed_at, ?) WHERE id=?", (now, now, now, booking_id))
                    event, detail, status = "Job completed", "Cleaner marked the job complete", "Completed"
                elif action == "notes":
                    notes = data.get("notes", "").strip()
                    conn.execute("UPDATE bookings SET cleaner_notes=? WHERE id=?", (notes, booking_id))
                    event, detail, status = "Cleaner notes updated", "Cleaner updated job notes", booking["status"]
                else:
                    raise ValueError("Invalid cleaner job action.")
            automation.timeline(booking_id, event, detail)
            if action == "complete":
                automation.enqueue(booking_id, "send_final_invoice")
                automation.enqueue(booking_id, "send_review")
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

    def update_booking(self, path):
        try:
            booking_id = int(path.split("/")[3])
            data = self.read_json()
            allowed_statuses = {"New", "Deposit Paid", "Assigned", "Accepted", "In Progress", "Completed", "Cancelled"}
            invoice_url, invoice_error = None, None
            with connect() as conn:
                booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                if not booking:
                    return self.send_json({"error": "Booking not found."}, 404)
                new_date = data.get("preferred_date", booking["preferred_date"])
                new_time = data.get("preferred_time", booking["preferred_time"])
                new_status = data.get("status", booking["status"])
                datetime.fromisoformat(new_date)
                if new_status not in allowed_statuses:
                    raise ValueError("Invalid booking status.")
                if booking["cleaner_id"] and cleaner_has_conflict(conn, booking["cleaner_id"], new_date, new_time, booking_id):
                    cleaner = conn.execute("SELECT name FROM cleaners WHERE id=?", (booking["cleaner_id"],)).fetchone()
                    return self.send_json({"error": f"{cleaner['name']} is already booked at that time."}, 409)
                conn.execute("UPDATE bookings SET preferred_date=?, preferred_time=?, status=? WHERE id=?", (new_date, new_time, new_status, booking_id))
                if new_status == "Completed" and booking["status"] != "Completed":
                    try:
                        refreshed = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
                        invoice = create_balance_invoice(conn, refreshed)
                        invoice_url = invoice.get("hosted_invoice_url") if invoice else refreshed["balance_payment_url"]
                    except ValueError as error:
                        invoice_error = str(error)
            if new_status == "Completed" and booking["status"] != "Completed":
                automation.timeline(booking_id, "Job completed", "Booking marked complete from the calendar")
                automation.enqueue(booking_id, "send_final_invoice")
                automation.enqueue(booking_id, "send_review")
            self.send_json({"ok": True, "preferred_date": new_date, "preferred_time": new_time, "status": new_status, "invoice_url": invoice_url, "invoice_error": invoice_error})
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Invalid schedule update."}, 400)


if __name__ == "__main__":
    initialise()
    automation.configure(connect, automation_handler)
    automation.start_worker()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Sparkles is ready on {host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()

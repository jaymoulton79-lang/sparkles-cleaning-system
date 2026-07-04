# Sparkles Cleaning Cambridge MVP

A mobile-friendly customer booking form and simple admin dashboard. Bookings and photo metadata are stored in a local SQLite database.

## Run

```powershell
& "C:\Users\LABco\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" server.py
```

Then visit `http://localhost:8000`. The dashboard is at `http://localhost:8000/admin`.

The cleaner portal is at `http://localhost:8000/cleaner`, and the admin cleaner directory is at `http://localhost:8000/admin/cleaners`.

The scheduling calendar is at `http://localhost:8000/admin/calendar` and includes day, week and month views with drag-to-reschedule support.

Cleaner matching filters by the requested service, day of the week and travel radius, then sorts eligible cleaners by approximate distance between Cambridge postcode districts.

Data is created in `data/sparkles.db`; uploaded photos are saved in `data/uploads/`.

## Stripe test mode

Set Stripe test credentials before starting the server:

```powershell
$env:STRIPE_SECRET_KEY="sk_test_..."
$env:STRIPE_WEBHOOK_SECRET="whsec_..."
$env:PUBLIC_URL="http://localhost:8000"
& "C:\Users\LABco\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" server.py
```

For local webhook testing, run Stripe CLI separately:

```powershell
stripe listen --forward-to localhost:8000/api/stripe/webhook
```

When a customer submits the booking form, the app saves the booking as `Deposit Due`, calculates the 25% deposit, creates a Stripe Checkout session, and returns the secure checkout link immediately. The booking stays `Deposit Due` unless Stripe confirms payment.

Use Stripe's test card `4242 4242 4242 4242`, any future expiry date and any CVC. After payment succeeds, Stripe redirects to `/payment-success` and the webhook endpoint `/api/stripe/webhook` also handles `checkout.session.completed`, records the payment, and marks the booking `Deposit Paid`.

For Railway, add these variables to the service:

```text
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
PUBLIC_URL=https://your-railway-app.up.railway.app
```

In Stripe test mode, create a webhook endpoint pointing to:

```text
https://your-railway-app.up.railway.app/api/stripe/webhook
```

Completing a job creates and finalizes the remaining-balance Stripe invoice when credentials are configured.

## Automated workflow

The automation engine runs inside the server and is monitored at `http://localhost:8000/admin/automations`. It queues quote emails, cleaner offers, confirmations, 24-hour reminders, final invoices and review requests. Failed jobs retry with exponential backoff and can also be retried manually.

For Railway production email, use Resend: set `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, and `SMTP_FROM` to a verified Resend sender. Existing booking, owner, cleaner, reminder and invoice emails use the same delivery path.

SMTP is still available for local/dev providers with `EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM`. Without real email settings, emails are stored as local previews in the automation logs so the complete workflow can be tested safely.

## AI Office Manager

Admins can open `http://localhost:8000/admin/ai-office` to draft customer enquiry replies, ask for missing booking details, generate quotes from Sparkles pricing rules, and send customers to the online booking page. Settings for business hours, pricing, service areas and response text are editable at `http://localhost:8000/admin/ai-office/settings`.

The automation engine also follows up unpaid bookings after 24 hours, confirms deposit payments, sends 24-hour reminders before cleans, and requests reviews after completed jobs.

## AI Receptionist live chat

The booking website includes a mobile-friendly AI Receptionist chat widget. Customer conversations are saved in the database, quotes use the same Sparkles pricing rules, completed chat bookings create normal bookings with Stripe deposit links, and admins can review or take over chats at `http://localhost:8000/admin/receptionist`.

## Production

Use the protected setup wizard at `http://localhost:8000/admin/setup`. Docker, cloud deployment, health checks, backups and logging are covered in `DEPLOYMENT.md`. Complete every item in `PRODUCTION_CHECKLIST.md` before accepting real customers or switching Stripe to live mode.

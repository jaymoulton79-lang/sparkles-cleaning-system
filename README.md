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

Use Stripe's test card `4242 4242 4242 4242`, any future expiry date and any CVC. Bookings calculate a 25% deposit. Completing a job creates and finalizes the remaining-balance Stripe invoice when credentials are configured.

## Automated workflow

The automation engine runs inside the server and is monitored at `http://localhost:8000/admin/automations`. It queues quote emails, cleaner offers, confirmations, 24-hour reminders, final invoices and review requests. Failed jobs retry with exponential backoff and can also be retried manually.

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM` to deliver real email. Without SMTP settings, emails are stored as local previews in the automation logs so the complete workflow can be tested safely.

## Production

Use the protected setup wizard at `http://localhost:8000/admin/setup`. Docker, cloud deployment, health checks, backups and logging are covered in `DEPLOYMENT.md`. Complete every item in `PRODUCTION_CHECKLIST.md` before accepting real customers or switching Stripe to live mode.

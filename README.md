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

Local development data is created in `data/sparkles.db`; uploaded photos are saved in `data/uploads/`.

## Production database

For Railway production, use Railway PostgreSQL so customer bookings, payments, cleaners and AI conversations survive redeploys.

Local development keeps using SQLite automatically when `DATABASE_URL` is blank. Production switches to PostgreSQL when `DATABASE_URL` starts with `postgres://` or `postgresql://`.

Safe migration from an existing SQLite deployment:

1. Export or copy the current `sparkles.db` before changing production variables.
2. Add Railway PostgreSQL to the project.
3. Set the app service `DATABASE_URL` to the Railway PostgreSQL connection string.
4. Run:

```powershell
$env:DATABASE_URL="postgresql://..."
python migrate_sqlite_to_postgres.py --source path\to\sparkles.db
```

5. Redeploy and verify `/admin/diagnostics` shows PostgreSQL-backed tables with live row counts.

Do not run production on Railway's ephemeral filesystem without either PostgreSQL or a Railway Volume.

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

Completing a job creates and finalizes the remaining-balance Stripe invoice when credentials are configured. When Stripe sends `invoice.paid` or `invoice.payment_succeeded`, the app records the balance payment, marks the booking `Paid in Full`, and then sends the review request.

## Automated workflow

The automation engine runs inside the server and is monitored at `http://localhost:8000/admin/automations`. It queues quote emails, cleaner offers, confirmations, 24-hour reminders, final invoices and review requests. Failed jobs retry with exponential backoff and can also be retried manually.

For Railway production email, use Resend: set `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, and `EMAIL_FROM` to a verified Resend sender such as `Sparkles Cleaning <bookings@sparkles-cleaning-cambridge.co.uk>`. `SMTP_FROM` remains supported as a fallback for older deployments. Existing booking, owner, cleaner, reminder and invoice emails use the same delivery path.

### Facebook recruitment connection

Sparkles Autopilot can prepare, approve, dry-run and publish a recruitment post to the connected Sparkles Facebook Page. Credentials are read from the server environment only and are never returned by the Autopilot API.

Add these variables to the Railway application service:

```text
META_PAGE_ID=your_facebook_page_id
META_PAGE_ACCESS_TOKEN=your_long_lived_page_access_token
META_GRAPH_API_VERSION=v25.0
```

Use a long-lived Page access token with `pages_manage_posts`, `pages_read_engagement` and `pages_show_list`. Do not use a short-lived Graph API Explorer token in production. Keep Facebook Page posting set to **Disabled** and **Dry run** in `/admin/autopilot` until the read-only connection test succeeds. Every draft requires explicit owner approval, and the first live post requires a separate publish confirmation.

SMTP is still available for local/dev providers with `EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM`. Without real email settings, emails are stored as local previews in the automation logs so the complete workflow can be tested safely.

## AI Office Manager

Admins can open `http://localhost:8000/admin/ai-office` to draft customer enquiry replies, ask for missing booking details, generate quotes from Sparkles pricing rules, and send customers to the online booking page. Settings for business hours, pricing, service areas and response text are editable at `http://localhost:8000/admin/ai-office/settings`.

The automation engine also follows up unpaid bookings after 24 hours, confirms deposit payments, sends 24-hour reminders before cleans, and requests reviews after completed jobs.

## AI Receptionist live chat

The booking website includes a mobile-friendly AI Receptionist chat widget. Customer conversations are saved in the database, quotes use the same Sparkles pricing rules, completed chat bookings create normal bookings with Stripe deposit links, and admins can review or take over chats at `http://localhost:8000/admin/receptionist`.

## Production

Use the protected setup wizard at `http://localhost:8000/admin/setup`. Docker, cloud deployment, health checks, backups and logging are covered in `DEPLOYMENT.md`. Complete every item in `PRODUCTION_CHECKLIST.md` before accepting real customers or switching Stripe to live mode.

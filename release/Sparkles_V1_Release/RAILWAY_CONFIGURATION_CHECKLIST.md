# Railway Configuration Checklist

## Project

- Railway project exists.
- Web service is connected to GitHub.
- Latest branch is deployed.
- Public production URL is active.
- Railway PostgreSQL database is attached.

## Variables

Confirm these are present:

- `DATABASE_URL`
- `PUBLIC_URL`
- `ADMIN_SETUP_TOKEN`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- Email provider variables:
  - Resend: `EMAIL_PROVIDER`, `RESEND_API_KEY`, `EMAIL_FROM`
  - or SendGrid: `EMAIL_PROVIDER`, `SENDGRID_API_KEY`, `EMAIL_FROM`

## Networking

- App is reachable over HTTPS.
- Stripe webhook points to the Railway HTTPS URL.
- Email provider API is reachable from Railway.
- Do not rely on outbound SMTP if Railway blocks it.

## Storage

- Production business records must use PostgreSQL via `DATABASE_URL`.
- Do not rely on Railway ephemeral filesystem for bookings, cleaners, payments, or AI conversations.
- Uploaded files should be reviewed before heavy production use. For long-term production file storage, use object storage.

## Deploy verification

- `/health` works.
- Admin login works.
- Booking page works.
- Stripe Checkout opens.
- Stripe webhook updates payment status.
- Email test succeeds.
- Diagnostics page shows the expected database/source.


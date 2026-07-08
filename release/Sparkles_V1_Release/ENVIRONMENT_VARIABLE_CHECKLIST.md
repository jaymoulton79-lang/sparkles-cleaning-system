# Environment Variable Checklist

Store real values in Railway, not in GitHub.

## Core app

- `PUBLIC_URL`
- `DATABASE_URL`
- `ADMIN_SETUP_TOKEN`
- `BOOTSTRAP_ADMIN_EMAIL`
- `BOOTSTRAP_ADMIN_PASSWORD`

## Stripe

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`

## Email

Use the provider configured for production.

### Resend

- `EMAIL_PROVIDER=resend`
- `RESEND_API_KEY`
- `EMAIL_FROM`

### SendGrid

- `EMAIL_PROVIDER=sendgrid`
- `SENDGRID_API_KEY`
- `EMAIL_FROM`

### SMTP fallback/local only

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

## Business settings

These may be stored through the setup page or environment variables depending on deployment:

- `COMPANY_NAME`
- `COMPANY_EMAIL`
- `COMPANY_PHONE`
- `BUSINESS_ADDRESS`
- `SERVICE_AREA`

## Safety checklist

- Never commit real secret values.
- Store secrets in Railway variables.
- Also store a copy in a secure password manager.
- Rotate keys if they were ever pasted into chat, logs, screenshots, or Git.


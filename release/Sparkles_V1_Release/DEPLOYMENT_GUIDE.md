# Sparkles OS Deployment Guide

## Production platform

Sparkles OS is designed to run on Railway using:

- Docker deployment from GitHub.
- Railway PostgreSQL for production data.
- Railway environment variables for secrets.
- Stripe for payments.
- Resend or SendGrid for email delivery.

## Deployment steps

1. Push the latest code to GitHub.
2. Open Railway.
3. Create or open the Sparkles Cleaning System service.
4. Connect the service to the GitHub repository.
5. Add a Railway PostgreSQL database.
6. Add all required environment variables.
7. Deploy the service.
8. Open the live URL.
9. Complete the Sparkles setup/admin login flow if needed.
10. Test one full booking journey.

## Required Railway service settings

- Build method: Dockerfile.
- Public URL: enabled.
- Production database: Railway PostgreSQL.
- Writable SQLite storage should not be used for production data.
- `DATABASE_URL` must be present for production.

## Health check

After deployment, check:

```text
/health
```

Expected result: a healthy JSON response from the application.

## Post-deployment smoke test

1. Open the Sparkles Booking Centre.
2. Submit a test booking.
3. Pay the Stripe test deposit.
4. Confirm the booking appears in the Owner Command Centre.
5. Assign a cleaner.
6. Log in as the cleaner.
7. Accept, start, and complete the job.
8. Confirm the final invoice/payment flow.
9. Confirm emails are recorded/sent.
10. Confirm dashboard metrics update.


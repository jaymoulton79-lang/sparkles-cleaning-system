# Restore Instructions

Use these steps if Sparkles OS needs to be restored on a new machine or redeployed.

## Restore source code

1. Unzip the Sparkles V1 Release backup.
2. Open the source code folder.
3. Confirm these files exist:
   - `server.py`
   - `public/`
   - `Dockerfile`
   - `README.md`
   - `DEPLOYMENT.md`
   - `.env.example`
4. Open the folder in your editor or push it back to GitHub.

## Restore production deployment

1. Create/open the Railway project.
2. Connect the GitHub repository.
3. Add a Railway PostgreSQL database.
4. Add all environment variables from the environment checklist.
5. Deploy the app.
6. Open `/health`.
7. Log into the admin area.

## Restore database

If you have a SQL backup:

```bash
psql "$DATABASE_URL" < sparkles_v1_backup.sql
```

Only restore into the correct database. Restoring into the wrong database can overwrite live data.

## Restore Stripe

1. Add `STRIPE_SECRET_KEY`.
2. Add `STRIPE_WEBHOOK_SECRET`.
3. Confirm webhook URL points to the new live app URL.
4. Send a test webhook or make a test booking/payment.

## Restore email

1. Add Resend or SendGrid variables.
2. Confirm sender/domain verification.
3. Send a test email.
4. Create a booking and confirm customer/owner/cleaner emails work.

## Final smoke test

1. Submit booking.
2. Pay deposit.
3. Confirm owner dashboard booking.
4. Assign cleaner.
5. Cleaner accepts, starts, completes.
6. Confirm invoice/final payment flow.
7. Confirm emails and dashboard metrics.


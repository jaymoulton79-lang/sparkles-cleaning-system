# Database Backup Instructions

Production data should be stored in Railway PostgreSQL using `DATABASE_URL`.

## What to back up

Back up all business data, including:

- Bookings.
- Cleaners.
- Cleaner applicants.
- Payments.
- Stripe payment records.
- AI conversations.
- Automation jobs/logs.
- Booking timelines.
- Settings.

## Railway PostgreSQL backup options

### Option 1: Railway dashboard

1. Open Railway.
2. Open the Sparkles project.
3. Open the PostgreSQL database service.
4. Use Railway backup/export tools if available on the plan.
5. Download and store the backup securely.

### Option 2: `pg_dump`

Use `pg_dump` from a trusted machine that has access to the database.

Example:

```bash
pg_dump "$DATABASE_URL" > sparkles_v1_backup.sql
```

If using PowerShell:

```powershell
pg_dump $env:DATABASE_URL > sparkles_v1_backup.sql
```

## Backup frequency

Recommended minimum:

- Daily during launch testing.
- Weekly once stable.
- Before every major deployment.

## Where to store backups

- Secure cloud storage.
- Password manager or encrypted vault for credentials.
- External drive or memory stick for offline copy.

Do not store raw database backups in a public GitHub repository.


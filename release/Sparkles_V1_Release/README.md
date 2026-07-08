# Sparkles V1 Release Backup Package

This folder documents the Sparkles V1 Release backup.

The complete release ZIP should contain:

- Source code
- README
- Deployment guide
- Environment variable checklist
- Railway configuration checklist
- Stripe webhook checklist
- SendGrid/Resend configuration notes
- Database backup instructions
- Restore instructions
- `VERSION_1_RELEASE.md`

## What this backup is for

Use this package if you need to:

- Keep a copy of the launch version.
- Move the project to another computer.
- Restore the application after a problem.
- Redeploy Sparkles OS to Railway.
- Hand the system to another developer.

## What is not included

Private production secrets are not included in the source code backup.

You must separately save:

- Railway environment variables.
- Railway PostgreSQL credentials or backup.
- Stripe secret key and webhook secret.
- Resend/SendGrid API key.
- Admin login details.
- Domain/DNS provider login details.

## Recommended storage

Keep at least three copies:

1. GitHub repository.
2. Local ZIP backup.
3. Memory stick or external drive backup.

For real business use, also keep a secure cloud backup.


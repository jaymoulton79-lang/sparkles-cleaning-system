# Sparkles Cleaning Cambridge Project Simplification Audit

Date: 2026-07-10

Purpose: make the project easier to use and easier to maintain without breaking bookings, payments, cleaners, emails or launch activity.

---

## The simple product we should keep

The money-making flow is:

1. Customer books a clean.
2. Customer pays 25% deposit.
3. Booking appears in admin.
4. Cleaner is assigned.
5. Cleaner completes job.
6. Final balance invoice is paid.
7. Review/follow-up happens.
8. Cleaner recruitment keeps supply growing.

Everything should support that loop.

---

## Core pages to keep visible

These should stay in the main navigation:

- Launch Console
- Bookings
- Applicants
- AI Recruitment
- Cleaners

These are the daily operating pages.

---

## Core files/features to keep

Do not remove these:

- `server.py`
- `automation.py`
- `public/index.html`
- `public/app.js`
- `public/admin.html`
- `public/admin.js`
- `public/owner-dashboard.html`
- `public/owner-dashboard.js`
- `public/launch-console.html`
- `public/launch-console.js`
- `public/cleaner-dashboard.html`
- `public/cleaner-dashboard.js`
- `public/cleaner-login.html`
- `public/cleaner-login.js`
- `public/cleaner-apply.html`
- `public/cleaner-apply.js`
- `public/cleaner-applicants-admin.html`
- `public/cleaner-applicants-admin.js`
- `public/cleaners-admin.html`
- `public/cleaners-admin.js`
- `public/payment-success.html`
- `public/payment-success.js`
- `public/quote.html`
- `public/quote.js`
- `public/reset-password.html`
- `public/reset-password.js`
- `public/setup.html`
- `public/setup.js`
- `Dockerfile`
- `requirements.txt`
- `migrate_sqlite_to_postgres.py`
- `.env.example`

---

## Advanced pages to keep, but hide from daily navigation

These are useful, but they do not need to be in the main daily nav:

- Calendar
- Automations
- Sparkles AI
- Sparkles AI Receptionist
- Diagnostics
- Emergency reset
- AI Office settings

They are still available by direct URL if needed.

Reason: they add visual noise while launching. The business needs customers, cleaners and payments first.

---

## Files/folders that make the project look more complex than it is

### `release/`

The `release/` folder contains full backup copies of the source code.

This is useful as a backup, but it does not need to live inside the active app repository forever.

Recommendation:

- Keep a copy on your USB stick.
- Keep a copy in cloud storage if wanted.
- Later, remove `release/` from the active repo and add `release/` to `.gitignore`.

Do not remove it until you are happy your V1 backup exists somewhere safe.

---

## Safe simplifications already made

- Removed one duplicated `sync_paid_balance_invoices` function in `server.py`.
- Simplified main admin navigation on the core launch pages.
- Kept advanced/debug pages available by URL instead of deleting them.

---

## What not to simplify yet

Do not remove these during launch testing:

- Stripe deposit flow
- Stripe final balance flow
- Email provider logic
- Cleaner portal
- Cleaner assignment
- PostgreSQL support
- Password reset/authentication
- Booking timeline
- Payment history
- Webhook handling

These are boring but important. They protect the business.

---

## Suggested next cleanup phase

After the first few real paid bookings:

1. Move `release/` outside the active repo.
2. Remove old unused branding assets if confirmed unused.
3. Split `server.py` into smaller files:
   - auth
   - bookings
   - payments
   - cleaners
   - recruitment
   - dashboard
4. Keep only Launch Console as the main operating page.

Do this only after launch flow is proven with real bookings.


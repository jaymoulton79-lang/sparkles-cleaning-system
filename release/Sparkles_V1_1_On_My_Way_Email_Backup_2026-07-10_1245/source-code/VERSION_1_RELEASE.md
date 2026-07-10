# Sparkles V1 Release

Release name: Sparkles V1 Release  
Application name: Sparkles OS  
Business: Sparkles Cleaning Cambridge  
Slogan: Smiles Come Standard.

## Release status

Sparkles V1 is the first production-ready release of the Sparkles OS cleaning agency system.

This release includes the customer booking journey, owner/admin management tools, cleaner portal, Stripe payment flow, email delivery support, automation timeline, production deployment support, and launch diagnostics.

## Completed in V1

### Customer booking

- Sparkles Booking Centre customer booking form.
- Customer details, address, postcode, clean type, bedrooms, bathrooms, preferred date/time, notes, and photo upload support.
- Automatic quote/deposit flow.
- Stripe Checkout deposit link creation.
- Payment success handling.
- Customer-facing success page.

### Owner/admin area

- Sparkles Owner Command Centre.
- Secure admin login.
- Bookings management.
- Cleaner management.
- Cleaner applicant review.
- Assign cleaner flow.
- Payment status display.
- Booking timeline and automation logs.
- Diagnostics page for production checks.
- Backup/export support.

### Cleaner workflow

- Sparkles Cleaner Portal.
- Cleaner login.
- Cleaner account creation/approval workflow.
- Assigned jobs view.
- Accept/reject job.
- Mark job started.
- Mark job completed.
- Before/after photos and cleaner notes.
- Owner timeline updates.

### Payments

- Stripe Checkout deposit workflow.
- Stripe webhook support.
- Payment status tracking.
- Deposit paid vs balance due separation.
- Final balance payment guard so a missing, blank, null, or zero Stripe amount cannot mark a booking as paid in full.

### Email

- Branded Sparkles OS HTML emails.
- Customer booking confirmation.
- Owner notification.
- Cleaner assignment email.
- Email provider support for Resend/SendGrid-style API delivery.
- SMTP fallback support for local/dev use.

### AI and automation

- Sparkles AI admin area.
- AI receptionist/chat support.
- Conversation history.
- Booking follow-up/reminder style automation.
- Automation logs and retry visibility.

### Production readiness

- Dockerfile.
- Railway deployment support.
- Environment variable setup.
- Health check endpoint.
- Logging.
- Production checklist.
- PostgreSQL support via `DATABASE_URL`.
- SQLite remains available for local development.

### Branding

- Rebranded as Sparkles OS.
- Main areas renamed:
  - Sparkles Booking Centre
  - Sparkles Owner Command Centre
  - Sparkles AI
  - Sparkles Cleaner Portal
- Electric blue brand colour `#1677FF`.
- Dark slate `#0F172A`.
- Rounded SaaS-style cards, soft shadows, branded buttons, transitions, loading states, and favicon support.

## Not included in V1

- Multi-company SaaS tenancy.
- Cleaner payroll.
- Native mobile apps.
- Advanced route optimisation.
- Accounting software integration.
- Live production secret values inside the repository.

## Important production note

This backup does not include private secrets such as Stripe keys, SendGrid/Resend API keys, Railway database credentials, admin passwords, or setup tokens.

Those must be exported from Railway and stored separately in a secure password manager.


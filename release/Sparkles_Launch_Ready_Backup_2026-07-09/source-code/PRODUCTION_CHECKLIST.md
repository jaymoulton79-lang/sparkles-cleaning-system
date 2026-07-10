# Production checklist

## Security

- [ ] Generate and configure a strong `ADMIN_SETUP_TOKEN`.
- [ ] Store Stripe, SMTP and setup secrets in the cloud secret manager.
- [ ] Confirm `.env`, database files and uploaded photos are not committed.
- [ ] Serve the application through HTTPS only.
- [ ] Restrict `/admin/*` with an identity-aware proxy or VPN before launch.
- [ ] Configure firewall rules so only the reverse proxy can reach port 8000.

## Company and customer experience

- [ ] Complete `/admin/setup` with legal company details and business address.
- [ ] Upload the approved company logo.
- [ ] Test quote, confirmation, reminder, invoice and review email copy.
- [ ] Add privacy policy, terms, cancellation policy and contact information.
- [ ] Confirm pricing and deposit rules with the business owner.

## Payments

- [ ] Complete the full workflow with Stripe test card `4242 4242 4242 4242`.
- [ ] Verify `checkout.session.completed` and `invoice.paid` webhooks.
- [ ] Confirm duplicate webhook delivery does not duplicate payment history.
- [ ] Confirm refund, cancellation and disputed-payment operating procedures.
- [ ] Replace test keys only after test-mode sign-off.

## Email and automation

- [ ] Verify SPF, DKIM and DMARC for the sending domain.
- [ ] Confirm SMTP delivery from the production server.
- [ ] Test cleaner acceptance, automatic assignment and double-booking prevention.
- [ ] Verify a 24-hour reminder in a staging environment.
- [ ] Force one workflow failure and confirm automatic and manual retry behavior.

## Infrastructure

- [ ] Mount a persistent volume at `/app/data`.
- [ ] Configure `/healthz` and `/readyz` probes.
- [ ] Configure daily encrypted backups and test a restore.
- [ ] Send JSON stdout logs to the cloud logging service.
- [ ] Alert on failed health checks, HTTP 500s and failed automation jobs.
- [ ] Keep the service at one replica while using SQLite and the embedded worker.
- [ ] Document rollback steps and the previous known-good image tag.

## Launch

- [ ] Run a mobile and desktop smoke test.
- [ ] Place a real low-value booking and verify the full lifecycle.
- [ ] Confirm support ownership for payment, cleaner and customer issues.
- [ ] Record the launch time, deployed image version and configuration owner.

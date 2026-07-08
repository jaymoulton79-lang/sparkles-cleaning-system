# SendGrid and Resend Configuration Notes

Sparkles OS supports API-based email delivery for production.

Railway may block outbound SMTP, so production should use Resend or SendGrid API delivery instead of Gmail SMTP.

## Resend

Recommended variables:

- `EMAIL_PROVIDER=resend`
- `RESEND_API_KEY`
- `EMAIL_FROM=bookings@sparkles-cleaning-cambridge.co.uk`

Checklist:

- Domain is verified in Resend.
- Sender address is allowed by Resend.
- API key is active.
- `EMAIL_FROM` matches a verified sender/domain.
- Test email sends from the live admin diagnostics or email test tool.

## SendGrid

Recommended variables:

- `EMAIL_PROVIDER=sendgrid`
- `SENDGRID_API_KEY`
- `EMAIL_FROM=bookings@sparkles-cleaning-cambridge.co.uk`

Checklist:

- Sender identity is verified.
- Domain authentication is complete where possible.
- API key has mail send permissions.
- `EMAIL_FROM` matches the verified sender/domain.
- Test email sends from production.

## Emails used by V1

- Customer booking confirmation.
- Owner booking notification copy.
- Cleaner assignment email.
- Quote/deposit/follow-up automation emails.
- Reminder and review-request style workflow emails.

## If emails fail

Check:

1. Railway variables are present.
2. Provider API key is valid.
3. Sender address is verified.
4. Provider response body for exact error.
5. Railway logs for application-side errors.


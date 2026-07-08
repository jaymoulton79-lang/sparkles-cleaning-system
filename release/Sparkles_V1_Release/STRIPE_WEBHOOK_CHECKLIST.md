# Stripe Webhook Checklist

## Required webhook endpoint

Use the production Railway URL:

```text
https://YOUR-RAILWAY-APP.up.railway.app/api/stripe/webhook
```

Replace the domain with the actual Sparkles OS Railway URL.

## Events to send

Enable these Stripe events:

- `checkout.session.completed`
- `invoice.paid`
- `invoice.payment_succeeded`

## Required Railway variables

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `PUBLIC_URL`

## Test checklist

1. Create a booking.
2. Open Stripe Checkout.
3. Pay the 25% deposit using Stripe test card.
4. Confirm booking payment status becomes `Balance Due`.
5. Confirm payment history shows Deposit = Paid.
6. Confirm Balance is not marked paid after invoice generation.
7. Pay the final balance.
8. Confirm payment status becomes `Paid in Full`.
9. Confirm payment history shows Deposit = Paid and Balance = Paid.

## Important guard

The final balance must only be marked paid after Stripe confirms a real paid amount.

Missing, blank, null, or zero `amount_paid` must never count as final balance payment.


async function verify() {
  const box = document.querySelector('#paymentResult');
  const session = new URLSearchParams(location.search).get('session_id');

  try {
    const r = await fetch(`/api/payments/verify?session_id=${encodeURIComponent(session || '')}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'Payment could not be confirmed.');

    const label = data.payment_type === 'deposit' ? 'Deposit paid' : 'Balance paid';
    box.innerHTML = `
      <div class="customer-flow-logo"><img src="/assets/sparkles-premium-logo.jpg" alt="Sparkles Cleaning Agency logo"></div>
      <div class="success-icon">Success</div>
      <h1>${label}</h1>
      <p>Thank you. Your payment has been confirmed and saved against your Sparkles booking.</p>
      <p class="payment-note">Smiles Come Standard.</p>
      <a class="sp-button" href="/">Back to Sparkles Booking Centre</a>`;
  } catch (e) {
    box.innerHTML = `
      <div class="customer-flow-logo"><img src="/assets/sparkles-premium-logo.jpg" alt="Sparkles Cleaning Agency logo"></div>
      <div class="flow-status flow-warning">Payment check in progress</div>
      <h1>We're checking your payment</h1>
      <p>We couldn't confirm the payment instantly, but your booking can still update automatically once Stripe confirms it.</p>
      <p class="payment-note">If money has left your account, please don't try again. We'll keep checking safely in the background.</p>
      <a class="sp-button sp-button-ghost" href="/">Back to Sparkles Booking Centre</a>`;
  }
}

function escapeHtml(value) {
  const d = document.createElement('div');
  d.textContent = value || '';
  return d.innerHTML;
}

verify();

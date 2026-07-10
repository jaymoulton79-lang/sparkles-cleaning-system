document.head.insertAdjacentHTML('beforeend', '<link rel="stylesheet" href="/payments.css">');

const form = document.querySelector('#bookingForm');
const alertBox = document.querySelector('#alert');
const submit = document.querySelector('#submit');
const files = document.querySelector('#files');
const photos = document.querySelector('#photos');
const date = document.querySelector('#preferred_date');
const prices = {
  'Regular clean': { base: 5500, bedroom_extra: 1400, bathroom_extra: 1000 },
  'Deep clean': { base: 9500, bedroom_extra: 1800, bathroom_extra: 1300 },
  'End of tenancy': { base: 14500, bedroom_extra: 2400, bathroom_extra: 1700 },
  'One-off clean': { base: 7500, bedroom_extra: 1600, bathroom_extra: 1100 }
};
const money = p => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(p / 100);

date.min = new Date().toISOString().split('T')[0];
showPaymentReturnNotice();
submit.insertAdjacentHTML('beforebegin', '<div class="quote-box sp-card"><div><strong>Estimated cleaning total</strong><span>25% deposit due now via secure Stripe Checkout</span></div><div class="quote-price"><b id="quoteTotal">—</b><small id="quoteDeposit">Choose your clean details</small></div></div>');

function updateQuote() {
  const type = form.clean_type.value;
  const beds = Number(form.bedrooms.value);
  const baths = Number(form.bathrooms.value);
  if (!type || form.bedrooms.value === '' || !baths) {
    document.querySelector('#quoteTotal').textContent = '—';
    document.querySelector('#quoteDeposit').textContent = 'Choose your clean details';
    return;
  }
  const rule = prices[type];
  const total = rule.base + Math.max(0, beds - 1) * rule.bedroom_extra + Math.max(0, baths - 1) * rule.bathroom_extra;
  document.querySelector('#quoteTotal').textContent = money(total);
  document.querySelector('#quoteDeposit').textContent = `${money(Math.round(total * .25))} deposit`;
}

[form.clean_type, form.bedrooms, form.bathrooms].forEach(el => el.addEventListener('change', updateQuote));
photos.addEventListener('change', () => {
  files.textContent = photos.files.length ? `${photos.files.length} photo${photos.files.length === 1 ? '' : 's'} selected: ${[...photos.files].map(f => f.name).join(', ')}` : '';
});

form.addEventListener('submit', async e => {
  e.preventDefault();
  alertBox.className = 'alert';
  submit.disabled = true;
  submit.textContent = 'Creating secure payment link…';
  const firstName = escapeHtml(capitaliseName(form.name.value.split(' ')[0] || 'there'));
  try {
    const response = await fetch('/api/bookings', { method: 'POST', body: new FormData(form) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Something went wrong.');
    const paymentPanel = result.checkout_url
      ? `<a class="sp-button pay-button" href="${escapeHtml(result.checkout_url)}">Pay 25% deposit securely</a><p class="fine">You’ll be taken to Stripe Checkout. Your booking stays as Deposit Due until payment succeeds.</p>`
      : `<div class="alert error show">Your booking was saved, but the secure deposit link could not be created just now. Please contact Sparkles Cleaning Agency and we’ll help you complete the deposit.</div>`;
    document.querySelector('#formCard').innerHTML = `
      <div class="success booking-success-panel">
        <div class="customer-flow-logo"><img src="/assets/sparkles-premium-logo.jpg" alt="Sparkles Cleaning Agency logo"></div>
        <div class="success-icon">Success</div>
        <h2>Sparkles booking received, ${firstName}.</h2>
        <p>Smiles Come Standard. Your quote is ready — pay the 25% deposit to confirm your booking.</p>
        <p class="ref">${escapeHtml(result.reference)}</p>
        <div class="success-summary">
          <div><span>Total</span><strong>${money(result.total_amount)}</strong></div>
          <div><span>Deposit</span><strong>${money(result.deposit_amount)}</strong></div>
          <div><span>Status</span><strong>${escapeHtml(result.payment_status)}</strong></div>
        </div>
        ${paymentPanel}
      </div>`;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (error) {
    alertBox.textContent = error.message;
    alertBox.className = 'alert error';
    alertBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } finally {
    submit.disabled = false;
    submit.textContent = 'Book your clean';
  }
});

function escapeHtml(value) {
  const d = document.createElement('div');
  d.textContent = value || '';
  return d.innerHTML;
}

function capitaliseName(value) {
  return String(value || '')
    .trim()
    .split(/([\s-]+)/)
    .map(part => /^[A-Za-z]/.test(part) ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : part)
    .join('');
}

function showPaymentReturnNotice() {
  const params = new URLSearchParams(location.search);
  if (params.get('payment') !== 'cancelled') return;
  alertBox.innerHTML = '<strong>Payment not completed.</strong><br>Your booking is still saved as Deposit Due. You can complete the secure Stripe deposit whenever you are ready.';
  alertBox.className = 'alert warning show';
}

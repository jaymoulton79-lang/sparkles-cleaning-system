document.head.insertAdjacentHTML('beforeend', '<link rel="stylesheet" href="/payments.css">');

const form = document.querySelector('#bookingForm');
const alertBox = document.querySelector('#alert');
const submit = document.querySelector('#submit');
const files = document.querySelector('#files');
const photos = document.querySelector('#photos');
const date = document.querySelector('#preferred_date');
const prices = {
  'Regular clean': { base: 5700, bedroom_extra: 1000, bathroom_extra: 1000 },
  'Deep clean': { base: 9700, bedroom_extra: 2000, bathroom_extra: 1000 },
  'End of tenancy': { base: 15700, bedroom_extra: 3000, bathroom_extra: 2000 },
  'One-off clean': { base: 7700, bedroom_extra: 2000, bathroom_extra: 1000 }
};
const money = p => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(p / 100);
const priceEnding7 = amount => {
  let pounds = Math.max(0, Math.ceil(Number(amount || 0) / 100));
  const remainder = pounds % 10;
  pounds += remainder <= 7 ? 7 - remainder : 17 - remainder;
  return pounds * 100;
};

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
  const total = priceEnding7(rule.base + Math.max(0, beds - 1) * rule.bedroom_extra + Math.max(0, baths - 1) * rule.bathroom_extra);
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
  const customer = {
    name: form.name.value.trim(),
    phone: form.phone.value.trim(),
    email: form.email.value.trim()
  };
  const firstName = escapeHtml(capitaliseName(customer.name.split(' ')[0] || 'there'));
  try {
    const response = await fetch('/api/bookings', { method: 'POST', body: new FormData(form) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Something went wrong.');
    renderBookingSuccess(result, customer, firstName);
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

function renderBookingSuccess(result, customer, firstName) {
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
      ${customerAccountPanel(customer)}
    </div>`;
  bindCustomerAccountForm(customer);
}

function customerAccountPanel(customer) {
  return `
    <section class="post-booking-account sp-card">
      <div>
        <p class="sp-kicker">Customer Portal</p>
        <h3>Create your account to manage this booking</h3>
        <p>Set a password now and next time you can log in to view this booking, check payment status and pay any remaining balance.</p>
      </div>
      <form id="postBookingAccountForm">
        <input type="hidden" name="name" value="${escapeAttr(customer.name)}">
        <input type="hidden" name="phone" value="${escapeAttr(customer.phone)}">
        <label>Email</label>
        <input name="email" type="email" value="${escapeAttr(customer.email)}" autocomplete="email" required>
        <label>Create password</label>
        <input name="password" type="password" minlength="8" autocomplete="new-password" required placeholder="At least 8 characters">
        <button class="sp-button" type="submit">Create customer account</button>
        <p class="fine">Already have an account? <a href="/customer">Log in to Customer Portal</a></p>
        <div id="postBookingAccountAlert" class="account-alert"></div>
      </form>
    </section>`;
}

function bindCustomerAccountForm(customer) {
  const accountForm = document.querySelector('#postBookingAccountForm');
  const accountAlert = document.querySelector('#postBookingAccountAlert');
  if (!accountForm) return;
  accountForm.addEventListener('submit', async event => {
    event.preventDefault();
    const button = accountForm.querySelector('button');
    button.disabled = true;
    button.textContent = 'Creating account…';
    accountAlert.className = 'account-alert';
    accountAlert.textContent = '';
    try {
      const payload = Object.fromEntries(new FormData(accountForm));
      payload.name = payload.name || customer.name;
      payload.phone = payload.phone || customer.phone;
      const response = await fetch('/api/customer/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 409) {
          accountAlert.innerHTML = 'An account already exists for this email. <a href="/customer">Log in to view your booking.</a>';
          accountAlert.className = 'account-alert warning';
          return;
        }
        throw new Error(data.error || 'Could not create your account.');
      }
      accountAlert.innerHTML = 'Account created. <a href="/customer">Open Customer Portal</a>';
      accountAlert.className = 'account-alert success';
      button.textContent = 'Account created';
    } catch (error) {
      accountAlert.textContent = error.message;
      accountAlert.className = 'account-alert error';
      button.disabled = false;
      button.textContent = 'Create customer account';
    }
  });
}

function escapeHtml(value) {
  const d = document.createElement('div');
  d.textContent = value || '';
  return d.innerHTML;
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('"', '&quot;');
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

const token = new URLSearchParams(location.search).get('token');
const card = document.querySelector('#quoteCard');
const money = p => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(p / 100);
let quote;

async function loadQuote() {
  try {
    const r = await fetch(`/api/quotes/${encodeURIComponent(token || '')}`);
    quote = await r.json();
    if (!r.ok) throw new Error(quote.error);

    card.innerHTML = `
      <div class="customer-flow-logo"><img src="/assets/sparkles-premium-logo.jpg" alt="Sparkles Cleaning logo"></div>
      <div class="eyebrow">Your Sparkles Quote</div>
      <h1>${money(quote.total_amount)}</h1>
      <p>Hello ${escapeHtml(quote.name)}. Here’s your tailored Sparkles quote. Smiles Come Standard.</p>
      <div class="accept-summary">
        <div><span>Service</span><strong>${escapeHtml(quote.clean_type)}</strong></div>
        <div><span>Date</span><strong>${escapeHtml(quote.preferred_date)}</strong></div>
        <div><span>Deposit today</span><strong>${money(quote.deposit_amount)}</strong></div>
        <div><span>Remaining balance</span><strong>${money(quote.balance_amount)}</strong></div>
      </div>
      <div class="engine-note">Accepting opens Stripe’s secure checkout. Your booking remains Deposit Due until Stripe confirms payment.</div>
      <div class="accept-actions">
        <button class="sp-button" id="acceptQuote">Accept quote & pay deposit</button>
        <a class="sp-button sp-button-ghost" href="/">Not yet</a>
      </div>`;
    document.querySelector('#acceptQuote').onclick = acceptQuote;
  } catch (e) {
    card.innerHTML = `
      <div class="customer-flow-logo"><img src="/assets/sparkles-premium-logo.jpg" alt="Sparkles Cleaning logo"></div>
      <div class="flow-status flow-error">Quote unavailable</div>
      <h1>We couldn’t load this quote.</h1>
      <p>${escapeHtml(e.message || 'Please return to the Booking Centre and try again.')}</p>
      <a class="sp-button" href="/">Back to Sparkles Booking Centre</a>`;
  }
}

async function acceptQuote() {
  const b = document.querySelector('#acceptQuote');
  b.disabled = true;
  b.textContent = 'Opening secure payment…';
  const r = await fetch(`/api/quotes/${encodeURIComponent(token)}/accept`, { method: 'POST' });
  const data = await r.json();
  if (data.url) location.href = data.url;
  else {
    b.disabled = false;
    b.textContent = 'Try again';
    alert(data.error || 'Could not open payment.');
  }
}

function escapeHtml(value) {
  const d = document.createElement('div');
  d.textContent = value || '';
  return d.innerHTML;
}

loadQuote();

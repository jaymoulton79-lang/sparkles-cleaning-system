const esc = v => { const d = document.createElement('div'); d.textContent = v ?? ''; return d.innerHTML; };
const money = p => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format((p || 0) / 100);
let register = false;
const form = document.querySelector('#loginForm'), alertBox = document.querySelector('#authAlert');

async function readJsonResponse(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('The customer portal took too long to respond. Please refresh and try again.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function setMode() {
  document.querySelectorAll('.register-only').forEach(x => x.style.display = register ? 'flex' : 'none');
  document.querySelectorAll('.register-only input').forEach(input => {
    input.required = register && input.name === 'name';
  });
  form.querySelector('button').textContent = register ? 'Create account' : 'Log in';
  document.querySelector('#toggleMode').textContent = register ? 'Log in instead' : 'Create account instead';
  form.password.autocomplete = register ? 'new-password' : 'current-password';
}

function paymentActions(b) {
  if (b.payment_status === 'Deposit Due' && b.deposit_checkout_url) {
    return `<a class="pay-button customer-pay-button" href="${esc(b.deposit_checkout_url)}" target="_blank" rel="noopener">Pay deposit</a>`;
  }
  if (b.status === 'Completed' && b.payment_status !== 'Paid in Full' && Number(b.balance_amount || 0) > 0) {
    return `<button class="pay-button customer-pay-button" onclick="startBalancePayment(${Number(b.id)},this)">Pay final balance</button>`;
  }
  return '';
}

function paymentSummary(b) {
  const payment = b.payment_status || 'Deposit Due';
  const deposit = b.deposit_amount ? money(b.deposit_amount) : 'Deposit due';
  const balance = b.balance_amount ? money(b.balance_amount) : 'No balance due';
  return `
    <strong>${esc(payment)}</strong>
    <div class="date-sub">Total ${money(b.total_amount)}</div>
    <div class="date-sub">Deposit ${deposit}</div>
    <div class="date-sub">Balance ${balance}</div>
    ${paymentActions(b)}`;
}

function bookingRow(b) {
  return `<tr>
    <td><strong>${esc(b.reference)}</strong><div class="date-sub">${esc(b.address)}, ${esc(b.postcode)}</div></td>
    <td>${esc(b.clean_type)}<div class="date-sub">${b.bedrooms} bed · ${b.bathrooms} bath</div></td>
    <td>${esc(b.preferred_date)}<div class="date-sub">${esc(b.preferred_time)}</div></td>
    <td><span class="badge">${esc(b.status)}</span>${b.cleaner_name ? `<div class="assigned-to">${esc(b.cleaner_name)}</div>` : ''}</td>
    <td>${paymentSummary(b)}</td>
  </tr>`;
}

async function showPortal() {
  const r = await fetchWithTimeout('/api/customer/bookings', { credentials: 'same-origin', cache: 'no-store' }), bookings = await readJsonResponse(r);
  if (!r.ok) return false;
  const authPanel = document.querySelector('#authPanel');
  const portal = document.querySelector('#portal');
  authPanel.hidden = true;
  authPanel.style.display = 'none';
  portal.hidden = false;
  portal.style.display = 'block';
  document.querySelector('#bookings').innerHTML = bookings.length
    ? `<table><thead><tr><th>Reference</th><th>Clean</th><th>Date</th><th>Status</th><th>Payments</th></tr></thead><tbody>${bookings.map(bookingRow).join('')}</tbody></table>`
    : '<div class="empty">No Sparkles bookings yet. Book with the same email address and they will appear here.</div>';
  portal.scrollIntoView({ block: 'start', behavior: 'smooth' });
  return true;
}

async function startBalancePayment(id, button) {
  button.disabled = true;
  const old = button.textContent;
  button.textContent = 'Opening secure payment...';
  try {
    const r = await fetch(`/api/bookings/${id}/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payment_type: 'balance' })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'Could not open final balance payment.');
    window.open(data.url, '_blank', 'noopener');
  } catch (err) {
    alert(err.message);
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

form.onsubmit = async e => {
  e.preventDefault();
  alertBox.className = 'alert';
  alertBox.textContent = '';
  const endpoint = register ? '/api/customer/register' : '/api/customer/login';
  const button = form.querySelector('button[type="submit"]');
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = register ? 'Creating account...' : 'Logging in...';
  try {
    const payload = Object.fromEntries(new FormData(form));
    const r = await fetchWithTimeout(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }), data = await readJsonResponse(r);
    if (!r.ok) {
      const message = data.error || 'Could not continue.';
      if (!register && /No customer account found/i.test(message)) {
        register = true;
        setMode();
        alertBox.textContent = 'Create your customer account first using the same email as your booking, then your bookings will appear here.';
        alertBox.className = 'alert error';
        return;
      }
      throw new Error(message);
    }
    const opened = await showPortal();
    if (!opened) throw new Error('Login succeeded, but your customer portal session did not load. Please refresh and try again.');
  } catch (err) {
    alertBox.textContent = err.message;
    alertBox.className = 'alert error';
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
};

document.querySelector('#toggleMode').onclick = e => { e.preventDefault(); register = !register; setMode(); };
document.querySelector('#logout').onclick = async () => { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); location.href = '/customer'; };
window.startBalancePayment = startBalancePayment;
setMode();
showPortal();

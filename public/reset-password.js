const params = new URLSearchParams(location.search);
const token = params.get('token');
const role = params.get('role') || (location.pathname.includes('/cleaner/setup') ? 'cleaner' : 'customer');
const alertBox = document.querySelector('#authAlert');
const roleSelect = document.querySelector('#role');

const loginTargets = {
  admin: ['/admin/login', 'Admin login'],
  cleaner: ['/cleaner/login', 'Cleaner Portal login'],
  customer: ['/customer', 'Customer login'],
};

if (roleSelect) roleSelect.value = role;

if (token) {
  document.querySelector('#requestForm').hidden = true;
  document.querySelector('#confirmForm').hidden = false;
  document.querySelector('#resetIntro').textContent =
    role === 'cleaner'
      ? 'Create your Sparkles Cleaner Portal password. This secure setup link can only be used once.'
      : 'Choose a new password for your Sparkles account.';
  document.querySelector('#resetCard h1').textContent = role === 'cleaner' ? 'Create cleaner password' : 'Reset password';
}

document.querySelector('#requestForm').onsubmit = async event => {
  event.preventDefault();
  alertBox.className = 'alert';
  const response = await fetch('/api/auth/password-reset/request', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
  });
  const data = await response.json();
  if (!response.ok) {
    alertBox.textContent = data.error;
    alertBox.className = 'alert error';
    return;
  }
  const extra = data.reset_link ? `<p class="fine">Email preview mode: <a href="${data.reset_link}">open reset link</a></p>` : '';
  document.querySelector('#resetCard').innerHTML = `<div class="success-icon">✓</div><h1>Check your email</h1><p>${data.message}</p>${extra}`;
};

document.querySelector('#confirmForm').onsubmit = async event => {
  event.preventDefault();
  alertBox.className = 'alert';
  const data = Object.fromEntries(new FormData(event.target));
  data.token = token;
  const response = await fetch('/api/auth/password-reset/confirm', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) {
    alertBox.textContent = result.error;
    alertBox.className = 'alert error';
    return;
  }
  const [href, label] = loginTargets[role] || loginTargets.customer;
  document.querySelector('#resetCard').innerHTML = `<div class="success-icon">✓</div><h1>Password updated</h1><p>You can now log in with your new password.</p><a class="pay-button" href="${href}">${label}</a>`;
};

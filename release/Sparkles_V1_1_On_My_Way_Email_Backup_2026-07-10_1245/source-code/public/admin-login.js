const form = document.querySelector('#loginForm');
const alertBox = document.querySelector('#authAlert');

if (new URLSearchParams(location.search).get('expired') === '1') {
  alertBox.textContent = 'Your admin session expired. Please log in again.';
  alertBox.className = 'alert error';
}

form.onsubmit = async event => {
  event.preventDefault();
  alertBox.className = 'alert';
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  button.textContent = 'Logging in…';
  try {
    const payload = Object.fromEntries(new FormData(form));
    delete payload.remember_me;
    const response = await fetch('/api/admin/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Login failed.');
    location.href = '/admin/dashboard';
  } catch (error) {
    alertBox.textContent = error.message;
    alertBox.className = 'alert error';
  } finally {
    button.disabled = false;
    button.textContent = 'Log in';
  }
};

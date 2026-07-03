const form = document.querySelector('#loginForm');
const alertBox = document.querySelector('#authAlert');

if (new URLSearchParams(location.search).get('expired') === '1') {
  alertBox.textContent = 'Your admin session expired. Please log in again.';
  alertBox.className = 'alert error';
}

form.onsubmit = async event => {
  event.preventDefault();
  alertBox.className = 'alert';
  const button = form.querySelector('button');
  button.disabled = true;
  button.textContent = 'Logging in…';
  try {
    const response = await fetch('/api/admin/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(form)))
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

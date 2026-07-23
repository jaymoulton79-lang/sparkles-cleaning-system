const params = new URLSearchParams(location.search);
const source = params.get('source') || 'Website';
const inviteCode = params.get('applicant') || '';
document.querySelector('#sourceInput').value = source;
document.querySelector('#sourceLabel').textContent = source;
document.querySelector('#inviteCodeInput').value = inviteCode;

async function loadPersonalInvite() {
  if (!inviteCode) return;
  const welcome = document.querySelector('#inviteWelcome');
  try {
    const response = await fetch(`/api/recruitment/invites/${encodeURIComponent(inviteCode)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'This invitation is not valid.');
    document.querySelector('#sourceInput').value = 'Indeed';
    document.querySelector('#sourceLabel').textContent = 'Indeed invitation';
    document.querySelector('[name="name"]').value = result.name || '';
    document.querySelector('#inviteWelcomeTitle').textContent = `Welcome, ${result.name || 'cleaner applicant'}`;
    document.querySelector('#inviteWelcomeText').textContent = result.completed
      ? 'Your Sparkles application has already been received. You do not need to submit it again.'
      : `Your personal application reference is ${result.applicant_identifier}. Complete the form below and Sparkles will track your progress automatically.`;
    welcome.hidden = false;
    if (result.completed) document.querySelector('#applyForm').hidden = true;
  } catch (error) {
    document.querySelector('#inviteWelcomeTitle').textContent = 'Invitation needs attention';
    document.querySelector('#inviteWelcomeText').textContent = error.message;
    welcome.hidden = false;
    document.querySelector('#applyForm').hidden = true;
  }
}

function checked(name) {
  return [...document.querySelectorAll(`[data-name="${name}"] input:checked`)].map(input => input.value);
}

function syncHiddenVerification() {
  document.querySelector('#hasOwnVehicle').value = document.querySelector('#ownVehicle').value;
  const rtw = document.querySelector('#rightToWork').value.toLowerCase();
  document.querySelector('#rightToWorkVerified').value = rtw === 'yes' || rtw === 'can provide evidence' ? '1' : '0';
}

document.querySelector('#ownVehicle').addEventListener('change', syncHiddenVerification);
document.querySelector('#rightToWork').addEventListener('change', syncHiddenVerification);
syncHiddenVerification();

document.querySelector('#applyForm').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector('#applyMessage');
  const availability = checked('availability');
  const services = checked('services');

  if (!availability.length) {
    message.textContent = 'Please choose at least one day you are available.';
    message.className = 'form-message error';
    return;
  }
  if (!services.length) {
    message.textContent = 'Please choose at least one service you can offer.';
    message.className = 'form-message error';
    return;
  }

  syncHiddenVerification();
  const data = new FormData(form);
  data.delete('availability');
  data.delete('services');
  availability.forEach(day => data.append('availability', day));
  services.forEach(service => data.append('services', service));
  if (data.get('experience_level')) {
    data.set('experience', `${data.get('experience_level')}\n\n${data.get('experience') || ''}`.trim());
  }

  message.textContent = 'Sending your application...';
  message.className = 'form-message';
  const button = form.querySelector('button[type="submit"]');
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = 'Sending...';
  try {
    const response = await fetch('/api/cleaner-applicants', {
      method: 'POST',
      body: data
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not submit application.');
    form.reset();
    document.querySelector('#sourceInput').value = inviteCode ? 'Indeed' : source;
    document.querySelector('#sourceLabel').textContent = inviteCode ? 'Indeed invitation' : source;
    document.querySelector('#inviteCodeInput').value = inviteCode;
    syncHiddenVerification();
    message.textContent = 'Thanks — your application has been sent. Sparkles Cleaning Cambridge will review it shortly.';
    message.className = 'form-message success';
    if (result.applicant_identifier) {
      message.textContent = `Thanks — your application ${result.applicant_identifier} has been received and scored for owner review.`;
    }
  } catch (error) {
    message.textContent = error.message;
    message.className = 'form-message error';
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
});

loadPersonalInvite();

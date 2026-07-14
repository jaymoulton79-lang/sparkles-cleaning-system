document.head.insertAdjacentHTML('beforeend','<link rel="stylesheet" href="/cleaner.css">');

const esc = value => {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
};
const money = pennies => new Intl.NumberFormat('en-GB', {style: 'currency', currency: 'GBP'}).format((Number(pennies || 0)) / 100);

const days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
const services = ['Regular clean','Deep clean','End of tenancy','One-off clean'];
let cleaners = [];

function initials(name) {
  return String(name || '').split(' ').filter(Boolean).map(x => x[0]).slice(0, 2).join('').toUpperCase() || 'SC';
}

function pillInputs(options, name, selected = []) {
  const chosen = new Set(selected);
  return options.map(option => `<label class="edit-pill">
    <input type="checkbox" name="${esc(name)}" value="${esc(option)}" ${chosen.has(option) ? 'checked' : ''}>
    <span>${esc(option)}</span>
  </label>`).join('');
}

function checkboxGroup(cleaner, field, options) {
  return `<div class="edit-pills" data-cleaner="${cleaner.id}" data-field="${field}">
    ${pillInputs(options, `${field}-${cleaner.id}`, cleaner[field] || [])}
  </div>`;
}

function selectedValues(cleanerId, field) {
  return [...document.querySelectorAll(`[data-cleaner="${cleanerId}"][data-field="${field}"] input:checked`)].map(input => input.value);
}

function createValues(field) {
  return [...document.querySelectorAll(`[data-create-field="${field}"] input:checked`)].map(input => input.value);
}

function showPreviewLink(invite) {
  if (invite?.setup_link) {
    alert(`Email preview mode: send this setup link to the cleaner:\n\n${invite.setup_link}`);
  }
}

async function loadCleaners() {
  try {
    const response = await fetch('/api/cleaners');
    cleaners = await response.json();
    if (!response.ok) throw new Error(cleaners.error || 'Could not load cleaners.');
    const active = cleaners.filter(c => Number(c.active) !== 0);
    document.querySelector('#cleanerTotal').textContent = active.length;
    document.querySelector('#activatedTotal').textContent = cleaners.filter(c => c.activated).length;
    document.querySelector('#pendingTotal').textContent = cleaners.filter(c => !c.activated).length;
    if (!cleaners.length) {
      document.querySelector('#cleanerList').innerHTML = '<div class="empty card-wide"><strong>No Sparkles cleaners yet</strong><br>Invite your first cleaner to begin the beta test.</div>';
      return;
    }
    document.querySelector('#cleanerList').innerHTML = cleaners.map(c => {
      const isActive = Number(c.active) !== 0;
      const activated = Boolean(c.activated);
      return `<article class="cleaner-card ${isActive ? '' : 'inactive'}">
        <div class="cleaner-card-head">
          <div class="avatar">${esc(initials(c.name))}</div>
          <div><h2>${esc(c.name)}</h2><p>${esc(c.postcode)} · ${c.travel_radius} mile radius</p></div>
          <span class="badge ${isActive ? '' : 'muted'}">${isActive ? 'Active' : 'Inactive'}</span>
        </div>
        <div class="rate">£${Number(c.hourly_rate).toFixed(2)} <span>/ hour</span></div>
        <div class="cleaner-meta">
          <div><span>Contact</span>${esc(c.phone)}<br>${esc(c.email)}</div>
          <div><span>Available</span>${(c.availability || []).map(esc).join(', ') || 'Not set'}</div>
          <div><span>Services</span>${(c.services || []).map(esc).join(', ') || 'Not set'}</div>
          <div><span>Account</span>${activated ? 'Activated' : 'Invitation pending'}<br>${activated ? 'Cleaner can log in' : 'Cleaner must create password'}</div>
        </div>
        <details class="cleaner-editor">
          <summary>Edit availability & services</summary>
          <div class="editor-block">
            <label>Working days</label>
            ${checkboxGroup(c, 'availability', days)}
          </div>
          <div class="editor-block">
            <label>Services offered</label>
            ${checkboxGroup(c, 'services', services)}
          </div>
          <button class="row-button" onclick="saveCleanerProfile(${c.id},this)">Save cleaner profile</button>
        </details>
        <div class="checks">
          <span class="${c.dbs_status === 'Verified' ? 'verified' : ''}">DBS: ${esc(c.dbs_status)}</span>
          <span class="${c.insurance_status === 'Verified' ? 'verified' : ''}">Insurance: ${esc(c.insurance_status)}</span>
          <span class="${activated ? 'verified' : ''}">Portal: ${activated ? 'Activated' : 'Pending setup'}</span>
        </div>
        <div class="cleaner-actions">
          <button class="row-button secondary" onclick="sendInvite(${c.id},this)">${activated ? 'Reset / resend invite' : 'Send invitation'}</button>
          <button class="row-button ${isActive ? 'danger' : ''}" onclick="toggleCleaner(${c.id},${isActive ? 0 : 1},this)">${isActive ? 'Deactivate' : 'Reactivate'}</button>
        </div>
      </article>`;
    }).join('');
  } catch (error) {
    document.querySelector('#cleanerList').innerHTML = '<div class="empty card-wide">Could not load cleaners. Please refresh.</div>';
  }
}

async function saveCleanerProfile(id, button) {
  const availability = selectedValues(id, 'availability');
  const chosenServices = selectedValues(id, 'services');
  if (!availability.length) return alert('Choose at least one working day.');
  if (!chosenServices.length) return alert('Choose at least one service.');
  button.disabled = true;
  button.textContent = 'Saving...';
  try {
    const response = await fetch(`/api/cleaners/${id}`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({availability, services: chosenServices})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save cleaner profile.');
    await loadCleaners();
  } catch (error) {
    button.disabled = false;
    button.textContent = 'Save cleaner profile';
    alert(error.message);
  }
}

async function sendInvite(id, button) {
  const cleaner = cleaners.find(c => Number(c.id) === Number(id));
  if (!confirm(`Send a secure setup link to ${cleaner?.name || 'this cleaner'}?`)) return;
  button.disabled = true;
  button.textContent = 'Sending...';
  try {
    const response = await fetch(`/api/cleaners/${id}/invite`, {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not send invitation.');
    showPreviewLink(result.invite);
    alert('Invitation sent.');
    await loadCleaners();
  } catch (error) {
    alert(error.message);
    button.disabled = false;
    button.textContent = 'Send invitation';
  }
}

async function toggleCleaner(id, active, button) {
  if (!confirm(`${active ? 'Reactivate' : 'Deactivate'} this cleaner account? ${active ? 'They will be eligible for future jobs again once activated.' : 'They will not be able to log in or receive new assignments.'}`)) return;
  button.disabled = true;
  button.textContent = active ? 'Reactivating...' : 'Deactivating...';
  try {
    const response = await fetch(`/api/cleaners/${id}`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({active: Boolean(active)})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not update cleaner.');
    await loadCleaners();
  } catch (error) {
    button.disabled = false;
    button.textContent = active ? 'Reactivate' : 'Deactivate';
    alert(error.message);
  }
}

function setupCreatePanel() {
  const panel = document.querySelector('#createCleanerPanel');
  const form = document.querySelector('#createCleanerForm');
  const message = document.querySelector('#createCleanerMessage');
  document.querySelector('[data-create-field="availability"]').innerHTML = pillInputs(days, 'create-availability', ['Friday']);
  document.querySelector('[data-create-field="services"]').innerHTML = pillInputs(services, 'create-services', ['One-off clean', 'Regular clean']);
  document.querySelector('#showCreateCleaner').onclick = () => {
    panel.hidden = false;
    panel.scrollIntoView({behavior: 'smooth', block: 'start'});
  };
  document.querySelector('#cancelCreateCleaner').onclick = () => {
    panel.hidden = true;
    form.reset();
  };
  form.onsubmit = async event => {
    event.preventDefault();
    message.className = 'alert';
    message.textContent = '';
    const availability = createValues('availability');
    const chosenServices = createValues('services');
    if (!availability.length || !chosenServices.length) {
      message.textContent = 'Choose at least one availability day and one service.';
      message.className = 'alert error';
      return;
    }
    const data = Object.fromEntries(new FormData(form));
    data.availability = availability;
    data.services = chosenServices;
    data.send_invite = true;
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    submit.textContent = 'Creating...';
    try {
      const response = await fetch('/api/cleaners', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not create cleaner.');
      showPreviewLink(result.invite);
      message.textContent = 'Cleaner created and invitation sent.';
      message.className = 'alert success';
      form.reset();
      await loadCleaners();
    } catch (error) {
      message.textContent = error.message;
      message.className = 'alert error';
    } finally {
      submit.disabled = false;
      submit.textContent = 'Create & send invitation';
    }
  };
}

async function loadPayouts() {
  const summary = document.querySelector('#payoutSummary');
  const list = document.querySelector('#payoutList');
  if (!summary || !list) return;
  summary.textContent = 'Loading cleaner payouts...';
  list.innerHTML = '';
  try {
    const response = await fetch('/api/cleaner-payouts');
    const payouts = await response.json();
    if (!response.ok) throw new Error(payouts.error || 'Could not load cleaner payouts.');
    const pending = payouts.filter(payout => payout.status === 'Pending');
    const paid = payouts.filter(payout => payout.status === 'Paid');
    const pendingTotal = pending.reduce((total, payout) => total + Number(payout.amount || 0), 0);
    summary.innerHTML = `<strong>${money(pendingTotal)} pending</strong><span>${pending.length} pending · ${paid.length} paid</span>`;
    list.innerHTML = payouts.length ? payouts.map(payout => `
      <article class="payout-card ${payout.status === 'Paid' ? 'paid' : ''}">
        <div>
          <span class="payout-status-pill">${esc(payout.status)}</span>
          <h3>${esc(payout.cleaner_name)} · ${money(payout.amount)}</h3>
          <p>${esc(payout.reference)} · ${esc(payout.customer_name)} · ${esc(payout.clean_type)} · ${esc(payout.preferred_date)} ${esc(payout.preferred_time)}</p>
          <small>${Number(payout.estimated_hours || 0)} hrs × ${money(Number(payout.hourly_rate || 0) * 100)}/hr${payout.paid_at ? ` · Paid ${new Date(payout.paid_at).toLocaleString('en-GB')}` : ''}</small>
        </div>
        ${payout.status === 'Pending' ? `<button class="row-button" onclick="markPayoutPaid(${payout.id},this)">Mark paid</button>` : '<span class="paid-label">Paid</span>'}
      </article>
    `).join('') : '<div class="empty">No cleaner payouts yet. Completed assigned jobs will appear here.</div>';
  } catch (error) {
    summary.textContent = error.message;
    list.innerHTML = '';
  }
}

async function markPayoutPaid(id, button) {
  const note = prompt('Optional note for this cleaner payment:', 'Paid manually by owner') || '';
  if (!confirm('Mark this cleaner payout as paid?')) return;
  button.disabled = true;
  button.textContent = 'Marking paid...';
  try {
    const response = await fetch(`/api/cleaner-payouts/${id}/mark-paid`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({paid_method: 'Manual payment', notes: note})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not mark payout paid.');
    await loadPayouts();
  } catch (error) {
    alert(error.message);
    button.disabled = false;
    button.textContent = 'Mark paid';
  }
}

window.loadCleaners = loadCleaners;
window.saveCleanerProfile = saveCleanerProfile;
window.sendInvite = sendInvite;
window.toggleCleaner = toggleCleaner;
window.loadPayouts = loadPayouts;
window.markPayoutPaid = markPayoutPaid;

setupCreatePanel();
loadCleaners();
loadPayouts();

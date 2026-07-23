const esc = value => { const div = document.createElement('div'); div.textContent = value ?? ''; return div.innerHTML; };
const sourceNames = ['Indeed', 'Facebook', 'WhatsApp', 'Google Business Profile', 'Referral', 'Website', 'Other'];
let applicants = [];
let currentIndeedInvite = null;

function applyUrl(source) {
  return `${location.origin}/become-a-cleaner?source=${encodeURIComponent(source.toLowerCase())}`;
}

function recommendationClass(value) {
  return String(value || '').toLowerCase().replaceAll(' ', '-');
}

function docs(label, files) {
  return files?.length
    ? `<div><strong>${esc(label)}:</strong> <span class="doc-list">${files.map(file => `<a href="${esc(file.url)}" target="_blank" rel="noopener">${esc(file.name)}</a>`).join('')}</span></div>`
    : `<div><strong>${esc(label)}:</strong> Not uploaded</div>`;
}

function renderLinks() {
  document.querySelector('#sourceLinks').innerHTML = sourceNames.map(source => {
    const url = applyUrl(source);
    const whatsappText = encodeURIComponent(`Hi, Sparkles Cleaning Cambridge is hiring cleaners. Apply here: ${url}`);
    return `<article class="source-link">
      <strong>${esc(source)}</strong>
      <input readonly value="${esc(url)}">
      <div class="mini-actions">
        <button onclick="copyLink('${esc(url)}',this)">Copy</button>
        <a href="https://wa.me/?text=${whatsappText}" target="_blank" rel="noopener">Share WhatsApp</a>
      </div>
    </article>`;
  }).join('');
}

async function copyValue(value, button) {
  await navigator.clipboard.writeText(value);
  const old = button.textContent;
  button.textContent = 'Copied';
  setTimeout(() => { button.textContent = old; }, 1200);
}

function copyLink(url, button) {
  return copyValue(url, button);
}

function showIndeedInvite(result) {
  currentIndeedInvite = result;
  document.querySelector('#indeedInviteIdentifier').textContent = result.applicant_identifier;
  document.querySelector('#indeedGeneratedMessage').value = result.message;
  document.querySelector('#openIndeedApplication').href = result.link;
  document.querySelector('#indeedInviteResult').hidden = false;
  document.querySelector('#indeedInviteMessage').textContent = `${result.name}'s tracked invitation is ready. Paste it into Indeed manually.`;
  document.querySelector('#indeedInviteMessage').className = 'form-message success';
}

async function loadIndeedMetrics() {
  const response = await fetch('/api/cleaner-applicants/metrics');
  const metrics = await response.json();
  if (!response.ok) return;
  document.querySelector('#indeedInvited').textContent = metrics.invited_candidates;
  document.querySelector('#indeedCompleted').textContent = metrics.applications_completed;
  document.querySelector('#indeedInterviewed').textContent = metrics.interviewed;
  document.querySelector('#indeedConverted').textContent = metrics.converted_to_cleaner;
  document.querySelector('#indeedConversion').textContent = `${Number(metrics.application_conversion_rate || 0).toFixed(1)}%`;
}

async function load() {
  const response = await fetch('/api/cleaner-applicants');
  applicants = await response.json();
  if (!response.ok) {
    document.querySelector('#applicantList').innerHTML = '<div class="empty card-wide">Could not load applicants.</div>';
    return;
  }
  document.querySelector('#totalApplicants').textContent = applicants.length;
  document.querySelector('#newApplicants').textContent = applicants.filter(applicant => applicant.status === 'New').length;
  document.querySelector('#contactApplicants').textContent = applicants.filter(applicant => ['New', 'Contacted', 'Interview'].includes(applicant.status)).length;
  renderApplicants();
  await loadIndeedMetrics();
}

function renderApplicants() {
  const root = document.querySelector('#applicantList');
  if (!applicants.length) {
    root.innerHTML = '<div class="empty card-wide">No cleaner applicants yet. Use the Indeed Bridge or share a tracked application link.</div>';
    return;
  }
  root.innerHTML = applicants.map(applicant => {
    const phone = String(applicant.phone || '').replace(/[^\d+]/g, '');
    const whatsapp = phone ? `https://wa.me/${phone.replace(/^0/, '44')}` : '#';
    const recommendation = applicant.recommendation || 'Review';
    const isIndeed = String(applicant.source || '').toLowerCase() === 'indeed';
    const applicationComplete = Boolean(applicant.application_completed_at || (applicant.phone && applicant.email && applicant.postcode && applicant.services?.length && applicant.availability?.length));
    const interviewStatus = applicant.interview_status || 'Not scheduled';
    const identifier = applicant.invitation_code ? `IND-${String(applicant.invitation_code).replace(/[^a-z0-9]/gi, '').slice(0, 10).toUpperCase()}` : '';
    return `<article class="applicant-card status-${esc(String(applicant.status || 'New').toLowerCase().replaceAll(' ', '-'))}">
      <div class="applicant-head">
        <div><h2>${esc(applicant.name)}</h2><p>${esc(applicant.email || 'Application not completed')} ${applicant.phone ? `&middot; ${esc(applicant.phone)}` : ''}</p></div>
        <span>${esc(applicant.status || 'New')}</span>
      </div>
      <div><span class="recommendation ${recommendationClass(recommendation)}">${esc(recommendation)} &middot; ${Number(applicant.score || 0)}/100</span></div>
      ${isIndeed ? `<div class="applicant-progress" aria-label="Indeed recruitment progress">
        <span class="progress-step ${applicant.invitation_created_at ? 'done' : ''}">Invited</span>
        <span class="progress-step ${applicant.invitation_opened_at ? 'done' : ''}">Opened</span>
        <span class="progress-step ${applicationComplete ? 'done' : ''}">Applied</span>
        <span class="progress-step ${applicant.ai_scored_at ? 'done' : ''}">AI scored</span>
        <span class="progress-step ${interviewStatus !== 'Not scheduled' ? 'done' : ''}">Interview</span>
        <span class="progress-step ${applicant.approved_cleaner_id ? 'done' : ''}">Converted</span>
      </div>${identifier ? `<div class="applicant-reference">${esc(identifier)}</div>` : ''}` : ''}
      <div class="applicant-meta">
        <span>${esc(applicant.postcode || 'Postcode pending')}</span><span>${esc(applicant.source)}</span>
        <span>${Number(applicant.travel_radius || 0)} mile radius</span><span>&pound;${Number(applicant.hourly_rate || 0).toFixed(2)}/hr</span>
        <span>${esc(applicant.travel_method || 'Unknown travel')}</span>
      </div>
      <p><strong>Availability:</strong> ${esc((applicant.availability || []).join(', ') || 'Not provided')}</p>
      <p><strong>Services:</strong> ${esc((applicant.services || []).join(', ') || 'Not provided')}</p>
      <p><strong>DBS:</strong> ${esc(applicant.dbs_status)} &middot; <strong>Right to work:</strong> ${esc(applicant.right_to_work_status || (applicant.right_to_work_verified ? 'Yes' : 'Not provided'))}</p>
      <p><strong>Vehicle:</strong> ${Number(applicant.has_own_vehicle || 0) ? 'Yes' : 'No'} &middot; <strong>Licence:</strong> ${esc(applicant.driving_licence_status || 'Not provided')}</p>
      <p><strong>Experience:</strong> ${esc(applicant.experience || 'No experience notes yet.')}</p>
      ${applicant.short_intro ? `<p><strong>Intro:</strong> ${esc(applicant.short_intro)}</p>` : ''}
      <div class="applicant-docs">${docs('ID', applicant.id_uploads)}${docs('Proof of address', applicant.proof_of_address_uploads)}${docs('Driving licence', applicant.driving_licence_uploads)}</div>
      <p><strong>Why:</strong> ${esc((applicant.reasons || []).join(', ') || 'No positive signals yet.')}</p>
      <p><strong>Watch:</strong> ${esc((applicant.risks || []).join(', ') || 'No major risks flagged.')}</p>
      <label>Admin notes<textarea data-notes="${applicant.id}" rows="2">${esc(applicant.notes || '')}</textarea></label>
      <div class="applicant-actions">
        <select data-status="${applicant.id}">${['Invited', 'New', 'Contacted', 'Interview', 'Approved', 'Rejected', 'Added as Cleaner'].map(status => `<option ${status === applicant.status ? 'selected' : ''}>${status}</option>`).join('')}</select>
        <select data-interview="${applicant.id}" aria-label="Interview status for ${esc(applicant.name)}">${['Not scheduled', 'Invited', 'Scheduled', 'Completed', 'No show', 'Declined'].map(value => `<option ${value === interviewStatus ? 'selected' : ''}>${value}</option>`).join('')}</select>
        <button onclick="saveApplicant(${applicant.id})">Save</button>
        ${phone ? `<a href="${whatsapp}" target="_blank" rel="noopener">WhatsApp</a>` : ''}
        ${applicant.email ? `<a href="mailto:${esc(applicant.email)}">Email</a>` : ''}
        ${isIndeed && !applicationComplete ? `<button onclick="inviteExistingIndeedApplicant(${applicant.id})">Invite to Sparkles</button>` : ''}
        <button ${applicant.approved_cleaner_id || !applicationComplete ? 'disabled' : ''} onclick="openApprove(${applicant.id})">Approve as cleaner</button>
      </div>
    </article>`;
  }).join('');
}

async function saveApplicant(id) {
  const status = document.querySelector(`[data-status="${id}"]`).value;
  const interview_status = document.querySelector(`[data-interview="${id}"]`).value;
  const notes = document.querySelector(`[data-notes="${id}"]`).value;
  const response = await fetch(`/api/cleaner-applicants/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, interview_status, notes })
  });
  const result = await response.json();
  if (!response.ok) return alert(result.error || 'Could not save applicant.');
  await load();
}

async function inviteExistingIndeedApplicant(id) {
  const response = await fetch(`/api/cleaner-applicants/${id}/invite`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  const result = await response.json();
  if (!response.ok) return alert(result.error || 'Could not generate the Indeed invitation.');
  showIndeedInvite(result);
  document.querySelector('#indeedInviteResult').scrollIntoView({ behavior: 'smooth', block: 'center' });
  await load();
}

function openApprove(id) {
  const applicant = applicants.find(item => item.id === id);
  document.querySelector('#approveModal').innerHTML = `<div class="modal-backdrop">
    <section class="modal">
      <div class="modal-head"><div><h2>Approve ${esc(applicant.name)}</h2><p>This creates a cleaner profile and emails a secure setup link.</p></div><button class="modal-close" onclick="closeApprove()" aria-label="Close">&times;</button></div>
      <p class="form-message">The cleaner will create their own password. No plain-text passwords are stored or shared.</p>
      <button class="primary" onclick="approveApplicant(${id})">Approve &amp; send invite</button>
    </section>
  </div>`;
}

function closeApprove() { document.querySelector('#approveModal').innerHTML = ''; }

async function approveApplicant(id) {
  const response = await fetch(`/api/cleaner-applicants/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  const result = await response.json();
  if (!response.ok) return alert(result.error || 'Could not approve applicant.');
  if (result.invite?.setup_link) alert(`Email preview mode: send this setup link to the cleaner:\n\n${result.invite.setup_link}`);
  closeApprove();
  await load();
}

document.querySelector('#importCsv').addEventListener('click', async () => {
  const csv = document.querySelector('#csvInput').value;
  const message = document.querySelector('#importMessage');
  message.textContent = 'Importing...';
  try {
    const response = await fetch('/api/cleaner-applicants/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv, source: 'CSV import' })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Import failed.');
    message.textContent = `Imported ${result.imported} applicant(s). ${result.skipped.length} skipped.`;
    message.className = 'form-message success';
    await load();
  } catch (error) {
    message.textContent = error.message;
    message.className = 'form-message error';
  }
});

document.querySelector('#indeedInviteForm').addEventListener('submit', async event => {
  event.preventDefault();
  const message = document.querySelector('#indeedInviteMessage');
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = 'Generating...';
  message.textContent = 'Creating a personal tracked application link...';
  message.className = 'form-message';
  try {
    const response = await fetch('/api/cleaner-applicants/indeed-invite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: document.querySelector('#indeedApplicantName').value,
        indeed_reference: document.querySelector('#indeedApplicantReference').value,
        notes: document.querySelector('#indeedApplicantNotes').value
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not generate the invitation.');
    showIndeedInvite(result);
    event.currentTarget.reset();
    await load();
  } catch (error) {
    message.textContent = error.message;
    message.className = 'form-message error';
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
});

document.querySelector('#copyIndeedMessage').addEventListener('click', event => {
  if (currentIndeedInvite) copyValue(currentIndeedInvite.message, event.currentTarget);
});

document.querySelector('#copyIndeedLink').addEventListener('click', event => {
  if (currentIndeedInvite) copyValue(currentIndeedInvite.link, event.currentTarget);
});

renderLinks();
load();

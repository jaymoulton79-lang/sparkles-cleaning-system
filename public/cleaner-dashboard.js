const esc = value => {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
};

const money = pennies => `£${(Number(pennies || 0) / 100).toFixed(2)}`;
const pretty = date => date ? new Date(`${date}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : 'Date not set';
const stamp = value => value ? new Date(value).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

function paymentLine(job) {
  const balance = Number(job.balance_amount || 0);
  if (job.payment_status === 'Paid in Full') return 'Paid in full';
  if (balance > 0) return `${esc(job.payment_status || 'Balance Due')} · ${money(balance)} balance`;
  return esc(job.payment_status || 'Payment status not set');
}

function actions(job) {
  const buttons = [];
  if (job.status === 'Assigned') {
    buttons.push(`<button onclick="jobAction(${job.id},'accept',this)">Accept Job</button>`);
    buttons.push(`<button class="secondary" onclick="declineJob(${job.id},this)">Reject Job</button>`);
  }
  if (job.status === 'Accepted') {
    buttons.push(`<button class="secondary" onclick="jobAction(${job.id},'on_way',this)">On my way</button>`);
    buttons.push(`<button onclick="jobAction(${job.id},'start',this)">Start Job</button>`);
  }
  if (job.status === 'In Progress') {
    buttons.push(`<button class="secondary" onclick="jobAction(${job.id},'on_way',this)">On my way</button>`);
    buttons.push(`<button class="complete-btn" onclick="jobAction(${job.id},'complete',this)">Complete Job</button>`);
  }
  if (job.status === 'Completed') buttons.push(`<span class="job-done">Job completed</span>`);
  return buttons.join('');
}

function photoList(photos) {
  return photos?.length
    ? `<div class="photos">${photos.map(photo => `<a href="${esc(photo.url)}" target="_blank" rel="noopener"><img src="${esc(photo.url)}" alt="${esc(photo.name)}"></a>`).join('')}</div>`
    : '<span class="date-sub">No photos yet.</span>';
}

function jobCard(job) {
  return `
    <article class="job-card cleaner-portal-card">
      <div class="job-card-head cleaner-portal-head">
        <div>
          <p class="eyebrow">Booking reference</p>
          <h2>${esc(job.reference)}</h2>
          <p>${pretty(job.preferred_date)} · ${esc(job.preferred_time)}</p>
        </div>
        <span class="badge status-${esc(String(job.status || '').toLowerCase().replaceAll(' ', '-'))}">${esc(job.status)}</span>
      </div>

      <div class="cleaner-job-hero">
        <div>
          <span>Customer</span>
          <strong>${esc(job.name)}</strong>
          <p>${esc(job.phone)}<br>${esc(job.email)}</p>
        </div>
        <div>
          <span>Address</span>
          <strong>${esc(job.address)}</strong>
          <p>${esc(job.postcode)}</p>
        </div>
      </div>

      <div class="detail-grid cleaner-detail-grid">
        <div class="detail-block"><span>Service</span><strong>${esc(job.clean_type)}</strong><br>${Number(job.bedrooms || 0)} bed · ${Number(job.bathrooms || 0)} bath</div>
        <div class="detail-block"><span>Payment</span><strong>${paymentLine(job)}</strong><br>Deposit: ${money(job.deposit_amount)} · Total: ${money(job.total_amount)}</div>
        <div class="detail-block"><span>Customer notes</span>${esc(job.notes) || 'No notes provided'}</div>
        <div class="detail-block"><span>Timestamps</span>Accepted: ${stamp(job.accepted_at)}<br>Started: ${stamp(job.started_at)}<br>Completed: ${stamp(job.completed_at)}</div>
        <div class="detail-block"><span>Before photos</span>${photoList(job.before_photos)}</div>
        <div class="detail-block"><span>After photos</span>${photoList(job.after_photos)}</div>
      </div>

      <div class="job-actions cleaner-action-bar">${actions(job)}</div>

      <div class="job-tools">
        <label>Upload before photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple onchange="uploadPhotos(${job.id},'before',this)"></label>
        <label>Upload after photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple onchange="uploadPhotos(${job.id},'after',this)"></label>
      </div>

      <div class="field cleaner-note-box">
        <label>Add cleaner notes</label>
        <textarea id="notes-${job.id}" placeholder="Access notes, issues, supplies used...">${esc(job.cleaner_notes || '')}</textarea>
        <button class="secondary" onclick="saveNotes(${job.id},this)">Save notes</button>
      </div>
    </article>`;
}

async function load() {
  const response = await fetch('/api/cleaner/jobs');
  const jobs = await response.json();
  if (!response.ok) {
    location.href = '/cleaner/login';
    return;
  }
  document.querySelector('#jobs').innerHTML = jobs.length
    ? `<div class="job-list">${jobs.map(jobCard).join('')}</div>`
    : '<div class="empty cleaner-empty"><strong>No assigned jobs yet.</strong><br>When Sparkles Cleaning Agency assigns you a booking, it will appear here.</div>';
}

async function jobAction(id, action, button) {
  button.disabled = true;
  const old = button.textContent;
  button.textContent = 'Saving...';
  try {
    const response = await fetch(`/api/cleaner/jobs/${id}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not update job.');
    await load();
  } catch (error) {
    alert(error.message);
    button.disabled = false;
    button.textContent = old;
  }
}

async function declineJob(id, button) {
  const notes = document.querySelector(`#notes-${id}`)?.value || '';
  if (!confirm('Reject this job and return it to admin for reassignment?')) return;
  button.disabled = true;
  button.textContent = 'Rejecting...';
  try {
    const response = await fetch(`/api/cleaner/jobs/${id}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'decline', notes })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not reject job.');
    await load();
  } catch (error) {
    alert(error.message);
    button.disabled = false;
    button.textContent = 'Reject Job';
  }
}

async function saveNotes(id, button) {
  button.disabled = true;
  button.textContent = 'Saving...';
  const notes = document.querySelector(`#notes-${id}`).value;
  try {
    const response = await fetch(`/api/cleaner/jobs/${id}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'notes', notes })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save notes.');
    button.textContent = 'Saved';
    setTimeout(() => button.textContent = 'Save notes', 1200);
  } catch (error) {
    alert(error.message);
    button.textContent = 'Save notes';
  } finally {
    button.disabled = false;
  }
}

async function uploadPhotos(id, type, input) {
  if (!input.files.length) return;
  const form = new FormData();
  [...input.files].forEach(file => form.append('photos', file));
  input.disabled = true;
  try {
    const response = await fetch(`/api/cleaner/jobs/${id}/photos?type=${type}`, { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not upload photos.');
    await load();
  } catch (error) {
    alert(error.message);
  } finally {
    input.disabled = false;
    input.value = '';
  }
}

window.jobAction = jobAction;
window.declineJob = declineJob;
window.saveNotes = saveNotes;
window.uploadPhotos = uploadPhotos;

document.querySelector('#logout').onclick = async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  location.href = '/cleaner/login';
};

load();
setInterval(load, 10000);

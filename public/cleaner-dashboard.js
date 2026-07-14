const esc = value => {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
};

const money = pennies => `£${(Number(pennies || 0) / 100).toFixed(2)}`;
const pounds = value => `£${Number(value || 0).toFixed(2)}`;
const pretty = date => date ? new Date(`${date}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : 'Date not set';
const stamp = value => value ? new Date(value).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—';
const todayIso = () => new Date().toISOString().slice(0, 10);

function paymentLine(job) {
  const balance = Number(job.balance_amount || 0);
  if (job.payment_status === 'Paid in Full') return 'Paid in full';
  if (balance > 0) return `${esc(job.payment_status || 'Balance Due')} · ${money(balance)} balance`;
  return esc(job.payment_status || 'Payment status not set');
}

function estimatedHours(job) {
  const bedrooms = Number(job.bedrooms || 0);
  const bathrooms = Number(job.bathrooms || 0);
  const clean = String(job.clean_type || '').toLowerCase();
  let hours = 1.5 + bedrooms * 0.45 + bathrooms * 0.35;
  if (clean.includes('deep')) hours += 1.25;
  if (clean.includes('end of tenancy')) hours += 2;
  return Math.max(2, Math.round(hours * 2) / 2);
}

function estimateDuration(job) {
  return `${estimatedHours(job)} hours approx.`;
}

function payoutSummary(job) {
  const hours = estimatedHours(job);
  const rate = Number(job.cleaner_hourly_rate || 0);
  const payout = hours * rate;
  const status = job.status === 'Completed' ? 'Pending owner payment' : 'Not payable until job is completed';
  return `
    <strong>${pounds(payout)}</strong>
    <br>${hours} hrs × ${pounds(rate)}/hr
    <br><span class="payout-status">${esc(status)}</span>
    <br><span class="date-sub">Paid manually by Sparkles owner for now.</span>`;
}

function mapsUrl(job) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${job.address || ''}, ${job.postcode || ''}`)}`;
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
  if (job.status === 'On My Way') {
    buttons.push(`<button onclick="jobAction(${job.id},'start',this)">Start Job</button>`);
  }
  if (job.status === 'In Progress') {
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
          <p><a class="directions-link" href="${mapsUrl(job)}" target="_blank" rel="noopener">Open Google Maps directions</a></p>
        </div>
      </div>

      <div class="detail-grid cleaner-detail-grid">
        <div class="detail-block"><span>Service</span><strong>${esc(job.clean_type)}</strong><br>${Number(job.bedrooms || 0)} bed · ${Number(job.bathrooms || 0)} bath<br>Estimated duration: ${estimateDuration(job)}</div>
        <div class="detail-block"><span>Customer payment</span><strong>${paymentLine(job)}</strong><br>Deposit: ${money(job.deposit_amount)} · Total: ${money(job.total_amount)}</div>
        <div class="detail-block cleaner-payout-block"><span>Your estimated payout</span>${payoutSummary(job)}</div>
        <div class="detail-block"><span>Customer notes & access instructions</span>${esc(job.notes) || 'No notes provided'}</div>
        <div class="detail-block"><span>Timestamps</span>Accepted: ${stamp(job.accepted_at)}<br>On my way: ${stamp(job.on_my_way_at)}<br>Started: ${stamp(job.started_at)}<br>Completed: ${stamp(job.completed_at)}</div>
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

function renderJobSections(jobs) {
  const today = todayIso();
  const groups = [
    ['Jobs awaiting your response', jobs.filter(job => job.status === 'Assigned')],
    ["Today's jobs", jobs.filter(job => job.preferred_date === today && job.status !== 'Assigned' && job.status !== 'Completed')],
    ['Upcoming jobs', jobs.filter(job => job.preferred_date > today && job.status !== 'Assigned' && job.status !== 'Completed')],
    ['Completed jobs', jobs.filter(job => job.status === 'Completed')],
  ];
  return groups
    .filter(([, items]) => items.length)
    .map(([title, items]) => `<section class="cleaner-job-section"><h2>${esc(title)}</h2><div class="job-list">${items.map(jobCard).join('')}</div></section>`)
    .join('');
}

function updateSummary(jobs) {
  const today = todayIso();
  const awaiting = jobs.filter(job => job.status === 'Assigned').length;
  const todayJobs = jobs.filter(job => job.preferred_date === today && job.status !== 'Completed').length;
  const upcoming = jobs.filter(job => job.preferred_date > today && job.status !== 'Completed').length;
  const completed = jobs.filter(job => job.status === 'Completed').length;
  const values = [awaiting, todayJobs, upcoming, completed];
  document.querySelectorAll('#cleanerSummary .summary-pill strong').forEach((node, index) => {
    node.textContent = values[index] ?? 0;
  });
  document.querySelector('#todayJobCount').textContent = todayJobs;
}

async function load() {
  const response = await fetch('/api/cleaner/jobs');
  const jobs = await response.json();
  if (!response.ok) {
    location.href = '/cleaner/login';
    return;
  }
  updateSummary(jobs);
  document.querySelector('#jobs').innerHTML = jobs.length
    ? renderJobSections(jobs)
    : '<div class="empty cleaner-empty"><strong>No assigned jobs yet.</strong><br>When Sparkles Cleaning Cambridge assigns you a booking, it will appear here.</div>';
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



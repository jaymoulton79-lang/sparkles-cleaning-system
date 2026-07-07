const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
const sourceNames = ['Indeed','Facebook','WhatsApp','Referral','Website','Other'];
let applicants = [];

function applyUrl(source){
  return `${location.origin}/cleaner/apply?source=${encodeURIComponent(source.toLowerCase())}`;
}

function renderLinks(){
  document.querySelector('#sourceLinks').innerHTML = sourceNames.map(source => {
    const url = applyUrl(source);
    const whatsappText = encodeURIComponent(`Hi, Sparkles OS is hiring cleaners. Apply here: ${url}`);
    return `<article class="source-link">
      <strong>${esc(source)}</strong>
      <input readonly value="${esc(url)}">
      <div class="mini-actions">
        <button onclick="copyLink('${esc(url)}',this)">Copy</button>
        <a href="https://wa.me/?text=${whatsappText}" target="_blank">Share WhatsApp</a>
      </div>
    </article>`;
  }).join('');
}

async function copyLink(url, button){
  await navigator.clipboard.writeText(url);
  const old = button.textContent;
  button.textContent = 'Copied';
  setTimeout(()=>button.textContent=old, 1200);
}

async function load(){
  const response = await fetch('/api/cleaner-applicants');
  applicants = await response.json();
  if(!response.ok){
    document.querySelector('#applicantList').innerHTML = '<div class="empty card-wide">Could not load applicants.</div>';
    return;
  }
  document.querySelector('#totalApplicants').textContent = applicants.length;
  document.querySelector('#newApplicants').textContent = applicants.filter(a=>a.status==='New').length;
  document.querySelector('#contactApplicants').textContent = applicants.filter(a=>['New','Contacted','Interview'].includes(a.status)).length;
  renderApplicants();
}

function renderApplicants(){
  const root = document.querySelector('#applicantList');
  if(!applicants.length){
    root.innerHTML = '<div class="empty card-wide">No cleaner applicants yet. Share your recruitment links to start building the database.</div>';
    return;
  }
  root.innerHTML = applicants.map(applicant => {
    const phone = String(applicant.phone || '').replace(/[^\d+]/g,'');
    const whatsapp = phone ? `https://wa.me/${phone.replace(/^0/,'44')}` : '#';
    return `<article class="applicant-card status-${esc(applicant.status.toLowerCase().replaceAll(' ','-'))}">
      <div class="applicant-head">
        <div>
          <h2>${esc(applicant.name)}</h2>
          <p>${esc(applicant.email)} · ${esc(applicant.phone)}</p>
        </div>
        <span>${esc(applicant.status)}</span>
      </div>
      <div class="applicant-meta">
        <span>${esc(applicant.postcode)}</span>
        <span>${esc(applicant.source)}</span>
        <span>${Number(applicant.travel_radius||0)} mile radius</span>
        <span>£${Number(applicant.hourly_rate||0).toFixed(2)}/hr</span>
      </div>
      <p><strong>Availability:</strong> ${esc((applicant.availability||[]).join(', ') || 'Not provided')}</p>
      <p><strong>Services:</strong> ${esc((applicant.services||[]).join(', ') || 'Not provided')}</p>
      <p><strong>DBS:</strong> ${esc(applicant.dbs_status)} · <strong>Insurance:</strong> ${esc(applicant.insurance_status)}</p>
      <p><strong>Experience:</strong> ${esc(applicant.experience || 'No experience notes yet.')}</p>
      <label>Admin notes<textarea data-notes="${applicant.id}" rows="2">${esc(applicant.notes || '')}</textarea></label>
      <div class="applicant-actions">
        <select data-status="${applicant.id}">
          ${['New','Contacted','Interview','Approved','Rejected','Added as Cleaner'].map(status=>`<option ${status===applicant.status?'selected':''}>${status}</option>`).join('')}
        </select>
        <button onclick="saveApplicant(${applicant.id})">Save</button>
        <a href="${whatsapp}" target="_blank">WhatsApp</a>
        <a href="mailto:${esc(applicant.email)}">Email</a>
        <button ${applicant.approved_cleaner_id?'disabled':''} onclick="openApprove(${applicant.id})">Approve as cleaner</button>
      </div>
    </article>`;
  }).join('');
}

async function saveApplicant(id){
  const status = document.querySelector(`[data-status="${id}"]`).value;
  const notes = document.querySelector(`[data-notes="${id}"]`).value;
  const response = await fetch(`/api/cleaner-applicants/${id}`, {
    method: 'PATCH',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({status, notes})
  });
  const result = await response.json();
  if(!response.ok) return alert(result.error || 'Could not save applicant.');
  await load();
}

function openApprove(id){
  const applicant = applicants.find(x=>x.id===id);
  document.querySelector('#approveModal').innerHTML = `<div class="modal-backdrop">
    <section class="modal">
      <div class="modal-head"><div><h2>Approve ${esc(applicant.name)}</h2><p>This creates an active cleaner login account.</p></div><button class="modal-close" onclick="closeApprove()">×</button></div>
      <label>Temporary cleaner password<input id="cleanerPassword" type="password" placeholder="At least 8 characters"></label>
      <p class="form-message">Give this password to the cleaner. They can log in at /cleaner/login.</p>
      <button class="primary" onclick="approveApplicant(${id})">Create cleaner account</button>
    </section>
  </div>`;
}

function closeApprove(){document.querySelector('#approveModal').innerHTML=''}

async function approveApplicant(id){
  const password = document.querySelector('#cleanerPassword').value;
  const response = await fetch(`/api/cleaner-applicants/${id}/approve`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password})
  });
  const result = await response.json();
  if(!response.ok) return alert(result.error || 'Could not approve applicant.');
  closeApprove();
  await load();
}

document.querySelector('#importCsv').addEventListener('click', async () => {
  const csv = document.querySelector('#csvInput').value;
  const message = document.querySelector('#importMessage');
  message.textContent = 'Importing...';
  try{
    const response = await fetch('/api/cleaner-applicants/import', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({csv, source:'CSV import'})
    });
    const result = await response.json();
    if(!response.ok) throw new Error(result.error || 'Import failed.');
    message.textContent = `Imported ${result.imported} applicant(s). ${result.skipped.length} skipped.`;
    message.className = 'form-message success';
    await load();
  }catch(error){
    message.textContent = error.message;
    message.className = 'form-message error';
  }
});

renderLinks();
load();

const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
const pretty=d=>new Date(d+'T00:00:00').toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric'});
const stamp=v=>v?new Date(v).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'}):'—';

function actions(job){
  const buttons=[];
  if(job.status==='Assigned'){
    buttons.push(`<button onclick="jobAction(${job.id},'accept',this)">Accept Job</button>`);
    buttons.push(`<button class="secondary" onclick="declineJob(${job.id},this)">Decline Job</button>`);
  }
  if(['Assigned','Accepted'].includes(job.status))buttons.push(`<button onclick="jobAction(${job.id},'start',this)">Start Job</button>`);
  if(['Assigned','Accepted','In Progress'].includes(job.status))buttons.push(`<button class="complete-btn" onclick="jobAction(${job.id},'complete',this)">Complete Job</button>`);
  return buttons.join('');
}

function photoList(photos){
  return photos?.length?`<div class="photos">${photos.map(p=>`<a href="${esc(p.url)}" target="_blank"><img src="${esc(p.url)}" alt="${esc(p.name)}"></a>`).join('')}</div>`:'<span class="date-sub">No photos yet.</span>';
}

async function load(){
  const r=await fetch('/api/cleaner/jobs'),jobs=await r.json();
  if(!r.ok){location.href='/cleaner/login';return}
  document.querySelector('#jobs').innerHTML=jobs.length?`<div class="job-list">${jobs.map(j=>`
    <article class="job-card">
      <div class="job-card-head">
        <div><h2>${esc(j.reference)} · ${esc(j.clean_type)}</h2><p>${pretty(j.preferred_date)} · ${esc(j.preferred_time)}</p></div>
        <span class="badge">${esc(j.status)}</span>
      </div>
      <div class="detail-grid">
        <div class="detail-block"><span>Customer</span><strong>${esc(j.name)}</strong><br>${esc(j.phone)}<br>${esc(j.email)}</div>
        <div class="detail-block"><span>Address</span>${esc(j.address)}, ${esc(j.postcode)}</div>
        <div class="detail-block"><span>Timestamps</span>Accepted: ${stamp(j.accepted_at)}<br>Started: ${stamp(j.started_at)}<br>Completed: ${stamp(j.completed_at)}</div>
        <div class="detail-block"><span>Before photos</span>${photoList(j.before_photos)}</div>
        <div class="detail-block"><span>After photos</span>${photoList(j.after_photos)}</div>
        <div class="detail-block"><span>Customer notes</span>${esc(j.notes)||'No notes provided'}</div>
      </div>
      <div class="job-actions">${actions(j)}</div>
      <div class="job-tools">
        <label>Upload before photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple onchange="uploadPhotos(${j.id},'before',this)"></label>
        <label>Upload after photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple onchange="uploadPhotos(${j.id},'after',this)"></label>
      </div>
      <div class="field cleaner-note-box">
        <label>Add notes</label>
        <textarea id="notes-${j.id}" placeholder="Access notes, issues, supplies used…">${esc(j.cleaner_notes||'')}</textarea>
        <button class="secondary" onclick="saveNotes(${j.id},this)">Save notes</button>
      </div>
    </article>`).join('')}</div>`:'<div class="empty">No assigned jobs yet.</div>';
}

async function jobAction(id,action,button){
  button.disabled=true;const old=button.textContent;button.textContent='Saving…';
  try{
    const r=await fetch(`/api/cleaner/jobs/${id}/action`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    const data=await r.json();if(!r.ok)throw new Error(data.error||'Could not update job.');
    await load();
  }catch(e){alert(e.message);button.disabled=false;button.textContent=old}
}

async function declineJob(id,button){
  const notes=document.querySelector(`#notes-${id}`)?.value||'';
  if(!confirm('Decline this job and return it to admin for reassignment?'))return;
  button.disabled=true;button.textContent='Declining…';
  try{
    const r=await fetch(`/api/cleaner/jobs/${id}/action`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'decline',notes})});
    const data=await r.json();if(!r.ok)throw new Error(data.error||'Could not decline job.');
    await load();
  }catch(e){alert(e.message);button.disabled=false;button.textContent='Decline Job'}
}

async function saveNotes(id,button){
  button.disabled=true;button.textContent='Saving…';
  const notes=document.querySelector(`#notes-${id}`).value;
  try{
    const r=await fetch(`/api/cleaner/jobs/${id}/action`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'notes',notes})});
    const data=await r.json();if(!r.ok)throw new Error(data.error||'Could not save notes.');
    button.textContent='Saved';
    setTimeout(()=>button.textContent='Save notes',1200);
  }catch(e){alert(e.message);button.textContent='Save notes'}finally{button.disabled=false}
}

async function uploadPhotos(id,type,input){
  if(!input.files.length)return;
  const form=new FormData();
  [...input.files].forEach(file=>form.append('photos',file));
  input.disabled=true;
  try{
    const r=await fetch(`/api/cleaner/jobs/${id}/photos?type=${type}`,{method:'POST',body:form});
    const data=await r.json();if(!r.ok)throw new Error(data.error||'Could not upload photos.');
    await load();
  }catch(e){alert(e.message)}finally{input.disabled=false;input.value=''}
}

document.querySelector('#logout').onclick=async()=>{await fetch('/api/auth/logout',{method:'POST'});location.href='/cleaner/login'};
load();
setInterval(load,10000);

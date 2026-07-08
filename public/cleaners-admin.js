document.head.insertAdjacentHTML('beforeend','<link rel="stylesheet" href="/cleaner.css">');
const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
const days=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
const services=['Regular clean','Deep clean','End of tenancy','One-off clean'];
let cleaners=[];

function initials(name){
  return String(name||'').split(' ').filter(Boolean).map(x=>x[0]).slice(0,2).join('').toUpperCase() || 'SC';
}

function checkboxGroup(cleaner,field,options){
  const selected=new Set(cleaner[field]||[]);
  return `<div class="edit-pills" data-cleaner="${cleaner.id}" data-field="${field}">
    ${options.map(option=>`<label class="edit-pill ${selected.has(option)?'selected':''}">
      <input type="checkbox" value="${esc(option)}" ${selected.has(option)?'checked':''}>
      <span>${esc(option)}</span>
    </label>`).join('')}
  </div>`;
}

async function loadCleaners(){
  try{
    const r=await fetch('/api/cleaners');
    cleaners=await r.json();
    if(!r.ok)throw new Error(cleaners.error||'Could not load cleaners.');
    const active=cleaners.filter(c=>Number(c.active)!==0);
    document.querySelector('#cleanerTotal').textContent=active.length;
    document.querySelector('#dbsTotal').textContent=active.filter(c=>c.dbs_status==='Verified').length;
    document.querySelector('#insuranceTotal').textContent=active.filter(c=>c.insurance_status==='Verified').length;
    if(!cleaners.length){
      document.querySelector('#cleanerList').innerHTML='<div class="empty card-wide"><strong>No Sparkles cleaners yet</strong><br>New cleaner accounts will appear here.</div>';
      return;
    }
    document.querySelector('#cleanerList').innerHTML=cleaners.map(c=>{
      const isActive=Number(c.active)!==0;
      return `<article class="cleaner-card ${isActive?'':'inactive'}">
        <div class="cleaner-card-head">
          <div class="avatar">${esc(initials(c.name))}</div>
          <div><h2>${esc(c.name)}</h2><p>${esc(c.postcode)} · ${c.travel_radius} mile radius</p></div>
          <span class="badge ${isActive?'':'muted'}">${isActive?'Active':'Inactive'}</span>
        </div>
        <div class="rate">£${Number(c.hourly_rate).toFixed(2)} <span>/ hour</span></div>
        <div class="cleaner-meta">
          <div><span>Contact</span>${esc(c.phone)}<br>${esc(c.email)}</div>
          <div><span>Available</span>${(c.availability||[]).map(esc).join(', ') || 'Not set'}</div>
          <div><span>Services</span>${(c.services||[]).map(esc).join(', ') || 'Not set'}</div>
        </div>
        <details class="cleaner-editor">
          <summary>Edit availability & services</summary>
          <div class="editor-block">
            <label>Working days</label>
            ${checkboxGroup(c,'availability',days)}
          </div>
          <div class="editor-block">
            <label>Services offered</label>
            ${checkboxGroup(c,'services',services)}
          </div>
          <button class="row-button" onclick="saveCleanerProfile(${c.id},this)">Save cleaner profile</button>
        </details>
        <div class="checks">
          <span class="${c.dbs_status==='Verified'?'verified':''}">DBS: ${esc(c.dbs_status)}</span>
          <span class="${c.insurance_status==='Verified'?'verified':''}">Insurance: ${esc(c.insurance_status)}</span>
        </div>
        <div class="cleaner-actions">
          <button class="row-button secondary" onclick="setCleanerPassword(${c.id},this)">Set password</button>
          <button class="row-button ${isActive?'danger':''}" onclick="toggleCleaner(${c.id},${isActive?0:1},this)">${isActive?'Deactivate':'Reactivate'}</button>
        </div>
      </article>`;
    }).join('');
  }catch(e){
    document.querySelector('#cleanerList').innerHTML='<div class="empty card-wide">Could not load cleaners. Please refresh.</div>';
  }
}

function selectedValues(cleanerId,field){
  return [...document.querySelectorAll(`[data-cleaner="${cleanerId}"][data-field="${field}"] input:checked`)].map(input=>input.value);
}

async function saveCleanerProfile(id,button){
  const availability=selectedValues(id,'availability');
  const chosenServices=selectedValues(id,'services');
  if(!availability.length)return alert('Choose at least one working day.');
  if(!chosenServices.length)return alert('Choose at least one service.');
  button.disabled=true;
  button.textContent='Saving…';
  try{
    const r=await fetch(`/api/cleaners/${id}`,{
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({availability,services:chosenServices})
    });
    const result=await r.json();
    if(!r.ok)throw new Error(result.error||'Could not save cleaner profile.');
    await loadCleaners();
  }catch(e){
    button.disabled=false;
    button.textContent='Save cleaner profile';
    alert(e.message);
  }
}

async function setCleanerPassword(id,button){
  const cleaner=cleaners.find(c=>Number(c.id)===Number(id));
  const name=cleaner?.name||'this cleaner';
  const password=prompt(`Set a temporary password for ${name}. Use at least 8 characters.`);
  if(password===null)return;
  if(password.length<8)return alert('Password must be at least 8 characters.');
  if(!confirm(`Update the cleaner login password for ${name}?`))return;
  button.disabled=true;
  button.textContent='Saving…';
  try{
    const r=await fetch(`/api/cleaners/${id}`,{
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password})
    });
    const result=await r.json();
    if(!r.ok)throw new Error(result.error||'Could not update cleaner password.');
    alert(`Password updated for ${name}. Give the new password to the cleaner.`);
    await loadCleaners();
  }catch(e){
    button.disabled=false;
    button.textContent='Set password';
    alert(e.message);
  }
}

async function toggleCleaner(id,active,button){
  if(!confirm(`${active?'Reactivate':'Deactivate'} this cleaner account? ${active?'They will be eligible for future jobs again.':'They will not be able to log in or receive new assignments.'}`))return;
  button.disabled=true;
  button.textContent=active?'Reactivating…':'Deactivating…';
  try{
    const r=await fetch(`/api/cleaners/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({active:!!active})});
    const result=await r.json();
    if(!r.ok)throw new Error(result.error||'Could not update cleaner.');
    await loadCleaners();
  }catch(e){
    button.disabled=false;
    button.textContent=active?'Reactivate':'Deactivate';
    alert(e.message);
  }
}

loadCleaners();

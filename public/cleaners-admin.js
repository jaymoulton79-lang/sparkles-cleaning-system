document.head.insertAdjacentHTML('beforeend','<link rel="stylesheet" href="/cleaner.css">');
const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
let cleaners=[];

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
      document.querySelector('#cleanerList').innerHTML='<div class="empty card-wide"><strong>No cleaners yet</strong><br>New cleaner accounts will appear here.</div>';
      return;
    }
    document.querySelector('#cleanerList').innerHTML=cleaners.map(c=>{
      const isActive=Number(c.active)!==0;
      return `<article class="cleaner-card ${isActive?'':'inactive'}">
        <div class="cleaner-card-head">
          <div class="avatar">${esc(c.name.split(' ').map(x=>x[0]).slice(0,2).join(''))}</div>
          <div><h2>${esc(c.name)}</h2><p>${esc(c.postcode)} · ${c.travel_radius} mile radius</p></div>
          <span class="badge ${isActive?'':'muted'}">${isActive?'Active':'Inactive'}</span>
        </div>
        <div class="rate">£${Number(c.hourly_rate).toFixed(2)} <span>/ hour</span></div>
        <div class="cleaner-meta">
          <div><span>Contact</span>${esc(c.phone)}<br>${esc(c.email)}</div>
          <div><span>Available</span>${c.availability.map(esc).join(', ')}</div>
          <div><span>Services</span>${c.services.map(esc).join(', ')}</div>
        </div>
        <div class="checks">
          <span class="${c.dbs_status==='Verified'?'verified':''}">DBS: ${esc(c.dbs_status)}</span>
          <span class="${c.insurance_status==='Verified'?'verified':''}">Insurance: ${esc(c.insurance_status)}</span>
        </div>
        <div class="cleaner-actions">
          <button class="row-button ${isActive?'danger':''}" onclick="toggleCleaner(${c.id},${isActive?0:1},this)">${isActive?'Deactivate':'Reactivate'}</button>
        </div>
      </article>`;
    }).join('');
  }catch(e){
    document.querySelector('#cleanerList').innerHTML='<div class="empty card-wide">Could not load cleaners. Please refresh.</div>';
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

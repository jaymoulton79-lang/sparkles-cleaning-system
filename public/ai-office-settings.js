const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
let settings;

async function loadSettings(){
  const r=await fetch('/api/ai-office/settings'),data=await r.json();
  if(!r.ok){location.href='/admin/login';return}
  settings=data;
  document.querySelector('#businessHours').value=data.business_hours;
  document.querySelector('#serviceAreas').value=data.service_areas;
  document.querySelector('#pricingRows').innerHTML=Object.entries(data.pricing).map(([service,rule])=>`
    <tr data-service="${esc(service)}">
      <td><input class="service-name" value="${esc(service)}"></td>
      <td><input class="base" type="number" min="0" step="100" value="${Number(rule.base||0)}"></td>
      <td><input class="bedroom" type="number" min="0" step="100" value="${Number(rule.bedroom_extra||0)}"></td>
      <td><input class="bathroom" type="number" min="0" step="100" value="${Number(rule.bathroom_extra||0)}"></td>
    </tr>`).join('');
  const responses={greeting:'Greeting',booking_prompt:'Booking question prompt',handoff:'Booking link handoff',...data.responses};
  document.querySelector('#responseRows').innerHTML=Object.entries(data.responses).map(([key,value])=>`
    <div class="field"><label>${esc(key.replaceAll('_',' '))}</label><textarea data-response="${esc(key)}">${esc(value)}</textarea></div>`).join('');
}

document.querySelector('#settingsForm').onsubmit=async e=>{
  e.preventDefault();
  const pricing={};
  document.querySelectorAll('#pricingRows tr').forEach(row=>{
    const service=row.querySelector('.service-name').value.trim();
    if(!service)return;
    pricing[service]={
      base:Number(row.querySelector('.base').value||0),
      bedroom_extra:Number(row.querySelector('.bedroom').value||0),
      bathroom_extra:Number(row.querySelector('.bathroom').value||0)
    };
  });
  const responses={};
  document.querySelectorAll('[data-response]').forEach(el=>responses[el.dataset.response]=el.value);
  const payload={
    business_hours:document.querySelector('#businessHours').value,
    service_areas:document.querySelector('#serviceAreas').value,
    pricing,
    responses
  };
  const button=e.target.querySelector('button');
  button.disabled=true;button.textContent='Saving…';
  try{
    const r=await fetch('/api/ai-office/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await r.json();
    if(!r.ok)throw new Error(data.error||'Could not save settings.');
    const alert=document.querySelector('#settingsAlert');
    alert.textContent='AI Office settings saved.';alert.className='alert';alert.style.display='block';alert.style.background='#e5f8f1';alert.style.color='#176b53';
  }catch(error){
    const alert=document.querySelector('#settingsAlert');
    alert.textContent=error.message;alert.className='alert error';
  }finally{
    button.disabled=false;button.textContent='Save AI Office settings';
  }
};

loadSettings();

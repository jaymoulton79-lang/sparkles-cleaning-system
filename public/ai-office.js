const esc=v=>{const d=document.createElement('div');d.textContent=v ?? '';return d.innerHTML};
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format((p||0)/100);
let settings;

async function loadSettings(){
  const r=await fetch('/api/ai-office/settings'),data=await r.json();
  if(!r.ok){location.href='/admin/login';return}
  settings=data;
  document.querySelector('#cleanType').innerHTML='<option value="">Unknown yet</option>'+Object.keys(settings.pricing).map(s=>`<option>${esc(s)}</option>`).join('');
  document.querySelector('#settingsSummary').innerHTML=`
    <div class="ai-pill"><span>Business hours</span>${esc(settings.business_hours)}</div>
    <div class="ai-pill"><span>Service areas</span>${esc(settings.service_areas)}</div>
    <div class="ai-pill"><span>Booking link</span><a class="mini-link" href="${esc(settings.booking_url)}" target="_blank">${esc(settings.booking_url)}</a></div>
    <div class="ai-pill"><span>Services</span>${Object.entries(settings.pricing).map(([name,rule])=>`${esc(name)} from ${money(rule.base)}`).join('<br>')}</div>
    <div class="ai-pill"><span>Automation</span>Follow-ups, payment confirmations, reminders and reviews run through the automation monitor.</div>`;
}

document.querySelector('#assistantForm').onsubmit=async e=>{
  e.preventDefault();
  const form=e.target;
  const raw=Object.fromEntries(new FormData(form));
  const details={};
  ['name','phone','email','address','postcode','clean_type','bedrooms','bathrooms','preferred_date','preferred_time'].forEach(k=>{if(raw[k]!==undefined&&raw[k]!== '')details[k]=raw[k]});
  const button=form.querySelector('button');
  button.disabled=true;button.textContent='Thinking…';
  try{
    const r=await fetch('/api/ai-office/respond',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:raw.message,details})});
    const data=await r.json();
    if(!r.ok)throw new Error(data.error||'Could not generate reply.');
    document.querySelector('#replyBox').textContent=data.reply;
    document.querySelector('#quoteBox').innerHTML=data.quote?`<div class="ai-quote"><div><small>Total</small>${money(data.quote.total_amount)}</div><div><small>Deposit</small>${money(data.quote.deposit_amount)}</div><div><small>Balance</small>${money(data.quote.balance_amount)}</div></div>`:'';
  }catch(error){
    const alert=document.querySelector('#aiAlert');
    alert.textContent=error.message;alert.className='alert error';
  }finally{
    button.disabled=false;button.textContent='Generate office manager reply';
  }
};

loadSettings();

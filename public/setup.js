let step=0,token='',config={},logoData='';
const gate=document.querySelector('#tokenGate'),form=document.querySelector('#setupForm'),alertBox=document.querySelector('#setupAlert');

function headers(){return {'Content-Type':'application/json','X-Setup-Token':token}}

function addAdminFields(){
  const review=document.querySelector('#REVIEW_URL')?.closest('.field');
  if(!review||document.querySelector('#ADMIN_EMAIL'))return;
  review.insertAdjacentHTML('afterend',`
    <div class="section-title">Sparkles Owner Command Centre login</div>
    <div class="grid">
      <div class="field"><label for="ADMIN_EMAIL">Admin email</label><input id="ADMIN_EMAIL" name="ADMIN_EMAIL" type="email" autocomplete="username" placeholder="labcontractors@outlook.com"></div>
      <div class="field"><label for="ADMIN_PASSWORD">Admin password</label><input id="ADMIN_PASSWORD" name="ADMIN_PASSWORD" type="password" minlength="8" autocomplete="new-password" placeholder="Leave blank to keep current password"><small>Stored securely as a salted hash.</small></div>
    </div>
  `);
}

async function unlock(){
  token=document.querySelector('#setupToken').value;
  const r=await fetch('/api/config',{headers:{'X-Setup-Token':token}}),data=await r.json();
  if(!r.ok){alertBox.textContent=data.error;alertBox.className='alert error';return}
  config=data;
  addAdminFields();
  gate.hidden=true;
  form.hidden=false;
  Object.entries(config).forEach(([k,v])=>{const el=form.elements[k];if(el&&typeof v==='string')el.value=v});
  if(!form.elements.ADMIN_EMAIL.value)form.elements.ADMIN_EMAIL.value='labcontractors@outlook.com';
  form.elements.ADMIN_PASSWORD.required=!data.ADMIN_CONFIGURED;
  form.elements.ADMIN_PASSWORD.placeholder=data.ADMIN_CONFIGURED?'Leave blank to keep current password':'Create the first admin password';
  document.querySelector('#stripeReady').textContent=data.STRIPE_CONFIGURED?'✓':'○';
  document.querySelector('#emailReady').textContent=data.EMAIL_CONFIGURED?'✓':'○';
}

function showStep(){
  document.querySelectorAll('.wizard-step').forEach((el,i)=>el.classList.toggle('active',i===step));
  document.querySelectorAll('[data-dot]').forEach((el,i)=>{el.classList.toggle('active',i===step);el.classList.toggle('done',i<step)});
  document.querySelector('#back').hidden=step===0;
  document.querySelector('#next').hidden=step===3;
  document.querySelector('#save').hidden=step!==3;
}

document.querySelector('#unlock').onclick=unlock;
document.querySelector('#next').onclick=()=>{if(!form.reportValidity())return;step=Math.min(3,step+1);showStep()};
document.querySelector('#back').onclick=()=>{step=Math.max(0,step-1);showStep()};
document.querySelector('#logo').onchange=e=>{const file=e.target.files[0];if(!file)return;if(file.size>1024*1024)return alert('Logo must be under 1MB.');const reader=new FileReader();reader.onload=()=>logoData=reader.result;reader.readAsDataURL(file)};
form.onsubmit=async e=>{
  e.preventDefault();
  const data=Object.fromEntries(new FormData(form));
  if(!data.ADMIN_PASSWORD)delete data.ADMIN_PASSWORD;
  if(logoData)data.LOGO_DATA=logoData;
  const r=await fetch('/api/config',{method:'POST',headers:headers(),body:JSON.stringify(data)}),result=await r.json();
  if(!r.ok){alertBox.textContent=result.error;alertBox.className='alert error';return}
  form.hidden=true;
  document.querySelector('#setupDone').hidden=false;
};

addAdminFields();
unlock();

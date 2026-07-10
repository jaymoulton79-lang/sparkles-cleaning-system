document.head.insertAdjacentHTML('beforeend','<link rel="stylesheet" href="/cleaner.css">');
const cleanerForm=document.querySelector('#cleanerForm');
const cleanerAlert=document.querySelector('#cleanerAlert');
const cleanerSubmit=document.querySelector('#cleanerSubmit');

cleanerForm.addEventListener('submit',async e=>{
  e.preventDefault();
  cleanerAlert.className='alert';
  const availability=[...document.querySelectorAll('input[name="availability"]:checked')].map(x=>x.value);
  const services=[...document.querySelectorAll('input[name="services"]:checked')].map(x=>x.value);
  if(!availability.length||!services.length){
    cleanerAlert.textContent='Please choose at least one available day and one service.';
    cleanerAlert.className='alert error';
    return;
  }
  const data=Object.fromEntries(new FormData(cleanerForm));
  data.availability=availability;
  data.services=services;
  cleanerSubmit.disabled=true;
  cleanerSubmit.textContent='Creating your account…';
  try{
    const response=await fetch('/api/cleaners',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'Something went wrong.');
    document.querySelector('.card').innerHTML='<div class="success"><div class="success-icon">✓</div><h2>Your profile is ready!</h2><p>Thanks for joining Sparkles Cleaning Agency. You can now log in to view assigned jobs.</p><a class="pay-button" href="/cleaner/login">Go to cleaner login</a></div>';
    window.scrollTo({top:0,behavior:'smooth'});
  }catch(error){
    cleanerAlert.textContent=error.message;
    cleanerAlert.className='alert error';
  }finally{
    cleanerSubmit.disabled=false;
    cleanerSubmit.textContent='Create cleaner account';
  }
});

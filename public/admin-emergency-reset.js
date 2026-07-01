const form=document.querySelector('#resetForm');
const alertBox=document.querySelector('#resetAlert');

form.onsubmit=async event=>{
  event.preventDefault();
  alertBox.className='alert';
  const button=form.querySelector('button');
  button.disabled=true;
  button.textContent='Setting password…';
  const data=Object.fromEntries(new FormData(form));
  try{
    const response=await fetch('/api/admin/emergency-reset',{
      method:'POST',
      headers:{'Content-Type':'application/json','X-Setup-Token':data.setupToken},
      body:JSON.stringify({email:data.email,password:data.password})
    });
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'Password could not be reset.');
    document.querySelector('.payment-card').innerHTML='<div class="success-icon">✓</div><h1>Password updated</h1><p>The admin password has been reset. You can now log in.</p><a class="pay-button" href="/admin/login">Go to admin login</a>';
  }catch(error){
    alertBox.textContent=error.message;
    alertBox.className='alert error';
  }finally{
    button.disabled=false;
    button.textContent='Set admin password';
  }
};

document.head.insertAdjacentHTML('beforeend','<link rel="stylesheet" href="/payments.css">');

const form=document.querySelector('#bookingForm');
const alertBox=document.querySelector('#alert');
const submit=document.querySelector('#submit');
const files=document.querySelector('#files');
const photos=document.querySelector('#photos');
const date=document.querySelector('#preferred_date');
const prices={'Regular clean':5500,'Deep clean':9500,'End of tenancy':14500,'One-off clean':7500};
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(p/100);

date.min=new Date().toISOString().split('T')[0];
submit.insertAdjacentHTML('beforebegin','<div class="quote-box"><div><strong>Estimated cleaning total</strong><span>25% deposit due now via secure Stripe Checkout</span></div><div class="quote-price"><b id="quoteTotal">—</b><small id="quoteDeposit">Choose your clean details</small></div></div>');

function updateQuote(){
  const type=form.clean_type.value,beds=Number(form.bedrooms.value),baths=Number(form.bathrooms.value);
  if(!type||form.bedrooms.value===''||!baths){
    document.querySelector('#quoteTotal').textContent='—';
    document.querySelector('#quoteDeposit').textContent='Choose your clean details';
    return;
  }
  const total=prices[type]+Math.max(0,beds-1)*1400+Math.max(0,baths-1)*1000;
  document.querySelector('#quoteTotal').textContent=money(total);
  document.querySelector('#quoteDeposit').textContent=`${money(Math.round(total*.25))} deposit`;
}

[form.clean_type,form.bedrooms,form.bathrooms].forEach(el=>el.addEventListener('change',updateQuote));
photos.addEventListener('change',()=>{
  files.textContent=photos.files.length?`${photos.files.length} photo${photos.files.length===1?'':'s'} selected: ${[...photos.files].map(f=>f.name).join(', ')}`:'';
});

form.addEventListener('submit',async e=>{
  e.preventDefault();
  alertBox.className='alert';
  submit.disabled=true;
  submit.textContent='Creating secure payment link…';
  const firstName=escapeHtml(form.name.value.split(' ')[0]||'there');
  try{
    const response=await fetch('/api/bookings',{method:'POST',body:new FormData(form)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'Something went wrong.');
    const paymentPanel=result.checkout_url
      ? `<a class="pay-button" href="${escapeHtml(result.checkout_url)}">Pay 25% deposit securely</a><p class="fine">You will be taken to Stripe test checkout. Your booking stays as Deposit Due until payment succeeds.</p>`
      : `<div class="alert error show">Your booking was saved, but the Stripe deposit link could not be created yet. ${escapeHtml(result.checkout_error||'Please contact Sparkles to arrange payment.')}</div>`;
    document.querySelector('#formCard').innerHTML=`<div class="success"><div class="success-icon">✓</div><h2>Booking received, ${firstName}.</h2><p>Your quote is ready. Pay the 25% deposit to confirm the booking and trigger cleaner assignment.</p><p class="ref">${escapeHtml(result.reference)}</p><p class="payment-note">Total ${money(result.total_amount)} · Deposit ${money(result.deposit_amount)} · Status ${escapeHtml(result.payment_status)}</p>${paymentPanel}</div>`;
    window.scrollTo({top:0,behavior:'smooth'});
  }catch(error){
    alertBox.textContent=error.message;
    alertBox.className='alert error';
    alertBox.scrollIntoView({behavior:'smooth',block:'center'});
  }finally{
    submit.disabled=false;
    submit.textContent='Send booking request';
  }
});

function escapeHtml(value){
  const d=document.createElement('div');
  d.textContent=value;
  return d.innerHTML;
}

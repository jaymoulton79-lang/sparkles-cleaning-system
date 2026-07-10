const esc=v=>{const d=document.createElement('div');d.textContent=v ?? '';return d.innerHTML};
const prettyDate=v=>new Date(`${v}T12:00:00`).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
const stamp=v=>v?new Date(v).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'}):'-';
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format((p||0)/100);
const gallery=photos=>photos?.length?`<div class="photos">${photos.map(p=>`<a href="${esc(p.url)}" target="_blank"><img src="${esc(p.url)}" alt="${esc(p.name)}"></a>`).join('')}</div>`:'None uploaded';
const paymentStatusClass=status=>status==='Deposit Paid'||status==='Paid in Full'?'paid':status==='Deposit Due'?'due':'';
const jsArg=v=>JSON.stringify(String(v ?? ''));
let bookings=[];

async function load(){
  try{
    const r=await fetch('/api/bookings');
    bookings=await r.json();
    if(!r.ok)throw new Error(bookings.error||'Could not load bookings.');
    document.querySelector('#total').textContent=bookings.length;
    document.querySelector('#newCount').textContent=bookings.filter(x=>x.status==='New').length;
    document.querySelector('#assignedCount').textContent=bookings.filter(x=>['Assigned','Accepted','In Progress'].includes(x.status)).length;
    if(!bookings.length){
      document.querySelector('#list').innerHTML='<div class="empty"><strong>No Sparkles bookings yet</strong><br>Your first request will appear here.</div>';
      return;
    }
    document.querySelector('#list').innerHTML=`<table><thead><tr><th>Customer</th><th>Clean</th><th>Preferred date</th><th>Location</th><th>Status</th><th></th></tr></thead><tbody>${bookings.map((b,i)=>`
      <tr>
        <td class="customer"><strong>${esc(b.name)}</strong><span>${esc(b.phone)} - ${esc(b.email)}</span></td>
        <td><strong>${esc(b.clean_type)}</strong><div class="date-sub">${b.bedrooms} bed - ${b.bathrooms} bath</div></td>
        <td><strong>${prettyDate(b.preferred_date)}</strong><div class="date-sub">${esc(b.preferred_time)}</div></td>
        <td>${esc(b.postcode)}</td>
        <td>
          <span class="badge ${['Assigned','Accepted','In Progress'].includes(b.status)?'status-assigned':''}">${esc(b.status)}</span>
          <div class="payment-badge ${paymentStatusClass(b.payment_status)}">${esc(b.payment_status)}</div>
          ${b.cleaner_name?`<div class="assigned-to">${esc(b.cleaner_name)}</div>`:''}
          ${b.deposit_checkout_url&&b.payment_status==='Deposit Due'?`<br><a class="balance-link" href="${esc(b.deposit_checkout_url)}" target="_blank">Open deposit checkout</a>`:''}
          ${b.status==='Completed'&&b.payment_status!=='Paid in Full'?`<br><button class="row-button balance-link" onclick="startBalancePayment(${b.id},this)">Pay balance online</button>`:''}
          ${b.status==='Completed'&&b.payment_status!=='Paid in Full'?`<br><button class="row-button" onclick="resendFinalInvoice(${b.id},this)">Resend final email</button>`:''}
        </td>
        <td>${b._source==='stripe.checkout.sessions'?'<button class="assign-button" disabled>Recovered payment</button>':`<button class="assign-button" onclick="openAssign(${b.id})">${b.cleaner_id?'Reassign':'Assign Cleaner'}</button>`}<br><button class="row-button" onclick="toggle(${i})">View details</button><br><button class="row-button danger" onclick='archiveBooking(${jsArg(b.id)},this,${jsArg(b.recovered_session_id||'')})'>Archive test</button></td>
      </tr>
      <tr class="detail-row" id="detail-${i}"><td class="detail" colspan="6"><div class="detail-grid">
        <div class="detail-block"><span>Reference</span><strong>${esc(b.reference)}</strong></div>
        <div class="detail-block"><span>Full address</span>${esc(b.address)}, ${esc(b.postcode)}</div>
        <div class="detail-block"><span>Submitted</span>${new Date(b.created_at).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'})}</div>
        <div class="detail-block"><span>Customer notes</span>${esc(b.notes)||'No notes provided'}</div>
        <div class="detail-block"><span>Customer photos</span>${gallery(b.photos)}</div>
        <div class="detail-block"><span>Cleaner timestamps</span>Accepted: ${stamp(b.accepted_at)}<br>Started: ${stamp(b.started_at)}<br>Completed: ${stamp(b.completed_at)}</div>
        <div class="detail-block"><span>Cleaner notes</span>${esc(b.cleaner_notes)||'No cleaner notes yet'}</div>
        <div class="detail-block"><span>Before photos</span>${gallery(b.before_photos)}</div>
        <div class="detail-block"><span>After photos</span>${gallery(b.after_photos)}</div>
        <div class="detail-block"><span>Price & payments</span><strong>${money(b.total_amount)} total</strong><br>Deposit: ${money(b.deposit_amount)}<br>Payment status: ${esc(b.payment_status)}${b.deposit_checkout_url?`<br><a class="balance-link" href="${esc(b.deposit_checkout_url)}" target="_blank">Deposit checkout link</a>`:'<br>No deposit checkout link stored'}${paymentHistory(b)}</div>
      </div></td></tr>`).join('')}</tbody></table>`;
  }catch(e){
    document.querySelector('#list').innerHTML='<div class="empty">Could not load bookings. Please refresh.</div>';
  }
}

function paymentHistory(b){
  return b.payments?.length?`<ul class="payment-history">${b.payments.map(p=>`<li>${esc(p.payment_type==='deposit'?'Deposit':'Balance')} - ${money(p.amount)} - ${esc(p.status)}</li>`).join('')}</ul>`:'<div class="date-sub">No payments recorded</div>';
}

function toggle(i){document.querySelector(`#detail-${i}`).classList.toggle('open')}

async function startBalancePayment(id,button){
  button.disabled=true;
  const original=button.textContent;
  button.textContent='Opening secure balance payment...';
  try{
    const r=await fetch(`/api/bookings/${id}/checkout`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({payment_type:'balance'})
    });
    const result=await r.json();
    if(!r.ok)throw new Error(result.error||'Could not open the balance payment.');
    window.open(result.url,'_blank','noopener');
    await load();
  }catch(e){
    alert(e.message);
  }finally{
    button.disabled=false;
    button.textContent=original;
  }
}

async function resendFinalInvoice(id,button){
  button.disabled=true;
  const original=button.textContent;
  button.textContent='Sending final email...';
  try{
    const r=await fetch(`/api/bookings/${id}/resend-final-invoice`,{method:'POST'});
    const result=await r.json();
    if(!r.ok)throw new Error(result.error||'Could not send the final balance email.');
    button.textContent='Email sent';
    await load();
  }catch(e){
    alert(e.message);
    button.disabled=false;
    button.textContent=original;
  }
}


async function archiveBooking(id,button,recoveredSessionId=''){
  const booking=bookings.find(x=>String(x.id)===String(id)||String(x.recovered_session_id||'')===String(recoveredSessionId||''));
  if(!confirm(`Archive ${booking?.reference||'this booking'} as test data? It will be hidden from the normal admin list and excluded from dashboard metrics.`))return;
  button.disabled=true;button.textContent='Archiving...';
  try{
    const url=recoveredSessionId?`/api/recovered-bookings/${encodeURIComponent(recoveredSessionId)}`:`/api/bookings/${encodeURIComponent(id)}`;
    const body=recoveredSessionId
      ?{archive_reason:'Archived recovered Stripe test booking from admin bookings'}
      :{archive:true,is_test:true,status:booking?.status||'Cancelled',archive_reason:'Archived as test data from admin bookings'};
    const r=await fetch(url,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await r.json();if(!r.ok)throw new Error(result.error||'Could not archive booking.');
    await load();
  }catch(e){button.disabled=false;button.textContent='Archive test';alert(e.message)}
}

async function openAssign(id){
  const b=bookings.find(x=>x.id===id);const root=document.querySelector('#modalRoot');
  root.innerHTML=`<div class="modal-backdrop" onclick="backdropClose(event)"><section class="modal"><div class="modal-head"><div><h2>Assign a cleaner</h2><p>${esc(b.clean_type)} - ${prettyDate(b.preferred_date)} - ${esc(b.postcode)}</p></div><button class="modal-close" onclick="closeModal()" aria-label="Close">x</button></div><div class="matches"><div class="no-matches">Finding nearby available cleaners...</div></div></section></div>`;
  try{
    const r=await fetch(`/api/bookings/${id}/matches`);const matches=await r.json();if(!r.ok)throw new Error(matches.error);
    const box=root.querySelector('.matches');
    if(!matches.length){box.innerHTML='<div class="no-matches"><strong>No eligible cleaners found</strong><br>Try adding a cleaner who offers this service, is available that day and covers this postcode.</div>';return}
    box.innerHTML=matches.map(c=>`<article class="match"><div><h3>${esc(c.name)}</h3><p>${c.distance} miles away - £${Number(c.hourly_rate).toFixed(2)}/hour - ${esc(c.postcode)}</p><div class="match-chips"><span>${esc(c.dbs_status)} DBS</span><span>${esc(c.insurance_status)} insurance</span></div></div><button onclick="assign(${id},${c.id},this)">Assign ${esc(c.name.split(' ')[0])}</button></article>`).join('');
  }catch(e){root.querySelector('.matches').innerHTML=`<div class="match-error">${esc(e.message||'Could not find cleaners.')}</div>`}
}

async function assign(bookingId,cleanerId,button){
  button.disabled=true;button.textContent='Assigning...';
  try{
    const r=await fetch(`/api/bookings/${bookingId}/assign`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cleaner_id:cleanerId})});
    const result=await r.json();if(!r.ok)throw new Error(result.error);
    closeModal();await load();
  }catch(e){button.disabled=false;button.textContent='Try again';alert(e.message)}
}

function closeModal(){document.querySelector('#modalRoot').innerHTML=''}
function backdropClose(e){if(e.target.classList.contains('modal-backdrop'))closeModal()}
document.querySelector('#adminLogout')?.addEventListener('click',async()=>{await fetch('/api/auth/logout',{method:'POST'});location.href='/admin/login'});
load();
setInterval(load,5000);


const esc=v=>{const d=document.createElement('div');d.textContent=v ?? '';return d.innerHTML};
let conversations=[],selectedId=null;

async function loadConversations(){
  const r=await fetch('/api/receptionist/conversations'),data=await r.json();
  if(!r.ok){location.href='/admin/login';return}
  conversations=data;
  const list=document.querySelector('#conversationList');
  list.innerHTML=data.length?data.map(c=>`<button class="conversation-item ${c.id===selectedId?'active':''}" onclick="openConversation(${c.id})"><strong>${esc(c.customer_name||c.customer_email||'Website visitor')}</strong><span>${esc(c.customer_phone||c.customer_email||'No contact yet')}</span><br><span class="conversation-status ${c.admin_takeover?'takeover':''}">${esc(c.status)}</span>${c.booking_reference?` <span class="conversation-status">${esc(c.booking_reference)}</span>`:''}</button>`).join(''):'<div class="empty">No conversations yet.</div>';
  if(selectedId)openConversation(selectedId,false);
}

async function openConversation(id,mark=true){
  selectedId=id;
  if(mark)loadConversations();
  const r=await fetch(`/api/receptionist/conversations/${id}`),data=await r.json();
  if(!r.ok)return;
  const c=data.conversation,details=JSON.parse(c.collected_details||'{}');
  document.querySelector('#conversationPanel').innerHTML=`
    <h2>${esc(c.customer_name||'Website visitor')}</h2>
    <div class="details-strip">
      <div><strong>${esc(c.status)}</strong>Status</div>
      <div><strong>${esc(c.customer_email||'Unknown')}</strong>Email</div>
      <div><strong>${esc(c.customer_phone||'Unknown')}</strong>Phone</div>
    </div>
    <div class="details-strip">
      <div><strong>${esc(details.clean_type||'Unknown')}</strong>Clean type</div>
      <div><strong>${esc(details.postcode||'Unknown')}</strong>Postcode</div>
      <div><strong>${c.booking_id?`Booking #${c.booking_id}`:'No booking yet'}</strong>Booking</div>
    </div>
    <div class="conversation-messages" id="messages">${data.messages.map(m=>`<div class="conversation-message ${esc(m.sender)}">${esc(m.message)}<div class="date-sub">${new Date(m.created_at).toLocaleString('en-GB')}</div></div>`).join('')}</div>
    <div class="conversation-actions">
      <textarea id="adminReply" placeholder="Type a manual reply to the customer…"></textarea>
      <div class="conversation-buttons">
        <button class="secondary" onclick="takeover(${id},${c.admin_takeover?0:1})">${c.admin_takeover?'Return to AI':'Take over manually'}</button>
        <button class="submit" onclick="sendReply(${id})">Send admin reply</button>
      </div>
    </div>`;
  const messages=document.querySelector('#messages');
  messages.scrollTop=messages.scrollHeight;
}

async function takeover(id,enabled){
  await fetch(`/api/receptionist/conversations/${id}/takeover`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({admin_takeover:!!enabled})});
  await openConversation(id);
}

async function sendReply(id){
  const box=document.querySelector('#adminReply'),message=box.value.trim();
  if(!message)return;
  const r=await fetch(`/api/receptionist/conversations/${id}/reply`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});
  if(!r.ok){alert('Could not send reply.');return}
  box.value='';
  await openConversation(id);
}

loadConversations();
setInterval(loadConversations,8000);

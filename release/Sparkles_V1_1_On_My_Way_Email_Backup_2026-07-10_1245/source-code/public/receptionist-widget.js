(()=> {
  const state={conversationId:localStorage.getItem('sparkles_chat_id'),open:false,seen:new Set()};
  const button=document.createElement('button');
  button.className='sparkles-chat-button';
  button.textContent='Chat with Sparkles AI';
  const panel=document.createElement('section');
  panel.className='sparkles-chat';
  panel.innerHTML=`<div class="sparkles-chat-head"><div><h2>Sparkles AI Receptionist</h2><p>Ask a question, get a quote, or book your clean.</p></div><button class="sparkles-chat-close" aria-label="Close">×</button></div><div class="sparkles-chat-body" id="sparklesChatBody"></div><form class="sparkles-chat-form"><input name="message" placeholder="Type your message…" autocomplete="off"><button>Send</button></form>`;
  document.body.append(button,panel);
  const body=panel.querySelector('#sparklesChatBody');
  const form=panel.querySelector('form');
  const input=form.elements.message;
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
  function linkify(text){
    return esc(text).replace(/(https?:\/\/[^\s]+)/g,'<a class="chat-pay" href="$1" target="_blank">$1</a>');
  }
  function add(sender,message){
    const div=document.createElement('div');
    div.className=`chat-msg ${sender}`;
    div.innerHTML=linkify(message);
    body.appendChild(div);body.scrollTop=body.scrollHeight;
  }
  async function loadMessages(){
    if(!state.conversationId){
      await start(true);
      return;
    }
    const r=await fetch(`/api/receptionist/conversations/${state.conversationId}/messages`);
    const data=await r.json();
    if(!r.ok){
      await start(true);
      return;
    }
    if(data.conversation_id&&String(data.conversation_id)!==String(state.conversationId)){
      state.conversationId=data.conversation_id;
      state.seen.clear();
      localStorage.setItem('sparkles_chat_id',state.conversationId);
    }
    const messages=Array.isArray(data)?data:(data.messages||[]);
    messages.forEach(m=>{
      if(state.seen.has(m.id))return;
      state.seen.add(m.id);
      add(m.sender,m.message);
    });
  }
  async function start(force=false){
    if(state.conversationId&&!force)return;
    const r=await fetch('/api/receptionist/start',{method:'POST'}),data=await r.json();
    if(!r.ok)throw new Error(data.error||'Could not start chat.');
    state.conversationId=data.conversation_id;
    state.seen.clear();
    body.innerHTML='';
    localStorage.setItem('sparkles_chat_id',state.conversationId);
    await loadMessages();
  }
  async function open(){
    panel.classList.add('open');state.open=true;
    if(!state.conversationId)await start();
    await loadMessages();
    input.focus();
  }
  button.onclick=()=>state.open?(panel.classList.remove('open'),state.open=false):open();
  panel.querySelector('.sparkles-chat-close').onclick=()=>{panel.classList.remove('open');state.open=false};
  form.onsubmit=async e=>{
    e.preventDefault();
    const message=input.value.trim();
    if(!message)return;
    input.value='';
    const typing=document.createElement('div');
    typing.className='chat-typing';typing.textContent='Sparkles is typing…';body.appendChild(typing);
    try{
      if(!state.conversationId)await start();
      const r=await fetch('/api/receptionist/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:state.conversationId,message})});
      const data=await r.json();
      typing.remove();
      if(!r.ok)throw new Error(data.error||'Could not send message.');
      if(data.conversation_id&&String(data.conversation_id)!==String(state.conversationId)){
        state.conversationId=data.conversation_id;
        state.seen.clear();
        body.innerHTML='';
        localStorage.setItem('sparkles_chat_id',state.conversationId);
      }
      await loadMessages();
    }catch(error){
      typing.remove();
      await start(true);
    }
  };
  setInterval(()=>{if(state.open)loadMessages()},5000);
})();

const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format((p||0)/100);
const prettyDate=v=>new Date(`${v}T12:00:00`).toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'});
const metricGrid=document.querySelector('#metricGrid');
const revenueChart=document.querySelector('#revenueChart');
const statusChart=document.querySelector('#statusChart');
const upcomingJobs=document.querySelector('#upcomingJobs');
const recentReviews=document.querySelector('#recentReviews');

const metricConfig=[
  ['Revenue Today','revenue_today','money','Successful payments today'],
  ['Revenue This Week','revenue_week','money','Monday to today'],
  ["Today's Jobs",'today_bookings','number','Scheduled for today'],
  ['Bookings Waiting','waiting_assignment','warning','Ready for assignment'],
  ['Cleaners Working','active_cleaners','number','Active cleaner accounts'],
  ['Outstanding Balances','outstanding_balances','pending','Metric not changed in design-system phase'],
  ['Sparkles AI Summary','ai_waiting_review','warning','Conversations to review']
];

function formatMetric(type,value){
  if(type==='money')return money(value);
  if(type==='percent')return `${Number(value||0).toFixed(1)}%`;
  if(type==='pending')return value ?? '—';
  return value??0;
}

function renderMetrics(cards){
  metricGrid.innerHTML=metricConfig.map(([label,key,type,sub])=>`
    <article class="owner-card sp-card ${type==='money'?'money':''} ${type==='warning'?'warning':''} ${type==='success'?'success':''} ${type==='pending'?'pending':''}">
      <span>${esc(label)}</span>
      <strong>${esc(formatMetric(type,cards[key]))}</strong>
      <small>${esc(sub)}</small>
    </article>
  `).join('');
}

function renderRevenue(days){
  const max=Math.max(...days.map(d=>d.amount),1);
  revenueChart.innerHTML=days.map(d=>{
    const height=Math.max(7,Math.round((d.amount/max)*150));
    return `<div class="bar-item"><div class="bar-value">${money(d.amount)}</div><div class="bar" style="height:${height}px"></div><div class="bar-label">${esc(d.label)}</div></div>`;
  }).join('');
}

function renderAiSummary(cards){
  const waiting=Number(cards.waiting_assignment||0);
  const cleaners=Number(cards.active_cleaners||0);
  const reviews=Number(cards.ai_waiting_review||0);
  statusChart.innerHTML=`
    <div class="ai-pulse">
      <p><strong>Good morning Luke.</strong></p>
      <p>Revenue today ${money(cards.revenue_today)}.</p>
      <p>${waiting} booking${waiting===1?'':'s'} require assigning.</p>
      <p>${cleaners} cleaner${cleaners===1?'':'s'} available.</p>
      <p>${reviews} Sparkles AI conversation${reviews===1?'':'s'} waiting for review.</p>
      <p>Everything is running smoothly.</p>
    </div>
  `;
}

function renderUpcoming(rows){
  upcomingJobs.innerHTML=rows.length?rows.map(job=>`
    <article class="mini-item">
      <strong>${esc(job.reference)} · ${esc(job.name)}</strong>
      <span>${prettyDate(job.preferred_date)} · ${esc(job.preferred_time)} · ${esc(job.clean_type)}</span>
      <span>${esc(job.status)}${job.cleaner_name?` · ${esc(job.cleaner_name)}`:' · No cleaner assigned'}</span>
    </article>
  `).join(''):'<div class="empty-mini">No jobs scheduled for today or tomorrow.</div>';
}

function renderReviews(rows){
  recentReviews.innerHTML=rows.length?rows.map(review=>`
    <article class="mini-item">
      <strong><span class="stars">${'★'.repeat(Math.max(1,Math.min(5,review.rating||5)))}</span> ${esc(review.customer_name||'Customer')}</strong>
      <span>${esc(review.comment||'No written comment')} ${review.booking_reference?`· ${esc(review.booking_reference)}`:''}</span>
      <span>${new Date(review.created_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})}</span>
    </article>
  `).join(''):'<div class="empty-mini">No customer reviews recorded yet.</div>';
}

function sessionExpired(){
  metricGrid.innerHTML='<div class="owner-card loading sp-loader">Your admin session expired. Redirecting to login…</div>';
  setTimeout(()=>{location.href='/admin/login?expired=1'},350);
}

async function loadDashboard(){
  try{
    const sessionResponse=await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store'});
    const session=await sessionResponse.json();
    if(!session.authenticated||session.session?.role!=='admin'){sessionExpired();return}
    const r=await fetch('/api/admin/dashboard',{credentials:'same-origin',cache:'no-store'});
    const data=await r.json();
    if(r.status===401){sessionExpired();return}
    if(!r.ok)throw new Error(data.error||'Could not load dashboard.');
    renderMetrics(data.cards);
    renderRevenue(data.charts.revenue_days||[]);
    renderAiSummary(data.cards);
    renderUpcoming(data.upcoming||[]);
    renderReviews(data.reviews||[]);
  }catch(error){
    metricGrid.innerHTML='<div class="owner-card loading sp-loader">Could not load the command centre. Please refresh.</div>';
  }
}

document.querySelector('#refreshDashboard').addEventListener('click',loadDashboard);
document.querySelector('#adminLogout')?.addEventListener('click',async()=>{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});location.href='/admin/login'});
loadDashboard();
setInterval(loadDashboard,30000);

const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format((p||0)/100);
const prettyDate=v=>new Date(`${v}T12:00:00`).toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'});
const metricGrid=document.querySelector('#metricGrid');
const revenueChart=document.querySelector('#revenueChart');
const statusChart=document.querySelector('#statusChart');
const upcomingJobs=document.querySelector('#upcomingJobs');
const recentReviews=document.querySelector('#recentReviews');

const metricConfig=[
  ['Revenue today','revenue_today','money','Successful payments today'],
  ['Revenue this week','revenue_week','money','Monday to today'],
  ['Revenue this month','revenue_month','money','Month to date'],
  ['Deposits today','deposits_today','money','Deposits received today'],
  ['Total bookings','total_bookings','number','All booking requests'],
  ["Today's bookings",'today_bookings','number','Scheduled for today'],
  ["Tomorrow's bookings",'tomorrow_bookings','number','Scheduled for tomorrow'],
  ['Waiting assignment','waiting_assignment','warning','Jobs needing a cleaner'],
  ['Jobs in progress','in_progress','warning','Cleaner has started'],
  ['Completed today','completed_today','success','Finished today'],
  ['Active cleaners','active_cleaners','number','Available cleaner accounts'],
  ['AI review queue','ai_waiting_review','warning','Conversations to check'],
  ['Conversion rate','booking_conversion_rate','percent','Paid deposit bookings'],
  ['Average booking value','average_job_value','money','Across quoted bookings']
];

function formatMetric(type,value){
  if(type==='money')return money(value);
  if(type==='percent')return `${Number(value||0).toFixed(1)}%`;
  return value??0;
}

function renderMetrics(cards){
  metricGrid.innerHTML=metricConfig.map(([label,key,type,sub])=>`
    <article class="owner-card ${type==='money'?'money':''} ${type==='warning'?'warning':''} ${type==='success'?'success':''}">
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

function renderStatuses(rows){
  const total=rows.reduce((sum,row)=>sum+Number(row.count||0),0)||1;
  statusChart.innerHTML=rows.length?rows.map(row=>{
    const width=Math.max(5,Math.round((row.count/total)*100));
    return `<div class="status-row"><div class="status-name">${esc(row.status)}</div><div class="status-track"><div class="status-fill" style="width:${width}%"></div></div><div class="status-count">${row.count}</div></div>`;
  }).join(''):'<div class="empty-mini">No bookings yet.</div>';
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

async function loadDashboard(){
  try{
    const r=await fetch('/api/admin/dashboard');
    const data=await r.json();
    if(!r.ok){location.href='/admin/login';return}
    renderMetrics(data.cards);
    renderRevenue(data.charts.revenue_days||[]);
    renderStatuses(data.charts.booking_statuses||[]);
    renderUpcoming(data.upcoming||[]);
    renderReviews(data.reviews||[]);
  }catch(error){
    metricGrid.innerHTML='<div class="owner-card loading">Could not load the command centre. Please refresh.</div>';
  }
}

document.querySelector('#refreshDashboard').addEventListener('click',loadDashboard);
document.querySelector('#adminLogout')?.addEventListener('click',async()=>{await fetch('/api/auth/logout',{method:'POST'});location.href='/admin/login'});
loadDashboard();
setInterval(loadDashboard,30000);

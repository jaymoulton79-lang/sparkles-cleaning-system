const esc=v=>{const d=document.createElement('div');d.textContent=v ?? '';return d.innerHTML};
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format((p||0)/100);
const prettyDate=v=>new Date(`${v}T12:00:00`).toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'});
const metricGrid=document.querySelector('#metricGrid');
const revenueChart=document.querySelector('#revenueChart');
const statusChart=document.querySelector('#statusChart');
const upcomingJobs=document.querySelector('#upcomingJobs');
const recentReviews=document.querySelector('#recentReviews');
const ownerHealthMessage=document.querySelector('#ownerHealthMessage');
const operationsHealth=document.querySelector('#operationsHealth');
const operationsSummary=document.querySelector('#operationsSummary');

const metricConfig=[
  ['Revenue Today','revenue_today','money','Successful payments today'],
  ['Revenue This Week','revenue_week','money','Monday to today'],
  ["Today's Jobs",'today_bookings','number','Scheduled for today'],
  ['Bookings Waiting','waiting_assignment','warning','Ready for assignment'],
  ['Cleaners Working','active_cleaners','number','Active cleaner accounts'],
  ['Outstanding Balances','outstanding_balances','money','Unpaid customer balances'],
  ['Sparkles AI Summary','ai_waiting_review','warning','Conversations to review']
];

function formatMetric(type,value){
  if(type==='money')return money(value);
  if(type==='percent')return `${Number(value||0).toFixed(1)}%`;
  if(type==='pending')return value ?? '—';
  return value ?? 0;
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

function renderAiSummary(cards,health){
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
      <p>${esc(health?.message||'Your operational view is up to date.')}</p>
    </div>
  `;
}

function renderUpcoming(rows){
  upcomingJobs.innerHTML=rows.length?rows.map(job=>`
    <article class="mini-item">
      <strong>${esc(job.reference)} Â· ${esc(job.name)}</strong>
      <span>${prettyDate(job.preferred_date)} Â· ${esc(job.preferred_time)} Â· ${esc(job.clean_type)}</span>
      <span>${esc(job.status)}${job.cleaner_name?` Â· ${esc(job.cleaner_name)}`:' Â· No cleaner assigned'}</span>
    </article>
  `).join(''):'<div class="empty-mini">No jobs scheduled for today or tomorrow.</div>';
}

function renderReviews(rows){
  recentReviews.innerHTML=rows.length?rows.map(review=>`
    <article class="mini-item">
      <strong><span class="stars">${'â˜…'.repeat(Math.max(1,Math.min(5,review.rating||5)))}</span> ${esc(review.customer_name||'Customer')}</strong>
      <span>${esc(review.comment||'No written comment')} ${review.booking_reference?`Â· ${esc(review.booking_reference)}`:''}</span>
      <span>${new Date(review.created_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})}</span>
    </article>
  `).join(''):'<div class="empty-mini">No customer reviews recorded yet.</div>';
}

function issueListMarkup(items,emptyMessage){
  return items.length?items.map(issue=>{
    const related=issue.related_record?.reference||issue.related_record?.id||'';
    return `
      <article class="operations-issue">
        <div class="operations-issue-top">
          <span class="operations-category">${esc(issue.category)}</span>
          ${related?`<small>${esc(related)}</small>`:''}
        </div>
        <strong>${esc(issue.title)}</strong>
        ${issue.detail?`<p>${esc(issue.detail)}</p>`:''}
        <div class="operations-action">
          <span>${esc(issue.recommended_action)}</span>
          <a href="${esc(issue.admin_url||'/admin/dashboard')}">Open</a>
        </div>
      </article>
    `;
  }).join(''):`<div class="operations-empty">${esc(emptyMessage)}</div>`;
}

function renderOperationsManager(operations){
  if(!operations){
    operationsHealth.className='operations-health-pill is-attention';
    operationsHealth.textContent='Unavailable';
    ownerHealthMessage.textContent='The Operations Manager could not load. The main dashboard remains available.';
    return;
  }
  const health=operations.business_health||{};
  const summary=operations.summary||{};
  const groups=operations.groups||{};
  const critical=groups.critical||[];
  const attention=groups.needs_attention||[];
  const suggested=groups.suggested_actions||[];
  const activity=groups.recent_activity||[];
  const healthClass=health.status==='Critical'?'is-critical':health.status==='Needs Attention'?'is-attention':'is-healthy';
  operationsHealth.className=`operations-health-pill ${healthClass}`;
  operationsHealth.textContent=`${health.status||'Unknown'} · ${Number(health.score||0)}/100`;
  ownerHealthMessage.textContent=health.message||'Your latest operational view is ready.';
  const summaryCards=[
    ["Today's Revenue",money(summary.today_revenue),'Successful payments today'],
    ['Bookings Today',summary.bookings_today??0,'Scheduled for today'],
    ['Available Cleaners',summary.available_cleaners??0,'Activated and available today'],
    ['Jobs Awaiting Assignment',summary.jobs_awaiting_assignment??0,'Paid bookings needing a cleaner'],
    ['Outstanding Balances',money(summary.outstanding_balances),'Customer balances still due']
  ];
  operationsSummary.innerHTML=summaryCards.map(([label,value,description])=>`
    <article class="operations-summary-card">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
      <small>${esc(description)}</small>
    </article>
  `).join('');
  document.querySelector('#criticalCount').textContent=critical.length;
  document.querySelector('#attentionCount').textContent=attention.length;
  document.querySelector('#suggestedCount').textContent=suggested.length;
  document.querySelector('#activityCount').textContent=activity.length;
  document.querySelector('#criticalIssues').innerHTML=issueListMarkup(critical,'No critical issues.');
  document.querySelector('#attentionIssues').innerHTML=issueListMarkup(attention,'Nothing currently needs attention.');
  document.querySelector('#suggestedActions').innerHTML=issueListMarkup(suggested,'No suggested actions right now.');
  document.querySelector('#recentOperationsActivity').innerHTML=issueListMarkup(activity,'No recent activity recorded.');
}

function sessionExpired(){
  metricGrid.innerHTML='<div class="owner-card loading sp-loader">Your admin session expired. Redirecting to loginâ€¦</div>';
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
    renderAiSummary(data.cards,data.operations_manager?.business_health);
    renderUpcoming(data.upcoming||[]);
    renderReviews(data.reviews||[]);
    renderOperationsManager(data.operations_manager);
  }catch(error){
    metricGrid.innerHTML='<div class="owner-card loading sp-loader">Could not load the Sparkles Owner Command Centre. Please refresh.</div>';
    renderOperationsManager(null);
  }
}

document.querySelector('#refreshDashboard').addEventListener('click',loadDashboard);
document.querySelector('#adminLogout')?.addEventListener('click',async()=>{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});location.href='/admin/login'});
loadDashboard();
setInterval(loadDashboard,30000);

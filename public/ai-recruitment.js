const esc = value => {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
};

let latestCopy = '';
let latestShort = '';
let latestPlan = '';
const recruitmentChannels = [
  { name: 'Facebook', source: 'facebook', icon: 'f', hint: 'Copy the advert and post it on your Sparkles page or approved local groups.' },
  { name: 'WhatsApp', source: 'whatsapp', icon: '💬', hint: 'Send to trusted local contacts and community chats.' },
  { name: 'Indeed', source: 'indeed', icon: 'in', hint: 'Paste this as the apply link when you create an Indeed job advert.' },
  { name: 'Google Business Profile', source: 'google-business-profile', icon: 'G', hint: 'Add the link to a Google Business Profile update.' },
  { name: 'Gumtree', source: 'gumtree', icon: 'G', hint: 'Use in a local cleaner opportunity advert.' },
  { name: 'Referral', source: 'referral', icon: '↗', hint: 'Share with friends, family and existing cleaners.' }
];

async function copyText(text, button){
  await navigator.clipboard.writeText(text);
  const old = button.textContent;
  button.textContent = 'Copied';
  setTimeout(()=>button.textContent=old, 1200);
}

function recommendationClass(value){
  return String(value || '').toLowerCase().replaceAll(' ', '-');
}

function renderStats(data){
  const counts = data.counts || {};
  document.querySelector('#recruitmentStats').innerHTML = `
    <div><span>Total applicants</span><strong>${counts.total || 0}</strong></div>
    <div><span>Recommended</span><strong>${counts.recommended || 0}</strong></div>
    <div><span>Active cleaners</span><strong>${counts.active_cleaners || 0}</strong></div>
    <div><span>Needs review</span><strong>${counts.needs_review || 0}</strong></div>
  `;
  document.querySelector('#recommendationBreakdown').innerHTML = `
    <span>Excellent ${counts.excellent || 0}</span>
    <span>Good ${counts.good || 0}</span>
    <span>Review ${counts.review || 0}</span>
    <span>Weak ${counts.weak || 0}</span>
  `;
  const sources = Object.entries(data.sources || {});
  document.querySelector('#sourceBreakdown').innerHTML = sources.length
    ? sources.map(([source,count]) => `<div><span>${esc(source)}</span><strong>${count} applicant${count===1?'':'s'}</strong></div>`).join('')
    : '<div class="empty-mini">No applicant sources yet.</div>';
}

function applyLink(source){
  return `${location.origin}/r/cleaners/${encodeURIComponent(source)}`;
}

function recruitmentMessage(channel){
  const link = applyLink(channel.source);
  return `Sparkles Cleaning Cambridge is looking for reliable cleaners for flexible local cleaning work.\n\nChoose your availability, local jobs, friendly support and competitive pay.\n\nApply here:\n${link}`;
}

function renderEngineLinks(){
  const root = document.querySelector('#engineLinks');
  if(!root) return;
  root.innerHTML = recruitmentChannels.map(channel => {
    const link = applyLink(channel.source);
    const message = recruitmentMessage(channel);
    const whatsapp = `https://wa.me/?text=${encodeURIComponent(message)}`;
    const facebook = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(link)}`;
    return `<article class="engine-card">
      <div class="engine-icon">${esc(channel.icon)}</div>
      <div>
        <h3>${esc(channel.name)}</h3>
        <p>${esc(channel.hint)}</p>
        <input readonly value="${esc(link)}" aria-label="${esc(channel.name)} recruitment link">
        <div class="campaign-actions">
          <button class="secondary" onclick="copyText('${esc(link)}',this)">Copy link</button>
          <button class="secondary" onclick="copyText(${JSON.stringify(message).replaceAll('"', '&quot;')},this)">Copy post</button>
          ${channel.name === 'WhatsApp' ? `<a class="secondary" href="${whatsapp}" target="_blank" rel="noopener">Open WhatsApp</a>` : ''}
          ${channel.name === 'Facebook' ? `<a class="secondary" href="${facebook}" target="_blank" rel="noopener">Open Facebook</a>` : ''}
        </div>
      </div>
    </article>`;
  }).join('');
}

async function sendFollowUp(applicantId, template, button){
  const old = button.textContent;
  button.disabled = true;
  button.textContent = 'Sending...';
  try{
    const response = await fetch(`/api/ai-recruitment/applicants/${applicantId}/follow-up`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({template})
    });
    const data = await response.json();
    if(!response.ok) throw new Error(data.error || 'Could not send follow-up.');
    button.textContent = 'Sent';
    await loadRecruitment();
  }catch(error){
    button.textContent = 'Failed';
    alert(error.message);
    setTimeout(()=>button.textContent=old, 1400);
  }finally{
    button.disabled = false;
  }
}

function renderShortlist(applicants){
  const root = document.querySelector('#shortlist');
  if(!applicants.length){
    root.innerHTML = '<div class="empty card-wide">No applicants yet. Generate an advert and share your application link first.</div>';
    return;
  }
  const ordered = [...applicants].sort((a,b)=>(b.score||0)-(a.score||0));
  root.innerHTML = ordered.map(applicant => {
    const recClass = recommendationClass(applicant.recommendation);
    const reasons = applicant.reasons?.length ? applicant.reasons : ['Not enough positive signals yet'];
    const risks = applicant.risks?.length ? applicant.risks : ['No major risks flagged'];
    const isAdded = applicant.recommendation === 'Already added';
    return `<article class="shortlist-card ${recClass}">
      <div class="shortlist-head">
        <div>
          <h3>${esc(applicant.name)}</h3>
          <p>${esc(applicant.email)} · ${esc(applicant.phone)}</p>
        </div>
        <div class="score-ring">${Number(applicant.score || 0)}</div>
      </div>
      <span class="recommendation ${recClass}">${esc(applicant.recommendation)}</span>
      <p><strong>${esc(applicant.postcode || 'No postcode')}</strong> · ${Number(applicant.travel_radius||0)} mile radius · £${Number(applicant.hourly_rate||0).toFixed(2)}/hr</p>
      <p><strong>Status:</strong> ${esc(applicant.status || 'New')} · <strong>Source:</strong> ${esc(applicant.source || 'Unknown')}</p>
      <p><strong>Availability:</strong> ${esc((applicant.availability||[]).join(', ') || 'Not supplied')}</p>
      <p><strong>Services:</strong> ${esc((applicant.services||[]).join(', ') || 'Not supplied')}</p>
      <div>
        <strong>Why:</strong>
        <ul class="reason-list">${reasons.map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul>
      </div>
      <div>
        <strong>Check:</strong>
        <ul class="risk-list">${risks.map(risk=>`<li>${esc(risk)}</li>`).join('')}</ul>
      </div>
      <div class="shortlist-actions">
        <button class="secondary" ${isAdded ? 'disabled' : ''} onclick="sendFollowUp(${Number(applicant.id)},'shortlist',this)">Send next-step email</button>
        <button class="secondary" ${isAdded ? 'disabled' : ''} onclick="sendFollowUp(${Number(applicant.id)},'missing',this)">Ask for missing details</button>
        <a class="secondary" href="/admin/cleaner-applicants">Approve / review</a>
      </div>
    </article>`;
  }).join('');
}

async function loadRecruitment(){
  const response = await fetch('/api/ai-recruitment/summary');
  const data = await response.json();
  if(!response.ok){
    document.querySelector('#shortlist').innerHTML = '<div class="empty card-wide">Could not load AI recruitment summary.</div>';
    return;
  }
  renderStats(data);
  renderShortlist(data.applicants || []);
}

function renderAutopilotStatus(data){
  const counts = data.counts || {};
  document.querySelector('#autopilotStats').innerHTML = `
    <div><span>Clicks</span><strong>${counts.clicks || 0}</strong></div>
    <div><span>Applicants</span><strong>${counts.applicants || 0}</strong></div>
    <div><span>Recommended</span><strong>${counts.recommended || 0}</strong></div>
    <div><span>Conversion</span><strong>${counts.conversion_rate || 0}%</strong></div>
  `;

  const actions = data.actions || [];
  document.querySelector('#autopilotActions').innerHTML = actions.length
    ? actions.map(action => `<a class="autopilot-action ${String(action.priority || '').toLowerCase()}" href="${esc(action.href || '#')}">
        <strong>${esc(action.priority || 'Info')} · ${esc(action.title)}</strong>
        <span>${esc(action.detail)}</span>
      </a>`).join('')
    : '<div class="empty-mini">No owner action needed right now.</div>';

  const sources = data.sources || [];
  document.querySelector('#trackedSources').innerHTML = sources.map(source => {
    const text = source.share_text || recruitmentMessage({ source: source.source });
    const whatsapp = `https://wa.me/?text=${encodeURIComponent(text)}`;
    const facebook = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(source.tracked_link)}`;
    return `<article class="tracked-source-card">
      <div>
        <h4>${esc(source.label)}</h4>
        <p>${Number(source.clicks || 0)} click${Number(source.clicks || 0)===1?'':'s'} · ${Number(source.applicants || 0)} applicant${Number(source.applicants || 0)===1?'':'s'} · ${Number(source.conversion_rate || 0)}% conversion</p>
        <input readonly value="${esc(source.tracked_link)}">
      </div>
      <div class="campaign-actions">
        <button class="secondary" onclick="copyText('${esc(source.tracked_link)}',this)">Copy link</button>
        <button class="secondary" onclick="copyText(${JSON.stringify(text).replaceAll('"', '&quot;')},this)">Copy post</button>
        <a class="secondary" href="${whatsapp}" target="_blank" rel="noopener">WhatsApp</a>
        <a class="secondary" href="${facebook}" target="_blank" rel="noopener">Facebook</a>
      </div>
    </article>`;
  }).join('');
}

async function loadAutopilotStatus(){
  const response = await fetch('/api/ai-recruitment/autopilot-status');
  const data = await response.json();
  if(!response.ok){
    document.querySelector('#trackedSources').innerHTML = '<div class="empty-mini">Could not load recruitment Autopilot status.</div>';
    return;
  }
  renderAutopilotStatus(data);
}

document.querySelector('#autopilotForm').addEventListener('submit', async event => {
  event.preventDefault();
  const output = document.querySelector('#autopilotOutput');
  output.textContent = 'Creating weekly posting plan...';
  const payload = Object.fromEntries(new FormData(event.target));
  const response = await fetch('/api/ai-recruitment/autopilot-plan', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  const data = await response.json();
  if(!response.ok){
    output.textContent = data.error || 'Could not create weekly posting plan.';
    return;
  }
  latestPlan = [
    `Cleaner recruitment area: ${data.area}`,
    `Target applicants: ${data.target}`,
    '',
    ...data.weekly_plan.map(item => `Day ${item.day}: ${item.channel}\n${item.action}\nGoal: ${item.goal}\nApply link: ${item.apply_link}`),
    '',
    'Checklist:',
    ...data.checklist.map(item => `- ${item}`)
  ].join('\n\n');
  output.innerHTML = `
    <h3>Weekly cleaner posting plan</h3>
    <div class="plan-list">
      ${data.weekly_plan.map(item => `<div>
        <strong>Day ${item.day}: ${esc(item.channel)}</strong>
        <p>${esc(item.action)}</p>
        <p><strong>Goal:</strong> ${esc(item.goal)}</p>
        <p><strong>Tracked link:</strong> <a href="${esc(item.apply_link)}" target="_blank">${esc(item.apply_link)}</a></p>
      </div>`).join('')}
    </div>
    <div class="campaign-actions">
      <button class="secondary" onclick="copyText(latestPlan,this)">Copy full plan</button>
    </div>
  `;
});

document.querySelector('#campaignForm').addEventListener('submit', async event => {
  event.preventDefault();
  const output = document.querySelector('#campaignOutput');
  output.textContent = 'Generating advert...';
  const payload = Object.fromEntries(new FormData(event.target));
  const response = await fetch('/api/ai-recruitment/campaign-copy', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  const data = await response.json();
  if(!response.ok){
    output.textContent = data.error || 'Could not generate advert.';
    return;
  }
  latestCopy = `${data.title}\n\n${data.body}`;
  latestShort = data.short || '';
  output.innerHTML = `
    <h3>${esc(data.title)}</h3>
    <p>${esc(data.body)}</p>
    <div class="campaign-actions">
      <button class="secondary" onclick="copyText(latestCopy,this)">Copy full advert</button>
      <button class="secondary" onclick="copyText(latestShort,this)">Copy short post</button>
      <a class="secondary" href="${esc(data.apply_link)}" target="_blank">Open apply link</a>
    </div>
  `;
});

document.querySelector('#refreshRecruitment').addEventListener('click', loadRecruitment);
document.querySelector('#refreshAutopilotStatus').addEventListener('click', loadAutopilotStatus);
renderEngineLinks();
loadRecruitment();
loadAutopilotStatus();

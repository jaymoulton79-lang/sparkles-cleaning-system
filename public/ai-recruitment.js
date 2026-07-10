const esc = value => {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
};

let latestCopy = '';
let latestShort = '';

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
    <div><span>Maybe</span><strong>${counts.maybe || 0}</strong></div>
    <div><span>Needs review</span><strong>${counts.needs_review || 0}</strong></div>
  `;
  const sources = Object.entries(data.sources || {});
  document.querySelector('#sourceBreakdown').innerHTML = sources.length
    ? sources.map(([source,count]) => `<div><span>${esc(source)}</span><strong>${count} applicant${count===1?'':'s'}</strong></div>`).join('')
    : '<div class="empty-mini">No applicant sources yet.</div>';
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
        <a class="secondary" href="/admin/cleaner-applicants">Open applicant list</a>
        <a class="secondary" href="mailto:${esc(applicant.email)}">Email</a>
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
loadRecruitment();

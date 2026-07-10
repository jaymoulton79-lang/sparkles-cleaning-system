const money = pence => `£${((Number(pence || 0)) / 100).toFixed(2)}`;
const text = value => value == null ? '' : String(value);

async function copyLaunchText(value, button){
  await navigator.clipboard.writeText(value);
  const old = button.textContent;
  button.textContent = 'Copied';
  setTimeout(()=>button.textContent=old, 1200);
}

function stat(label, value){
  return `<div class="launch-stat"><span>${label}</span><strong>${value}</strong></div>`;
}

function renderStats(cards){
  document.querySelector('#launchStats').innerHTML = [
    stat('New applicants', cards.new_applicants || 0),
    stat('Active cleaners', cards.active_cleaners || 0),
    stat('Bookings', cards.total_bookings || 0),
    stat('Revenue this week', money(cards.revenue_week)),
    stat('Waiting assignment', cards.waiting_assignment || 0),
    stat('Outstanding balances', money(cards.outstanding_balances)),
    stat('Recommended cleaners', cards.recommended_applicants || 0),
    stat('Applicant pool', cards.applicants_total || 0)
  ].join('');
}

function renderActions(actions){
  document.querySelector('#launchActions').innerHTML = (actions || []).map(action => `
    <article class="action-card">
      <div>
        <span class="action-pill">${text(action.priority)}</span>
        <strong>${text(action.title)}</strong>
        <p>${text(action.detail)}</p>
      </div>
      <a class="launch-button" href="${text(action.href)}" ${String(action.href || '').startsWith('http') ? 'target="_blank"' : ''}>${text(action.button)}</a>
    </article>
  `).join('');
}

function renderLinks(data){
  const links = [
    ['Customer booking page', data.booking_link],
    ['Cleaner apply - Facebook', data.cleaner_links?.facebook],
    ['Cleaner apply - WhatsApp', data.cleaner_links?.whatsapp],
    ['Cleaner apply - Indeed', data.cleaner_links?.indeed],
    ['Open Facebook', 'https://www.facebook.com/'],
    ['Open WhatsApp Web', 'https://web.whatsapp.com/'],
    ['Open Indeed', 'https://uk.indeed.com/'],
    ['Open Gumtree', 'https://www.gumtree.com/']
  ];
  document.querySelector('#quickLinks').innerHTML = links.map(([label, href]) => `
    <a class="quick-link" href="${text(href)}" target="_blank">${label}</a>
  `).join('');
}

function renderCopyBlocks(copy){
  const blocks = [
    ['Cleaner Facebook post', copy.cleaner_facebook],
    ['Cleaner WhatsApp referral', copy.whatsapp_referral],
    ['Customer Facebook post', copy.customer_facebook],
    ['Customer WhatsApp message', copy.customer_whatsapp]
  ];
  document.querySelector('#copyBlocks').innerHTML = blocks.map(([title, body], index) => `
    <article class="copy-block">
      <h3>${title}</h3>
      <textarea id="copyBlock${index}" readonly>${text(body)}</textarea>
      <div class="copy-actions">
        <button class="copy-button" onclick="copyLaunchText(document.querySelector('#copyBlock${index}').value,this)">Copy</button>
      </div>
    </article>
  `).join('');
}

function renderApplicants(applicants){
  const root = document.querySelector('#recentApplicants');
  if(!applicants || !applicants.length){
    root.innerHTML = '<div class="empty-launch">No applicants yet. Start with the cleaner advert.</div>';
    return;
  }
  root.innerHTML = applicants.map(applicant => `
    <article class="applicant-mini">
      <strong>${text(applicant.name)}</strong>
      <span>${text(applicant.email)} · ${text(applicant.phone)}</span>
      <span>${text(applicant.postcode)} · ${text(applicant.source || 'Unknown source')}</span>
      <span class="recommendation">${text(applicant.recommendation || 'Needs review')}</span>
    </article>
  `).join('');
}

async function loadLaunchConsole(){
  const response = await fetch('/api/admin/launch-console');
  const data = await response.json();
  if(!response.ok){
    if(response.status === 401) location.href = '/admin/login?expired=1';
    return;
  }
  renderStats(data.cards || {});
  renderActions(data.actions || []);
  renderLinks(data);
  renderCopyBlocks(data.copy || {});
  renderApplicants(data.recent_applicants || []);
}

document.querySelector('#refreshLaunch').addEventListener('click', loadLaunchConsole);
loadLaunchConsole();

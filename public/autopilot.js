let autopilotState = { automations: [], logs: [], runs: [], alerts: [], facebook: null };
let activeConfigKey = null;

const grid = document.getElementById('automationGrid');
const attentionList = document.getElementById('attentionList');
const attentionCount = document.getElementById('attentionCount');
const recentActivity = document.getElementById('recentActivity');
const runHistory = document.getElementById('runHistory');
const configDialog = document.getElementById('configDialog');
const configTitle = document.getElementById('configTitle');
const configKicker = document.getElementById('configKicker');
const configFields = document.getElementById('configFields');
const toast = document.getElementById('toast');
const facebookDialog = document.getElementById('facebookDialog');
const facebookDraftStatus = document.getElementById('facebookDraftStatus');
const facebookDraftMessage = document.getElementById('facebookDraftMessage');
const facebookDraftLink = document.getElementById('facebookDraftLink');
const facebookPublishButton = document.getElementById('facebookPublishButton');

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 3200);
}

function fmtDate(value) {
  if (!value) return 'Just now';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function automationName(key) {
  const item = autopilotState.automations.find((automation) => automation.key === key);
  return item ? item.name : key.replaceAll('_', ' ');
}

function facebookPanelMarkup() {
  const facebook = autopilotState.facebook || {};
  const connection = facebook.configured ? 'Railway credentials ready' : 'Railway setup required';
  const approval = facebook.published ? 'Published' : facebook.approved ? 'Approved' : 'Draft not approved';
  const publishLabel = String(facebook.mode || 'Dry run').toLowerCase() === 'live' ? 'Publish approved post' : 'Run safe dry test';
  return `
    <section class="facebook-panel" aria-label="Facebook Page recruitment">
      <div class="facebook-panel-head">
        <div>
          <span class="facebook-icon" aria-hidden="true">f</span>
          <strong>Facebook Page recruitment</strong>
          <p>Prepare, approve and publish one Page post at a time.</p>
        </div>
        <span class="sp-badge ${facebook.configured ? 'sp-badge-success' : 'sp-badge-warning'}">${escapeHtml(connection)}</span>
      </div>
      <div class="facebook-status-grid">
        <span><strong>Posting</strong>${facebook.posting_enabled ? 'Enabled' : 'Disabled'}</span>
        <span><strong>Mode</strong>${escapeHtml(facebook.mode || 'Dry run')}</span>
        <span><strong>Draft</strong>${escapeHtml(approval)}</span>
      </div>
      <div class="facebook-panel-actions">
        <button class="sp-button sp-button-secondary" data-action="facebook-draft">Review draft</button>
        <button class="sp-button sp-button-secondary" data-action="facebook-test">Test connection</button>
        <button class="sp-button" data-action="facebook-publish" ${facebook.can_publish ? '' : 'disabled'}>${escapeHtml(publishLabel)}</button>
      </div>
      <small>Live publishing stays off until Railway credentials are connected, the exact draft is approved and Live mode is deliberately enabled.</small>
    </section>
  `;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 401) {
    window.location.href = '/admin/login?expired=1';
    throw new Error('Session expired.');
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}

function renderAutomations() {
  if (!autopilotState.automations.length) {
    grid.innerHTML = '<div class="sp-card empty-state">No Autopilot automations are configured yet.</div>';
    return;
  }
  grid.innerHTML = autopilotState.automations.map((automation) => `
    <article class="sp-card automation-card">
      <div class="automation-card-head">
        <div>
          <div class="sp-kicker">${automation.enabled ? 'Enabled' : 'Paused'}</div>
          <h2>${automation.name}</h2>
          <p>${automation.summary || ''}</p>
        </div>
        <button class="toggle ${automation.enabled ? 'is-on' : ''}" data-action="toggle" data-key="${automation.key}" aria-label="Toggle ${automation.name}">
          <span></span>
        </button>
      </div>
      <div class="automation-meta">
        <div>
          <strong>Mode</strong>
          <span>${automation.mode || 'Dry run'}</span>
        </div>
        <div>
          <strong>Last run</strong>
          <span>${automation.last_run ? fmtDate(automation.last_run) : 'Not run yet'}</span>
        </div>
        <div>
          <strong>Next run</strong>
          <span>${automation.next_run ? (String(automation.next_run).includes('T') ? fmtDate(automation.next_run) : automation.next_run) : 'Runs when triggered'}</span>
        </div>
        <div class="automation-stats">
          <span><strong>${automation.success_count || 0}</strong>Success</span>
          <span><strong>${automation.failure_count || 0}</strong>Failed</span>
          <span><strong>${automation.needs_attention_count || 0}</strong>Needs attention</span>
        </div>
        <div>
          <strong>Owner notification rule</strong>
          <span>${automation.owner_trigger || 'Only notify the owner when intervention is required.'}</span>
        </div>
        <div>
          <strong>Autopilot safety</strong>
          <span>Run Now is safe by default. Dry-run records findings without changing live workflows.</span>
        </div>
      </div>
      <div class="automation-actions">
        <button class="sp-button" data-action="run" data-key="${automation.key}">Run now</button>
        <button class="sp-button sp-button-secondary" data-action="configure" data-key="${automation.key}">Configure</button>
        ${automation.key === 'cleaner_recruitment' ? '<a class="sp-button sp-button-secondary" href="/admin/ai-recruitment">Open Cleaner Recruitment</a>' : ''}
      </div>
      ${automation.key === 'cleaner_recruitment' ? facebookPanelMarkup() : ''}
    </article>
  `).join('');
}

function renderAttention() {
  const alerts = autopilotState.alerts || [];
  attentionCount.textContent = `${alerts.length} open`;
  if (!alerts.length) {
    attentionList.innerHTML = '<div class="empty-state">Nothing needs attention. Lovely and quiet.</div>';
    return;
  }
  attentionList.innerHTML = alerts.map((alert) => `
    <div class="attention-item">
      <strong>${alert.title}</strong>
      <p>${alert.detail || 'No extra detail provided.'}</p>
      <small>${automationName(alert.automation_key)} · ${fmtDate(alert.created_at)}</small>
      <button class="sp-button sp-button-secondary" data-action="resolve-alert" data-alert-id="${alert.id}">Mark resolved</button>
    </div>
  `).join('');
}

function renderLogs() {
  const logs = autopilotState.logs || [];
  if (!logs.length) {
    recentActivity.innerHTML = '<div class="empty-state">No Autopilot activity yet.</div>';
    return;
  }
  recentActivity.innerHTML = logs.slice(0, 18).map((log) => `
    <div class="activity-item">
      <strong>${log.event}</strong>
      <p>${log.detail || ''}</p>
      <small>${automationName(log.automation_key)} · ${log.level || 'Info'} · ${fmtDate(log.created_at)}</small>
    </div>
  `).join('');
}

function renderRuns() {
  const runs = autopilotState.runs || [];
  if (!runs.length) {
    runHistory.innerHTML = '<div class="empty-state">Run an automation dry-run to see history here.</div>';
    return;
  }
  runHistory.innerHTML = runs.map((run) => `
    <div class="activity-item">
      <strong>${automationName(run.automation_key)} · ${run.status}</strong>
      <p>${run.summary || run.error || 'No summary recorded.'}</p>
      <small>${run.triggered_by || 'manual'} · ${fmtDate(run.started_at)}</small>
    </div>
  `).join('');
}

function renderAll() {
  renderAutomations();
  renderAttention();
  renderLogs();
  renderRuns();
}

async function loadAutopilot() {
  try {
    autopilotState = await api('/api/admin/autopilot');
    renderAll();
  } catch (error) {
    grid.innerHTML = `<div class="sp-card empty-state">${error.message}</div>`;
  }
}

function openConfig(key) {
  const automation = autopilotState.automations.find((item) => item.key === key);
  if (!automation) return;
  activeConfigKey = key;
  configKicker.textContent = automation.name;
  configTitle.textContent = 'Configure automation';
  const config = automation.config || {};
  const choices = {
    mode: ['Dry run', 'Live'],
    facebook_page_posting: ['Disabled', 'Enabled'],
    facebook_post_mode: ['Dry run', 'Live'],
    facebook_post_frequency: ['Manual approval only'],
  };
  configFields.innerHTML = Object.keys(config).filter((field) => !field.startsWith('_')).map((field) => {
    const label = field.replaceAll('_', ' ');
    if (choices[field]) {
      return `<label>${escapeHtml(label)}
        <select name="${escapeHtml(field)}">${choices[field].map((option) => `<option value="${escapeHtml(option)}" ${String(config[field]) === option ? 'selected' : ''}>${escapeHtml(option)}</option>`).join('')}</select>
      </label>`;
    }
    return `<label>${escapeHtml(label)}
      <input name="${escapeHtml(field)}" value="${escapeHtml(config[field])}">
    </label>`;
  }).join('') || '<p>No configurable fields yet.</p>';
  configDialog.showModal();
}

async function saveConfig(event) {
  event.preventDefault();
  if (!activeConfigKey) return;
  const config = {};
  configFields.querySelectorAll('input, select').forEach((input) => {
    config[input.name] = input.value;
  });
  autopilotState = await api(`/api/admin/autopilot/${activeConfigKey}/configure`, {
    method: 'POST',
    body: JSON.stringify({ config }),
  });
  configDialog.close();
  renderAll();
  showToast('Autopilot settings saved.');
}

function renderFacebookDialog() {
  const facebook = autopilotState.facebook || {};
  const draft = facebook.draft || {};
  const state = facebook.published ? 'Published' : facebook.approved ? 'Approved and ready' : 'Awaiting approval';
  facebookDraftStatus.innerHTML = `
    <span class="sp-badge ${facebook.approved ? 'sp-badge-success' : 'sp-badge-warning'}">${escapeHtml(state)}</span>
    <span>${escapeHtml(facebook.mode || 'Dry run')} · ${facebook.posting_enabled ? 'Posting enabled' : 'Posting disabled'}</span>
  `;
  facebookDraftMessage.textContent = draft.message || 'Draft unavailable.';
  facebookDraftLink.href = draft.link || '#';
  facebookPublishButton.textContent = String(facebook.mode || 'Dry run').toLowerCase() === 'live' ? 'Publish approved post' : 'Run safe dry test';
  facebookPublishButton.disabled = !facebook.can_publish;
}

async function openFacebookDraft() {
  autopilotState = await api('/api/admin/autopilot/cleaner_recruitment/facebook/draft', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  renderAll();
  renderFacebookDialog();
  facebookDialog.showModal();
}

async function approveFacebookDraft() {
  autopilotState = await api('/api/admin/autopilot/cleaner_recruitment/facebook/approve', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  renderAll();
  renderFacebookDialog();
  showToast('The exact Facebook draft is approved. Nothing has been published.');
}

async function publishFacebookDraft() {
  const facebook = autopilotState.facebook || {};
  const live = String(facebook.mode || 'Dry run').toLowerCase() === 'live';
  if (live && !window.confirm('Publish this exact recruitment post to the connected Sparkles Facebook Page now?')) return;
  autopilotState = await api('/api/admin/autopilot/cleaner_recruitment/facebook/publish', {
    method: 'POST',
    body: JSON.stringify({ confirm: live ? 'PUBLISH APPROVED FACEBOOK DRAFT' : '' }),
  });
  renderAll();
  renderFacebookDialog();
  showToast(live ? 'Facebook recruitment post published.' : 'Dry test passed. Nothing was published.');
}

async function handleClick(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  const key = button.dataset.key;

  try {
    if (action === 'toggle') {
      const automation = autopilotState.automations.find((item) => item.key === key);
      button.disabled = true;
      autopilotState = await api(`/api/admin/autopilot/${key}/toggle`, {
        method: 'POST',
        body: JSON.stringify({ enabled: !automation.enabled }),
      });
      renderAll();
      showToast(`${automation.name} ${automation.enabled ? 'paused' : 'enabled'}.`);
    }
    if (action === 'run') {
      button.disabled = true;
      button.textContent = 'Running…';
      autopilotState = await api(`/api/admin/autopilot/${key}/run-now`, {
        method: 'POST',
        body: JSON.stringify({ dry_run: true }),
      });
      renderAll();
      showToast('Dry run completed safely. No live actions were taken.');
    }
    if (action === 'configure') {
      openConfig(key);
    }
    if (action === 'resolve-alert') {
      autopilotState = await api(`/api/admin/autopilot/alerts/${button.dataset.alertId}/resolve`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      renderAll();
      showToast('Attention item resolved.');
    }
    if (action === 'facebook-draft') {
      button.disabled = true;
      await openFacebookDraft();
    }
    if (action === 'facebook-approve') {
      button.disabled = true;
      await approveFacebookDraft();
    }
    if (action === 'facebook-test') {
      button.disabled = true;
      autopilotState = await api('/api/admin/autopilot/cleaner_recruitment/facebook/test', {
        method: 'POST',
        body: JSON.stringify({}),
      });
      renderAll();
      showToast('Read-only Facebook Page connection verified.');
    }
    if (action === 'facebook-publish') {
      button.disabled = true;
      await publishFacebookDraft();
    }
  } catch (error) {
    showToast(error.message);
    renderAll();
  }
}

async function logoutAdmin() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  window.location.href = '/admin/login';
}

document.getElementById('refreshAutopilot').addEventListener('click', loadAutopilot);
document.getElementById('saveConfig').addEventListener('click', saveConfig);
document.getElementById('adminLogout')?.addEventListener('click', logoutAdmin);
document.addEventListener('click', handleClick);

loadAutopilot();

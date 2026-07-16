let autopilotState = { automations: [], logs: [], runs: [], alerts: [] };
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
          <strong>Owner notification rule</strong>
          <span>${automation.owner_trigger || 'Only notify the owner when intervention is required.'}</span>
        </div>
        <div>
          <strong>Phase 1 safety</strong>
          <span>Run Now is dry-run only. It records findings without changing live workflows.</span>
        </div>
      </div>
      <div class="automation-actions">
        <button class="sp-button" data-action="run" data-key="${automation.key}">Run now</button>
        <button class="sp-button sp-button-secondary" data-action="configure" data-key="${automation.key}">Configure</button>
      </div>
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
  configFields.innerHTML = Object.keys(config).map((field) => `
    <label>${field.replaceAll('_', ' ')}
      <input name="${field}" value="${String(config[field]).replaceAll('"', '&quot;')}">
    </label>
  `).join('') || '<p>No configurable fields yet.</p>';
  configDialog.showModal();
}

async function saveConfig(event) {
  event.preventDefault();
  if (!activeConfigKey) return;
  const config = {};
  configFields.querySelectorAll('input').forEach((input) => {
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

const esc = value => {
  const element = document.createElement('div');
  element.textContent = value ?? '';
  return element.innerHTML;
};

const prettyJson = value => JSON.stringify(value ?? null, null, 2);

function renderList(target, rows){
  target.innerHTML = rows.map(([label, value]) => `<li><strong>${esc(label)}</strong><span>${esc(value)}</span></li>`).join('');
}

async function loadDiagnostics(){
  try{
    const response = await fetch('/api/admin/diagnostics', {credentials:'same-origin', cache:'no-store'});
    const data = await response.json();
    if(response.status === 401){
      location.href = '/admin/login?expired=1';
      return;
    }
    if(!response.ok) throw new Error(data.error || 'Could not load diagnostics.');
    renderList(document.querySelector('#databaseSummary'), [
      ['Dashboard database path', data.database_path],
      ['Application write path', data.write_database_path || data.database_path],
      ['Database exists', data.database_exists ? 'Yes' : 'No'],
      ['Current admin email', data.current_admin_email || 'Unknown'],
      ['Tables', (data.table_names || []).join(', ') || 'None']
    ]);
    renderList(document.querySelector('#tableCounts'), Object.entries(data.row_counts || {}).map(([name, count]) => [name, count]));
    document.querySelector('#discoveredDatabases').textContent = prettyJson(data.discovered_databases);
    document.querySelector('#latestBooking').textContent = prettyJson(data.latest_booking);
    document.querySelector('#latestPayment').textContent = prettyJson(data.latest_stripe_payment);
    document.querySelector('#latestCleaner').textContent = prettyJson(data.latest_cleaner);
    document.querySelector('#latestConversation').textContent = prettyJson(data.latest_ai_conversation);
    document.querySelector('#dashboardRaw').textContent = prettyJson(data.raw_dashboard_metrics);
  }catch(error){
    document.querySelector('#databaseSummary').innerHTML = `<li class="diagnostics-muted">${esc(error.message)}</li>`;
  }
}

document.querySelector('#refreshDiagnostics').addEventListener('click', loadDiagnostics);
loadDiagnostics();

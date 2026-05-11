// connectorPanel.js -- Connector status panel for the avatar page.
// Fetches connector list from the avatar server's proxy endpoint,
// displays status, and provides a search/query interface for Supabase.

import { HTTP_URL } from './config.js';

const API = `${HTTP_URL}/connectors`;

// -- styles --
function injectStyles() {
  const css = `
  #connector-toggle {
    position: fixed; top: 16px; right: 16px; z-index: 1001;
    background: rgba(16, 18, 24, 0.72);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 10px; padding: 8px 14px;
    color: #fff; font-size: 13px; cursor: pointer;
    backdrop-filter: blur(10px);
    font-family: system-ui, -apple-system, sans-serif;
    transition: background 0.15s;
  }
  #connector-toggle:hover { background: rgba(120,80,220,0.5); }
  #connector-toggle .dot {
    display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; margin-right: 6px;
  }
  #connector-toggle .dot.ok { background: #4ade80; }
  #connector-toggle .dot.err { background: #f87171; }
  #connector-toggle .dot.off { background: #6b7280; }

  #connector-panel {
    position: fixed; top: 56px; right: 16px; z-index: 1001;
    width: 360px; max-height: 70vh;
    background: rgba(16, 18, 24, 0.92);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 14px;
    backdrop-filter: blur(14px);
    font-family: system-ui, -apple-system, sans-serif;
    color: #e2e8f0;
    overflow: hidden;
    display: none;
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  }
  #connector-panel.open { display: flex; flex-direction: column; }

  #connector-panel .panel-header {
    padding: 14px 16px 10px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    font-size: 14px; font-weight: 600;
    color: #c084fc;
  }

  #connector-panel .connector-list {
    padding: 8px 12px;
    overflow-y: auto; flex: 1;
  }

  .connector-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 12px; margin: 4px 0;
    background: rgba(255,255,255,0.04);
    border-radius: 10px;
    transition: background 0.1s;
  }
  .connector-item:hover { background: rgba(255,255,255,0.08); }
  .connector-item .left { display: flex; align-items: center; gap: 10px; }
  .connector-item .status-dot {
    width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
  }
  .connector-item .status-dot.healthy { background: #4ade80; }
  .connector-item .status-dot.unhealthy { background: #f87171; }
  .connector-item .status-dot.disabled { background: #4b5563; }
  .connector-item .info .name { font-size: 13px; font-weight: 500; }
  .connector-item .info .actions-list {
    font-size: 11px; color: #94a3b8; margin-top: 2px;
  }
  .connector-item .toggle-btn {
    background: rgba(255,255,255,0.08); border: 0;
    color: #e2e8f0; border-radius: 6px; padding: 4px 10px;
    font-size: 11px; cursor: pointer;
    transition: background 0.15s;
  }
  .connector-item .toggle-btn:hover { background: rgba(120,80,220,0.5); }

  #connector-panel .search-section {
    padding: 10px 12px;
    border-top: 1px solid rgba(255,255,255,0.08);
  }
  #connector-panel .search-section label {
    font-size: 12px; color: #94a3b8; display: block; margin-bottom: 6px;
  }
  .search-row {
    display: flex; gap: 6px;
  }
  .search-row select, .search-row input {
    background: rgba(0,0,0,0.4);
    color: #fff; border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px; padding: 7px 10px; font-size: 13px;
    outline: none;
  }
  .search-row input { flex: 1; min-width: 0; }
  .search-row select { width: 120px; }
  .search-row button {
    background: rgba(120,80,220,0.85); color: #fff;
    border: 0; border-radius: 8px; padding: 7px 14px;
    font-size: 13px; cursor: pointer;
    transition: background 0.15s;
  }
  .search-row button:hover { background: rgba(140,100,240,0.95); }

  #connector-results {
    max-height: 200px; overflow-y: auto;
    padding: 8px 12px;
    border-top: 1px solid rgba(255,255,255,0.08);
  }
  .result-row {
    padding: 6px 8px; margin: 2px 0;
    background: rgba(255,255,255,0.03);
    border-radius: 6px; font-size: 12px;
    color: #cbd5e1; line-height: 1.4;
    word-break: break-word;
  }
  .result-row .key { color: #a78bfa; font-weight: 500; }
  .result-count {
    font-size: 11px; color: #64748b; padding: 4px 8px;
  }
  .result-error {
    color: #f87171; font-size: 12px; padding: 6px 8px;
  }
  `;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
}

// -- state --
let connectors = [];
let panelOpen = false;

// -- API helpers --
async function fetchConnectors() {
  try {
    const resp = await fetch(`${API}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    connectors = await resp.json();
  } catch (e) {
    console.warn('Failed to fetch connectors:', e);
    connectors = [];
  }
  return connectors;
}

async function toggleConnector(id, enable) {
  try {
    const action = enable ? 'enable' : 'disable';
    await fetch(`${API}/${id}/${action}`, { method: 'POST' });
  } catch (e) {
    console.warn(`Failed to toggle ${id}:`, e);
  }
  await fetchConnectors();
  renderList();
  renderToggleBtn();
}

async function runSearch(connectorId, table, query) {
  try {
    const resp = await fetch(`${API}/${connectorId}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'search', params: { table, query, limit: 10 } }),
    });
    return await resp.json();
  } catch (e) {
    return { success: false, error: e.message };
  }
}

// -- rendering (safe DOM construction) --
let toggleBtn, panel, listEl, resultsEl;

function renderToggleBtn() {
  if (!toggleBtn) return;
  const ok = connectors.filter(c => c.enabled && c.healthy).length;
  const total = connectors.length;
  const dotClass = total === 0 ? 'off' : ok === total ? 'ok' : ok > 0 ? 'ok' : 'err';
  toggleBtn.textContent = '';
  const dot = document.createElement('span');
  dot.className = `dot ${dotClass}`;
  toggleBtn.appendChild(dot);
  toggleBtn.appendChild(document.createTextNode(`Connectors (${ok}/${total})`));
}

function renderList() {
  if (!listEl) return;
  listEl.textContent = '';
  for (const c of connectors) {
    const dotClass = !c.enabled ? 'disabled' : c.healthy ? 'healthy' : 'unhealthy';

    const item = document.createElement('div');
    item.className = 'connector-item';

    const left = document.createElement('div');
    left.className = 'left';

    const statusDot = document.createElement('div');
    statusDot.className = `status-dot ${dotClass}`;

    const info = document.createElement('div');
    info.className = 'info';
    const nameEl = document.createElement('div');
    nameEl.className = 'name';
    nameEl.textContent = c.name;
    const actionsEl = document.createElement('div');
    actionsEl.className = 'actions-list';
    actionsEl.textContent = c.actions.join(' \u00b7 ');
    info.append(nameEl, actionsEl);

    left.append(statusDot, info);

    const btn = document.createElement('button');
    btn.className = 'toggle-btn';
    btn.textContent = c.enabled ? 'Disable' : 'Enable';
    btn.addEventListener('click', () => toggleConnector(c.id, !c.enabled));

    item.append(left, btn);
    listEl.appendChild(item);
  }
}

function renderResults(result) {
  if (!resultsEl) return;
  resultsEl.textContent = '';
  if (!result.success) {
    const err = document.createElement('div');
    err.className = 'result-error';
    err.textContent = result.error || 'Unknown error';
    resultsEl.appendChild(err);
    return;
  }
  const rows = result.data || [];
  const countEl = document.createElement('div');
  countEl.className = 'result-count';
  countEl.textContent = `${result.row_count} result${result.row_count !== 1 ? 's' : ''}`;
  resultsEl.appendChild(countEl);

  for (const row of rows) {
    const div = document.createElement('div');
    div.className = 'result-row';
    const key = row.key || row.id || '';
    const content = row.content || row.name || JSON.stringify(row).slice(0, 200);
    if (key) {
      const keySpan = document.createElement('span');
      keySpan.className = 'key';
      keySpan.textContent = key;
      div.appendChild(keySpan);
      div.appendChild(document.createTextNode(': ' + content));
    } else {
      div.textContent = content;
    }
    resultsEl.appendChild(div);
  }
}

// -- mount --
async function mount() {
  injectStyles();
  await fetchConnectors();

  // Toggle button
  toggleBtn = document.createElement('button');
  toggleBtn.id = 'connector-toggle';
  renderToggleBtn();
  toggleBtn.addEventListener('click', () => {
    panelOpen = !panelOpen;
    panel.classList.toggle('open', panelOpen);
    if (panelOpen) fetchConnectors().then(() => { renderList(); renderToggleBtn(); });
  });
  document.body.appendChild(toggleBtn);

  // Panel
  panel = document.createElement('div');
  panel.id = 'connector-panel';

  const header = document.createElement('div');
  header.className = 'panel-header';
  header.textContent = 'Connectors';

  listEl = document.createElement('div');
  listEl.className = 'connector-list';
  renderList();

  // Search section
  const searchSection = document.createElement('div');
  searchSection.className = 'search-section';
  const label = document.createElement('label');
  label.textContent = 'Quick Search (Supabase)';

  const searchRow = document.createElement('div');
  searchRow.className = 'search-row';

  const tableSelect = document.createElement('select');
  for (const t of ['memories', 'agent_memories', 'game_notes', 'games', 'game_currencies', 'anime_series']) {
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = t.replace(/_/g, ' ');
    tableSelect.appendChild(opt);
  }

  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.placeholder = 'Search...';

  const searchBtn = document.createElement('button');
  searchBtn.textContent = 'Go';

  const doSearch = async () => {
    const q = searchInput.value.trim();
    if (!q) return;
    searchBtn.textContent = '...';
    const result = await runSearch('supabase', tableSelect.value, q);
    searchBtn.textContent = 'Go';
    renderResults(result);
    resultsEl.style.display = 'block';
  };
  searchBtn.addEventListener('click', doSearch);
  searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });

  searchRow.append(tableSelect, searchInput, searchBtn);
  searchSection.append(label, searchRow);

  resultsEl = document.createElement('div');
  resultsEl.id = 'connector-results';
  resultsEl.style.display = 'none';

  panel.append(header, listEl, searchSection, resultsEl);
  document.body.appendChild(panel);

  // Refresh every 30s
  setInterval(async () => {
    await fetchConnectors();
    renderToggleBtn();
    if (panelOpen) renderList();
  }, 30000);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
else mount();

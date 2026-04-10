const API = '';

async function fetchJSON(url) {
  const res = await fetch(API + url);
  if (!res.ok) return null;
  return res.json();
}

async function init() {
  const journeys = await fetchJSON('/api/journeys');
  if (journeys) _knownJourneyIds = new Set(journeys.map(j => j.id));
  loadStats();
  loadDomains();
  loadJourneys();
  loadCoverage();
  loadRunHistory();
  loadLLMStatus();
  loadReviewQueue();
  loadReviewStats();
}

// --- Stats ---
async function loadStats() {
  const stats = await fetchJSON('/api/coverage');
  if (!stats) return;
  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="stat-value">${stats.total_journeys}</div><div class="stat-label">Journeys</div></div>
    <div class="stat"><div class="stat-value">${stats.unique_domains}</div><div class="stat-label">Domains</div></div>
    <div class="stat"><div class="stat-value">${stats.unique_features}</div><div class="stat-label">Features</div></div>
    <div class="stat"><div class="stat-value">${stats.avg_confidence ? (stats.avg_confidence * 100).toFixed(0) + '%' : '—'}</div><div class="stat-label">Confidence</div></div>
  `;
}

// --- Domains ---
async function loadDomains() {
  const domains = await fetchJSON('/api/domains');
  if (!domains) return;
  const select = document.getElementById('domain-filter');
  select.innerHTML = '<option value="">All Domains</option>';
  domains.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d; opt.textContent = d;
    select.appendChild(opt);
  });
  select.onchange = () => loadJourneys(select.value || undefined);
}

// --- Journeys ---
let _knownJourneyIds = new Set();

async function loadJourneys(domain, highlightNew = false) {
  const url = domain ? `/api/journeys?domain=${encodeURIComponent(domain)}` : '/api/journeys';
  const journeys = await fetchJSON(url);
  const container = document.getElementById('journeys-list');

  if (!journeys || !journeys.length) {
    container.innerHTML = '<p class="empty-state">No journeys discovered yet.<br>Upload captured events or run: <code>python -m testai.demo</code></p>';
    return;
  }

  const newIds = new Set(journeys.map(j => j.id));
  const freshIds = highlightNew ? journeys.filter(j => !_knownJourneyIds.has(j.id)).map(j => j.id) : [];

  container.innerHTML = journeys.map(j => {
    const conf = j.confidence || 0;
    const confClass = conf >= 0.8 ? 'high' : conf >= 0.5 ? 'medium' : 'low';
    let tags = [];
    try { tags = JSON.parse(j.tags || '[]'); } catch { tags = []; }
    const date = j.discovered_at ? new Date(j.discovered_at).toLocaleDateString() : '';
    const isNew = freshIds.includes(j.id);
    return `
      <div class="journey-card${isNew ? ' journey-new' : ''}" onclick="openJourney('${j.id}')" id="journey-${j.id}">
        <div class="journey-card-header">
          <span class="journey-name">${esc(j.name)}</span>
          <div style="display:flex;gap:.4rem;align-items:center">
            ${isNew ? '<span class="badge-new">NEW</span>' : ''}
            <span class="confidence-badge confidence-${confClass}">${(conf * 100).toFixed(0)}%</span>
          </div>
        </div>
        <div class="journey-meta">
          <span>${esc(j.domain || 'Uncategorized')} &rarr; ${esc(j.feature || 'General')}</span>
          <span>${date}</span>
        </div>
        <div class="journey-tags">${tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
      </div>`;
  }).join('');

  _knownJourneyIds = newIds;

  if (highlightNew && freshIds.length > 0) {
    const firstNew = document.getElementById(`journey-${freshIds[0]}`);
    if (firstNew) {
      setTimeout(() => {
        firstNew.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 300);
    }
  }
}

// --- Coverage ---
async function loadCoverage() {
  const domains = await fetchJSON('/api/coverage/domains');
  const grid = document.getElementById('coverage-grid');
  if (!domains || !domains.length) {
    grid.innerHTML = '<p class="empty-state">Coverage data will appear after journeys are discovered.</p>';
    return;
  }
  grid.innerHTML = domains.map(d => `
    <div class="coverage-card">
      <div class="coverage-domain">${esc(d.domain)}</div>
      <div class="coverage-count">${d.journey_count}</div>
      <div class="coverage-label">journeys discovered</div>
    </div>`).join('');
}

// --- Base URL extraction helper ---
function _extractBaseUrl(steps) {
  for (const s of (steps || [])) {
    if (s.url) {
      try {
        const u = new URL(s.url);
        return u.origin;
      } catch {}
    }
  }
  return '';
}

// --- Journey Modal ---
async function openJourney(id) {
  const journey = await fetchJSON(`/api/journeys/${id}`);
  if (!journey) return;

  const steps = journey.steps || [];
  let tags = [];
  try { tags = JSON.parse(journey.tags || '[]'); } catch { tags = []; }

  document.getElementById('modal-body').innerHTML = `
    <h2>${esc(journey.name)}</h2>
    <div class="journey-meta" style="margin:.6rem 0">
      <span>${esc(journey.domain || '')} &rarr; ${esc(journey.feature || '')}</span>
      <span>Confidence: ${((journey.confidence || 0) * 100).toFixed(0)}%</span>
    </div>
    <div class="journey-tags" style="margin-bottom:1rem">
      ${tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}
    </div>
    <h3 style="margin-bottom:.4rem;font-size:.9rem">Steps (${steps.length})</h3>
    <ul class="step-list">
      ${steps.map(s => `
        <li class="step-item">
          <span class="step-number">${s.step_order}</span>
          <div>
            <div class="step-desc">${esc(s.description)}</div>
            ${s.url ? `<div class="step-url">${esc(s.url)}</div>` : ''}
          </div>
        </li>`).join('')}
    </ul>
    <div class="modal-actions" style="margin-top: 24px; display: flex; gap: 12px; border-top: 1px solid var(--border); padding-top: 16px;">
      <button class="btn btn-primary" onclick="closeModal(); openReplayModal('${id}', '${esc(journey.name)}', '${esc(_extractBaseUrl(steps))}')">▶ Replay</button>
      <button class="btn btn-explore" onclick="closeModal(); openExploreModal('${id}', '${esc(journey.name)}', '${esc(_extractBaseUrl(steps))}')">&#128270; Explore</button>
      <button class="btn btn-outline" onclick="expandJourney('${id}')">&#127793; Discover Related Flows</button>
      <button class="btn btn-outline" onclick="openPerfTab('${id}')">&#9202; Performance</button>
      <button class="btn btn-outline" onclick="generateAssertions('${id}')">&#10003; Assertions</button>
      <button class="btn btn-outline" onclick="exportPlaywright('${id}')">↓ Playwright</button>
      <button class="btn btn-outline" onclick="exportCypress('${id}')">↓ Cypress</button>
    </div>
  `;
  document.getElementById('journey-modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('journey-modal').classList.add('hidden');
}

async function exportPlaywright(id) {
  const res = await fetch(`/api/journeys/${id}/export/playwright`);
  const code = await res.text();
  const blob = new Blob([code], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `test_${id.slice(0, 8)}.py`;
  a.click();
  URL.revokeObjectURL(url);
}

async function exportCypress(id) {
  const res = await fetch(`/api/journeys/${id}/export/cypress`);
  const code = await res.text();
  const blob = new Blob([code], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `${id.slice(0, 8)}.cy.js`;
  a.click();
  URL.revokeObjectURL(url);
}

// --- Run History ---

async function loadRunHistory() {
  const [runs, stats] = await Promise.all([
    fetchJSON('/api/runs?limit=20'),
    fetchJSON('/api/runs/stats'),
  ]);

  const statsEl = document.getElementById('run-stats');
  if (stats && stats.total_runs > 0) {
    const rate = stats.pass_rate || 0;
    const rateColor = rate >= 90 ? 'var(--green)' : rate >= 70 ? 'var(--yellow)' : 'var(--red)';
    statsEl.innerHTML = `
      <span class="run-stat">${stats.total_runs} runs</span>
      <span class="run-stat" style="color:var(--green)">${stats.total_passed || 0} passed</span>
      <span class="run-stat" style="color:var(--red)">${stats.total_failed || 0} failed</span>
      <span class="run-stat" style="color:${rateColor}">${rate}% pass rate</span>
    `;
  }

  const listEl = document.getElementById('runs-list');
  if (!runs || !runs.length) return;

  listEl.innerHTML = runs.map(r => {
    const passed = r.passed === 1;
    const icon = passed ? '✓' : '✗';
    const cls = passed ? 'run-pass' : 'run-fail';
    const dur = r.duration_ms >= 1000 ? `${(r.duration_ms / 1000).toFixed(1)}s` : `${r.duration_ms}ms`;
    const time = r.started_at ? new Date(r.started_at).toLocaleString() : '';
    const healedBadge = r.healed ? '<span class="run-healed-badge">AI HEALED</span>' : '';
    const visionBadge = r.vision_healed ? '<span class="run-vision-badge">VISION HEALED</span>' : '';
    return `
      <div class="run-card ${cls}">
        <span class="run-icon">${icon}</span>
        <div class="run-info">
          <div class="run-name">${esc(r.journey_name || '')}${healedBadge}${visionBadge}</div>
          <div class="run-meta">${esc(r.base_url)} · ${r.passed_steps}/${r.total_steps} steps · ${dur}</div>
        </div>
        <div class="run-time">${time}</div>
      </div>`;
  }).join('');
}

// --- Auth ---

async function checkAuthForUrl(url) {
  const badge = document.getElementById('replay-auth-status');
  const dl = document.getElementById('replay-auth-download');
  const msg = document.getElementById('replay-auth-msg');
  msg.textContent = '';
  dl.classList.add('hidden');

  if (!url || !url.startsWith('http')) {
    badge.className = 'auth-badge no-auth';
    badge.textContent = 'No auth';
    return;
  }
  try {
    const res = await fetch(`/api/auth/check?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    if (data.has_auth) {
      badge.className = 'auth-badge has-auth';
      badge.textContent = `Authenticated`;
      dl.href = `/api/auth/download/${encodeURIComponent(data.domain)}`;
      dl.classList.remove('hidden');
    } else {
      badge.className = 'auth-badge no-auth';
      badge.textContent = 'No auth';
    }
  } catch {
    badge.className = 'auth-badge no-auth';
    badge.textContent = 'No auth';
  }
}

async function generateAuth() {
  const url = document.getElementById('replay-base-url').value.trim();
  if (!url || !url.startsWith('http')) {
    alert('Enter a Base URL first (e.g. https://app.example.com)');
    return;
  }

  const msg = document.getElementById('replay-auth-msg');
  const badge = document.getElementById('replay-auth-status');
  badge.className = 'auth-badge auth-pending';
  badge.textContent = 'Opening browser...';
  msg.textContent = 'A browser will open — log in, then close it. Auth saves automatically.';
  msg.className = 'replay-auth-msg info';

  try {
    const res = await fetch(`/api/auth/generate?url=${encodeURIComponent(url)}`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      badge.className = 'auth-badge has-auth';
      badge.textContent = 'Authenticated';
      msg.textContent = `Auth saved for ${data.domain}`;
      msg.className = 'replay-auth-msg success';
      const dl = document.getElementById('replay-auth-download');
      dl.href = `/api/auth/download/${encodeURIComponent(data.domain)}`;
      dl.classList.remove('hidden');
    } else {
      badge.className = 'auth-badge no-auth';
      badge.textContent = 'No auth';
      msg.textContent = data.detail || 'Auth generation failed';
      msg.className = 'replay-auth-msg error';
    }
  } catch (e) {
    badge.className = 'auth-badge no-auth';
    badge.textContent = 'No auth';
    msg.textContent = 'Error: ' + e.message;
    msg.className = 'replay-auth-msg error';
  }
}

async function uploadAuthFile(input) {
  const file = input.files[0];
  if (!file) return;

  const url = document.getElementById('replay-base-url').value.trim();
  let domain = '';
  try { domain = new URL(url).host; } catch {}

  if (!domain) {
    domain = prompt('Enter domain for this auth (e.g. app.example.com):');
    if (!domain) return;
  }

  const formData = new FormData();
  formData.append('file', file);
  const msg = document.getElementById('replay-auth-msg');

  try {
    const res = await fetch(`/api/auth/upload?domain=${encodeURIComponent(domain)}`, {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    if (data.ok) {
      const badge = document.getElementById('replay-auth-status');
      badge.className = 'auth-badge has-auth';
      badge.textContent = 'Authenticated';
      msg.textContent = `Auth uploaded for ${domain}`;
      msg.className = 'replay-auth-msg success';
      const dl = document.getElementById('replay-auth-download');
      dl.href = `/api/auth/download/${encodeURIComponent(domain)}`;
      dl.classList.remove('hidden');
      input.value = '';
    } else {
      msg.textContent = 'Upload failed: ' + (data.detail || 'unknown');
      msg.className = 'replay-auth-msg error';
    }
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
    msg.className = 'replay-auth-msg error';
  }
}

// --- Replay ---
let _replayEventSource = null;

async function checkOllamaStatus() {
  const badge = document.getElementById('ollama-status');
  try {
    const res = await fetch('/api/heal/status');
    const data = await res.json();
    if (data.available) {
      const label = data.provider && data.provider !== 'Ollama' ? data.provider : data.model;
      badge.textContent = label || 'ready';
      badge.className = 'ollama-badge available';
      if (data.has_vision) badge.textContent += ' (vision)';
    } else {
      badge.textContent = 'offline';
      badge.className = 'ollama-badge offline';
    }
  } catch {
    badge.textContent = 'offline';
    badge.className = 'ollama-badge offline';
  }
}

async function openReplayModal(journeyId, journeyName, baseUrl) {
  document.getElementById('replay-journey-id').value = journeyId;
  document.getElementById('replay-title').textContent = `Replay: ${journeyName}`;
  document.getElementById('replay-output').innerHTML = '<span class="term-dim">Waiting to run…</span>';
  document.getElementById('replay-status').className = 'replay-status hidden';

  const urlInput = document.getElementById('replay-base-url');
  if (baseUrl) {
    urlInput.value = baseUrl;
    checkAuthForUrl(baseUrl);
  } else if (!urlInput.value) {
    try {
      const j = await fetchJSON(`/api/journeys/${journeyId}`);
      if (j && j.steps) {
        const auto = _extractBaseUrl(j.steps);
        if (auto) { urlInput.value = auto; checkAuthForUrl(auto); }
      }
    } catch {}
  }
  checkOllamaStatus();

  // Fetch the test file and detect required env vars (e.g. passwords)
  const envContainer = document.getElementById('replay-env-vars');
  envContainer.innerHTML = '';
  try {
    const res = await fetch(`/api/journeys/${journeyId}/export/playwright`);
    const code = await res.text();
    // Match: os.environ.get("KEY", "default")  or  os.environ.get("KEY", "")
    const matches = [...code.matchAll(/os\.environ\.get\("([A-Z0-9_]+)",\s*"([^"]*)"\)/g)];
    const seen = new Map();   // key → default value
    matches.forEach(([, key, def]) => { if (!seen.has(key)) seen.set(key, def); });

    if (seen.size > 0) {
      const label = document.createElement('div');
      label.className = 'replay-label';
      label.style.marginTop = '0.75rem';
      label.textContent = 'Test inputs (env vars)';
      envContainer.appendChild(label);

      seen.forEach((defaultVal, varName) => {
        const isSecret = defaultVal === '';
        const row = document.createElement('div');
        row.className = 'replay-env-row';
        row.innerHTML = `
          <span class="replay-env-name">${varName}</span>
          <input type="${isSecret ? 'password' : 'text'}"
                 class="replay-url-input replay-env-input"
                 id="env-${varName}"
                 value="${esc(defaultVal)}"
                 data-default="${esc(defaultVal)}"
                 placeholder="${isSecret ? '(required)' : defaultVal}"
                 autocomplete="off">
        `;
        envContainer.appendChild(row);
      });
    }
  } catch {}

  document.getElementById('replay-modal').classList.remove('hidden');
}

function closeReplayModal() {
  if (_replayEventSource) { _replayEventSource.close(); _replayEventSource = null; }
  document.getElementById('replay-modal').classList.add('hidden');
}

// --- Explore Modal ---

let _exploreJourneyId = null;
let _exploreAbortController = null;

async function openExploreModal(journeyId, journeyName, baseUrl) {
  _exploreJourneyId = journeyId;
  document.getElementById('explore-journey-id').value = journeyId;
  document.getElementById('explore-title').textContent = `Explore: ${journeyName}`;
  if (baseUrl) {
    document.getElementById('explore-base-url').value = baseUrl;
  }
  document.getElementById('explore-table-body').innerHTML = '';
  document.getElementById('explore-summary').innerHTML = '';
  document.getElementById('explore-progress-text').textContent = 'Loading variants…';
  document.getElementById('explore-run-btn').disabled = false;
  document.getElementById('explore-run-btn').innerHTML = '&#128270; Run Exploration';
  document.getElementById('explore-research-panel').classList.add('hidden');
  document.getElementById('explore-research-status').textContent = '';

  try {
    const preview = await fetch(`/api/journeys/${journeyId}/explore/preview`).then(r => r.json());
    const count = preview.variants ? preview.variants.length : '?';
    document.getElementById('explore-progress-text').textContent = `${count} variants ready`;
  } catch {
    document.getElementById('explore-progress-text').textContent = 'Ready';
  }

  document.getElementById('explore-modal').classList.remove('hidden');
}

function closeExploreModal() {
  if (_exploreAbortController) { _exploreAbortController.abort(); _exploreAbortController = null; }
  document.getElementById('explore-modal').classList.add('hidden');
}

function renderBehaviorBadge(behavior) {
  const map = {
    correctly_rejected:  ['badge-ok',  '&#10003; Blocked'],
    bug_accepted_invalid: ['badge-bug', '&#128027; BUG'],
    dependency_confirmed: ['badge-dep', '&#8627; Required'],
    step_redundant:       ['badge-info', '~ Optional'],
    passed:               ['badge-ok',  '&#10003; Passed'],
    failed:               ['badge-bug', '&#10007; Failed'],
  };
  const [cls, label] = map[behavior] || ['badge-info', behavior];
  return `<span class="badge ${cls}">${label}</span>`;
}

async function runExploration() {
  const journeyId = _exploreJourneyId;
  const baseUrl = document.getElementById('explore-base-url').value.trim();

  if (!baseUrl) {
    document.getElementById('explore-progress-text').textContent = '✗ Please enter a Base URL';
    return;
  }

  if (_exploreAbortController) { _exploreAbortController.abort(); }
  _exploreAbortController = new AbortController();

  const runBtn = document.getElementById('explore-run-btn');
  runBtn.disabled = true;
  runBtn.innerHTML = '<span class="spinner"></span> Running…';

  document.getElementById('explore-table-body').innerHTML = '';
  document.getElementById('explore-summary').innerHTML = '';
  document.getElementById('explore-progress-text').textContent = 'Starting…';

  const envVars = {};
  try {
    const res = await fetch(`/api/journeys/${journeyId}/explore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: baseUrl,
        env_vars: envVars,
        headed: false,
        autoresearch: document.getElementById('explore-autoresearch').checked,
      }),
      signal: _exploreAbortController.signal,
    });

    if (!res.ok) throw new Error(`Server error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    // Pending output lines per variant
    const variantOutputs = {};

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        const dataLine = part.split('\n').find(l => l.startsWith('data:'));
        if (!dataLine) continue;
        let msg;
        try { msg = JSON.parse(dataLine.slice(5)); } catch { continue; }

        if (msg.type === 'research_start') {
          const panel = document.getElementById('explore-research-panel');
          panel.classList.remove('hidden');
          document.getElementById('explore-research-status').textContent = msg.message;
          document.getElementById('explore-progress-text').textContent = 'Researching…';

        } else if (msg.type === 'research_done') {
          document.getElementById('explore-research-status').innerHTML =
            `DOM fields: <strong>${msg.dom_fields}</strong> &nbsp;·&nbsp;` +
            `Constraint mutations: <strong>${msg.constraint_mutations}</strong> &nbsp;·&nbsp;` +
            `AI mutations: <strong>${msg.llm_mutations}</strong> &nbsp;·&nbsp;` +
            `Total variants: <strong>${msg.total_variants}</strong>`;
          document.getElementById('explore-progress-text').textContent =
            `Running ${msg.total_variants} variants for "${msg.journey_name}"…`;

        } else if (msg.type === 'start') {
          document.getElementById('explore-progress-text').textContent =
            `Running ${msg.total_variants} variants for "${msg.journey_name}"…`;

        } else if (msg.type === 'variant_start') {
          variantOutputs[msg.variant_id] = [];
          const tbody = document.getElementById('explore-table-body');
          const tr = document.createElement('tr');
          tr.id = `explore-row-${msg.variant_id}`;
          tr.innerHTML = `
            <td><span class="variant-id">${esc(msg.variant_id)}</span> ${esc(msg.description)}</td>
            <td><span class="badge badge-info">&#8987; Running…</span></td>
            <td>—</td>
            <td>—</td>
            <td><details><summary>Log</summary><pre class="explore-log" id="explore-log-${msg.variant_id}"></pre></details></td>
          `;
          tbody.appendChild(tr);
          document.getElementById('explore-progress-text').textContent =
            `Variant ${msg.index + 1}/${msg.total}: ${msg.description}`;

        } else if (msg.type === 'line') {
          // Append to the most recent variant's log (track by last seen variant_start)
          const logs = document.querySelectorAll('.explore-log');
          if (logs.length > 0) {
            const last = logs[logs.length - 1];
            last.textContent += (msg.text || '') + '\n';
          }

        } else if (msg.type === 'variant_done') {
          const tr = document.getElementById(`explore-row-${msg.variant_id}`);
          if (tr) {
            const dur = msg.duration_ms >= 1000 ? `${(msg.duration_ms / 1000).toFixed(1)}s` : `${msg.duration_ms}ms`;
            const cells = tr.querySelectorAll('td');
            cells[1].innerHTML = msg.passed
              ? '<span class="badge badge-ok">&#10003; Pass</span>'
              : '<span class="badge badge-bug">&#10007; Fail</span>';
            cells[2].innerHTML = renderBehaviorBadge(msg.app_behavior);
            cells[3].textContent = dur;
          }

        } else if (msg.type === 'explore_done') {
          const s = msg.summary;
          const bugColor = s.bugs_found > 0 ? 'var(--red)' : 'var(--green)';
          document.getElementById('explore-summary').innerHTML = `
            <div class="explore-summary-bar">
              <span class="explore-sum-item">Total: <strong>${s.total}</strong></span>
              <span class="explore-sum-item" style="color:var(--red)">&#128027; Bugs: <strong>${s.bugs_found}</strong></span>
              <span class="explore-sum-item" style="color:var(--green)">&#10003; Blocked: <strong>${s.correctly_rejected}</strong></span>
              <span class="explore-sum-item">&#8627; Required: <strong>${s.dependency_confirmed}</strong></span>
              <span class="explore-sum-item">~ Optional: <strong>${s.step_redundant}</strong></span>
              <span class="explore-sum-item explore-exp-id">ID: ${esc(msg.exploration_id)}</span>
            </div>
          `;
          document.getElementById('explore-progress-text').textContent =
            `Done — ${s.bugs_found > 0 ? s.bugs_found + ' bug(s) found' : 'no bugs found'}`;
          runBtn.disabled = false;
          runBtn.innerHTML = '&#128270; Run Again';
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      document.getElementById('explore-progress-text').textContent = `Error: ${err.message}`;
    }
    runBtn.disabled = false;
    runBtn.innerHTML = '&#128270; Run Exploration';
  }
}

async function runReplay() {
  const journeyId = document.getElementById('replay-journey-id').value;
  const baseUrl   = document.getElementById('replay-base-url').value.trim();
  const headed    = document.getElementById('replay-headed').checked;
  const output    = document.getElementById('replay-output');
  const statusEl  = document.getElementById('replay-status');
  const runBtn    = document.getElementById('replay-run-btn');

  if (!baseUrl) {
    output.innerHTML = '<span class="term-error">✗ Please enter a Base URL (e.g. https://www.saucedemo.com)</span>';
    return;
  }

  if (_replayEventSource) { _replayEventSource.close(); _replayEventSource = null; }

  output.innerHTML = '';
  statusEl.className = 'replay-status hidden';
  runBtn.disabled = true;
  runBtn.innerHTML = '<span class="spinner"></span> Running…';

  document.getElementById('replay-progress').classList.add('hidden');
  document.getElementById('progress-fill').style.width = '0%';
  document.getElementById('progress-fill').className = 'progress-fill';
  document.getElementById('progress-text').textContent = '';
  document.getElementById('screenshot-strip').innerHTML = '';
  document.getElementById('screenshot-dots').innerHTML = '';
  document.getElementById('screenshot-counter').textContent = '';
  document.getElementById('replay-screenshots').classList.add('hidden');
  _ssIndex = 0;

  // Reset diagnostics panel
  const diagPanel = document.getElementById('diagnostics-panel');
  if (diagPanel) {
    diagPanel.classList.add('hidden');
    document.getElementById('diag-summary').textContent = '';
    ['diag-console', 'diag-network', 'diag-api', 'diag-empty'].forEach(id => {
      document.getElementById(id).classList.add('hidden');
    });
    ['diag-console-list', 'diag-network-list', 'diag-api-list'].forEach(id => {
      document.getElementById(id).innerHTML = '';
    });
    const h = diagPanel.querySelector('.diag-header');
    if (h) h.classList.remove('open');
    const b = document.getElementById('diag-body');
    if (b) b.style.display = '';
  }

  const appendLine = (text, cls = '') => {
    const line = document.createElement('div');
    line.className = 'term-line' + (cls ? ` ${cls}` : '');
    line.textContent = text;
    output.appendChild(line);
    output.scrollTop = output.scrollHeight;
  };

  const envVars = {};
  document.querySelectorAll('.replay-env-input').forEach(input => {
    const key = input.id.replace('env-', '');
    const def = input.getAttribute('data-default') || '';
    if (input.value && input.value !== def) envVars[key] = input.value;
  });

  try {
    const res = await fetch(`/api/journeys/${journeyId}/replay`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: baseUrl,
        headed: headed,
        env_vars: envVars,
        auto_heal: document.getElementById('replay-auto-heal').checked,
        max_heal_attempts: 2,
      }),
    });

    if (!res.ok) throw new Error(`Server error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        const dataLine = part.split('\n').find(l => l.startsWith('data:'));
        if (!dataLine) continue;
        try {
          const msg = JSON.parse(dataLine.slice(5));

          if (msg.type === 'start') {
            appendLine('$ ' + msg.cmd, 'term-cmd');
            appendLine('');
          } else if (msg.type === 'line') {
            const t = msg.text;
            const stepMatch = t.match(/Step\s+(\d+)\/(\d+)/);
            if (stepMatch) {
              const cur = parseInt(stepMatch[1]);
              const tot = parseInt(stepMatch[2]);
              const pct = Math.round((cur / tot) * 100);
              document.getElementById('replay-progress').classList.remove('hidden');
              document.getElementById('progress-fill').style.width = `${pct}%`;
              document.getElementById('progress-text').textContent = `Step ${cur}/${tot}`;
              appendLine(t, 'term-step');
            } else {
              const cls = t.includes('PASSED') ? 'term-pass'
                        : t.includes('FAILED') || t.includes('ERROR') ? 'term-fail'
                        : t.startsWith('WARNINGS') || t.includes('warning') ? 'term-warn'
                        : '';
              appendLine(t, cls);
            }
          } else if (msg.type === 'screenshot') {
            const strip = document.getElementById('screenshot-strip');
            const container = document.getElementById('replay-screenshots');
            container.classList.remove('hidden');

            const idx = strip.children.length;

            const wrapper = document.createElement('div');
            wrapper.className = 'screenshot-item' + (idx === 0 ? '' : ' hidden-slide');
            wrapper.dataset.idx = idx;

            const img = document.createElement('img');
            img.className = 'screenshot-thumb';
            img.src = `data:image/png;base64,${msg.data}`;
            img.alt = msg.name;
            img.onclick = () => openScreenshotFullsize(msg.data, idx);

            const label = document.createElement('div');
            label.className = 'screenshot-label';
            label.textContent = msg.name.replace('.png', '').replace('step_', 'Step ');

            wrapper.appendChild(img);
            wrapper.appendChild(label);
            strip.appendChild(wrapper);

            // Add dot indicator
            const dots = document.getElementById('screenshot-dots');
            const dot = document.createElement('button');
            dot.className = 'screenshot-dot' + (idx === 0 ? ' active' : '');
            dot.dataset.idx = idx;
            dot.title = label.textContent;
            dot.onclick = () => screenshotGoTo(idx);
            dots.appendChild(dot);

            _ssUpdateUI();
          } else if (msg.type === 'vision_heal') {
            appendLine(`👁 Vision heal triggered (${msg.count} so far)`, 'term-heal-ok');
          } else if (msg.type === 'heal_start') {
            appendLine('');
            appendLine(`🔧 Auto-Heal Attempt ${msg.attempt}/${msg.max}`, 'term-heal');
            const fill = document.getElementById('progress-fill');
            fill.classList.add('healing');
            statusEl.textContent = '🔧 HEALING';
            statusEl.className = 'replay-status healing';
          } else if (msg.type === 'heal_success') {
            appendLine(`✓ Healed by ${msg.model}`, 'term-heal-ok');
          } else if (msg.type === 'heal_fail') {
            appendLine(`✗ Heal failed: ${msg.reason}`, 'term-heal-fail');
          } else if (msg.type === 'done') {
            appendLine('');
            const fill = document.getElementById('progress-fill');
            fill.classList.remove('healing');
            if (msg.passed) {
              if (msg.vision_healed) {
                appendLine(`✓ Tests passed (vision-healed ${msg.vision_heal_count} element${msg.vision_heal_count > 1 ? 's' : ''})`, 'term-pass');
                statusEl.textContent = '👁 VISION HEALED';
                statusEl.className = 'replay-status healed';
              } else if (msg.healed) {
                appendLine(`✓ Tests passed (auto-healed in ${msg.heal_attempts} attempt${msg.heal_attempts > 1 ? 's' : ''})`, 'term-pass');
                statusEl.textContent = '✓ HEALED';
                statusEl.className = 'replay-status healed';
              } else {
                appendLine('✓ All tests passed', 'term-pass');
                statusEl.textContent = '✓ PASSED';
                statusEl.className = 'replay-status pass';
              }
              fill.style.width = '100%';
              fill.classList.add('done');
            } else {
              appendLine('✗ Tests failed', 'term-fail');
              statusEl.textContent = '✗ FAILED';
              statusEl.className = 'replay-status fail';
              fill.classList.add('fail');
            }
            loadRunHistory();
            if (msg.run_id) fetchAndRenderDiagnostics(msg.run_id, msg);
          }
        } catch {}
      }
    }
  } catch (e) {
    appendLine(`Error: ${e.message}`, 'term-error');
    statusEl.textContent = '✗ ERROR';
    statusEl.className = 'replay-status fail';
  }

  runBtn.disabled = false;
  runBtn.innerHTML = '▶ Run Replay';
}

// ── Replay Diagnostics ─────────────────────────────────────────────────────

async function fetchAndRenderDiagnostics(runId, doneMsg) {
  try {
    const resp = await fetch(`/api/runs/${runId}/diagnostics`);
    if (!resp.ok) return;
    const d = await resp.json();
    renderDiagnostics(d, doneMsg);
  } catch {}
}

function renderDiagnostics(d, doneMsg) {
  const panel  = document.getElementById('diagnostics-panel');
  const body   = document.getElementById('diag-body');
  const header = panel.querySelector('.diag-header');

  const errs  = d.console_errors   || [];
  const nets  = d.network_failures  || [];
  const apis  = d.api_calls         || [];

  // Summary badge
  const parts = [];
  if (errs.length)  parts.push(`${errs.length} error${errs.length > 1 ? 's' : ''}`);
  if (nets.length)  parts.push(`${nets.length} net fail${nets.length > 1 ? 's' : ''}`);
  if (apis.length)  parts.push(`${apis.length} API call${apis.length > 1 ? 's' : ''}`);
  document.getElementById('diag-summary').textContent = parts.join(' · ');

  // Console errors section
  const consoleSection = document.getElementById('diag-console');
  if (errs.length) {
    document.getElementById('diag-console-count').textContent = errs.length;
    const ul = document.getElementById('diag-console-list');
    ul.innerHTML = '';
    errs.forEach(e => { const li = document.createElement('li'); li.textContent = e; ul.appendChild(li); });
    consoleSection.classList.remove('hidden');
  }

  // Network failures section
  const netSection = document.getElementById('diag-network');
  if (nets.length) {
    document.getElementById('diag-network-count').textContent = nets.length;
    const ul = document.getElementById('diag-network-list');
    ul.innerHTML = '';
    nets.forEach(n => { const li = document.createElement('li'); li.textContent = n; ul.appendChild(li); });
    netSection.classList.remove('hidden');
  }

  // API calls section
  const apiSection = document.getElementById('diag-api');
  if (apis.length) {
    document.getElementById('diag-api-count').textContent = apis.length;
    const ul = document.getElementById('diag-api-list');
    ul.innerHTML = '';
    apis.forEach(a => { const li = document.createElement('li'); li.textContent = a; ul.appendChild(li); });
    apiSection.classList.remove('hidden');
  }

  // Empty state
  if (!errs.length && !nets.length && !apis.length) {
    document.getElementById('diag-empty').classList.remove('hidden');
  }

  panel.classList.remove('hidden');
  // Auto-expand if there are errors or network failures
  if (errs.length || nets.length) {
    header.classList.add('open');
    body.style.display = '';
  } else {
    body.style.display = 'none';
  }
}

function toggleDiagnostics() {
  const header = document.querySelector('.diag-header');
  const body   = document.getElementById('diag-body');
  const isOpen = header.classList.toggle('open');
  body.style.display = isOpen ? '' : 'none';
}

// ── Screenshot carousel state ──────────────────────────────────────────────
let _ssIndex = 0;

function _ssItems() {
  return Array.from(document.getElementById('screenshot-strip').children);
}

function _ssDots() {
  return Array.from(document.getElementById('screenshot-dots').children);
}

function _ssUpdateUI() {
  const items = _ssItems();
  const total = items.length;

  // Show only the active slide
  items.forEach((el, i) => {
    el.classList.toggle('hidden-slide', i !== _ssIndex);
  });

  // Sync dots
  _ssDots().forEach((d, i) => d.classList.toggle('active', i === _ssIndex));

  // Counter
  document.getElementById('screenshot-counter').textContent =
    total > 0 ? `${_ssIndex + 1} / ${total}` : '';

  // Arrow states
  const prev = document.getElementById('ss-prev');
  const next = document.getElementById('ss-next');
  if (prev) prev.disabled = (_ssIndex === 0);
  if (next) next.disabled = (_ssIndex >= total - 1);
}

function screenshotNav(dir) {
  const total = _ssItems().length;
  _ssIndex = Math.max(0, Math.min(total - 1, _ssIndex + dir));
  _ssUpdateUI();
}

function screenshotGoTo(idx) {
  _ssIndex = idx;
  _ssUpdateUI();
}

// Keyboard arrow support (only when not typing in an input)
document.addEventListener('keydown', (e) => {
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  const container = document.getElementById('replay-screenshots');
  if (!container || container.classList.contains('hidden')) return;
  if (e.key === 'ArrowLeft')  { e.preventDefault(); screenshotNav(-1); }
  if (e.key === 'ArrowRight') { e.preventDefault(); screenshotNav(1); }
});

function openScreenshotFullsize(b64, startIdx) {
  const items = _ssItems();
  let currentIdx = startIdx ?? _ssIndex;

  const overlay = document.createElement('div');
  overlay.className = 'screenshot-overlay';

  const img = document.createElement('img');
  img.src = `data:image/png;base64,${b64}`;

  const counter = document.createElement('div');
  counter.className = 'ov-counter';

  const btnLeft = document.createElement('button');
  btnLeft.className = 'ov-arrow left';
  btnLeft.innerHTML = '&#8249;';

  const btnRight = document.createElement('button');
  btnRight.className = 'ov-arrow right';
  btnRight.innerHTML = '&#8250;';

  function updateOverlay() {
    const el = items[currentIdx];
    const src = el?.querySelector('img')?.src;
    if (src) img.src = src;
    counter.textContent = `${currentIdx + 1} / ${items.length}`;
    btnLeft.disabled  = currentIdx === 0;
    btnRight.disabled = currentIdx >= items.length - 1;
    // Sync the strip carousel too
    _ssIndex = currentIdx;
    _ssUpdateUI();
  }

  btnLeft.onclick  = (e) => { e.stopPropagation(); currentIdx = Math.max(0, currentIdx - 1); updateOverlay(); };
  btnRight.onclick = (e) => { e.stopPropagation(); currentIdx = Math.min(items.length - 1, currentIdx + 1); updateOverlay(); };

  // Close on click outside arrows/image
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  // Keyboard nav inside overlay
  const onKey = (e) => {
    if (e.key === 'ArrowLeft')  { currentIdx = Math.max(0, currentIdx - 1); updateOverlay(); }
    if (e.key === 'ArrowRight') { currentIdx = Math.min(items.length - 1, currentIdx + 1); updateOverlay(); }
    if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); }
  };
  document.addEventListener('keydown', onKey);
  overlay.addEventListener('remove', () => document.removeEventListener('keydown', onKey));

  overlay.appendChild(btnLeft);
  overlay.appendChild(img);
  overlay.appendChild(btnRight);
  overlay.appendChild(counter);
  document.body.appendChild(overlay);
  updateOverlay();
}

// --- Toast Notifications ---
function showToast(message, type = 'success', duration = 6000) {
  const existing = document.getElementById('toast-container');
  if (existing) existing.remove();

  const container = document.createElement('div');
  container.id = 'toast-container';
  container.className = `toast toast-${type}`;
  container.innerHTML = `
    <span class="toast-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
    <span class="toast-message">${message}</span>
    <button class="toast-close" onclick="this.parentElement.remove()">×</button>
  `;
  document.body.appendChild(container);

  setTimeout(() => container.classList.add('toast-visible'), 10);
  if (duration > 0) {
    setTimeout(() => {
      container.classList.remove('toast-visible');
      setTimeout(() => container.remove(), 400);
    }, duration);
  }
}

// --- File Upload ---
const fileInput = document.getElementById('file-upload');
const uploadBtn = document.getElementById('upload-btn');
const fileNameEl = document.getElementById('file-name');
const uploadStatus = document.getElementById('upload-status');

fileInput.addEventListener('change', () => {
  if (fileInput.files.length) {
    fileNameEl.textContent = fileInput.files[0].name;
    uploadBtn.disabled = false;
    uploadStatus.className = 'upload-status hidden';
  }
});

uploadBtn.addEventListener('click', async () => {
  if (!fileInput.files.length) return;

  uploadBtn.disabled = true;
  uploadBtn.innerHTML = '<span class="spinner"></span> Processing...';
  uploadStatus.className = 'upload-status hidden';

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  try {
    const res = await fetch('/api/ingest/file', { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();

    const eventsWord = data.events_received === 1 ? 'event' : 'events';
    const journeysWord = data.journeys_created === 1 ? 'journey' : 'journeys';

    uploadStatus.innerHTML = `
      <strong>✓ Processing complete!</strong><br>
      ${data.events_received} ${eventsWord} ingested &nbsp;·&nbsp;
      <strong>${data.journeys_created} ${journeysWord} discovered</strong>
    `;
    uploadStatus.className = 'upload-status success';

    showToast(
      `Learned from your session! ${data.events_received} events → ${data.journeys_created} new ${journeysWord} discovered.`,
      'success',
      8000
    );

    await Promise.all([loadStats(), loadDomains(), loadJourneys(undefined, true), loadCoverage()]);

  } catch (e) {
    uploadStatus.textContent = `Error: ${e.message}`;
    uploadStatus.className = 'upload-status error';
    showToast(`Upload failed: ${e.message}`, 'error', 0);
  }

  uploadBtn.innerHTML = 'Process Events';
  uploadBtn.disabled = false;
});

// --- Chat ---
document.getElementById('chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const q = input.value.trim();
  if (!q) return;

  const msgs = document.getElementById('chat-messages');
  msgs.innerHTML += `<div class="message user">${esc(q)}</div>`;
  input.value = '';

  msgs.innerHTML += `<div class="message bot" id="typing">Thinking...</div>`;
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q }),
    });
    const data = await res.json();
    document.getElementById('typing').textContent = data.answer;
  } catch {
    document.getElementById('typing').textContent = 'Error connecting to backend.';
  }
  msgs.scrollTop = msgs.scrollHeight;
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeModal();
    closeSettingsModal();
    closeNLTestModal();
    closeRCAModal();
    closeExplorerModal();
  }
});

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// --- LLM Provider Badge ---

let _llmProviders = {};

async function loadLLMStatus() {
  const badge = document.getElementById('llm-provider-badge');
  if (!badge) return;
  try {
    const data = await fetchJSON('/api/settings/llm');
    if (!data) return;
    _llmProviders = data.providers || {};
    const cur = data.current || {};
    if (cur.has_key || cur.provider === 'ollama') {
      badge.textContent = `${cur.provider_name} — ${cur.model}`;
      badge.className = 'llm-badge active';
    } else {
      badge.textContent = 'Not configured';
      badge.className = 'llm-badge inactive';
    }
  } catch {
    badge.textContent = 'error';
    badge.className = 'llm-badge inactive';
  }
}

// --- LLM Settings Modal ---

async function openSettingsModal() {
  const data = await fetchJSON('/api/settings/llm');
  if (!data) return;
  _llmProviders = data.providers || {};
  const cur = data.current || {};

  const provSelect = document.getElementById('settings-provider');
  provSelect.innerHTML = Object.entries(_llmProviders).map(([key, p]) =>
    `<option value="${key}" ${key === cur.provider ? 'selected' : ''}>${esc(p.name)} — ${esc(p.description)}</option>`
  ).join('');

  populateModels(cur.provider, cur.model);
  toggleKeyRow(cur.provider);

  document.getElementById('settings-api-key').value = '';
  document.getElementById('settings-status').textContent = '';
  document.getElementById('settings-modal').classList.remove('hidden');
}

function closeSettingsModal() {
  document.getElementById('settings-modal').classList.add('hidden');
}

function onProviderChange() {
  const prov = document.getElementById('settings-provider').value;
  toggleKeyRow(prov);
  populateModels(prov, '');
}

function toggleKeyRow(provider) {
  const info = _llmProviders[provider];
  const row = document.getElementById('settings-key-row');
  if (info && info.needs_key) {
    row.classList.remove('hidden');
  } else {
    row.classList.add('hidden');
  }
}

function populateModels(provider, currentModel) {
  const info = _llmProviders[provider];
  const select = document.getElementById('settings-model');
  if (!info) return;
  select.innerHTML = info.models.map(m =>
    `<option value="${m.id}" ${m.id === currentModel ? 'selected' : ''}>${esc(m.name)}${m.vision ? ' (vision)' : ''}</option>`
  ).join('');
}

async function saveLLMSettings() {
  const provider = document.getElementById('settings-provider').value;
  const apiKey = document.getElementById('settings-api-key').value.trim();
  const model = document.getElementById('settings-model').value;
  const status = document.getElementById('settings-status');

  status.textContent = 'Saving...';
  status.className = 'settings-status';

  try {
    const res = await fetch('/api/settings/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey, model }),
    });
    const data = await res.json();
    if (data.ok) {
      status.textContent = 'Saved';
      status.className = 'settings-status success';
      loadLLMStatus();
      showToast(`LLM provider set to ${data.provider_name}`, 'success');
    } else {
      status.textContent = data.error || 'Failed';
      status.className = 'settings-status error';
    }
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    status.className = 'settings-status error';
  }
}

async function testLLMConnection() {
  const status = document.getElementById('settings-status');
  status.textContent = 'Testing...';
  status.className = 'settings-status';

  try {
    const res = await fetch('/api/settings/llm/test', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      status.textContent = `Connected — "${data.response}"`;
      status.className = 'settings-status success';
    } else {
      status.textContent = data.error || 'Connection failed';
      status.className = 'settings-status error';
    }
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    status.className = 'settings-status error';
  }
}

// --- NL Test Generator ---

let _lastGeneratedTest = '';

function openNLTestModal() {
  document.getElementById('nl-output').innerHTML = '<span class="term-dim">Describe your test above and click Generate...</span>';
  document.getElementById('nl-download-btn').classList.add('hidden');
  document.getElementById('nl-test-modal').classList.remove('hidden');
}

function closeNLTestModal() {
  document.getElementById('nl-test-modal').classList.add('hidden');
}

async function generateNLTest() {
  const desc = document.getElementById('nl-description').value.trim();
  const baseUrl = document.getElementById('nl-base-url').value.trim();
  const output = document.getElementById('nl-output');

  if (!desc) {
    output.innerHTML = '<span class="term-error">Please enter a test description</span>';
    return;
  }

  output.innerHTML = '<span class="term-dim">Generating test...</span>';

  try {
    const res = await fetch('/api/ai/generate-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: desc, base_url: baseUrl }),
    });
    const data = await res.json();
    if (data.test_code) {
      _lastGeneratedTest = data.test_code;
      output.innerHTML = `<span class="term-dim"># Generated by ${esc(data.model)}</span>\n` +
        esc(data.test_code);
      document.getElementById('nl-download-btn').classList.remove('hidden');
    } else {
      output.innerHTML = `<span class="term-error">${esc(data.detail || 'Generation failed')}</span>`;
    }
  } catch (e) {
    output.innerHTML = `<span class="term-error">Error: ${esc(e.message)}</span>`;
  }
}

function downloadNLTest() {
  if (!_lastGeneratedTest) return;
  const blob = new Blob([_lastGeneratedTest], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'test_generated.py';
  a.click();
  URL.revokeObjectURL(url);
}

// --- Root Cause Analysis ---

// --- CI/CD Pipeline ---

let _ciYaml = '';

function openCIModal() {
  document.getElementById('ci-output').innerHTML = '<span class="term-dim">Configure options above and click Generate...</span>';
  document.getElementById('ci-download-btn').classList.add('hidden');
  document.getElementById('ci-modal').classList.remove('hidden');
}

function closeCIModal() {
  document.getElementById('ci-modal').classList.add('hidden');
}

async function generateCI() {
  const framework = document.getElementById('ci-framework').value;
  const base_url = document.getElementById('ci-base-url').value || 'https://your-app.example.com';
  const cron = document.getElementById('ci-cron').value;
  const has_auth = document.getElementById('ci-auth').checked;

  document.getElementById('ci-output').innerHTML = '<span class="term-dim">Generating workflow...</span>';

  try {
    const res = await fetch('/api/export/ci', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ framework, base_url, cron, has_auth }),
    });
    _ciYaml = await res.text();
    document.getElementById('ci-output').innerHTML = `<pre style="margin:0;white-space:pre-wrap;color:var(--text-primary)">${esc(_ciYaml)}</pre>`;
    document.getElementById('ci-download-btn').classList.remove('hidden');
  } catch (e) {
    document.getElementById('ci-output').innerHTML = `<span class="term-fail">Error: ${e.message}</span>`;
  }
}

function downloadCI() {
  const blob = new Blob([_ciYaml], { type: 'text/yaml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'vigil.yml';
  a.click();
  URL.revokeObjectURL(url);
}

// --- RCA ---

function openRCAModal() {
  document.getElementById('rca-output').innerHTML = '<span class="term-dim">Click Analyze to inspect recent failures...</span>';
  document.getElementById('rca-modal').classList.remove('hidden');
}

function closeRCAModal() {
  document.getElementById('rca-modal').classList.add('hidden');
}

async function runRCA() {
  const output = document.getElementById('rca-output');
  output.innerHTML = '<span class="term-dim">Analyzing failures...</span>';

  try {
    const data = await fetchJSON('/api/ai/rca?limit=30');
    if (!data || !data.analysis) {
      output.innerHTML = '<span class="term-dim">No data returned.</span>';
      return;
    }
    const a = data.analysis;
    let html = '';

    if (typeof a === 'string') {
      html = `<p>${esc(a)}</p>`;
    } else {
      html += `<div class="rca-summary">${esc(a.summary || '')}</div>`;

      if (a.patterns && a.patterns.length) {
        html += '<h3>Failure Patterns</h3><div class="rca-patterns">';
        a.patterns.forEach(p => {
          const sev = p.severity || 'medium';
          html += `<div class="rca-pattern rca-${sev}">
            <div class="rca-pattern-title">${esc(p.pattern)} <span class="rca-freq">${esc(p.frequency || '')}</span></div>
            <div class="rca-fix">${esc(p.fix || '')}</div>
          </div>`;
        });
        html += '</div>';
      }

      if (a.flaky_tests && a.flaky_tests.length) {
        html += '<h3>Flaky Tests</h3><ul class="rca-list">';
        a.flaky_tests.forEach(t => { html += `<li>${esc(t)}</li>`; });
        html += '</ul>';
      }

      if (a.recommendations && a.recommendations.length) {
        html += '<h3>Recommendations</h3><ul class="rca-list">';
        a.recommendations.forEach(r => { html += `<li>${esc(r)}</li>`; });
        html += '</ul>';
      }

      if (data.model && data.model !== 'none') {
        html += `<div class="rca-model">Analyzed by ${esc(data.model)}</div>`;
      }
    }

    output.innerHTML = html;
  } catch (e) {
    output.innerHTML = `<span class="term-error">Error: ${esc(e.message)}</span>`;
  }
}

// --- AI Explorer ---

let _explorerSessionId = null;
let _explorerReader = null;
let _skillsData = null;
let _bundlesData = null;

async function loadSkills() {
  if (_skillsData) return;
  try {
    const res = await fetch('/api/explorer/skills');
    const data = await res.json();
    _skillsData = data.skills || [];
    _bundlesData = data.bundles || {};
  } catch { _skillsData = []; _bundlesData = {}; }
}

function renderSkillsGrid() {
  const grid = document.getElementById('skills-grid');
  if (!grid || !_skillsData) return;
  grid.innerHTML = _skillsData.map(sk => `
    <div class="skill-chip active" data-skill-id="${sk.id}"
         data-tooltip="${sk.curiosity_rules.slice(0,3).join(' • ')}"
         onclick="toggleSkill(this)">
      <span class="skill-chip-icon">${sk.icon}</span>
      <div class="skill-chip-body">
        <div class="skill-chip-name">${sk.name}</div>
        <div class="skill-chip-desc">${sk.description}</div>
      </div>
      <div class="skill-chip-check"></div>
    </div>
  `).join('');
  applySkillBundle('deep_qa');
}

function toggleSkill(el) {
  el.classList.toggle('active');
}

function getSelectedSkills() {
  const chips = document.querySelectorAll('#skills-grid .skill-chip.active');
  const ids = Array.from(chips).map(c => c.dataset.skillId);
  return ids.length ? ids : ['curious_explorer'];
}

function applySkillBundle(bundleId) {
  if (!_bundlesData || !_bundlesData[bundleId]) return;
  const ids = _bundlesData[bundleId];
  document.querySelectorAll('#skills-grid .skill-chip').forEach(chip => {
    chip.classList.toggle('active', ids.includes(chip.dataset.skillId));
  });
}

async function openExplorerModal() {
  document.getElementById('explorer-config').classList.remove('hidden');
  document.getElementById('explorer-progress').classList.add('hidden');
  document.getElementById('explorer-results').classList.add('hidden');
  document.getElementById('explorer-start-btn').classList.remove('hidden');
  document.getElementById('explorer-stop-btn').classList.add('hidden');
  document.getElementById('explorer-session-status').className = 'explorer-status hidden';
  document.getElementById('explorer-log').innerHTML = '<span class="term-dim">Configure and start exploring...</span>';
  document.getElementById('explorer-pages-count').textContent = '0';
  document.getElementById('explorer-steps-count').textContent = '0';
  document.getElementById('explorer-flows-count').textContent = '0';
  document.getElementById('explorer-journeys-list').innerHTML = '';
  document.getElementById('explorer-save-status').textContent = '';
  _explorerSessionId = null;
  document.getElementById('explorer-modal').classList.remove('hidden');
  await loadSkills();
  renderSkillsGrid();
}

function closeExplorerModal() {
  if (_explorerReader) {
    try { _explorerReader.cancel(); } catch {}
    _explorerReader = null;
  }
  document.getElementById('explorer-modal').classList.add('hidden');
}

async function startExploration() {
  const url = document.getElementById('explorer-url').value.trim();
  if (!url || !url.startsWith('http')) {
    alert('Enter a valid URL (e.g. https://www.saucedemo.com)');
    return;
  }

  const strategy = document.getElementById('explorer-strategy').value;
  const maxPages = parseInt(document.getElementById('explorer-max-pages').value) || 30;
  const maxTime = parseInt(document.getElementById('explorer-max-time').value) || 10;
  const headed = document.getElementById('explorer-headed').checked;

  document.getElementById('explorer-start-btn').classList.add('hidden');
  document.getElementById('explorer-stop-btn').classList.remove('hidden');
  document.getElementById('explorer-progress').classList.remove('hidden');
  document.getElementById('explorer-results').classList.add('hidden');

  const log = document.getElementById('explorer-log');
  log.innerHTML = '';
  const statusEl = document.getElementById('explorer-session-status');
  statusEl.textContent = 'EXPLORING';
  statusEl.className = 'explorer-status exploring';

  const appendLog = (text, cls = '') => {
    const line = document.createElement('div');
    line.className = 'term-line' + (cls ? ` ${cls}` : '');
    line.textContent = text;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  };

  try {
    const res = await fetch('/api/explorer/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: url,
        strategy: strategy,
        max_pages: maxPages,
        max_time_minutes: maxTime,
        headed: headed,
        skills: getSelectedSkills(),
      }),
    });

    if (!res.ok) throw new Error(`Server error: ${res.status}`);

    const reader = res.body.getReader();
    _explorerReader = reader;
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        const dataLine = part.split('\n').find(l => l.startsWith('data:'));
        if (!dataLine) continue;
        try {
          const msg = JSON.parse(dataLine.slice(5));
          handleExplorerEvent(msg, appendLog);
        } catch {}
      }
    }
  } catch (e) {
    appendLog(`Error: ${e.message}`, 'term-error');
    statusEl.textContent = 'ERROR';
    statusEl.className = 'explorer-status error';
  }

  _explorerReader = null;
  document.getElementById('explorer-start-btn').classList.remove('hidden');
  document.getElementById('explorer-stop-btn').classList.add('hidden');
}

function handleExplorerEvent(msg, appendLog) {
  const statusEl = document.getElementById('explorer-session-status');

  if (msg.type === 'start') {
    _explorerSessionId = msg.session_id;
    appendLog(`Starting exploration of ${msg.base_url}`, 'term-cmd');
    appendLog(`Strategy: ${msg.strategy} | Max: ${msg.max_pages} pages, ${msg.max_time_minutes} min`);
  } else if (msg.type === 'status') {
    appendLog(msg.message, 'term-step');
  } else if (msg.type === 'page') {
    document.getElementById('explorer-pages-count').textContent = msg.pages_visited || 0;
    document.getElementById('explorer-steps-count').textContent = msg.step || 0;
    const title = msg.title ? ` — "${msg.title}"` : '';
    appendLog(`Page: ${msg.url}${title} (${msg.elements} elements)`, 'term-step');
  } else if (msg.type === 'interaction') {
    document.getElementById('explorer-pages-count').textContent = msg.pages_visited || 0;
    document.getElementById('explorer-steps-count').textContent = msg.step || 0;
    const icon = msg.success ? '\u2713' : '\u2717';
    const cls = msg.success ? 'term-pass' : 'term-fail';
    const element = msg.element ? msg.element.substring(0, 60) : '';
    appendLog(`  ${icon} ${msg.action}: ${element}`, cls);
    if (msg.error) appendLog(`    Error: ${msg.error}`, 'term-fail');
  } else if (msg.type === 'error') {
    appendLog(`Error: ${msg.message}`, 'term-error');
  } else if (msg.type === 'done') {
    statusEl.textContent = (msg.status === 'stopped') ? 'STOPPED' : 'COMPLETED';
    statusEl.className = 'explorer-status ' + (msg.status === 'stopped' ? 'stopped' : 'completed');

    document.getElementById('explorer-pages-count').textContent = msg.pages_visited || 0;
    const journeys = msg.journeys || [];
    document.getElementById('explorer-flows-count').textContent = journeys.length;

    appendLog('');
    appendLog(`Exploration complete: ${msg.pages_visited} pages, ${(msg.interactions || []).length} interactions, ${journeys.length} journeys`, 'term-pass');

    if (journeys.length > 0) {
      renderExplorerResults(journeys);
    }

    loadJourneys(undefined, false);
    loadStats();
  }
}

function renderExplorerResults(journeys) {
  document.getElementById('explorer-results').classList.remove('hidden');
  const list = document.getElementById('explorer-journeys-list');

  list.innerHTML = journeys.map((j, idx) => {
    const stepCount = (j.steps || []).length;
    const urlCount = (j.urls || []).length;
    return `
      <div class="explorer-journey-card">
        <div class="explorer-journey-header">
          <input type="checkbox" class="explorer-journey-check" data-idx="${idx}" checked>
          <span class="explorer-journey-name">${esc(j.name)}</span>
          <span class="explorer-journey-meta">${stepCount} steps, ${urlCount} pages</span>
        </div>
        <div class="explorer-journey-desc">${esc(j.description || '')}</div>
        <div class="explorer-journey-steps">
          ${(j.steps || []).slice(0, 5).map(s =>
            `<div class="explorer-step">${esc(s.description || '')}</div>`
          ).join('')}
          ${stepCount > 5 ? `<div class="explorer-step term-dim">...and ${stepCount - 5} more steps</div>` : ''}
        </div>
      </div>`;
  }).join('');
}

async function stopExploration() {
  if (!_explorerSessionId) return;
  try {
    await fetch(`/api/explorer/stop/${_explorerSessionId}`, { method: 'POST' });
  } catch {}
}

async function saveExplorerJourneys() {
  if (!_explorerSessionId) return;
  const status = document.getElementById('explorer-save-status');
  status.textContent = 'Saving...';

  const checks = document.querySelectorAll('.explorer-journey-check:checked');
  const indices = Array.from(checks).map(c => parseInt(c.dataset.idx));

  try {
    const res = await fetch(`/api/explorer/results/${_explorerSessionId}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ journey_indices: indices }),
    });
    const data = await res.json();
    if (data.ok) {
      status.textContent = `Saved ${data.count} journeys`;
      status.className = 'settings-status success';
      showToast(`Saved ${data.count} journeys from exploration`, 'success');
      loadJourneys(undefined, true);
      loadStats();
    } else {
      status.textContent = data.detail || 'Save failed';
      status.className = 'settings-status error';
    }
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    status.className = 'settings-status error';
  }
}

// --- Assertions (triggered from journey modal) ---

async function generateAssertions(journeyId) {
  const output = document.getElementById('modal-body');
  const existing = output.innerHTML;
  output.innerHTML += '<div class="assertions-loading">Generating assertions...</div>';

  try {
    const res = await fetch('/api/ai/assertions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ journey_id: journeyId }),
    });
    const data = await res.json();

    const loadingEl = output.querySelector('.assertions-loading');
    if (loadingEl) loadingEl.remove();

    if (data.assertions && data.assertions.length) {
      let html = '<div class="assertions-block"><h3>AI-Generated Assertions</h3>';
      data.assertions.forEach(a => {
        html += `<div class="assertion-item">
          <span class="assertion-step">After step ${a.after_step || '?'}</span>
          <code>${esc(a.code)}</code>
          <span class="assertion-desc">${esc(a.description || '')}</span>
        </div>`;
      });
      html += `<div class="rca-model">Generated by ${esc(data.model)}</div></div>`;
      output.innerHTML += html;
    } else {
      output.innerHTML += '<div class="term-dim" style="margin-top:0.5rem">No assertions generated.</div>';
    }
  } catch (e) {
    const loadingEl = output.querySelector('.assertions-loading');
    if (loadingEl) loadingEl.textContent = 'Error: ' + e.message;
  }
}

init();

// --- Hero Carousel ---
let currentSlide = 0;
let carouselInterval;

function initCarousel() {
  const slides = document.querySelectorAll('.carousel-slide');
  if (!slides.length) return;
  
  // Start auto-rotation
  startCarouselTimer();
}

function setCarousel(index) {
  const slides = document.querySelectorAll('.carousel-slide');
  const dots = document.querySelectorAll('.dot');
  
  if (index >= slides.length) currentSlide = 0;
  else if (index < 0) currentSlide = slides.length - 1;
  else currentSlide = index;
  
  slides.forEach((s, i) => {
    if (i === currentSlide) {
      s.classList.add('active');
    } else {
      s.classList.remove('active');
    }
  });
  
  dots.forEach((d, i) => {
    if (i === currentSlide) d.classList.add('active');
    else d.classList.remove('active');
  });
  
  resetCarouselTimer();
}

function moveCarousel(direction) {
  setCarousel(currentSlide + direction);
}

function startCarouselTimer() {
  carouselInterval = setInterval(() => {
    moveCarousel(1);
  }, 5000); // Rotate every 5 seconds
}

function resetCarouselTimer() {
  clearInterval(carouselInterval);
  startCarouselTimer();
}

// Initialize carousel on load
document.addEventListener('DOMContentLoaded', initCarousel);


// --- HITL Review Queue ---

let _selectedReviewIds = new Set();
let _reviewJourneyCache = {};

async function loadReviewStats() {
  const stats = await fetchJSON('/api/reviews/stats');
  if (!stats) return;
  const bar = document.getElementById('review-stats-bar');
  const byStatus = stats.by_status || {};
  const pending = (byStatus.pending_review || {}).count || 0;
  const autoApproved = (byStatus.auto_approved || {}).count || 0;
  const approved = (byStatus.approved || {}).count || 0;
  const rejected = (byStatus.rejected || {}).count || 0;
  const accuracy = ((stats.accuracy_rate || 0) * 100).toFixed(0);
  bar.innerHTML = `
    <div class="review-stat"><span class="review-stat-value">${pending}</span><span class="review-stat-label">Pending</span></div>
    <div class="review-stat"><span class="review-stat-value">${autoApproved}</span><span class="review-stat-label">Auto-Approved</span></div>
    <div class="review-stat"><span class="review-stat-value">${approved}</span><span class="review-stat-label">Human Approved</span></div>
    <div class="review-stat"><span class="review-stat-value">${rejected}</span><span class="review-stat-label">Rejected</span></div>
    <div class="review-stat accuracy"><span class="review-stat-value">${accuracy}%</span><span class="review-stat-label">AI Accuracy</span></div>
  `;
}

async function loadReviewQueue() {
  const status = document.getElementById('review-status-filter').value;
  const domain = document.getElementById('review-domain-filter').value;
  let url = '/api/reviews?limit=50';
  if (status) url += `&status=${encodeURIComponent(status)}`;
  if (domain) url += `&domain=${encodeURIComponent(domain)}`;

  const items = await fetchJSON(url);
  const container = document.getElementById('review-queue-list');
  _selectedReviewIds.clear();
  updateBatchButton();

  if (!items || !items.length) {
    container.innerHTML = '<p class="empty-state">No journeys in this queue.</p>';
    return;
  }

  // Populate domain filter with unique domains
  const domainFilter = document.getElementById('review-domain-filter');
  const currentDomainVal = domainFilter.value;
  const domains = [...new Set(items.map(j => j.domain).filter(Boolean))].sort();
  const existingOpts = new Set([...domainFilter.options].map(o => o.value));
  domains.forEach(d => {
    if (!existingOpts.has(d)) {
      const opt = document.createElement('option');
      opt.value = d; opt.textContent = d;
      domainFilter.appendChild(opt);
    }
  });
  domainFilter.value = currentDomainVal;

  _reviewJourneyCache = {};
  items.forEach(j => { _reviewJourneyCache[j.id] = j; });

  container.innerHTML = items.map(j => {
    const conf = j.confidence || 0;
    const confClass = conf >= 0.8 ? 'high' : conf >= 0.5 ? 'medium' : 'low';
    const statusLabel = (j.review_status || 'pending_review').replace(/_/g, ' ');
    const stepCount = j.step_count || 0;
    const date = j.discovered_at ? timeAgo(new Date(j.discovered_at)) : '';
    return `
      <div class="review-card" data-journey-id="${j.id}">
        <input type="checkbox" class="review-card-checkbox"
               onchange="toggleReviewSelection('${j.id}', this.checked)">
        <div class="review-card-body">
          <div class="review-card-header">
            <span class="review-card-name">${esc(j.name)}</span>
            <div style="display:flex;gap:0.4rem;align-items:center">
              <span class="review-status-badge ${j.review_status || 'pending_review'}">${esc(statusLabel)}</span>
              <span class="confidence-badge confidence-${confClass}">${(conf * 100).toFixed(0)}%</span>
            </div>
          </div>
          <div class="review-card-meta">
            ${esc(j.domain || 'Uncategorized')} &rarr; ${esc(j.feature || 'General')} | ${stepCount} steps | ${date}
          </div>
        </div>
        <div class="review-card-actions">
          <button class="btn-approve" onclick="event.stopPropagation(); approveJourney('${j.id}')">Approve</button>
          <button class="btn-reject" onclick="event.stopPropagation(); rejectJourney('${j.id}')">Reject</button>
          <button class="btn-correct" onclick="event.stopPropagation(); openCorrectModalById('${j.id}')">Correct</button>
        </div>
      </div>
    `;
  }).join('');
}

function timeAgo(date) {
  const seconds = Math.floor((new Date() - date) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + 'm ago';
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + 'h ago';
  const days = Math.floor(hours / 24);
  return days + 'd ago';
}

function toggleReviewSelection(id, checked) {
  if (checked) _selectedReviewIds.add(id);
  else _selectedReviewIds.delete(id);
  updateBatchButton();
}

function toggleSelectAllReviews(checked) {
  const checkboxes = document.querySelectorAll('.review-card-checkbox');
  checkboxes.forEach(cb => {
    cb.checked = checked;
    const card = cb.closest('.review-card');
    if (card) {
      const id = card.dataset.journeyId;
      if (checked) _selectedReviewIds.add(id);
      else _selectedReviewIds.delete(id);
    }
  });
  updateBatchButton();
}

function updateBatchButton() {
  const btn = document.getElementById('batch-approve-btn');
  btn.disabled = _selectedReviewIds.size === 0;
  btn.textContent = _selectedReviewIds.size > 0
    ? `Batch Approve (${_selectedReviewIds.size})`
    : 'Batch Approve';
}

async function approveJourney(id) {
  const res = await fetch(API + `/api/reviews/${id}/approve`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reviewer: '', note: ''}),
  });
  if (res.ok) {
    loadReviewQueue();
    loadReviewStats();
  }
}

async function rejectJourney(id) {
  const res = await fetch(API + `/api/reviews/${id}/reject`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reviewer: '', note: ''}),
  });
  if (res.ok) {
    loadReviewQueue();
    loadReviewStats();
  }
}

async function batchApproveSelected() {
  const ids = [..._selectedReviewIds];
  if (!ids.length) return;
  const res = await fetch(API + '/api/reviews/batch-approve', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({journey_ids: ids, reviewer: ''}),
  });
  if (res.ok) {
    _selectedReviewIds.clear();
    document.getElementById('review-select-all').checked = false;
    loadReviewQueue();
    loadReviewStats();
  }
}

// --- Correct Modal ---

async function openCorrectModalById(id) {
  const j = _reviewJourneyCache[id];
  if (!j) return;
  await openCorrectModal(id, j.name || '', j.domain || '', j.feature || '', j.tags || '[]', j.confidence || 0);
}

async function openCorrectModal(id, name, domain, feature, tagsJson, confidence) {
  document.getElementById('correct-journey-id').value = id;
  document.getElementById('correct-ai-name').textContent = 'Name: ' + name;
  document.getElementById('correct-ai-domain').textContent = 'Domain: ' + (domain || 'Uncategorized');
  document.getElementById('correct-ai-feature').textContent = 'Feature: ' + (feature || 'General');
  document.getElementById('correct-ai-confidence').textContent = 'Confidence: ' + (confidence * 100).toFixed(0) + '%';

  document.getElementById('correct-name').value = name;
  document.getElementById('correct-domain').value = domain;
  document.getElementById('correct-feature').value = feature;

  let tags = [];
  try { tags = typeof tagsJson === 'string' ? JSON.parse(tagsJson) : tagsJson; } catch {}
  document.getElementById('correct-tags').value = Array.isArray(tags) ? tags.join(', ') : '';
  document.getElementById('correct-note').value = '';
  document.getElementById('correct-status').textContent = '';

  // Show modal immediately, then load vocabulary in background
  document.getElementById('correct-modal').classList.remove('hidden');

  // Load vocabulary for datalists
  const vocab = await fetchJSON('/api/labels/vocabulary');
  if (vocab) {
    const domainList = document.getElementById('correct-domain-list');
    domainList.innerHTML = (vocab.domains || []).map(d => `<option value="${esc(d)}">`).join('');
    const featureList = document.getElementById('correct-feature-list');
    featureList.innerHTML = (vocab.features || []).map(f => `<option value="${esc(f)}">`).join('');
  }
}

function closeCorrectModal() {
  document.getElementById('correct-modal').classList.add('hidden');
}

async function submitCorrection() {
  const id = document.getElementById('correct-journey-id').value;
  const tagsStr = document.getElementById('correct-tags').value;
  const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];

  const body = {
    name: document.getElementById('correct-name').value,
    domain: document.getElementById('correct-domain').value,
    feature: document.getElementById('correct-feature').value,
    tags: tags,
    reviewer: '',
    note: document.getElementById('correct-note').value,
  };

  const statusEl = document.getElementById('correct-status');
  statusEl.textContent = 'Saving...';

  const res = await fetch(API + `/api/reviews/${id}/correct`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });

  if (res.ok) {
    statusEl.textContent = 'Saved!';
    setTimeout(() => {
      closeCorrectModal();
      loadReviewQueue();
      loadReviewStats();
    }, 500);
  } else {
    statusEl.textContent = 'Error saving';
  }
}

// --- HITL Config Modal ---

function openHITLConfigModal() {
  document.getElementById('hitl-config-modal').classList.remove('hidden');
  loadHITLConfig();
}

function closeHITLConfigModal() {
  document.getElementById('hitl-config-modal').classList.add('hidden');
}

async function loadHITLConfig() {
  const config = await fetchJSON('/api/hitl/config');
  if (config && config.auto_approve_threshold) {
    const val = parseFloat(config.auto_approve_threshold);
    document.getElementById('hitl-threshold-slider').value = val;
    document.getElementById('hitl-threshold-val').textContent = (val * 100).toFixed(0) + '%';
  }
}

async function saveHITLConfig() {
  const threshold = parseFloat(document.getElementById('hitl-threshold-slider').value);
  const statusEl = document.getElementById('hitl-config-status');
  statusEl.textContent = 'Saving...';

  const res = await fetch(API + '/api/hitl/config', {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({auto_approve_threshold: threshold}),
  });

  if (res.ok) {
    statusEl.textContent = 'Saved!';
    setTimeout(() => { statusEl.textContent = ''; }, 2000);
  } else {
    statusEl.textContent = 'Error saving';
  }
}

// ═══════════════════════════════════════════════════════════
// GUIDED TOUR — Interactive walkthrough for client demos
// ═══════════════════════════════════════════════════════════

const TOUR_STEPS = [
  {
    target: '.hero-section',
    title: 'Welcome to Vigil',
    body: 'AI-powered QA automation that replaces fragile test scripts. Vigil captures, understands, and replays user journeys — then self-heals when UI changes.',
    position: 'bottom',
  },
  {
    target: '.stats-bar',
    title: 'Live Dashboard Stats',
    body: 'Real-time overview: total journeys discovered, domains covered, features tested, and overall AI confidence scores.',
    position: 'bottom',
  },
  {
    target: '.journeys-section',
    title: 'Discovered Journeys',
    body: 'AI automatically organizes captured interactions into logical user journeys. Each card shows the domain, feature, confidence score, and tags.',
    position: 'top',
  },
  {
    target: '.journeys-section .journey-card',
    title: 'Journey Details',
    body: 'Click any journey to see step-by-step actions, selectors captured, and export options. You can replay, export to Playwright/Cypress/Selenium, or edit labels.',
    position: 'top',
  },
  {
    target: '.runs-section',
    title: 'Test Run History',
    body: 'Every replay is tracked with pass/fail status, duration, and step-level results. Failed tests show exactly which step broke and why.',
    position: 'top',
  },
  {
    target: '.ai-section',
    title: 'AI-Powered Features',
    body: 'Autonomous Explorer crawls your app without human guidance. NL Test Generation creates tests from plain English. Root Cause Analysis identifies failure patterns.',
    position: 'top',
  },
  {
    target: '.ai-card-explorer',
    title: 'AI Explorer',
    body: 'Give it a URL — the AI agent systematically explores every page, fills forms, clicks buttons, and discovers all user flows automatically.',
    position: 'top',
  },
  {
    target: '.review-section',
    title: 'Human-in-the-Loop Review',
    body: 'AI labels are reviewed by your team. Auto-approve high-confidence journeys, manually verify edge cases. Your corrections improve future accuracy.',
    position: 'top',
  },
  {
    target: '.coverage-section',
    title: 'Coverage Overview',
    body: 'Visual heatmap showing which domains and features have test coverage. Quickly identify gaps in your QA regression suite.',
    position: 'top',
  },
];

let _tourActive = false;
let _tourStep = 0;

function startTour() {
  _tourActive = true;
  _tourStep = 0;
  showTourStep();
}

function showTourStep() {
  // Remove any existing tour elements
  document.querySelectorAll('.tour-overlay, .tour-tooltip, .tour-spotlight').forEach(el => el.remove());

  if (_tourStep >= TOUR_STEPS.length) {
    endTour();
    return;
  }

  const step = TOUR_STEPS[_tourStep];
  const targetEl = document.querySelector(step.target);

  if (!targetEl) {
    _tourStep++;
    showTourStep();
    return;
  }

  // Scroll target into view
  targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });

  setTimeout(() => {
    const rect = targetEl.getBoundingClientRect();

    // Overlay
    const overlay = document.createElement('div');
    overlay.className = 'tour-overlay';
    overlay.onclick = () => { nextTourStep(); };
    document.body.appendChild(overlay);

    // Spotlight cutout
    const spotlight = document.createElement('div');
    spotlight.className = 'tour-spotlight';
    spotlight.style.top = (rect.top + window.scrollY - 8) + 'px';
    spotlight.style.left = (rect.left - 8) + 'px';
    spotlight.style.width = (rect.width + 16) + 'px';
    spotlight.style.height = (rect.height + 16) + 'px';
    document.body.appendChild(spotlight);

    // Tooltip
    const tooltip = document.createElement('div');
    tooltip.className = 'tour-tooltip';
    tooltip.innerHTML = `
      <div class="tour-tooltip-header">
        <span class="tour-step-badge">${_tourStep + 1} / ${TOUR_STEPS.length}</span>
        <button class="tour-close" onclick="endTour()">&times;</button>
      </div>
      <h3 class="tour-title">${step.title}</h3>
      <p class="tour-body">${step.body}</p>
      <div class="tour-nav">
        <button class="btn btn-outline btn-sm" onclick="prevTourStep()" ${_tourStep === 0 ? 'disabled' : ''}>Back</button>
        <button class="btn btn-primary btn-sm" onclick="nextTourStep()">
          ${_tourStep === TOUR_STEPS.length - 1 ? 'Finish' : 'Next'}
        </button>
      </div>
    `;

    // Position tooltip
    const tooltipTop = step.position === 'bottom'
      ? (rect.bottom + window.scrollY + 16)
      : (rect.top + window.scrollY - 16);

    tooltip.style.top = tooltipTop + 'px';
    tooltip.style.left = Math.max(16, Math.min(rect.left, window.innerWidth - 420)) + 'px';

    if (step.position === 'top') {
      tooltip.style.transform = 'translateY(-100%)';
    }

    document.body.appendChild(tooltip);

    // Animate in
    requestAnimationFrame(() => {
      tooltip.classList.add('tour-tooltip-visible');
      spotlight.classList.add('tour-spotlight-visible');
    });
  }, 400);
}

function nextTourStep() {
  _tourStep++;
  showTourStep();
}

function prevTourStep() {
  if (_tourStep > 0) {
    _tourStep--;
    showTourStep();
  }
}

function endTour() {
  _tourActive = false;
  document.querySelectorAll('.tour-overlay, .tour-tooltip, .tour-spotlight').forEach(el => el.remove());
}

// ═══════════════════════════════════════════════════════════
// ANIMATED STAT COUNTERS — smooth count-up on load
// ═══════════════════════════════════════════════════════════

function animateCounters() {
  document.querySelectorAll('.stat-value').forEach(el => {
    const text = el.textContent.trim();
    const isPercent = text.endsWith('%');
    const num = parseInt(text);
    if (isNaN(num) || num === 0) return;

    const duration = 1200;
    const start = performance.now();
    el.textContent = isPercent ? '0%' : '0';

    function tick(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(num * eased);
      el.textContent = isPercent ? current + '%' : String(current);
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });
}

// Trigger counter animation after stats load
const _origLoadStats = loadStats;
loadStats = async function() {
  await _origLoadStats();
  setTimeout(animateCounters, 100);
};

// ═══════════════════════════════════════════════════════════
// SITE AUDIT
// ═══════════════════════════════════════════════════════════

function openAuditModal() {
  document.getElementById('audit-modal').classList.remove('hidden');
  document.getElementById('audit-results').classList.add('hidden');
  document.getElementById('audit-loading').classList.add('hidden');
}

function closeAuditModal() {
  document.getElementById('audit-modal').classList.add('hidden');
}

function _gradeColor(grade) {
  if (!grade) return 'var(--muted)';
  const g = grade.charAt(0).toUpperCase();
  if (g === 'A') return 'var(--green)';
  if (g === 'B') return '#4dabf7';
  if (g === 'C') return 'var(--yellow)';
  if (g === 'D') return '#fd7e14';
  return 'var(--red)';
}

async function runSiteAudit() {
  const url = document.getElementById('audit-url').value.trim();
  if (!url || !url.startsWith('http')) {
    alert('Enter a valid URL starting with http:// or https://');
    return;
  }

  document.getElementById('audit-loading').classList.remove('hidden');
  document.getElementById('audit-results').classList.add('hidden');
  document.getElementById('audit-run-btn').disabled = true;

  try {
    const res = await fetch('/api/audit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url, depth: 1}),
    });
    const data = await res.json();
    document.getElementById('audit-loading').classList.add('hidden');

    if (data.status === 'error') {
      document.getElementById('audit-results').innerHTML = `<div class="diag-empty">Audit failed: ${esc(data.error || 'Unknown error')}</div>`;
      document.getElementById('audit-results').classList.remove('hidden');
      return;
    }

    const r = data.result || {};
    const review = r.llm_review || {};
    const overall = review.overall_grade || '?';
    const score = review.overall_score || 0;
    const summary = review.summary || 'No AI review available (connect an LLM in Settings)';

    const categories = ['usability', 'appearance', 'accessibility', 'performance'];
    const catCards = categories.map(cat => {
      const c = review[cat] || {};
      const grade = c.grade || '?';
      const catScore = c.score || 0;
      const items = c.issues || c.feedback || c.strengths || [];
      return `
        <div class="audit-cat-card">
          <div class="audit-cat-grade" style="color:${_gradeColor(grade)}">${esc(grade)}</div>
          <div class="audit-cat-name">${esc(cat.charAt(0).toUpperCase() + cat.slice(1))}</div>
          <div class="audit-cat-score">${catScore}/100</div>
          ${items.length ? `<ul class="audit-cat-items">${items.slice(0,3).map(i => `<li>${esc(String(i))}</li>`).join('')}</ul>` : ''}
        </div>`;
    }).join('');

    const tech = r.tech_stack || {};
    const perf = r.perf_metrics || {};
    const recs = review.recommendations || [];

    document.getElementById('audit-results').innerHTML = `
      <div class="audit-overall">
        <div class="audit-overall-grade" style="color:${_gradeColor(overall)}">${esc(overall)}</div>
        <div class="audit-overall-detail">
          <div class="audit-overall-score">${score}/100</div>
          <div class="audit-overall-summary">${esc(summary)}</div>
        </div>
      </div>
      <div class="audit-categories">${catCards}</div>
      <div class="audit-section">
        <h4>Tech Stack</h4>
        <div class="audit-tech">
          <span class="tag">${esc(tech.framework || 'Unknown')}</span>
          <span class="tag">${esc(tech.css_library || 'Unknown CSS')}</span>
          ${tech.is_spa ? '<span class="tag">SPA</span>' : ''}
          ${tech.is_pwa ? '<span class="tag">PWA</span>' : ''}
          ${(tech.analytics || []).map(a => `<span class="tag">${esc(a)}</span>`).join('')}
        </div>
      </div>
      <div class="audit-section">
        <h4>Performance</h4>
        <div class="audit-perf-grid">
          <div class="audit-perf-item"><span class="audit-perf-val">${perf.ttfb_ms || 0}ms</span><span class="audit-perf-label">TTFB</span></div>
          <div class="audit-perf-item"><span class="audit-perf-val">${perf.lcp_ms || 0}ms</span><span class="audit-perf-label">LCP</span></div>
          <div class="audit-perf-item"><span class="audit-perf-val">${perf.cls || 0}</span><span class="audit-perf-label">CLS</span></div>
          <div class="audit-perf-item"><span class="audit-perf-val">${perf.load_time_ms || 0}ms</span><span class="audit-perf-label">Full Load</span></div>
          <div class="audit-perf-item"><span class="audit-perf-val">${perf.total_resources || 0}</span><span class="audit-perf-label">Resources</span></div>
          <div class="audit-perf-item"><span class="audit-perf-val">${perf.total_transfer_kb || 0}KB</span><span class="audit-perf-label">Transfer</span></div>
        </div>
      </div>
      ${recs.length ? `<div class="audit-section"><h4>Recommendations</h4><ol class="audit-recs">${recs.map(r => `<li>${esc(String(r))}</li>`).join('')}</ol></div>` : ''}
    `;
    document.getElementById('audit-results').classList.remove('hidden');
  } catch (e) {
    document.getElementById('audit-loading').classList.add('hidden');
    document.getElementById('audit-results').innerHTML = `<div class="diag-empty">Error: ${esc(e.message)}</div>`;
    document.getElementById('audit-results').classList.remove('hidden');
  } finally {
    document.getElementById('audit-run-btn').disabled = false;
  }
}

// ═══════════════════════════════════════════════════════════
// PERFORMANCE TELEMETRY TAB
// ═══════════════════════════════════════════════════════════

function openPerfTab(journeyId) {
  closeModal();
  document.getElementById('perf-modal').classList.remove('hidden');
  document.getElementById('perf-loading').classList.remove('hidden');
  document.getElementById('perf-results').innerHTML = '';
  loadPerfData(journeyId);
}

function closePerfModal() {
  document.getElementById('perf-modal').classList.add('hidden');
}

function _vitalColor(metric, val) {
  if (metric === 'lcp_ms') return val <= 2500 ? 'var(--green)' : val <= 4000 ? 'var(--yellow)' : 'var(--red)';
  if (metric === 'cls') return val <= 0.1 ? 'var(--green)' : val <= 0.25 ? 'var(--yellow)' : 'var(--red)';
  if (metric === 'ttfb_ms') return val <= 800 ? 'var(--green)' : val <= 1800 ? 'var(--yellow)' : 'var(--red)';
  if (metric === 'inp_ms') return val <= 200 ? 'var(--green)' : val <= 500 ? 'var(--yellow)' : 'var(--red)';
  return 'var(--muted)';
}

async function loadPerfData(journeyId) {
  try {
    const data = await fetchJSON(`/api/journeys/${journeyId}/performance?limit=10`);
    document.getElementById('perf-loading').classList.add('hidden');
    if (!data || !data.runs || !data.runs.length) {
      document.getElementById('perf-results').innerHTML = '<div class="diag-empty">No test runs with performance data yet. Run a replay first.</div>';
      return;
    }

    const latestRun = data.runs[0];
    const wv = latestRun.web_vitals || {};
    const timings = latestRun.step_timings || {};
    const sortedSteps = Object.entries(timings).sort((a, b) => parseInt(a[0]) - parseInt(b[0]));
    const maxTime = Math.max(...sortedSteps.map(s => s[1]), 1);

    let html = '<div class="perf-section">';
    html += '<h4>Web Vitals (Latest Run)</h4>';
    html += '<div class="audit-perf-grid">';
    const vitals = [
      {key: 'lcp_ms', label: 'LCP', unit: 'ms', threshold: '< 2500ms'},
      {key: 'cls', label: 'CLS', unit: '', threshold: '< 0.1'},
      {key: 'ttfb_ms', label: 'TTFB', unit: 'ms', threshold: '< 800ms'},
      {key: 'dom_content_loaded_ms', label: 'DCL', unit: 'ms'},
      {key: 'load_time_ms', label: 'Load', unit: 'ms'},
    ];
    for (const v of vitals) {
      const val = wv[v.key] || 0;
      const color = _vitalColor(v.key, val);
      html += `<div class="audit-perf-item">
        <span class="audit-perf-val" style="color:${color}">${val}${v.unit}</span>
        <span class="audit-perf-label">${v.label}</span>
        ${v.threshold ? `<span class="perf-threshold">${v.threshold}</span>` : ''}
      </div>`;
    }
    html += '</div></div>';

    if (sortedSteps.length) {
      html += '<div class="perf-section"><h4>Step Timings</h4>';
      html += '<div class="step-timing-chart">';
      for (const [step, ms] of sortedSteps) {
        const pct = Math.round((ms / maxTime) * 100);
        const barColor = ms > 5000 ? 'var(--red)' : ms > 2000 ? 'var(--yellow)' : 'var(--green)';
        html += `<div class="step-timing-row">
          <span class="step-timing-label">Step ${step}</span>
          <div class="step-timing-bar-bg"><div class="step-timing-bar" style="width:${pct}%;background:${barColor}"></div></div>
          <span class="step-timing-val">${ms}ms</span>
        </div>`;
      }
      html += '</div></div>';
    }

    if (data.runs.length > 1) {
      html += '<div class="perf-section"><h4>Trend (Last ' + data.runs.length + ' Runs)</h4>';
      html += '<div class="perf-trend-table"><table class="explore-table"><thead><tr><th>Run</th><th>Duration</th><th>LCP</th><th>CLS</th><th>TTFB</th><th>Status</th></tr></thead><tbody>';
      for (const run of data.runs) {
        const rv = run.web_vitals || {};
        const dur = run.duration_ms >= 1000 ? `${(run.duration_ms/1000).toFixed(1)}s` : `${run.duration_ms}ms`;
        const date = run.started_at ? new Date(run.started_at).toLocaleDateString() : '';
        html += `<tr>
          <td>${date}</td>
          <td>${dur}</td>
          <td style="color:${_vitalColor('lcp_ms', rv.lcp_ms||0)}">${rv.lcp_ms||'—'}ms</td>
          <td style="color:${_vitalColor('cls', rv.cls||0)}">${rv.cls||'—'}</td>
          <td style="color:${_vitalColor('ttfb_ms', rv.ttfb_ms||0)}">${rv.ttfb_ms||'—'}ms</td>
          <td>${run.passed ? '<span style="color:var(--green)">PASS</span>' : '<span style="color:var(--red)">FAIL</span>'}</td>
        </tr>`;
      }
      html += '</tbody></table></div></div>';
    }

    document.getElementById('perf-results').innerHTML = html;
  } catch (e) {
    document.getElementById('perf-loading').classList.add('hidden');
    document.getElementById('perf-results').innerHTML = `<div class="diag-empty">Error loading performance data: ${esc(e.message)}</div>`;
  }
}

// ═══════════════════════════════════════════════════════════
// SEED-BASED JOURNEY EXPANSION
// ═══════════════════════════════════════════════════════════

let _expandEventSource = null;
let _expandSessionId = null;

function expandJourney(journeyId) {
  closeModal();
  document.getElementById('expand-modal').classList.remove('hidden');
  document.getElementById('expand-results').classList.add('hidden');
  document.getElementById('expand-log').innerHTML = '<span class="term-dim">Starting seed-based expansion...</span>';
  document.getElementById('expand-pages-count').textContent = '0';
  document.getElementById('expand-steps-count').textContent = '0';
  document.getElementById('expand-flows-count').textContent = '0';

  _expandEventSource = new EventSource(`/api/journeys/${journeyId}/expand`);
  // POST doesn't work with EventSource, so use fetch with SSE parsing
  fetch(`/api/journeys/${journeyId}/expand`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({max_pages: 20, max_time_minutes: 8, headed: true}),
  }).then(async response => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));
          handleExpandEvent(event);
        } catch (e) {}
      }
    }
  }).catch(e => {
    const log = document.getElementById('expand-log');
    log.innerHTML += `<div style="color:var(--red)">Error: ${esc(e.message)}</div>`;
  });
}

function handleExpandEvent(event) {
  const log = document.getElementById('expand-log');
  const type = event.type;

  if (type === 'expansion_start' || type === 'start') {
    log.innerHTML += `<div>Exploring from ${esc(event.base_url || '')}...</div>`;
    _expandSessionId = event.session_id;
  } else if (type === 'page_visited') {
    document.getElementById('expand-pages-count').textContent = event.total_pages || 0;
    log.innerHTML += `<div><span class="term-dim">Page:</span> ${esc(event.url || '')}</div>`;
  } else if (type === 'interaction') {
    const count = parseInt(document.getElementById('expand-steps-count').textContent) + 1;
    document.getElementById('expand-steps-count').textContent = count;
    log.innerHTML += `<div><span style="color:var(--brand)">${esc(event.action || '')}</span> ${esc((event.element_summary || '').slice(0, 60))}</div>`;
  } else if (type === 'done') {
    const journeys = event.journeys || [];
    document.getElementById('expand-flows-count').textContent = journeys.length;
    log.innerHTML += `<div style="color:var(--green)">Expansion complete — ${journeys.length} related flows discovered</div>`;

    if (journeys.length) {
      const list = document.getElementById('expand-journeys-list');
      list.innerHTML = journeys.map((j, i) => `
        <div class="explorer-journey-card">
          <div class="explorer-journey-name">${esc(j.name || 'Flow ' + (i+1))}</div>
          <div class="explorer-journey-desc">${esc(j.description || '')}</div>
          <div class="explorer-journey-meta">${(j.steps || []).length} steps · ${(j.urls || []).length} pages</div>
        </div>
      `).join('');
      document.getElementById('expand-results').classList.remove('hidden');
    }
  } else if (type === 'error') {
    log.innerHTML += `<div style="color:var(--red)">Error: ${esc(event.message || '')}</div>`;
  }

  log.scrollTop = log.scrollHeight;
}

function closeExpandModal() {
  document.getElementById('expand-modal').classList.add('hidden');
}

async function saveExpandedJourneys() {
  if (!_expandSessionId) return;
  const statusEl = document.getElementById('expand-save-status');
  statusEl.textContent = 'Saving...';

  try {
    const res = await fetch(`/api/explorer/results/${_expandSessionId}/save`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({journey_indices: []}),
    });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = `Saved ${data.count} journeys`;
      statusEl.style.color = 'var(--green)';
      loadJourneys(undefined, true);
    } else {
      statusEl.textContent = 'Save failed';
      statusEl.style.color = 'var(--red)';
    }
  } catch (e) {
    statusEl.textContent = 'Error: ' + e.message;
    statusEl.style.color = 'var(--red)';
  }
}

const API = 'http://localhost:8000/api/v1';
let _companies = [];
let _jobs = [];
let _analyticsChart = null;
let _dcfChart = null;
let _selectedFiles = [];

// ============================================================
// INIT
// ============================================================
window.addEventListener('DOMContentLoaded', async () => {
  await checkApiHealth();
  await loadCompanies();
  
  // Set default dates for Market Data to Last 30 days
  const today = new Date();
  const prior30 = new Date(new Date().setDate(today.getDate() - 30));
  document.getElementById('m-end').value = today.toISOString().split('T')[0];
  document.getElementById('m-start').value = prior30.toISOString().split('T')[0];

  const dz = document.getElementById('dropzone');
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.style.borderColor = 'var(--accent)'; });
  dz.addEventListener('dragleave', () => dz.style.borderColor = 'var(--border)');
  dz.addEventListener('drop', e => {
    e.preventDefault();
    dz.style.borderColor = 'var(--border)';
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      _selectedFiles = Array.from(files);
      const el = document.getElementById('file-selected');
      el.classList.remove('hidden');
      const totalSize = _selectedFiles.reduce((acc, f) => acc + f.size, 0) / 1024;
      el.textContent = `${_selectedFiles.length} file(s) selected (${totalSize.toFixed(1)} KB total)`;
    }
  });
});

async function checkApiHealth() {
  try {
    const res = await fetch(`${API.replace('/v1', '/health')}`);
    if (res.ok) {
      document.getElementById('api-status-dot').className = 'status-dot online';
      document.getElementById('api-status-text').textContent = 'API Online';
    } else throw new Error();
  } catch {
    document.getElementById('api-status-dot').className = 'status-dot';
    document.getElementById('api-status-text').textContent = 'API Offline';
  }
}

// ============================================================
// TAB ROUTING
// ============================================================
function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  document.getElementById(`nav-${name}`).classList.add('active');

  const titles = {
    workspace: ['Workspace', 'Unified Analysis Command Center'],
    exec: ['Executive Dashboard', 'Multi-Company Comparative Analytics & Benchmarking'],
    companies: ['Portfolio', 'Manage tracked financial entities'],
    audit: ['Audit Trail', 'Immutable event history'],
  };
  const [t, s] = titles[name] || ['', ''];
  document.getElementById('page-title').textContent = t;
  document.getElementById('page-subtitle').textContent = s;

  if (name === 'audit') loadAuditPreview();
  if (name === 'exec') loadExecutiveDashboard();
}

// ============================================================
// COMPANIES
// ============================================================
async function loadCompanies() {
  try {
    const res = await fetch(`${API}/companies`);
    _companies = await res.json();
    renderCompanyTable();
    
    const sel = document.getElementById('w-company');
    const current = sel.value;
    sel.innerHTML = '<option value="">Select a company to begin analysis...</option>';
    _companies.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = `${c.ticker} - ${c.name}`;
      sel.appendChild(opt);
    });
    if (current) sel.value = current;
  } catch {
    _companies = [];
  }
}

function renderCompanyTable() {
  const wrap = document.getElementById('companies-table-wrap');
  if (!_companies.length) {
    wrap.innerHTML = '<div class="empty-state">No companies registered yet. Search a ticker to add one.</div>';
    return;
  }
  wrap.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>Ticker</th><th>Name</th><th>Sector</th><th>Currency</th><th>ID</th>
      </tr></thead>
      <tbody>
        ${_companies.map(c => `
          <tr>
            <td><strong style="color:var(--text-primary)">${c.ticker}</strong></td>
            <td>${c.name}</td>
            <td>${c.sector || '—'}</td>
            <td>${c.currency}</td>
            <td style="color:var(--text-muted)">${c.id.substring(0,8)}...</td>
          </tr>
        `).join('')}
      </tbody>
    </table>`;
}

async function createCompany(e) {
  e.preventDefault();
  const ticker = document.getElementById('f-ticker').value.trim().toUpperCase();
  const btn = document.getElementById('btn-add-company');
  btn.disabled = true;
  btn.textContent = 'Searching...';

  try {
    const res = await fetch(`${API}/companies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
    });
    const data = await res.json();
    
    if (!res.ok) {
      showAlert('company-alert', data.detail || 'Failed to add company.', 'error');
    } else {
      showAlert('company-alert', `Added ${data.name} successfully.`, 'success');
      document.getElementById('company-form').reset();
      await loadCompanies();
      toast(`Added ${data.ticker} to portfolio`, 'success');
    }
  } catch (err) {
    showAlert('company-alert', 'Network error. Is the API server running?', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Search & Add';
  }
}

// ============================================================
// WORKSPACE LOGIC
// ============================================================
function onWorkspaceCompanyChange() {
  const companyId = document.getElementById('w-company').value;
  const body = document.getElementById('workspace-body');
  const empty = document.getElementById('workspace-empty');
  
  if (companyId) {
    body.classList.remove('hidden');
    empty.classList.add('hidden');
    // Hide old results
    document.getElementById('upload-result').classList.add('hidden');
    document.getElementById('fetch-result').classList.add('hidden');
    document.getElementById('analytics-result').classList.add('hidden');
    document.getElementById('dcf-result-card').classList.add('hidden');
    document.getElementById('report-viewer').classList.add('hidden');
    
    // Load dashboard reports
    loadReports(companyId);
  } else {
    body.classList.add('hidden');
    empty.classList.remove('hidden');
  }
}

function handleFileSelect(e) {
  const files = e.target.files;
  if (files && files.length > 0) {
    _selectedFiles = Array.from(files);
    const el = document.getElementById('file-selected');
    el.classList.remove('hidden');
    const totalSize = _selectedFiles.reduce((acc, f) => acc + f.size, 0) / 1024;
    el.textContent = `${_selectedFiles.length} file(s) selected (${totalSize.toFixed(1)} KB total)`;
  }
}

async function uploadDocument(e) {
  e.preventDefault();
  if (!_selectedFiles || !_selectedFiles.length) { toast('Please select file(s) first.', 'error'); return; }
  const companyId = document.getElementById('w-company').value;
  
  const btn = document.getElementById('upload-btn');
  btn.disabled = true;
  btn.textContent = 'Ingesting...';

  const form = new FormData();
  _selectedFiles.forEach(f => form.append('files', f));
  form.append('company_id', companyId);
  
  const y = document.getElementById('w-year').value;
  if(y) form.append('fiscal_year', y);
  
  const p = document.getElementById('w-period').value;
  if(p) form.append('fiscal_period', p);
  
  form.append('source_authority', document.getElementById('u-authority').value);

  try {
    const res = await fetch(`${API}/documents`, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) {
      toast(data.detail || 'Upload failed.', 'error');
    } else {
      showUploadResult(data);
      if (data.jobs) {
        data.jobs.forEach(j => _jobs.push(j));
      }
      toast(`${data.files_processed} file(s) ingested`, 'success');
    }
  } catch (err) {
    toast('Network error.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Ingest Files';
  }
}

function showUploadResult(data) {
  const el = document.getElementById('upload-result');
  const body = document.getElementById('upload-result-body');
  el.classList.remove('hidden');
  
  const hasErrors = data.errors && data.errors.length > 0;
  
  body.innerHTML = `
    <div class="result-grid">
      <div class="result-stat"><div class="result-stat-label">Files Processed</div><div class="result-stat-value">${data.files_processed}</div></div>
      <div class="result-stat"><div class="result-stat-label">Metrics Stored</div><div class="result-stat-value">${data.total_rows_stored}</div></div>
      <div class="result-stat"><div class="result-stat-label">Errors</div><div class="result-stat-value" style="color:${hasErrors ? 'var(--accent-red)' : 'var(--text-primary)'}">${hasErrors ? data.errors.length : 0}</div></div>
    </div>
  `;
}

async function fetchMarketData() {
  const companyId = document.getElementById('w-company').value;
  // Get ticker from _companies list
  const company = _companies.find(c => c.id === companyId);
  if (!company) return;

  const startDate = document.getElementById('m-start').value;
  const endDate = document.getElementById('m-end').value;
  
  const btn = document.getElementById('fetch-btn');
  btn.disabled = true;
  btn.textContent = 'Fetching...';

  try {
    const res = await fetch(`${API}/documents/fetch-market-data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: companyId, ticker: company.ticker, start_date: startDate, end_date: endDate }),
    });
    const data = await res.json();

    if (!res.ok) {
      toast(data.detail || 'Failed to fetch.', 'error');
    } else {
      const el = document.getElementById('fetch-result');
      const body = document.getElementById('fetch-result-body');
      el.classList.remove('hidden');
      const isOk = data.status === 'COMPLETED';
      body.innerHTML = `
        <div class="result-grid">
          <div class="result-stat"><div class="result-stat-label">Status</div><div class="result-stat-value" style="color:${isOk ? 'var(--accent-green)' : 'var(--accent-red)'}">${data.status}</div></div>
          <div class="result-stat"><div class="result-stat-label">Data Points</div><div class="result-stat-value">${data.rows_fetched}</div></div>
          <div class="result-stat"><div class="result-stat-label">Metrics Stored</div><div class="result-stat-value">${data.rows_stored}</div></div>
        </div>
      `;
      _jobs.push(data);
      toast(`Fetched market data for ${company.ticker}`, 'success');
    }
  } catch (err) {
    toast('Network error.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Fetch & Ingest Prices';
  }
}

// ============================================================
// ANALYTICS & DCF
// ============================================================
async function runAnalytics() {
  const companyId = document.getElementById('w-company').value;
  const year = document.getElementById('w-start-year').value;
  const period = document.getElementById('w-period').value;

  const btn = document.getElementById('analyze-btn');
  btn.disabled = true;
  btn.textContent = 'Running...';

  let url = `${API}/analytics/${companyId}?fiscal_year=${year}&fiscal_period=${period}`;

  document.getElementById('analytics-error').classList.add('hidden');
  document.getElementById('analytics-result').classList.add('hidden');

  try {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) {
      document.getElementById('analytics-error').textContent = data.detail || 'Analysis failed.';
      document.getElementById('analytics-error').classList.remove('hidden');
      return;
    }
    renderAnalyticsResults(data);
  } catch {
    document.getElementById('analytics-error').textContent = 'Network error.';
    document.getElementById('analytics-error').classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run Analysis';
  }
}

// ============================================================
// GENERIC EXPLAINABILITY PANEL
// ============================================================

/**
 * Renders a structured explainability panel for ANY metric.
 * Driven entirely by the CalculationResult metadata — no per-metric custom code.
 */
function renderExplainabilityPanel(m) {
  const id = `explain-${m.key}-${Math.random().toString(36).substr(2, 6)}`;

  // --- Inputs Grid ---
  let inputsHtml = '';
  if (m.inputs_used && Object.keys(m.inputs_used).length) {
    inputsHtml = `<div class="explain-inputs-grid">
      ${Object.entries(m.inputs_used).map(([k, v]) =>
        `<span class="input-key">${k.replace(/_/g, ' ')}</span><span class="input-val">${formatNumber(v)} ${m.currency || 'USD'}</span>`
      ).join('')}
    </div>`;
  }

  // --- Lineage ---
  const lineage = m.data_lineage || ['RawMetric', 'NormalizedMetric', 'CalculatedMetric'];
  const lineageHtml = `<div class="lineage-flow">
    ${lineage.map((step, i) =>
      `<span class="lineage-step">${step}</span>${i < lineage.length - 1 ? '<span class="lineage-arrow">&#x2192;</span>' : ''}`
    ).join('')}
  </div>`;

  // --- References ---
  let refsHtml = '';
  if (m.references && m.references.length) {
    refsHtml = `<div class="explain-refs">
      ${m.references.map(r => `<span class="explain-ref-chip">${r.source || r.Type || ''}${r.title ? ': ' + r.title : ''}</span>`).join('')}
    </div>`;
  }

  // --- Validation ---
  let validationHtml = '';
  if (m.validation_messages && m.validation_messages.length) {
    validationHtml = m.validation_messages.map(msg =>
      `<div style="color: var(--accent-amber); font-size: 11px;">${msg}</div>`
    ).join('');
  }

  return `
    <button class="explain-toggle" onclick="toggleExplain('${id}')">&#x25B6; View Calculation</button>
    <div id="${id}" class="explainability-panel">

      <div class="explain-section">
        <div class="explain-section-title">Business Definition</div>
        <div style="color: var(--text-secondary); font-size: 11px; line-height: 1.5;">${m.description || 'No description available.'}</div>
      </div>

      <div class="explain-section">
        <div class="explain-section-title">Formula</div>
        <div class="explain-formula-box">${m.formula_display || 'N/A'}</div>
      </div>

      ${inputsHtml ? `
      <div class="explain-section">
        <div class="explain-section-title">Input Values</div>
        ${inputsHtml}
      </div>` : ''}

      <div class="explain-section">
        <div class="explain-section-title">Result</div>
        <div class="explain-row"><span class="explain-label">Final Value</span><span class="explain-value" style="font-size:14px; font-weight:700;">${formatMetricValue(m.key, m.value, m.unit)}</span></div>
        <div class="explain-row"><span class="explain-label">Confidence</span><span class="explain-value">${(m.confidence * 100).toFixed(1)}%</span></div>
        <div class="explain-row"><span class="explain-label">Validation</span><span class="explain-value" style="color:${m.status === 'success' ? 'var(--accent-green)' : 'var(--accent-amber)'}">${m.status === 'success' ? 'Passed' : m.status}</span></div>
        ${validationHtml}
      </div>

      <div class="explain-section">
        <div class="explain-section-title">Engine Metadata</div>
        <div class="explain-row"><span class="explain-label">Fiscal Period</span><span class="explain-value">${m.fiscal_period_label || 'N/A'}</span></div>
        <div class="explain-row"><span class="explain-label">Formula Version</span><span class="explain-value">${m.formula_version || m.formula || 'v1'}</span></div>
        <div class="explain-row"><span class="explain-label">Engine Version</span><span class="explain-value">${m.engine_version || 'v2.0'}</span></div>
        <div class="explain-row"><span class="explain-label">Config Version</span><span class="explain-value">${m.configuration_version || '2026.08'}</span></div>
        <div class="explain-row"><span class="explain-label">Strategy</span><span class="explain-value">${m.calculation_strategy || 'deterministic'}</span></div>
        <div class="explain-row"><span class="explain-label">Timestamp</span><span class="explain-value">${m.calculation_timestamp ? new Date(m.calculation_timestamp).toLocaleString() : 'N/A'}</span></div>
      </div>

      <div class="explain-section">
        <div class="explain-section-title">Data Lineage</div>
        ${lineageHtml}
      </div>

      ${refsHtml ? `
      <div class="explain-section">
        <div class="explain-section-title">References</div>
        ${refsHtml}
      </div>` : ''}

    </div>
  `;
}

function toggleExplain(id) {
  const panel = document.getElementById(id);
  if (panel) {
    panel.classList.toggle('open');
    // Update button text
    const btn = panel.previousElementSibling;
    if (btn && btn.classList.contains('explain-toggle')) {
      btn.innerHTML = panel.classList.contains('open') ? '&#x25BC; Hide Calculation' : '&#x25B6; View Calculation';
    }
  }
}

/**
 * Renders a single metric card with explainability toggle.
 * Works for both live analytics results and saved report data.
 */
function renderMetricCard(m) {
  const statusClass = (m.status || 'success').replace(/ /g, '_');
  const category = m.category || '';
  return `
    <div class="metric-card" data-category="${category}">
      <div class="metric-card-name">${m.name || m.key.replace(/_/g, ' ')}</div>
      <div class="metric-card-key">${m.key.replace(/_/g, ' ')}</div>
      <div class="metric-card-value">${formatMetricValue(m.key, m.value, m.unit)}</div>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
        <span class="metric-card-status ${statusClass}">${m.status || 'success'}</span>
        <span style="font-size:9px; color:var(--text-muted); font-family:'JetBrains Mono',monospace;">${(m.confidence * 100).toFixed(0)}% conf</span>
      </div>
      ${renderExplainabilityPanel(m)}
    </div>
  `;
}

function renderAnalyticsResults(data) {
  const grid = document.getElementById('metrics-cards');
  
  // Group metrics by category
  const categories = {};
  data.metrics.forEach(m => {
    const cat = m.category || 'other';
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push(m);
  });

  const categoryLabels = {
    profitability: 'Profitability',
    liquidity: 'Liquidity',
    leverage: 'Leverage',
    cash_flow: 'Cash Flow',
    other: 'Other',
  };

  const categoryOrder = ['profitability', 'liquidity', 'leverage', 'cash_flow', 'other'];

  let html = '';
  for (const cat of categoryOrder) {
    if (!categories[cat]) continue;
    html += `<div style="grid-column: 1 / -1; margin-top: 12px; margin-bottom: 4px;">
      <span style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted);">${categoryLabels[cat] || cat}</span>
    </div>`;
    html += categories[cat].map(m => renderMetricCard(m)).join('');
  }

  grid.innerHTML = html;

  // Chart — only successful metrics
  const successMetrics = data.metrics.filter(m => m.status === 'success');
  const labels = successMetrics.map(m => (m.name || m.key).replace(/_/g, ' '));
  const values = successMetrics.map(m => {
    if (m.unit === 'percentage') return parseFloat((m.value * 100).toFixed(2));
    return parseFloat(m.value.toFixed(4));
  });
  const ctx = document.getElementById('metrics-chart').getContext('2d');
  if (_analyticsChart) _analyticsChart.destroy();

  const barColors = successMetrics.map(m => {
    if (m.category === 'profitability') return '#22c55e';
    if (m.category === 'liquidity') return '#3b82f6';
    if (m.category === 'leverage') return '#f59e0b';
    if (m.category === 'cash_flow') return '#a855f7';
    return '#3b82f6';
  });

  _analyticsChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label: 'Value', data: values, backgroundColor: barColors }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#27272a' }, ticks: { color: '#a1a1aa', font: {family: 'JetBrains Mono'}, maxRotation: 45 } },
        y: { grid: { color: '#27272a' }, ticks: { color: '#a1a1aa', font: {family: 'JetBrains Mono'} } },
      },
    },
  });

  document.getElementById('analytics-result').classList.remove('hidden');
  toast('Analysis Complete', 'success');
}

function formatMetricValue(key, value, unit) {
  if (unit === 'percentage') {
    return (value * 100).toFixed(2) + '%';
  }
  if (unit === 'ratio') {
    return value.toFixed(4) + 'x';
  }
  // Legacy fallback for old data without unit field
  if (!unit || unit === 'absolute') {
    if (key && (key.includes('margin') || key.includes('return'))) {
      return (value * 100).toFixed(2) + '%';
    }
    if (key && key.includes('ratio')) {
      return value.toFixed(4) + 'x';
    }
  }
  return formatNumber(value);
}

function formatNumber(n) {
  if (n === undefined || n === null) return 'N/A';
  if (Math.abs(n) >= 1e12) return (n / 1e12).toFixed(2) + 'T';
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toFixed(4);
}

// ============================================================
// DASHBOARD & 1-CLICK ANALYSIS
// ============================================================

let _currentReports = [];

async function loadReports(companyId) {
  try {
    const res = await fetch(`${API}/analytics/${companyId}/reports`);
    const data = await res.json();
    _currentReports = data;
    renderReportsTable();
  } catch (err) {
    toast('Failed to load saved reports.', 'error');
  }
}

function renderReportsTable() {
  const tbody = document.getElementById('reports-tbody');
  if (!_currentReports || _currentReports.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 16px;">No reports generated yet.</td></tr>';
    return;
  }
  
  tbody.innerHTML = _currentReports.map(r => `
    <tr>
      <td><strong>${r.name}</strong></td>
      <td>${r.fiscal_year || 'TTM'}</td>
      <td style="color: var(--text-muted);">${new Date(r.created_at).toLocaleString()}</td>
      <td style="text-align: right;">
        <button class="btn btn-secondary" onclick="viewReport('${r.id}')" style="padding: 4px 8px; font-size: 12px;">View Report</button>
      </td>
    </tr>
  `).join('');
}

async function runAutoAnalysis() {
  const companyId = document.getElementById('w-company').value;
  if (!companyId) return;
  
  const startYear = document.getElementById('w-start-year').value || 2024;
  const endYear = document.getElementById('w-end-year').value || 2026;
  const period = document.getElementById('w-period').value || 'FY';

  const btn = document.getElementById('btn-auto-run');
  btn.disabled = true;
  btn.textContent = 'Fetching & Analyzing...';

  try {
    const res = await fetch(`${API}/analytics/${companyId}/auto-run?start_year=${startYear}&end_year=${endYear}&fiscal_period=${period}`, { method: 'POST' });
    const data = await res.json();
    
    if (!res.ok) {
      toast(data.detail || 'Analysis failed.', 'error');
    } else {
      toast('Analysis Complete & Saved!', 'success');
      await loadReports(companyId);
      viewReport(data.id);
    }
  } catch (err) {
    toast('Network error during auto-analysis.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Run Full Analysis';
  }
}


function viewReport(reportId) {
  const report = _currentReports.find(r => r.id === reportId);
  if (!report) return;

  const viewer = document.getElementById('report-viewer');
  const title = document.getElementById('rv-title');
  const metricsGrid = document.getElementById('rv-metrics');

  title.textContent = report.name;
  
  const data = report.report_data;
  if (data.metrics) {
    // Old single-year structure — render with explainability
    metricsGrid.innerHTML = `<div class="metrics-grid">${data.metrics.map(m => renderMetricCard(m)).join('')}</div>`;
  } else if (data.years) {
    // New multi-year structure — render as a comparison table with expandable details
    const years = Object.keys(data.years).sort();
    if (years.length === 0) {
      metricsGrid.innerHTML = '<div>No data available</div>';
    } else {
      // Collect all unique metrics across years
      const metricMap = new Map();
      for (const y of years) {
         for (const m of data.years[y].metrics) {
            if (!metricMap.has(m.key)) {
               metricMap.set(m.key, m);
            }
         }
      }
      const metricsList = Array.from(metricMap.values());

      // Group by category
      const categoryOrder = ['profitability', 'liquidity', 'leverage', 'cash_flow', 'other'];
      const categoryLabels = {
        profitability: 'PROFITABILITY', liquidity: 'LIQUIDITY',
        leverage: 'LEVERAGE', cash_flow: 'CASH FLOW', other: 'OTHER',
      };
      
      let tableHtml = `<table class="data-table" style="width:100%;">
        <thead>
          <tr>
            <th style="text-align: left; padding: 12px;">Metric</th>`;
      for (const y of years) {
         tableHtml += `<th style="text-align: right; padding: 12px;">${y}</th>`;
      }
      tableHtml += `<th style="text-align: center; padding: 12px; width: 40px;">Info</th>`;
      tableHtml += `</tr></thead><tbody>`;

      let currentCat = '';
      // Sort metrics by category
      const sortedMetrics = metricsList.sort((a, b) => {
        const catA = categoryOrder.indexOf(a.category || 'other');
        const catB = categoryOrder.indexOf(b.category || 'other');
        return catA - catB;
      });
      
      for (const m of sortedMetrics) {
        const cat = m.category || 'other';
        if (cat !== currentCat) {
          currentCat = cat;
          tableHtml += `<tr><td colspan="${years.length + 2}" style="padding: 8px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.08em; color: var(--accent); border-bottom: 2px solid var(--border); background: var(--bg-base);">${categoryLabels[cat] || cat.toUpperCase()}</td></tr>`;
        }

        const explainId = `rv-explain-${m.key}-${Math.random().toString(36).substr(2, 6)}`;
        tableHtml += `<tr>
          <td style="padding: 12px; border-bottom: 1px solid var(--border);">
            <strong style="color: var(--text-primary);">${m.name || m.key.replace(/_/g, ' ')}</strong><br>
            <span style="font-size:10px; color:var(--text-muted); font-family:'JetBrains Mono',monospace;">${m.formula_display || m.formula || ''}</span>
          </td>`;
        for (const y of years) {
          const yrMetrics = data.years[y].metrics;
          const found = yrMetrics.find(x => x.key === m.key);
          const val = found ? formatMetricValue(m.key, found.value, found.unit || m.unit) : '<span style="color:var(--text-muted)">N/A</span>';
          const statusColor = found && found.status === 'success' ? 'var(--text-primary)' : 'var(--text-muted)';
          tableHtml += `<td style="text-align: right; padding: 12px; border-bottom: 1px solid var(--border); color: ${statusColor}; font-family: 'JetBrains Mono', monospace;">${val}</td>`;
        }
        tableHtml += `<td style="text-align: center; padding: 12px; border-bottom: 1px solid var(--border);">
          <button class="explain-toggle" onclick="toggleExplain('${explainId}')" style="margin:0; padding:2px;">&#x25B6;</button>
        </td></tr>`;
        // Inline explainability row
        const latestYear = years[years.length - 1];
        const latestMetric = data.years[latestYear].metrics.find(x => x.key === m.key) || m;
        tableHtml += `<tr><td colspan="${years.length + 2}" style="padding: 0;">
          <div id="${explainId}" class="explainability-panel" style="border: none; border-bottom: 1px solid var(--border);">
            ${renderInlineExplainContent(latestMetric)}
          </div>
        </td></tr>`;
      }
      tableHtml += `</tbody></table>`;
      metricsGrid.innerHTML = tableHtml;
    }
  }

  viewer.classList.remove('hidden');
  viewer.scrollIntoView({ behavior: 'smooth' });
}

/**
 * Renders inline explainability content (without the wrapper div / toggle).
 * Used inside the report table rows.
 */
function renderInlineExplainContent(m) {
  let inputsHtml = '';
  if (m.inputs_used && Object.keys(m.inputs_used).length) {
    inputsHtml = `<div class="explain-section">
      <div class="explain-section-title">Input Values</div>
      <div class="explain-inputs-grid">
        ${Object.entries(m.inputs_used).map(([k, v]) =>
          `<span class="input-key">${k.replace(/_/g, ' ')}</span><span class="input-val">${formatNumber(v)}</span>`
        ).join('')}
      </div>
    </div>`;
  }

  let refsHtml = '';
  if (m.references && m.references.length) {
    refsHtml = `<div class="explain-section">
      <div class="explain-section-title">References</div>
      <div class="explain-refs">
        ${m.references.map(r => `<span class="explain-ref-chip">${r.source || ''}${r.title ? ': ' + r.title : ''}</span>`).join('')}
      </div>
    </div>`;
  }

  const lineage = m.data_lineage || ['RawMetric', 'NormalizedMetric', 'CalculatedMetric'];

  return `
    <div class="explain-section">
      <div class="explain-section-title">Business Definition</div>
      <div style="color: var(--text-secondary); font-size: 11px;">${m.description || 'N/A'}</div>
    </div>
    <div class="explain-section">
      <div class="explain-section-title">Formula</div>
      <div class="explain-formula-box">${m.formula_display || 'N/A'}</div>
    </div>
    ${inputsHtml}
    <div class="explain-section">
      <div class="explain-section-title">Result</div>
      <div class="explain-row"><span class="explain-label">Confidence</span><span class="explain-value">${((m.confidence || 0) * 100).toFixed(1)}%</span></div>
      <div class="explain-row"><span class="explain-label">Formula Version</span><span class="explain-value">${m.formula_version || m.formula || 'v1'}</span></div>
      <div class="explain-row"><span class="explain-label">Engine Version</span><span class="explain-value">${m.engine_version || 'v2.0'}</span></div>
      <div class="explain-row"><span class="explain-label">Strategy</span><span class="explain-value">${m.calculation_strategy || 'deterministic'}</span></div>
    </div>
    <div class="explain-section">
      <div class="explain-section-title">Data Lineage</div>
      <div class="lineage-flow">
        ${lineage.map((step, i) =>
          `<span class="lineage-step">${step}</span>${i < lineage.length - 1 ? '<span class="lineage-arrow">&#x2192;</span>' : ''}`
        ).join('')}
      </div>
    </div>
    ${refsHtml}
  `;
}

async function runDCF() {
  const companyId = document.getElementById('w-company').value;
  const fcfRaw = document.getElementById('d-fcf').value;
  const wacc = parseFloat(document.getElementById('d-wacc').value) / 100;
  const tgr = parseFloat(document.getElementById('d-tgr').value) / 100;
  const debt = parseFloat(document.getElementById('d-debt').value) || 0;

  const fcfs = fcfRaw.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
  if (!fcfs.length) { toast('Enter FCF values.', 'error'); return; }

  document.getElementById('dcf-error').classList.add('hidden');
  document.getElementById('dcf-result-card').classList.add('hidden');

  try {
    const res = await fetch(`${API}/analytics/${companyId}/dcf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ free_cash_flows: fcfs, wacc, terminal_growth_rate: tgr, net_debt: debt }),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById('dcf-error').textContent = data.detail || 'DCF failed.';
      document.getElementById('dcf-error').classList.remove('hidden');
      return;
    }
    renderDCFResult(data, fcfs);
  } catch {
    document.getElementById('dcf-error').textContent = 'Network error.';
    document.getElementById('dcf-error').classList.remove('hidden');
  }
}

function renderDCFResult(data, fcfs) {
  const body = document.getElementById('dcf-result-body');
  body.innerHTML = `
    <div class="dcf-result-grid">
      <div class="dcf-stat"><div class="dcf-stat-label">Enterprise Value</div><div class="dcf-stat-value" style="color:var(--text-primary)">$${formatBig(data.enterprise_value)}M</div></div>
      <div class="dcf-stat"><div class="dcf-stat-label">Equity Value</div><div class="dcf-stat-value">$${formatBig(data.equity_value)}M</div></div>
    </div>
  `;

  const ctx = document.getElementById('dcf-chart').getContext('2d');
  if (_dcfChart) _dcfChart.destroy();
  _dcfChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: fcfs.map((_, i) => `Yr ${i + 1}`).concat(['Term']),
      datasets: [{
        label: 'Discounted FCF ($M)',
        data: [...data.discounted_fcfs, data.discounted_terminal_value],
        backgroundColor: data.discounted_fcfs.map(() => '#3b82f6').concat(['#22c55e']),
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#27272a' }, ticks: { color: '#a1a1aa', font: {family: 'JetBrains Mono'} } },
        y: { grid: { color: '#27272a' }, ticks: { color: '#a1a1aa', font: {family: 'JetBrains Mono'} } },
      },
    },
  });

  document.getElementById('dcf-result-card').classList.remove('hidden');
  toast('DCF Computed', 'success');
}

function formatBig(n) {
  if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1) + 'K';
  return n.toFixed(1);
}

// ============================================================
// AUDIT
// ============================================================
async function loadAuditPreview() {
  const el = document.getElementById('audit-log-list');
  try {
    const res = await fetch(`${API}/audit?limit=50`);
    if (!res.ok) throw new Error();
    const logs = await res.json();

    if (!logs.length) {
      el.innerHTML = '<div class="empty-state">No audit events generated yet. Ingest data to generate immutable logs.</div>';
      return;
    }

    el.innerHTML = logs.map(l => `
      <div class="audit-item">
        <div class="audit-dot" style="background:${l.action === 'CORRECTION' ? 'var(--accent-amber)' : 'var(--accent)'}"></div>
        <div style="flex:1">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span class="audit-action">${l.action}</span>
            <span style="font-size:11px; color:var(--text-muted); font-family:'JetBrains Mono'">${l.timestamp ? new Date(l.timestamp).toLocaleString() : ''}</span>
          </div>
          <div class="audit-desc" style="margin-top:4px">${l.description || 'System event recorded'}</div>
          ${l.old_state || l.new_state ? `
            <div style="font-size:11px; font-family:'JetBrains Mono'; color:var(--text-muted); margin-top:4px; background:rgba(0,0,0,0.2); padding:4px 8px; border-radius:4px">
              ${l.action === 'CORRECTION' ? `Resolved Value: ${l.new_state?.value} (Authority: ${l.new_state?.authority})` : `Payload: ${JSON.stringify(l.new_state || {})}`}
            </div>
          ` : ''}
        </div>
      </div>
    `).join('');
  } catch {
    el.innerHTML = '<div class="empty-state">Could not load audit logs. Verify server status.</div>';
  }
}

function toast(msg, type = 'success') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ============================================================
// EXECUTIVE DASHBOARD & COMPARATIVE ANALYTICS (Phase 4A)
// ============================================================

let _radarChart = null;
let _trendChart = null;
let _lastComparisonData = null;

async function loadExecutiveDashboard() {
  renderCohortCheckboxes();
  await loadSavedCohorts();
  await loadAnalystNotes();
}

function renderCohortCheckboxes() {
  const wrap = document.getElementById('cohort-checkboxes');
  if (!_companies || !_companies.length) {
    wrap.innerHTML = '<div class="empty-state">No companies registered yet. Add companies in Portfolio first.</div>';
    return;
  }
  wrap.innerHTML = _companies.map(c => `
    <label class="cohort-chip-label">
      <input type="checkbox" name="cohort-company" value="${c.id}" />
      <strong>${c.ticker}</strong> (${c.name})
    </label>
  `).join('');
}

async function runCohortComparison() {
  const selectedCheckboxes = document.querySelectorAll('input[name="cohort-company"]:checked');
  const companyIds = Array.from(selectedCheckboxes).map(cb => cb.value);

  if (companyIds.length < 1) {
    toast('Select at least 1 company to compare.', 'error');
    return;
  }

  const year = parseInt(document.getElementById('exec-year').value) || 2024;
  const period = document.getElementById('exec-period').value || 'FY';
  const btn = document.getElementById('btn-run-cohort');
  btn.disabled = true;
  btn.textContent = 'Comparing Cohort...';

  try {
    const res = await fetch(`${API}/comparison/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_ids: companyIds, fiscal_year: year, fiscal_period: period }),
    });
    const data = await res.json();
    if (!res.ok) {
      toast(data.detail || 'Cohort comparison failed.', 'error');
      return;
    }

    _lastComparisonData = data;
    renderExecutiveHealthCards(data.executive_healths);
    renderComparisonMatrix(data.metric_stats, data.company_tickers);
    renderRadarChart(data.executive_healths);
    await fetchAndRenderTrends(companyIds, year);

    // Show sections
    document.getElementById('exec-health-cards').classList.remove('hidden');
    document.getElementById('exec-matrix-card').classList.remove('hidden');
    document.getElementById('exec-charts-grid').classList.remove('hidden');
    document.getElementById('exec-workspace-grid').classList.remove('hidden');

    toast(`Calculated comparison for ${companyIds.length} company cohort`, 'success');
  } catch (err) {
    toast('Network error during cohort comparison.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '📊 Compare Selected Cohort';
  }
}

function renderExecutiveHealthCards(healths) {
  const container = document.getElementById('exec-health-cards');
  const items = Object.values(healths);
  if (!items.length) { container.classList.add('hidden'); return; }

  container.innerHTML = items.map(h => {
    const ratingLower = h.rating.toLowerCase();
    const trafficLightClass = `traffic-${h.traffic_light}`;
    return `
      <div class="exec-card">
        <div class="exec-card-header">
          <div>
            <div class="exec-card-ticker">${h.ticker}</div>
            <div style="font-size:11px; color:var(--text-muted);">${h.company_name}</div>
          </div>
          <span class="rating-badge rating-${ratingLower}">${h.rating}</span>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:12px;">
          <div>
            <span class="traffic-light-dot ${trafficLightClass}"></span>
            <span style="font-size:11px; text-transform:uppercase; color:var(--text-secondary);">${h.traffic_light}</span>
          </div>
          <div class="exec-card-score">${h.overall_score.toFixed(0)}<span style="font-size:14px; color:var(--text-muted);">/100</span></div>
        </div>
        ${h.strengths && h.strengths.length ? `
          <div style="margin-bottom:6px;">
            <div style="font-size:9px; font-weight:700; color:var(--accent-green); text-transform:uppercase;">Top Strengths</div>
            <div style="font-size:10px; color:var(--text-secondary);">${h.strengths.join('<br>')}</div>
          </div>
        ` : ''}
        ${h.vulnerabilities && h.vulnerabilities.length ? `
          <div>
            <div style="font-size:9px; font-weight:700; color:var(--accent-red); text-transform:uppercase;">Vulnerabilities</div>
            <div style="font-size:10px; color:var(--text-secondary);">${h.vulnerabilities.join('<br>')}</div>
          </div>
        ` : ''}
      </div>
    `;
  }).join('');
}

function renderComparisonMatrix(metricStats, companyTickers) {
  const wrap = document.getElementById('exec-matrix-wrap');
  const keys = Object.keys(metricStats);
  const companyIds = Object.keys(companyTickers);

  if (!keys.length || !companyIds.length) {
    wrap.innerHTML = '<div class="empty-state">No comparison data.</div>';
    return;
  }

  let html = `
    <table class="data-table" style="width:100%;">
      <thead>
        <tr>
          <th style="text-align:left;">Metric</th>
          ${companyIds.map(cid => `<th style="text-align:right;">${companyTickers[cid]}</th>`).join('')}
          <th style="text-align:right; border-left:1px solid var(--border);">Cohort Avg</th>
          <th style="text-align:right;">Median</th>
          <th style="text-align:right;">Min</th>
          <th style="text-align:right;">Max</th>
        </tr>
      </thead>
      <tbody>
  `;

  for (const k of keys) {
    const stat = metricStats[k];
    html += `
      <tr>
        <td style="padding:10px 12px; border-bottom:1px solid var(--border);">
          <strong>${stat.name}</strong><br>
          <span style="font-size:10px; color:var(--text-muted); font-family:'JetBrains Mono';">${stat.category.toUpperCase()}</span>
        </td>
    `;

    for (const cid of companyIds) {
      const val = stat.company_values[cid];
      const zScore = stat.z_scores[cid] || 0.0;
      let heatmapClass = 'heatmap-cell neutral';
      if (zScore >= 1.0) heatmapClass = 'heatmap-cell high-pos';
      else if (zScore >= 0.3) heatmapClass = 'heatmap-cell mod-pos';
      else if (zScore <= -1.0) heatmapClass = 'heatmap-cell high-neg';
      else if (zScore <= -0.3) heatmapClass = 'heatmap-cell mod-neg';

      const formattedVal = val !== undefined ? formatMetricValue(k, val, stat.unit) : 'N/A';
      html += `<td style="text-align:right; border-bottom:1px solid var(--border);" class="${heatmapClass}">
        ${formattedVal}<br><span style="font-size:9px; font-weight:normal; opacity:0.8;">Z: ${zScore > 0 ? '+' : ''}${zScore.toFixed(2)}</span>
      </td>`;
    }

    html += `
        <td style="text-align:right; border-bottom:1px solid var(--border); border-left:1px solid var(--border); font-weight:600;">${formatMetricValue(k, stat.mean, stat.unit)}</td>
        <td style="text-align:right; border-bottom:1px solid var(--border); color:var(--text-secondary);">${formatMetricValue(k, stat.median, stat.unit)}</td>
        <td style="text-align:right; border-bottom:1px solid var(--border); color:var(--text-muted);">${formatMetricValue(k, stat.min_value, stat.unit)}</td>
        <td style="text-align:right; border-bottom:1px solid var(--border); color:var(--text-muted);">${formatMetricValue(k, stat.max_value, stat.unit)}</td>
      </tr>
    `;
  }

  html += '</tbody></table>';
  wrap.innerHTML = html;
}

function renderRadarChart(healths) {
  const items = Object.values(healths);
  if (!items.length) return;

  const ctx = document.getElementById('radar-chart').getContext('2d');
  if (_radarChart) _radarChart.destroy();

  const categories = ['profitability', 'liquidity', 'leverage', 'cash_flow'];
  const categoryLabels = ['Profitability', 'Liquidity', 'Leverage', 'Cash Flow'];

  const datasets = items.map((h, idx) => {
    const colors = ['#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ec4899', '#06b6d4'];
    const color = colors[idx % colors.length];

    const catScores = categories.map(cat => {
      const catHealths = h.metric_healths.filter(m => m.category === cat);
      if (!catHealths.length) return 50;
      return catHealths.reduce((acc, curr) => acc + curr.score, 0) / catHealths.length;
    });

    return {
      label: h.ticker,
      data: catScores,
      borderColor: color,
      backgroundColor: color + '33', // 20% alpha
      borderWidth: 2,
    };
  });

  _radarChart = new Chart(ctx, {
    type: 'radar',
    data: { labels: categoryLabels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        r: {
          min: 0, max: 100,
          ticks: { color: '#71717a', backdropColor: 'transparent' },
          grid: { color: '#27272a' },
          angleLines: { color: '#3f3f46' },
          pointLabels: { color: '#a1a1aa', font: { family: 'Inter', size: 11, weight: 'bold' } },
        },
      },
      plugins: { legend: { labels: { color: '#fafafa', font: { family: 'JetBrains Mono' } } } },
    },
  });
}

let _lastTrendData = null;

async function fetchAndRenderTrends(companyIds, endYear) {
  try {
    const res = await fetch(`${API}/comparison/trends`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_ids: companyIds, start_year: endYear - 4, end_year: endYear }),
    });
    if (res.ok) {
      _lastTrendData = await res.json();
      updateTrendChart();
    }
  } catch (err) {
    console.warn('Failed to fetch trend data:', err);
  }
}

function updateTrendChart() {
  if (!_lastTrendData || !_lastTrendData.company_trends) return;
  const metricKey = document.getElementById('trend-metric-select').value;
  const ctx = document.getElementById('trend-chart').getContext('2d');
  if (_trendChart) _trendChart.destroy();

  const companies = Object.values(_lastTrendData.company_trends);
  const colors = ['#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ec4899', '#06b6d4'];

  let allYearsSet = new Set();
  companies.forEach(c => {
    const t = c.trends[metricKey];
    if (t && t.time_series) {
      t.time_series.forEach(point => allYearsSet.add(point.year));
    }
  });

  const years = Array.from(allYearsSet).sort();

  const datasets = companies.map((c, idx) => {
    const t = c.trends[metricKey];
    const color = colors[idx % colors.length];
    const seriesMap = (t && t.time_series) ? Object.fromEntries(t.time_series.map(p => [p.year, p.value])) : {};
    const data = years.map(yr => seriesMap[yr] !== undefined ? seriesMap[yr] : null);

    const cagrLabel = (t && t.cagr) ? ` (CAGR: ${(t.cagr * 100).toFixed(1)}%)` : '';

    return {
      label: `${c.ticker}${cagrLabel}`,
      data,
      borderColor: color,
      backgroundColor: color,
      tension: 0.2,
      spanGaps: true,
    };
  });

  _trendChart = new Chart(ctx, {
    type: 'line',
    data: { labels: years, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#fafafa', font: { family: 'JetBrains Mono' } } } },
      scales: {
        x: { grid: { color: '#27272a' }, ticks: { color: '#a1a1aa', font: { family: 'JetBrains Mono' } } },
        y: { grid: { color: '#27272a' }, ticks: { color: '#a1a1aa', font: { family: 'JetBrains Mono' } } },
      },
    },
  });
}

// --- Saved Cohorts & Notes ---

async function loadSavedCohorts() {
  const el = document.getElementById('saved-cohorts-list');
  try {
    const res = await fetch(`${API}/workspace/comparisons`);
    const list = await res.json();
    if (!list.length) {
      el.innerHTML = '<div class="empty-state">No saved cohorts.</div>';
      return;
    }
    el.innerHTML = list.map(c => `
      <div class="note-card" style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div class="note-card-title">${c.name}</div>
          <div class="note-card-meta">${c.company_ids.length} companies | ${c.fiscal_period}${c.fiscal_year || 2024}</div>
        </div>
        <div>
          <button class="btn btn-secondary" onclick="loadCohortFromSaved('${c.id}')" style="padding:2px 6px; font-size:10px;">Load</button>
          <button class="btn btn-secondary" onclick="deleteSavedCohort('${c.id}')" style="padding:2px 6px; font-size:10px; color:var(--accent-red);">Delete</button>
        </div>
      </div>
    `).join('');
  } catch {
    el.innerHTML = '<div class="empty-state">Failed to load saved cohorts.</div>';
  }
}

async function saveCurrentCohort() {
  const selectedCheckboxes = document.querySelectorAll('input[name="cohort-company"]:checked');
  const companyIds = Array.from(selectedCheckboxes).map(cb => cb.value);
  if (!companyIds.length) { toast('Select companies first.', 'error'); return; }

  const name = prompt('Enter a name for this cohort:', `Cohort ${new Date().toLocaleDateString()}`);
  if (!name) return;

  const year = parseInt(document.getElementById('exec-year').value) || 2024;
  const period = document.getElementById('exec-period').value || 'FY';

  try {
    const res = await fetch(`${API}/workspace/comparisons`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, company_ids: companyIds, fiscal_year: year, fiscal_period: period }),
    });
    if (res.ok) {
      toast('Cohort Saved', 'success');
      await loadSavedCohorts();
    }
  } catch {
    toast('Failed to save cohort.', 'error');
  }
}

async function deleteSavedCohort(id) {
  try {
    await fetch(`${API}/workspace/comparisons/${id}`, { method: 'DELETE' });
    toast('Cohort deleted', 'success');
    await loadSavedCohorts();
  } catch {
    toast('Delete failed.', 'error');
  }
}

async function loadAnalystNotes() {
  const el = document.getElementById('analyst-notes-list');
  try {
    const res = await fetch(`${API}/workspace/notes`);
    const notes = await res.json();
    if (!notes.length) {
      el.innerHTML = '<div class="empty-state">No analyst decision notes recorded yet.</div>';
      return;
    }
    el.innerHTML = notes.map(n => `
      <div class="note-card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div class="note-card-title">${n.title}</div>
          <button class="btn btn-secondary" onclick="deleteAnalystNote('${n.id}')" style="padding:2px 4px; font-size:9px; color:var(--accent-red);">Remove</button>
        </div>
        <div style="color:var(--text-secondary); margin:4px 0; font-size:11px; white-space:pre-wrap;">${n.content}</div>
        <div class="note-card-meta">${new Date(n.created_at).toLocaleString()} | Author: ${n.author}</div>
      </div>
    `).join('');
  } catch {
    el.innerHTML = '<div class="empty-state">Failed to load analyst notes.</div>';
  }
}

async function handleCreateNote(e) {
  e.preventDefault();
  const title = document.getElementById('note-title').value.trim();
  const content = document.getElementById('note-content').value.trim();
  if (!title || !content) return;

  try {
    const res = await fetch(`${API}/workspace/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content }),
    });
    if (res.ok) {
      toast('Decision note recorded', 'success');
      document.getElementById('note-title').value = '';
      document.getElementById('note-content').value = '';
      await loadAnalystNotes();
    }
  } catch {
    toast('Failed to create note.', 'error');
  }
}

async function deleteAnalystNote(id) {
  try {
    await fetch(`${API}/workspace/notes/${id}`, { method: 'DELETE' });
    toast('Note deleted', 'success');
    await loadAnalystNotes();
  } catch {
    toast('Delete failed.', 'error');
  }
}

function exportComparisonCSV() {
  if (!_lastComparisonData || !_lastComparisonData.metric_stats) {
    toast('Run a comparison first.', 'error'); return;
  }
  const stats = _lastComparisonData.metric_stats;
  const tickers = _lastComparisonData.company_tickers;
  const companyIds = Object.keys(tickers);

  let csv = `Metric,Category,Unit,${companyIds.map(cid => tickers[cid]).join(',')},Cohort Mean,Cohort Median,Min,Max\n`;
  for (const k of Object.keys(stats)) {
    const s = stats[k];
    const vals = companyIds.map(cid => s.company_values[cid] !== undefined ? s.company_values[cid] : '').join(',');
    csv += `"${s.name}","${s.category}","${s.unit}",${vals},${s.mean},${s.median},${s.min_value},${s.max_value}\n`;
  }

  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `cohort_comparison_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  toast('CSV Exported', 'success');
}


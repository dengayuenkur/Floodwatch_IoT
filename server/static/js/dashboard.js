/**
 * FloodWatch IoT — Dashboard JavaScript
 * ======================================
 * Manages:
 *  - JWT authentication guard
 *  - Socket.IO real-time data feed
 *  - Chart.js water level visualisation
 *  - Sensor status cards
 *  - Alert table and acknowledgement
 *  - Stats counters
 *  - Toast notifications
 *
 * Author: Deng Daniel Ayuen Kur (240103002054)
 */

'use strict';

// ═══════════════════════════════════════════════════════════════
//  Config
// ═══════════════════════════════════════════════════════════════
const MAX_CHART_POINTS  = 60;   // max data points per sensor on chart
const STATS_POLL_MS     = 30_000;
const ALERT_POLL_MS     = 15_000;
const READINGS_POLL_MS  = 20_000;

// ═══════════════════════════════════════════════════════════════
//  Auth guard — redirect to login if no token
// ═══════════════════════════════════════════════════════════════
const token    = localStorage.getItem('access_token');
const username = localStorage.getItem('username') || '?';
const userRole = localStorage.getItem('role')     || 'viewer';

if (!token) { window.location.href = '/login'; }

document.getElementById('navUsername').textContent = username;
document.getElementById('navRole').textContent     = userRole;

document.getElementById('logoutBtn').addEventListener('click', () => {
  localStorage.clear();
  window.location.href = '/login';
});

// Show admin-only controls
if (userRole !== 'viewer') {
  document.querySelectorAll('.admin-only').forEach(el => el.classList.remove('d-none'));
}

// ═══════════════════════════════════════════════════════════════
//  Live clock
// ═══════════════════════════════════════════════════════════════
const navTime = document.getElementById('navTime');
function updateClock() {
  navTime.textContent = new Date().toUTCString().replace(' GMT', ' UTC');
}
updateClock();
setInterval(updateClock, 1000);

// ═══════════════════════════════════════════════════════════════
//  API helper — all requests include JWT Bearer token
// ═══════════════════════════════════════════════════════════════
async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    localStorage.clear();
    window.location.href = '/login';
  }
  return res;
}

// ═══════════════════════════════════════════════════════════════
//  Chart.js — water level line chart
// ═══════════════════════════════════════════════════════════════
const LEVEL_COLORS = [
  '#0d6efd', '#20c997', '#fd7e14', '#6f42c1',
  '#e83e8c', '#17a2b8', '#ffc107', '#28a745',
];

const chartCtx     = document.getElementById('waterLevelChart').getContext('2d');
const chartDatasets = {};   // sensor_id → dataset index

const waterChart = new Chart(chartCtx, {
  type: 'line',
  data: { labels: [], datasets: [] },
  options: {
    responsive:          true,
    maintainAspectRatio: false,
    animation:           { duration: 300 },
    interaction:         { mode: 'index', intersect: false },
    plugins: {
      legend: {
        labels: { color: '#ccc', boxWidth: 12 },
      },
      tooltip: {
        backgroundColor: 'rgba(30,34,42,0.95)',
        titleColor:      '#fff',
        bodyColor:       '#ccc',
        callbacks: {
          label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} cm`,
        },
      },
    },
    scales: {
      x: {
        ticks:    { color: '#888', maxTicksLimit: 8, maxRotation: 0 },
        grid:     { color: 'rgba(255,255,255,0.06)' },
      },
      y: {
        title:    { display: true, text: 'Water Level (cm)', color: '#888' },
        ticks:    { color: '#888' },
        grid:     { color: 'rgba(255,255,255,0.06)' },
        beginAtZero: true,
      },
    },
  },
});

// Safe-warning-danger band annotations via afterDraw plugin
Chart.register({
  id: 'threshold-bands',
  afterDraw(chart) {
    const { ctx, chartArea, scales } = chart;
    if (!chartArea) return;
    const yScale   = scales.y;
    const toPixel  = v => yScale.getPixelForValue(v);
    // DEMO: water LEVEL values (cm above container bottom).
    // sensor_height(35) - WARNING_DIST(10) = 25 cm → warning band
    // sensor_height(35) - DANGER_DIST(7)   = 28 cm → danger band
    const warnY    = toPixel(25);
    const dangerY  = toPixel(28);
    const bottom   = chartArea.bottom;
    const left     = chartArea.left;
    const right    = chartArea.right;

    ctx.save();
    // Safe zone (green tint)
    ctx.fillStyle = 'rgba(25,135,84,0.06)';
    ctx.fillRect(left, warnY, right - left, bottom - warnY);
    // Warning zone (yellow tint)
    ctx.fillStyle = 'rgba(255,193,7,0.06)';
    ctx.fillRect(left, dangerY, right - left, warnY - dangerY);
    // Danger zone (red tint)
    ctx.fillStyle = 'rgba(220,53,69,0.07)';
    ctx.fillRect(left, chartArea.top, right - left, dangerY - chartArea.top);

    // Dashed lines
    ctx.setLineDash([5, 5]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(255,193,7,0.5)';
    ctx.beginPath(); ctx.moveTo(left, warnY);   ctx.lineTo(right, warnY);   ctx.stroke();
    ctx.strokeStyle = 'rgba(220,53,69,0.5)';
    ctx.beginPath(); ctx.moveTo(left, dangerY); ctx.lineTo(right, dangerY); ctx.stroke();
    ctx.restore();
  },
});

function addChartPoint(sensorId, sensorName, waterLevel, timestamp) {
  const label = new Date(timestamp).toLocaleTimeString();

  // Add shared x-axis label if it doesn't already exist
  const labels = waterChart.data.labels;
  if (!labels.includes(label)) {
    labels.push(label);
    if (labels.length > MAX_CHART_POINTS) labels.shift();
  }

  // Get or create dataset for this sensor
  if (!(sensorId in chartDatasets)) {
    const colorIdx = Object.keys(chartDatasets).length % LEVEL_COLORS.length;
    chartDatasets[sensorId] = waterChart.data.datasets.length;
    waterChart.data.datasets.push({
      label:           sensorName || sensorId,
      data:            new Array(labels.length - 1).fill(null),
      borderColor:     LEVEL_COLORS[colorIdx],
      backgroundColor: LEVEL_COLORS[colorIdx] + '22',
      borderWidth:     2,
      pointRadius:     3,
      tension:         0.3,
      fill:            false,
    });

    // Populate chart sensor filter dropdown
    const opt = document.createElement('option');
    opt.value       = sensorId;
    opt.textContent = sensorName || sensorId;
    document.getElementById('chartSensorFilter').appendChild(opt);
  }

  const dsIdx = chartDatasets[sensorId];
  const ds    = waterChart.data.datasets[dsIdx];

  // Pad datasets that don't have a point for this label yet
  waterChart.data.datasets.forEach((d, i) => {
    if (i !== dsIdx && d.data.length < labels.length) {
      d.data.push(null);
    }
  });

  ds.data.push(waterLevel);
  if (ds.data.length > MAX_CHART_POINTS) ds.data.shift();

  // Apply sensor filter
  const filter = document.getElementById('chartSensorFilter').value;
  waterChart.data.datasets.forEach(d => {
    const sid = Object.keys(chartDatasets).find(k => chartDatasets[k] === waterChart.data.datasets.indexOf(d));
    d.hidden = filter !== 'all' && sid !== filter;
  });

  waterChart.update('none');
}

document.getElementById('chartSensorFilter').addEventListener('change', () => {
  const filter = document.getElementById('chartSensorFilter').value;
  waterChart.data.datasets.forEach((d, idx) => {
    const sid = Object.keys(chartDatasets).find(k => chartDatasets[k] === idx);
    d.hidden  = filter !== 'all' && sid !== filter;
  });
  waterChart.update();
});

// ═══════════════════════════════════════════════════════════════
//  Sensor status cards
// ═══════════════════════════════════════════════════════════════
const sensorState = {};   // sensor_id → latest data

function renderSensorCards() {
  const container = document.getElementById('sensorCards');
  if (Object.keys(sensorState).length === 0) {
    container.innerHTML = `<div class="text-center text-secondary py-4">No sensor data yet</div>`;
    return;
  }

  container.innerHTML = Object.values(sensorState).map(s => {
    const lvl     = s.alert_level;
    const classes = lvl === 3 ? 'bg-alert-danger' : lvl === 2 ? 'bg-alert-warning' : 'bg-alert-safe';
    const dot     = s.sensor_online ? 'online' : 'offline';
    const dotTip  = s.sensor_online ? 'Online' : 'Offline';
    const barColor= lvl === 3 ? '#dc3545' : lvl === 2 ? '#ffc107' : '#198754';
    const maxLevel= 300;   // assumed max cm — adjust per installation
    const barPct  = Math.min(100, (s.water_level / maxLevel) * 100).toFixed(1);

    return `
    <div class="sensor-card ${classes}">
      <div class="d-flex justify-content-between align-items-start">
        <div>
          <span class="status-dot ${dot}" title="${dotTip}"></span>
          <strong class="small">${esc(s.sensor_name || s.sensor_id)}</strong>
        </div>
        <span class="badge ${lvl === 3 ? 'bg-danger' : lvl === 2 ? 'bg-warning text-dark' : 'bg-success'} ${lvl === 3 ? 'pulse-danger' : ''}">
          ${esc(s.alert_label)}
        </span>
      </div>
      <div class="text-secondary" style="font-size:0.72rem;">${esc(s.sensor_location || '')}</div>
      <div class="d-flex justify-content-between mt-1 small">
        <span>Water: <strong>${s.water_level.toFixed(1)} cm</strong></span>
        <span>Dist: ${s.distance.toFixed(1)} cm</span>
      </div>
      <div class="sensor-level-bar-track">
        <div class="sensor-level-bar-fill" style="width:${barPct}%;background:${barColor};"></div>
      </div>
      <div class="text-secondary mt-1" style="font-size:0.65rem;">
        ${new Date(s.timestamp).toLocaleTimeString()}
      </div>
    </div>`;
  }).join('');
}

// ═══════════════════════════════════════════════════════════════
//  Recent readings table
// ═══════════════════════════════════════════════════════════════
const readingRows = [];   // LIFO, max 50

function prependReadingRow(r) {
  readingRows.unshift(r);
  if (readingRows.length > 50) readingRows.pop();
  renderReadingsTable();
}

function renderReadingsTable() {
  const tbody = document.getElementById('readingsBody');
  if (readingRows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-secondary py-3">Waiting for data…</td></tr>`;
    return;
  }
  tbody.innerHTML = readingRows.map(r => {
    const lvl  = r.alert_level;
    const cls  = lvl === 3 ? 'text-danger' : lvl === 2 ? 'text-warning' : 'text-success';
    const rssi = r.rssi ? `${r.rssi} dBm` : '—';
    return `<tr>
      <td class="small">${esc(r.sensor_name || r.sensor_id)}</td>
      <td>${r.distance.toFixed(1)} cm</td>
      <td><strong>${r.water_level.toFixed(1)} cm</strong></td>
      <td class="${cls} fw-semibold small">${esc(r.alert_label)}</td>
      <td class="small text-secondary">${rssi}</td>
      <td class="small text-secondary">${new Date(r.timestamp).toLocaleTimeString()}</td>
    </tr>`;
  }).join('');
}

// ═══════════════════════════════════════════════════════════════
//  Alert table
// ═══════════════════════════════════════════════════════════════
async function loadAlerts() {
  try {
    const res  = await apiFetch('/api/v1/alerts?resolved=false&limit=20');
    const data = await res.json();
    renderAlertsTable(data.alerts || []);
  } catch (e) {
    console.error('Alert load error:', e);
  }
}

function renderAlertsTable(alerts) {
  const tbody = document.getElementById('alertsBody');
  if (alerts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-secondary py-3">No active alerts</td></tr>`;
    return;
  }
  tbody.innerHTML = alerts.map(a => {
    const isAdmin = userRole !== 'viewer';
    const typeStr = a.alert_type === 'DANGER'
      ? `<span class="badge bg-danger pulse-danger">DANGER</span>`
      : `<span class="badge bg-warning text-dark">WARNING</span>`;
    const ackBtn = isAdmin
      ? `<button class="btn btn-sm btn-outline-warning py-0 px-1" onclick="promptAck(${a.id},'${esc(a.message)}')">Ack</button>`
      : `<span class="text-secondary small">—</span>`;
    return `<tr>
      <td>${typeStr}</td>
      <td class="small">${esc(a.sensor_id)}</td>
      <td>${a.water_level != null ? a.water_level.toFixed(1) + ' cm' : '—'}</td>
      <td class="small text-secondary">${new Date(a.created_at).toLocaleTimeString()}</td>
      <td>${ackBtn}</td>
    </tr>`;
  }).join('');
}

// Acknowledge alert
let pendingAckId = null;
const ackModal   = new bootstrap.Modal(document.getElementById('ackModal'));

function promptAck(alertId, message) {
  pendingAckId = alertId;
  document.getElementById('ackModalBody').textContent =
    `Acknowledge this alert?\n"${message}"`;
  ackModal.show();
}

document.getElementById('ackConfirmBtn').addEventListener('click', async () => {
  if (!pendingAckId) return;
  try {
    const res = await apiFetch(`/api/v1/alerts/${pendingAckId}/acknowledge`, { method: 'POST' });
    if (res.ok) {
      showToast('Alert acknowledged', 'safe');
      loadAlerts();
      loadStats();
    } else {
      showToast('Failed to acknowledge alert', 'danger');
    }
  } catch (e) {
    showToast('Network error', 'danger');
  }
  ackModal.hide();
  pendingAckId = null;
});

// ═══════════════════════════════════════════════════════════════
//  Stats
// ═══════════════════════════════════════════════════════════════
async function loadStats() {
  try {
    const res  = await apiFetch('/api/v1/stats');
    const data = await res.json();
    document.getElementById('statSensors').textContent   = data.active_sensors  ?? '—';
    document.getElementById('statMaxLevel').textContent  = data.max_water_level != null
      ? `${data.max_water_level.toFixed(1)} cm` : '—';
    document.getElementById('statAlerts').textContent    = data.open_alerts     ?? '—';
    document.getElementById('statReadings').textContent  = data.total_readings  ?? '—';

    // Colour the alert card
    const alertCard = document.getElementById('statAlertCard');
    const alertIcon = document.getElementById('statAlertIcon');
    alertCard.className = alertCard.className
      .replace(/\bbg-\S+\b/g, '')
      .replace(/\btext-bg-\S+\b/g, '')
      .trim();

    if (data.danger_alerts > 0) {
      alertCard.classList.add('text-bg-danger', 'pulse-danger');
      alertIcon.className = 'bi bi-bell-fill fs-2 text-white opacity-75';
    } else if (data.open_alerts > 0) {
      alertCard.classList.add('text-bg-warning');
      alertIcon.className = 'bi bi-bell-fill fs-2 text-dark opacity-75';
    } else {
      alertCard.classList.add('text-bg-secondary');
      alertIcon.className = 'bi bi-bell fs-2 text-white opacity-75';
    }
  } catch (e) {
    console.error('Stats error:', e);
  }
}

// ═══════════════════════════════════════════════════════════════
//  Load historical readings on page load
// ═══════════════════════════════════════════════════════════════
async function loadHistoricalReadings() {
  try {
    const res  = await apiFetch('/api/v1/readings/latest');
    const data = await res.json();
    (data.latest || []).forEach(r => {
      sensorState[r.sensor_id] = r;
      addChartPoint(r.sensor_id, r.sensor_name, r.water_level, r.timestamp);
    });
    renderSensorCards();
    renderReadingsTable();
  } catch (e) {
    console.error('History load error:', e);
  }
}

async function loadRecentReadings() {
  try {
    const res  = await apiFetch('/api/v1/readings?limit=50&hours=2');
    const data = await res.json();
    // Resync (not append) so periodic polling doesn't duplicate rows
    // already shown via live WebSocket updates.
    const rows = (data.readings || []).slice().reverse(); // newest first
    readingRows.length = 0;
    rows.slice(0, 50).forEach(r => readingRows.push(r));
    renderReadingsTable();
  } catch (e) {
    console.error('Recent readings error:', e);
  }
}

// ═══════════════════════════════════════════════════════════════
//  Socket.IO — real-time feed
// ═══════════════════════════════════════════════════════════════
const socket      = io({ transports: ['websocket', 'polling'] });
const wsStatusBadge = document.getElementById('wsStatusBadge');

socket.on('connect', () => {
  wsStatusBadge.innerHTML = '<i class="bi bi-circle-fill me-1" style="font-size:0.5rem;"></i>Live';
  wsStatusBadge.className = 'badge bg-danger ms-2';
  socket.emit('request_state');
});

socket.on('disconnect', () => {
  wsStatusBadge.innerHTML = '<i class="bi bi-circle-fill me-1" style="font-size:0.5rem;"></i>Disconnected';
  wsStatusBadge.className = 'badge bg-secondary ms-2';
});

socket.on('new_reading', (r) => {
  sensorState[r.sensor_id] = r;
  addChartPoint(r.sensor_id, r.sensor_name, r.water_level, r.timestamp);
  renderSensorCards();
  prependReadingRow(r);
});

socket.on('new_alert', (a) => {
  const typeLabel = a.alert_type === 'DANGER' ? 'DANGER' : 'WARNING';
  const toastType = a.alert_type === 'DANGER' ? 'danger' : 'warning';
  showToast(`${typeLabel}: ${a.sensor_id} — ${a.message}`, toastType, 8000);
  loadAlerts();
  loadStats();
});

// ═══════════════════════════════════════════════════════════════
//  Toast notifications
// ═══════════════════════════════════════════════════════════════
function showToast(message, level = 'safe', delay = 4000) {
  const container = document.getElementById('toastContainer');
  const id        = `toast-${Date.now()}`;
  const iconMap   = { safe: 'check-circle-fill', warning: 'exclamation-circle-fill', danger: 'exclamation-octagon-fill' };
  const colorMap  = { safe: 'text-success', warning: 'text-warning', danger: 'text-danger' };

  const div = document.createElement('div');
  div.innerHTML = `
  <div id="${id}" class="toast toast-fw toast-${level} show mb-2" role="alert">
    <div class="d-flex align-items-start p-3 gap-2">
      <i class="bi bi-${iconMap[level] || 'info-circle-fill'} ${colorMap[level] || ''} fs-5 flex-shrink-0 mt-1"></i>
      <div class="flex-grow-1 small">${esc(message)}</div>
      <button type="button" class="btn-close btn-close-white btn-close-sm flex-shrink-0"
              onclick="this.closest('.toast').remove()"></button>
    </div>
  </div>`;
  container.appendChild(div.firstElementChild);
  setTimeout(() => document.getElementById(id)?.remove(), delay);
}

// ═══════════════════════════════════════════════════════════════
//  Utility
// ═══════════════════════════════════════════════════════════════
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ═══════════════════════════════════════════════════════════════
//  Initialisation
// ═══════════════════════════════════════════════════════════════
(async function init() {
  await loadStats();
  await loadHistoricalReadings();
  await loadRecentReadings();
  await loadAlerts();

  setInterval(loadStats,           STATS_POLL_MS);
  setInterval(loadAlerts,          ALERT_POLL_MS);
  setInterval(loadRecentReadings,  READINGS_POLL_MS);
})();

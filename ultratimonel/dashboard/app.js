/**
 * app.js — Ultratimonel Dashboard Frontend
 *
 * NES-style hierarchy viewer.
 * Flow: Project → Missions (Deck) → Checklist Items → Intentos → Gates (Acciones)
 *
 * NO hay vista "Acciones" separada — las acciones viven al hacer click en un
 * intento (ciclo 1a→1e) dentro de un item del checklist.
 */

// ── State ─────────────────────────────────────────────────────────────────

let state = {
  projects: [],
  missions: [],
  selectedProject: null,
  selectedMission: null,
  selectedChecklistItem: null,
  selectedChecklistItemText: '',
  selectedIntento: null,
};

// ── Views ─────────────────────────────────────────────────────────────────
// We use a simple view stack for the content area
const VIEW = {
  MISSIONS: 'missions',
  CHECKLIST_ITEMS: 'checklist-items',
  INTENTOS: 'intentos',
  INTENTO_DETAIL: 'intento-detail',
};

let currentView = VIEW.MISSIONS;

// ── DOM refs ──────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);
const projectListEl = $('project-list');
const missionListEl = $('mission-list');
const contentTitle = $('content-title');
const contentSubtitle = $('content-subtitle');
const contentBreadcrumb = $('content-breadcrumb');
const detailOverlay = $('detail-overlay');
const detailContent = $('detail-content');
const detailClose = $('detail-close');
const dbStatus = $('db-status');
const backBtn = $('back-btn');

// ── Icons per gate state ──────────────────────────────────────────────────

const GATE_ICONS = {
  PASS: '✅',
  SKIP: '⏭️',
  WARN: '⚠️',
  BLOCK: '❌',
  PENDING: '⏳',
};

const GATE_CLASS = {
  PASS: 'gate-pass',
  SKIP: 'gate-skip',
  WARN: 'gate-warn',
  BLOCK: 'gate-block',
  PENDING: 'gate-skip',
};

const STATUS_LABEL = {
  pendiente: '⏳ PENDIENTE',
  en_progreso: '🔄 EN PROGRESO',
  completada: '✅ COMPLETADA',
  bloqueada: '🔒 BLOQUEADA',
  running: '🔄 EJECUTANDO',
  success: '✅ ÉXITO',
  fail: '❌ FALLIDO',
};

const STATUS_CLASS = {
  pendiente: 'status-pending',
  en_progreso: 'status-active',
  completada: 'status-completed',
  bloqueada: 'status-blocked',
  running: 'status-active',
  success: 'status-completed',
  fail: 'status-failed',
};

// ── API helpers ───────────────────────────────────────────────────────────

async function api(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      console.warn('API error', path, err);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.warn('API fetch failed', path, err.message);
    return null;
  }
}

// ── DB status ─────────────────────────────────────────────────────────────

async function checkDb() {
  const data = await api('/api/projects');
  if (data && data.projects) {
    dbStatus.textContent = `💾 ${data.total} proyectos`;
    dbStatus.style.color = '#27ae60';
  } else {
    dbStatus.textContent = '💾 Sin DB';
    dbStatus.style.color = '#e94560';
  }
  return data;
}

// ── Render Projects (sidebar) ─────────────────────────────────────────────

function renderProjects(projects) {
  projectListEl.innerHTML = '';
  if (!projects || projects.length === 0) {
    projectListEl.innerHTML = `
      <div style="padding:16px;font-size:7px;color:#636e72;text-align:center;">
        (vacío)
      </div>
    `;
    return;
  }

  for (const p of projects) {
    const item = document.createElement('div');
    item.className = 'project-item' + (state.selectedProject === p.project ? ' active' : '');
    item.dataset.project = p.project;

    const count = p.mission_count || 0;
    const completed = p.completed_count || 0;
    const hasBoard = p.has_board;

    item.innerHTML = `
      <span>📁</span>
      <span>${p.project}</span>
      <span class="badge">${count}</span>
    `;

    item.addEventListener('click', () => selectProject(p.project));
    projectListEl.appendChild(item);
  }
}

// ── Breadcrumb ────────────────────────────────────────────────────────────

function updateBreadcrumb(items) {
  if (!contentBreadcrumb) return;
  const parts = items.map((item, i) => {
    const isLast = i === items.length - 1;
    if (item.onClick) {
      return `<span class="breadcrumb-link" data-idx="${i}">${item.label}</span>`;
    }
    return `<span class="breadcrumb-current">${item.label}</span>`;
  });
  contentBreadcrumb.innerHTML = parts.join(' › ');
  contentBreadcrumb.querySelectorAll('.breadcrumb-link').forEach(el => {
    const idx = parseInt(el.dataset.idx);
    el.addEventListener('click', () => {
      const item = items[idx];
      if (item.onClick) item.onClick();
    });
  });
}

// ── View 1: Missions List ────────────────────────────────────────────────

function renderMissions(project, missions) {
  currentView = VIEW.MISSIONS;
  state.selectedMission = null;
  state.selectedChecklistItem = null;
  state.selectedIntento = null;

  missionListEl.innerHTML = '';
  contentTitle.textContent = `📋 ${project}`;
  contentSubtitle.textContent = `${missions.length} misión(es)`;
  updateBreadcrumb([
    { label: project },
  ]);

  if (!missions || missions.length === 0) {
    missionListEl.innerHTML = `
      <div class="empty-state">
        <i class="nes-icon trophy is-large"></i>
        <h3>Sin misiones</h3>
        <p>No hay misiones sincronizadas desde Nextcloud Deck</p>
        <p style="font-size:6px;margin-top:12px;color:#636e72;">
          Usa <code style="color:#e94560;">sync_tasks("${project}")</code> en Hermes para sincronizar
        </p>
      </div>
    `;
    return;
  }

  for (const m of missions) {
    const card = document.createElement('div');
    card.className = 'mission-card';
    card.dataset.missionId = m.id;

    const status = m.status || 'pendiente';
    const label = STATUS_LABEL[status] || status;
    const cls = STATUS_CLASS[status] || '';
    const total = m.checklist_total || 0;
    const done = m.checklist_done || 0;
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    const date = (m.last_sync || m.created_at || '').split('T')[0] || '—';
    const description = (m.description || '').substring(0, 120);

    card.innerHTML = `
      <div class="mission-card-header">
        <div class="mission-card-title">
          🎯 ${m.title || 'Sin título'}
        </div>
        <span class="status-badge ${cls}">${label}</span>
      </div>
      ${description ? `<div class="mission-desc">${description}${m.description && m.description.length > 120 ? '…' : ''}</div>` : ''}
      <div class="mission-meta">
        📋 ${done}/${total} · 🕐 ${date}
      </div>
    `;

    card.addEventListener('click', () => openMission(m.id));
    missionListEl.appendChild(card);
  }
}

// ── View 2: Checklist Items (inside a mission) ────────────────────────────

async function openMission(missionId) {
  state.selectedMission = missionId;
  const data = await api(`/api/missions/${missionId}`);
  if (!data || !data.mission) {
    missionListEl.innerHTML = `
      <div class="empty-state">
        <h3>🚫 Misión no encontrada</h3>
      </div>
    `;
    return;
  }

  const m = data.mission;
  currentView = VIEW.CHECKLIST_ITEMS;
  state.selectedChecklistItem = null;
  state.selectedIntento = null;

  const items = m.checklist || [];
  contentTitle.textContent = `📝 ${m.title || 'Sin título'}`;
  contentSubtitle.textContent = `${items.length} item(s)`;
  updateBreadcrumb([
    {
      label: state.selectedProject || '—',
      onClick: () => selectProject(state.selectedProject),
    },
    { label: m.title || 'Misión' },
  ]);

  missionListEl.innerHTML = '';

  if (items.length === 0) {
    missionListEl.innerHTML = `
      <div class="empty-state">
        <h3>📋 Sin checklist</h3>
        <p>Esta misión no tiene items de checklist</p>
      </div>
    `;
    return;
  }

  for (const item of items) {
    const card = document.createElement('div');
    card.className = 'checklist-item-card';
    card.dataset.itemId = item.id;

    const icon = item.done ? '✅' : '⬜';
    const intentoCount = item.intentos ? item.intentos.length : 0;
    const latest = item.intentos && item.intentos.length > 0 ? item.intentos[0] : null;
    const latestLabel = latest ? (STATUS_LABEL[latest.status] || latest.status) : '—';
    const latestCls = latest ? (STATUS_CLASS[latest.status] || '') : '';
    const itemText = item.text || '—';

    card.innerHTML = `
      <div class="checklist-item-header">
        <span style="font-size:14px;">${icon}</span>
        <span class="checklist-item-text">${itemText}</span>
      </div>
      <div class="checklist-item-meta">
        <span>🔄 ${intentoCount} intento(s)</span>
        ${latest ? `<span class="status-badge ${latestCls}" style="font-size:6px;">${latestLabel}</span>` : ''}
      </div>
    `;

    card.addEventListener('click', () => openIntentos(item.id, itemText));
    missionListEl.appendChild(card);
  }
}

// ── View 3: Intentos List (for a checklist item) ──────────────────────────

async function openIntentos(itemId, itemText) {
  state.selectedChecklistItem = itemId;
  state.selectedChecklistItemText = itemText || '';
  const data = await api(`/api/checklist/${itemId}/intentos`);
  if (!data) return;

  const intentos = data.intentos || [];
  currentView = VIEW.INTENTOS;
  state.selectedIntento = null;

  contentTitle.textContent = `🔄 Intentos`;
  contentSubtitle.textContent = `${intentos.length} intento(s)`;
  const label = state.selectedChecklistItemText 
    ? state.selectedChecklistItemText.substring(0, 60)
    : `Item #${data.checklist_item_id}`;
  updateBreadcrumb([
    {
      label: state.selectedProject || '—',
      onClick: () => selectProject(state.selectedProject),
    },
    {
      label: 'Misión',
      onClick: () => openMission(state.selectedMission),
    },
    { label: label },
  ]);

  missionListEl.innerHTML = '';

  if (intentos.length === 0) {
    missionListEl.innerHTML = `
      <div class="empty-state">
        <h3>🔄 Sin intentos</h3>
        <p>Este item del checklist aún no tiene intentos de assert_gates</p>
        <p style="font-size:6px;margin-top:12px;color:#636e72;">
          Ejecuta <code style="color:#e94560;">assert_gates("...")</code> para este proyecto
        </p>
      </div>
    `;
    return;
  }

  for (const it of intentos) {
    const card = document.createElement('div');
    card.className = 'intento-card';
    card.dataset.intentoId = it.id;

    const status = it.status || 'running';
    const label = STATUS_LABEL[status] || status;
    const cls = STATUS_CLASS[status] || '';
    const pct = it.gates_total > 0
      ? Math.min(100, Math.round((it.gates_passed / it.gates_total) * 100))
      : 0;
    const date = (it.started_at || '').split('T')[0] || '—';
    const sid = (it.session_id || '').substring(0, 12);

    card.innerHTML = `
      <div class="intento-card-header">
        <div class="intento-card-title">
          🎯 Intento #${it.id}
          <span style="font-size:6px;color:#5dade2;">${sid}…</span>
        </div>
        <span class="status-badge ${cls}">${label}</span>
      </div>
      <div class="progress-row">
        <progress class="nes-progress ${pct === 100 ? 'is-success' : ''}" value="${pct}" max="100"></progress>
        <span class="progress-label">${it.gates_passed}/${it.gates_total} gates · ${pct}%</span>
      </div>
      <div class="intento-meta">
        🕐 ${date}
        ${it.completed_at ? `· ✅ ${it.completed_at.split('T')[0]}` : ''}
      </div>
    `;

    card.addEventListener('click', () => openIntentoDetail(it.id));
    missionListEl.appendChild(card);
  }
}

// ── View 4: Intento Detail (gates with actions) ──────────────────────────

async function openIntentoDetail(intentoId) {
  state.selectedIntento = intentoId;
  const data = await api(`/api/intentos/${intentoId}`);
  if (!data || !data.intento) return;

  const intento = data.intento;
  currentView = VIEW.INTENTO_DETAIL;

  contentTitle.textContent = `🎯 Intento #${intento.id}`;
  contentSubtitle.textContent = `${intento.gates_passed}/${intento.gates_total} gates`;
  updateBreadcrumb([
    {
      label: state.selectedProject,
      onClick: () => selectProject(state.selectedProject),
    },
    {
      label: 'Misión',
      onClick: () => openMission(state.selectedMission),
    },
    {
      label: 'Intentos',
      onClick: () => openIntentos(state.selectedChecklistItem),
    },
    { label: `Intento #${intento.id}` },
  ]);

  // Show mission + item context
  const mission = intento.mission || {};
  const item = intento.checklist_item || {};
  const gates = intento.gates || [];
  const statusLabel = STATUS_LABEL[intento.status] || intento.status;
  const statusCls = STATUS_CLASS[intento.status] || '';

  let gatesHtml = '';
  for (const g of gates) {
    const icon = GATE_ICONS[g.state] || '❓';
    const gcls = GATE_CLASS[g.state] || '';
    const dur = g.duration_ms ? `${g.duration_ms}ms` : '—';
    gatesHtml += `
      <div class="gate-row" data-gate-name="${g.gate_name}">
        <span class="gate-name">${g.gate_name}</span>
        <span class="gate-state ${gcls}">${icon} ${g.state}</span>
        <span class="gate-msg">${g.message || '—'}</span>
        <span class="gate-duration">${dur}</span>
        <button class="gate-log-btn" data-intento-id="${intento.id}" data-gate-name="${g.gate_name}">📋</button>
      </div>
    `;
  }

  missionListEl.innerHTML = `
    <div class="intento-context">
      <div style="font-size:7px;color:#7f8c8d;margin-bottom:8px;">
        <div>📁 <strong style="color:#e0e0e0;">${mission.title || '—'}</strong></div>
        <div>📋 Item: <strong style="color:#e0e0e0;">${item.text || '—'}</strong></div>
        <div>🆔 Sesión: <code style="color:#5dade2;">${intento.session_id}</code></div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <span class="status-badge ${statusCls}">${statusLabel}</span>
      </div>
    </div>

    <div class="detail-section-title">🔌 Gates (acciones del intento)</div>
    ${gatesHtml || '<div style="font-size:7px;color:#636e72;">Sin datos de gates</div>'}

    <div class="detail-section-title">📅 Timeline</div>
    <div style="font-size:7px;color:#636e72;">
      <div>Inicio: ${(intento.started_at || '').split('.')[0] || '—'}</div>
      ${intento.completed_at ? `<div>Fin: ${(intento.completed_at || '').split('.')[0]}</div>` : ''}
    </div>
  `;

  // Wire gate log buttons
  missionListEl.querySelectorAll('.gate-log-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const gateName = btn.dataset.gateName;
      const iId = btn.dataset.intentoId;
      await showGateLogs(iId, gateName);
    });
  });
}

// ── Gate Logs Modal (actions timeline for a specific gate) ────────────────

async function showGateLogs(intentoId, gateName) {
  const data = await api(`/api/intentos/${intentoId}/gate/${gateName}/logs`);
  const logs = data?.logs || [];

  let logsHtml = '';
  if (logs.length === 0) {
    logsHtml = '<div style="font-size:7px;color:#636e72;text-align:center;padding:20px;">Sin registros de transiciones</div>';
  } else {
    for (const log of logs) {
      logsHtml += `
        <div class="log-row">
          <span class="gate-state ${GATE_CLASS[log.from_state] || ''}">${GATE_ICONS[log.from_state] || '❓'}</span>
          <span class="arrow">→</span>
          <span class="gate-state ${GATE_CLASS[log.to_state] || ''}">${GATE_ICONS[log.to_state] || '❓'}</span>
          <span style="flex:1;color:#b2bec3;">${log.reason || '—'}</span>
          <span style="font-size:6px;color:#636e72;">${(log.created_at || '').split('.')[0]}</span>
        </div>
      `;
    }
  }

  detailContent.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div>
        <div style="font-size:12px;color:#e94560;">📋 Gate ${gateName}</div>
        <div style="font-size:7px;color:#5dade2;">Intento #${intentoId} · Timeline de acciones</div>
      </div>
      <span class="close-btn" id="detail-inner-close" style="font-size:12px;cursor:pointer;">✕ CERRAR</span>
    </div>
    <div class="detail-section-title">🕐 Transiciones</div>
    ${logsHtml}
  `;

  detailOverlay.classList.add('open');
  const innerClose = document.getElementById('detail-inner-close');
  if (innerClose) innerClose.addEventListener('click', () => closeDetail());
}

// ── Actions ───────────────────────────────────────────────────────────────

async function selectProject(project) {
  state.selectedProject = project;
  state.selectedMission = null;
  state.selectedChecklistItem = null;
  state.selectedIntento = null;

  // Update sidebar active state
  document.querySelectorAll('.project-item').forEach(el => {
    el.classList.toggle('active', el.dataset.project === project);
  });

  const data = await api(`/api/projects/${encodeURIComponent(project)}/missions`);
  state.missions = data?.missions || [];
  renderMissions(project, state.missions);
}

function closeDetail() {
  detailOverlay.classList.remove('open');
}

// ── Init ──────────────────────────────────────────────────────────────────

async function init() {
  const data = await checkDb();
  if (data && data.projects) {
    state.projects = data.projects;
    renderProjects(data.projects);

    // Auto-select first project if available
    if (data.projects.length > 0) {
      selectProject(data.projects[0].project);
    }
  } else {
    projectListEl.innerHTML = `
      <div style="padding:16px;font-size:7px;color:#636e72;text-align:center;">
        💿 No hay base de datos<br>
        <span style="font-size:6px;">Esperando misiones...</span>
      </div>
    `;
    missionListEl.innerHTML = `
      <div class="empty-state">
        <i class="nes-icon trophy is-large"></i>
        <h3>⚡ Sin datos</h3>
        <p>Ultratimonel aún no ha registrado datos.<br>
        Usa <code style="color:#e94560;">sync_tasks()</code> en Hermes para sincronizar proyectos.</p>
      </div>
    `;
    contentTitle.textContent = '💿 Bienvenido';
    contentSubtitle.textContent = '';
  }
}

// ── Events ────────────────────────────────────────────────────────────────

detailClose.addEventListener('click', closeDetail);
detailOverlay.addEventListener('click', (e) => {
  if (e.target === detailOverlay) closeDetail();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeDetail();
});

// ── Boot ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);

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

// ── Gate state icons (NES.css icon names) ────────────────────────────────
// Replaces GATE_ICONS emoji map — now returns semantic text labels

function getGateIconHTML(stateName) {
  const iconMap = {
    PASS: 'check',
    WARN: 'warning',
    BLOCK: 'close',
    SKIP: 'menu',
    PENDING: 'setting',
  };
  return `<i class="nes-icon ${iconMap[stateName] || 'info'} is-small"></i>`;
}

function getGateStateText(stateName) {
  const labels = {
    PASS: 'PASS',
    WARN: 'WARN',
    BLOCK: 'BLOCK',
    SKIP: 'SKIP',
    PENDING: 'PENDING',
  };
  return labels[stateName] || stateName;
}

const GATE_CLASS = {
  PASS: 'gate-pass',
  SKIP: 'gate-skip',
  WARN: 'gate-warn',
  BLOCK: 'gate-block',
  PENDING: 'gate-skip',
};

// ── Phase 3: STATUS_LABEL — text only, NO emoji ────────────────────────
const STATUS_LABEL = {
  pendiente: 'PENDIENTE',
  en_progreso: 'EN PROGRESO',
  completada: 'COMPLETADA',
  bloqueada: 'BLOQUEADA',
  running: 'EJECUTANDO',
  success: 'EXITO',
  fail: 'FALLIDO',
};

const STATUS_CLASS = {
  pendiente: 'is-warning',
  en_progreso: 'is-success',
  completada: 'is-success',
  bloqueada: 'is-error',
  running: 'is-warning',
  success: 'is-success',
  fail: 'is-error',
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

// ── Phase 2: Theme system ────────────────────────────────────────────────

function initTheme() {
  const stored = localStorage.getItem('ultratimonel-theme');
  if (stored === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
    const checkbox = $('theme-toggle');
    if (checkbox) checkbox.checked = true;
  }
}

function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  if (isDark) {
    html.removeAttribute('data-theme');
    localStorage.setItem('ultratimonel-theme', 'light');
  } else {
    html.setAttribute('data-theme', 'dark');
    localStorage.setItem('ultratimonel-theme', 'dark');
  }
}

// ── DB status ─────────────────────────────────────────────────────────────

async function checkDb() {
  const data = await api('/api/projects');
  if (data && data.projects) {
    dbStatus.textContent = `DB: ${data.total} proyectos`;
    dbStatus.style.color = 'var(--success)';
  } else {
    dbStatus.textContent = 'DB: Sin DB';
    dbStatus.style.color = 'var(--error)';
  }
  return data;
}

// ── Render Projects (sidebar) ─────────────────────────────────────────────

function renderProjects(projects) {
  projectListEl.innerHTML = '';
  if (!projects || projects.length === 0) {
    projectListEl.innerHTML = `
      <div style="padding:16px;color:var(--text-secondary);text-align:center;">
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

    // Phase 3: Replace 📁 with semantic folder label
    item.innerHTML = `
      <span class="nes-badge is-splited">
        <span style="background:var(--border);border-color:var(--border);"></span>
        <span>${p.project}</span>
      </span>
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
    if (isLast) {
      return `<span class="breadcrumb-current">${item.label}</span>`;
    }
    if (item.onClick) {
      return `<span class="breadcrumb-link" data-idx="${i}">${item.label}</span>`;
    }
    return `<span>${item.label}</span>`;
  });
  contentBreadcrumb.innerHTML = parts.join('');
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
  
  // Phase 3: Remove prefix, use NES.css icon instead
  contentTitle.textContent = project;
  contentSubtitle.textContent = `${missions.length} misión(es)`;
  updateBreadcrumb([]);

  if (!missions || missions.length === 0) {
    missionListEl.innerHTML = `
      <div class="empty-state">
        <i class="nes-icon trophy is-large"></i>
        <h3>Sin misiones</h3>
        <p>No hay misiones sincronizadas desde Nextcloud Deck</p>
        <p style="margin-top:12px;color:var(--text-secondary);">
          Usa <code style="color:var(--error);">sync_tasks("${project}")</code> en Hermes para sincronizar
        </p>
      </div>
    `;
    return;
  }

  for (const m of missions) {
    const card = document.createElement('div');
    card.className = 'nes-container with-title';
    card.dataset.missionId = m.id;

    const status = m.status || 'pendiente';
    const label = STATUS_LABEL[status] || status;
    const cls = STATUS_CLASS[status] || '';
    const total = m.checklist_total || 0;
    const done = m.checklist_done || 0;
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    const date = (m.last_sync || m.created_at || '').split('T')[0] || '—';
    const description = (m.description || '').substring(0, 120);

    card.style.cursor = 'pointer';

    card.innerHTML = `
      <p class="title">${m.title || 'Sin título'}</p>
      <span class="nes-badge"><span class="${cls}">${label}</span></span>
      ${description ? `<div class="mission-desc">${description}${m.description && m.description.length > 120 ? '…' : ''}</div>` : ''}
      <div class="mission-meta">
        Items: ${done}/${total} · Última sincronización: ${date}
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
        <h3 style="color:var(--error);">Misión no encontrada</h3>
      </div>
    `;
    return;
  }

  const m = data.mission;
  currentView = VIEW.CHECKLIST_ITEMS;
  state.selectedChecklistItem = null;
  state.selectedIntento = null;

  const items = m.checklist || [];
  
  // Phase 3: Remove 📝 prefix from content title
  contentTitle.textContent = m.title || 'Sin título';
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
    // Phase 3: Remove emoji from empty state, use NES.css icon
    missionListEl.innerHTML = `
      <div class="empty-state">
        <i class="nes-icon setting is-large"></i>
        <h3>Sin checklist</h3>
        <p>Esta misión no tiene items de checklist</p>
      </div>
    `;
    return;
  }

  for (const item of items) {
    const card = document.createElement('div');
    card.className = 'nes-container with-title';
    card.dataset.itemId = item.id;

    // Phase 3: Replace ✅/⬜ emoji with NES.css icon + semantic label
    const iconHtml = item.done
      ? '<i class="nes-icon check is-small" style="color:var(--success);"></i>'
      : '<i class="nes-icon setting is-small"></i>';
    
    // Phase 3: Replace ✅/⬜ with semantic indicator label
    const statusLabel = item.done ? 'Completado' : 'Pendiente';
    const statusCls = item.done ? 'is-success' : 'is-dark';

    const intentoCount = item.intentos ? item.intentos.length : 0;
    const latest = item.intentos && item.intentos.length > 0 ? item.intentos[0] : null;
    const latestLabel = latest ? (STATUS_LABEL[latest.status] || latest.status) : '—';
    const latestCls = latest ? (STATUS_CLASS[latest.status] || '') : '';
    const itemText = item.text || '—';

    card.style.cursor = 'pointer';

    card.innerHTML = `
      <p class="title">${itemText}</p>
      <div style="display:flex;align-items:center;gap:8px;margin-top:6px;">
        ${iconHtml}
        <span class="nes-badge"><span class="${statusCls}">${statusLabel}</span></span>
      </div>
      <div style="margin-top:6px;">
        <span>${intentoCount} intento(s)</span>
        ${latest ? `<span class="nes-badge" style="margin-left:8px;"><span class="${latestCls}">${latestLabel}</span></span>` : ''}
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

  // Phase 3: Remove 🔄 prefix from content title, use text label
  contentTitle.textContent = 'Intentos';
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
    // Phase 3: Remove 🔄 emoji from empty state, use NES.css icon
    missionListEl.innerHTML = `
      <div class="empty-state">
        <i class="nes-icon setting is-large"></i>
        <h3>Sin intentos</h3>
        <p>Este item del checklist aún no tiene intentos de assert_gates</p>
        <p style="margin-top:12px;color:var(--text-secondary);">
          Ejecuta <code style="color:var(--error);">assert_gates("...")</code> para este proyecto
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

    // Phase 3: Remove 🎯 emoji from title, remove 🕐/✅ emojis from meta
    card.innerHTML = `
      <div class="intento-card-header">
        <div class="intento-card-title">
          Intento #${it.id}
          <span style="color:var(--accent);">${sid}</span>
        </div>
          <span class="nes-badge"><span class="${cls}">${label}</span></span>
      </div>
      <div class="progress-row">
        <progress class="nes-progress is-rounded ${pct === 100 ? 'is-success' : (pct >= 50 ? 'is-warning' : '')}" value="${pct}" max="100"></progress>
        <span class="progress-label">${it.gates_passed}/${it.gates_total} gates · ${pct}%</span>
      </div>
      <div class="intento-meta">
        Inicio: ${date}
        ${it.completed_at ? ` · Finalizado: ${it.completed_at.split('T')[0]}` : ''}
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

  // Phase 3: Remove 🎯 prefix, use text label
  contentTitle.textContent = `Intento #${intento.id}`;
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

  const mission = intento.mission || {};
  const item = intento.checklist_item || {};
  const gates = intento.gates || [];
  const statusLabel = STATUS_LABEL[intento.status] || intento.status;
  const statusCls = STATUS_CLASS[intento.status] || '';

  // Phase 3: Replace GATE_ICONS emojis with NES.css icons + semantic text labels
  let gatesHtml = '';
  for (const g of gates) {
    const iconHtml = getGateIconHTML(g.state);
    const stateText = getGateStateText(g.state);
    const gcls = GATE_CLASS[g.state] || '';
    const dur = g.duration_ms ? `${g.duration_ms}ms` : '—';
    gatesHtml += `
      <div class="gate-row" data-gate-name="${g.gate_name}">
        <span class="gate-name">${g.gate_name}</span>
        <span class="gate-state ${gcls}">${iconHtml} ${stateText}</span>
        <span class="gate-msg">${g.message || '—'}</span>
        <span class="gate-duration">${dur}</span>
        <button class="gate-log-btn" data-intento-id="${intento.id}" data-gate-name="${g.gate_name}">Ver logs</button>
      </div>
    `;
  }

  // Phase 3: Remove emojis from context, replace with semantic labels
  missionListEl.innerHTML = `
    <div class="intento-context">
      <div style="color:var(--text-secondary);margin-bottom:8px;">
        <div>Proyecto: <strong style="color:var(--text-primary);">${mission.title || '—'}</strong></div>
        <div>Item: <strong style="color:var(--text-primary);">${item.text || '—'}</strong></div>
        <div>Sesión: <code style="color:var(--accent);">${intento.session_id}</code></div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <span class="nes-badge"><span class="${statusCls}">${statusLabel}</span></span>
      </div>
    </div>

    <div class="detail-section-title">Gates</div>
    ${gatesHtml || '<div style="color:var(--text-secondary);">Sin datos de gates</div>'}

    <div class="detail-section-title">Timeline</div>
    <div style="color:var(--text-secondary);">
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
    // Phase 3: Remove emoji from title, use NES.css icon
    logsHtml = `
      <div style="color:var(--text-secondary);text-align:center;padding:20px;">
        <i class="nes-icon setting is-large"></i>
        <p>Sin registros de transiciones</p>
      </div>
    `;
  } else {
    for (const log of logs) {
      // Phase 3: Replace GATE_ICONS emojis with NES.css icons + CSS arrow instead of emoji →
      const fromIcon = getGateIconHTML(log.from_state);
      const toIcon = getGateIconHTML(log.to_state);
      logsHtml += `
        <div class="log-row">
          <span class="gate-state ${GATE_CLASS[log.from_state] || ''}">${fromIcon}</span>
          <span class="arrow">→</span>
          <span class="gate-state ${GATE_CLASS[log.to_state] || ''}">${toIcon}</span>
          <span style="flex:1;color:var(--text-primary);">${log.reason || '—'}</span>
          <span style="color:var(--text-secondary);">${(log.created_at || '').split('.')[0]}</span>
        </div>
      `;
    }
  }

  detailContent.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div>
        <!-- Phase 3: Remove emoji from title, use NES.css icon -->
        <i class="nes-icon setting is-small"></i>
        <span style="color:var(--error);">Gate ${gateName}</span>
        <div style="color:var(--accent);">Intento #${intentoId} · Timeline de acciones</div>
      </div>
      <span class="close-btn" id="detail-inner-close" style="cursor:pointer;">X CERRAR</span>
    </div>
    <div class="detail-section-title">Transiciones</div>
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
  // Phase 2: Initialize theme BEFORE any rendering
  initTheme();

  const data = await checkDb();
  if (data && data.projects) {
    state.projects = data.projects;
    renderProjects(data.projects);

    if (data.projects.length > 0) {
      selectProject(data.projects[0].project);
    }
  } else {
    // Phase 3: Remove 💿 emojis, use NES.css icons + semantic labels
    projectListEl.innerHTML = `
      <div style="padding:16px;color:var(--text-secondary);text-align:center;">
        Sin base de datos
        <br><span>Esperando misiones...</span>
      </div>
    `;
    missionListEl.innerHTML = `
      <div class="empty-state">
        <i class="nes-icon trophy is-large"></i>
        <h3>Sin datos</h3>
        <p>Ultratimonel aún no ha registrado datos.<br>
        Usa <code style="color:var(--error);">sync_tasks()</code> en Hermes para sincronizar proyectos.</p>
      </div>
    `;
    contentTitle.textContent = 'Bienvenido';
    contentSubtitle.textContent = '';
  }

  // Phase 2: Wire up theme toggle
  const checkbox = $('theme-toggle');
  if (checkbox) {
    checkbox.addEventListener('change', toggleTheme);
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

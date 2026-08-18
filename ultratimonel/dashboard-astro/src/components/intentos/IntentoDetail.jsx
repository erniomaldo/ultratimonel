// IntentoDetail — intento detail island (T9, F-DA-12, F-DA-15, S6/S7/S8/S9;
// Ejecución 9: the intento now has its OWN route — the fifth hierarchical
// level /{proyectoName}/{misionId}/{checklistItemId}/{intentoId}/, card #154).
// Replaces the old dialog slot inside ItemDetail: "Ver detalle y logs" now
// links to this page instead of opening a modal. The gate-log timeline remains
// on-demand (NesDialog, S6/S7) inside this page.
//
// Fetches `/api/intentos/{id}` via the shared useApi hook and renders:
//   - header: `Intento #<id>`, StatusBadge(intento.status), gates_passed/gates_total
//   - mission/checklist context (F-DA-12): project, mission title, checklist item,
//     session id, started/completed dates
//   - IntentoCard: per-gate states (gate_name, state, mandatory, duration_ms,
//     message) + Progress
//   - gate logs on demand: clicking a gate fetches
//     `/api/intentos/{id}/gate/{name}/logs` (via useApi, null URL while the dialog
//     is closed) and renders the transition timeline (from_state → to_state,
//     reason, created_at) inside a NesDialog (S7).
//
// Breadcrumbs resolve from the URL hierarchy (F-DA-15): the island receives the
// four path segments as props from the static shell, or resolves them from
// window.location.pathname at runtime when served from a fallback shell
// (post-build intentos). The chain is
// Dashboard (auto-prepended) → project → Misión #<id> → Ítem #<id> →
// Intento #<id> (current, clickeable — refreshes the live view, F-DA-08).
//
// Edge states: loading / error with retry (S9) / 404 not-found (S8) / empty gates
// / empty logs — all render without crashing (NF-DA-06).

import React, { useEffect, useState } from 'react';
import useApi from '../../hooks/useApi';
import Breadcrumbs from '../Breadcrumbs';
import { List } from 'nes-react';
import StatusBadge from '../StatusBadge';
import IntentoCard from '../IntentoCard';
import { NesDialog } from '../ui';

// Fallback param resolution when the static shell has no props (post-build
// fallback shells served for intentos created after the build).
function paramsFromPathname() {
  if (typeof window === 'undefined') return null;
  const m = window.location.pathname.match(/^\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)\/?$/);
  if (!m) return null;
  return {
    project: decodeURIComponent(m[1]),
    missionId: decodeURIComponent(m[2]),
    itemId: decodeURIComponent(m[3]),
    id: decodeURIComponent(m[4]),
  };
}

function dateLabel(value) {
  return value ? String(value).replace('T', ' ').split('.')[0] : '—';
}

export default function IntentoDetail({ id: idProp, project: projectProp, missionId: missionIdProp, itemId: itemIdProp }) {
  const resolved = {
    id: idProp != null ? String(idProp) : null,
    project: projectProp != null ? String(projectProp) : null,
    missionId: missionIdProp != null ? String(missionIdProp) : null,
    itemId: itemIdProp != null ? String(itemIdProp) : null,
  };
  if (!resolved.id || !resolved.project || !resolved.missionId || !resolved.itemId) {
    const fromPath = paramsFromPathname();
    if (fromPath) {
      resolved.id = resolved.id || fromPath.id;
      resolved.project = resolved.project || fromPath.project;
      resolved.missionId = resolved.missionId || fromPath.missionId;
      resolved.itemId = resolved.itemId || fromPath.itemId;
    }
  }

  const { id, project, missionId: mId, itemId: iId } = resolved;
  const current = id ? `Intento #${id}` : 'Intento';
  const currentHref =
    project && mId && iId && id
      ? `/${encodeURIComponent(project)}/${encodeURIComponent(mId)}/${encodeURIComponent(iId)}/${encodeURIComponent(id)}/`
      : '';
  const url = id ? `/api/intentos/${encodeURIComponent(id)}` : null;
  const { data, loading, error, retry } = useApi(url);

  useEffect(() => {
    if (id) document.title = `Intento ${id} · Ultratimonel`;
  }, [id]);

  const [logGate, setLogGate] = useState(null);
  const logUrl = logGate && id
    ? `/api/intentos/${encodeURIComponent(id)}/gate/${encodeURIComponent(logGate.gate_name)}/logs`
    : null;
  const logsApi = useApi(logUrl);
  const logs = logsApi.data && Array.isArray(logsApi.data.logs) ? logsApi.data.logs : [];

  if (!id) {
    return (
      <section className="stack">
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Intento sin identificador.</p>
        </div>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          <p className="nes-text">Cargando intento…</p>
        </div>
      </section>
    );
  }

  if (error) {
    const notFound = error.status === 404;
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          {notFound ? (
            <>
              <p className="title">Intento no encontrado</p>
              <p className="nes-text is-disabled">
                El intento solicitado no existe (HTTP 404).
              </p>
              <div className="row">
                <a className="nes-btn" href="/">
                  Ir al Dashboard
                </a>
              </div>
            </>
          ) : (
            <>
              <p className="title">Error</p>
              <p className="nes-text is-error">{error.message}</p>
              <div className="row">
                <button type="button" className="nes-btn" onClick={retry}>
                  Reintentar
                </button>
              </div>
            </>
          )}
        </div>
      </section>
    );
  }

  const intento = data && data.intento ? data.intento : null;
  if (!intento) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Intento sin datos.</p>
        </div>
      </section>
    );
  }

  const mission = intento.mission || null;
  const item = intento.checklist_item || null;
  const apiProject = (mission && mission.project) || intento.project || project || '';
  const projectSegment = project || apiProject;
  const missionSegment = mId || (mission && mission.id != null ? String(mission.id) : null);
  const itemSegment = iId || (item && item.id != null ? String(item.id) : null);
  const missionHref =
    missionSegment && projectSegment
      ? `/${encodeURIComponent(projectSegment)}/${encodeURIComponent(missionSegment)}/`
      : null;
  const itemHref =
    missionHref && itemSegment
      ? `${missionHref}${encodeURIComponent(itemSegment)}/`
      : null;

  const crumbs = [];
  if (projectSegment) {
    crumbs.push({ label: projectSegment, href: `/${encodeURIComponent(projectSegment)}/` });
  }
  if (mission && missionHref) {
    crumbs.push({ label: `Misión #${mission.id}`, href: missionHref });
  }
  if (item && itemHref) {
    crumbs.push({ label: `Ítem #${item.id}`, href: itemHref });
  }

  const total = intento.gates_total || 0;
  const passed = Math.min(intento.gates_passed || 0, total || 0);

  return (
    <section className="stack">
      <Breadcrumbs crumbs={crumbs} current={current} currentHref={currentHref} />

      <div className="nes-container is-rounded">
        <div className="row">
          <h2 className="nes-text is-primary">{current}</h2>
          <StatusBadge status={intento.status} />
        </div>
        <p className="nes-text is-disabled">{passed}/{total} gates</p>

        {(projectSegment || mission || item) ? (
          <List>
            {projectSegment ? <li>Proyecto: {projectSegment}</li> : null}
            {mission && missionHref ? (
              <li>
                Misión:{' '}
                <a className="nes-text is-primary" href={missionHref}>
                  {mission.title || `Misión #${mission.id}`}
                </a>
              </li>
            ) : null}
            {item && item.text ? <li>Item: {item.text}</li> : null}
            <li>Sesión: {intento.session_id || '—'}</li>
            <li>Inicio: {dateLabel(intento.started_at)}</li>
            <li>Fin: {dateLabel(intento.completed_at)}</li>
          </List>
        ) : null}
      </div>

      <IntentoCard intento={intento} onViewLogs={(gate) => setLogGate(gate)} />

      {logGate && (
        <NesDialog title={`Gate ${logGate.gate_name}`} open onClose={() => setLogGate(null)}>
          <p className="nes-text is-disabled">
            {current} · Timeline de transiciones
          </p>
          {logsApi.loading ? (
            <p className="nes-text">Cargando logs…</p>
          ) : logsApi.error ? (
            <div className="stack stack--sm">
              <p className="nes-text is-error">{logsApi.error.message}</p>
              <div className="row">
                <button type="button" className="nes-btn" onClick={logsApi.retry}>
                  Reintentar
                </button>
              </div>
            </div>
          ) : logs.length === 0 ? (
            <p className="nes-text is-disabled">Sin registros de transiciones.</p>
          ) : (
            <List>
              {logs.map((log) => (
                <li key={log.id} className="row">
                  <StatusBadge status={log.from_state} gate />
                  <span aria-hidden="true">→</span>
                  <StatusBadge status={log.to_state} gate />
                  <span className="nes-text">{log.reason || '—'}</span>
                  <span className="nes-text is-disabled">
                    {(log.created_at || '').replace('T', ' ').split('.')[0]}
                  </span>
                </li>
              ))}
            </List>
          )}
        </NesDialog>
      )}
    </section>
  );
}

// IntentoDetail — intento view island (T9, F-DA-12, F-DA-15, S6/S7/S8/S9).
//
// Fetches `/api/intentos/{id}` via the shared useApi hook and renders:
//   - header: `Intento #<id>`, StatusBadge(intento.status), gates_passed/gates_total
//   - mission/checklist context (F-DA-12): project, mission title, checklist item,
//     session id
//   - IntentoCard: per-gate states (gate_name, state, mandatory, duration_ms,
//     message) + Progress
//   - gate logs on demand: clicking a gate fetches
//     `/api/intentos/{id}/gate/{name}/logs` (via useApi, null URL while the dialog
//     is closed) and renders the transition timeline (from_state → to_state,
//     reason, created_at) inside a NesDialog (S7).
//
// Breadcrumbs resolve parents from API data (F-DA-15): `intento.mission` gives
// Dashboard (auto-prepended) → project link → mission title link → `Intento #<id>`
// current (S6).
//
// Edge states: loading / error with retry (S9) / 404 not-found (S8) / empty gates
// / empty logs — all render without crashing (NF-DA-06).

import React, { useState } from 'react';
import useApi from '../../hooks/useApi';
import Breadcrumbs from '../Breadcrumbs';
import { List } from 'nes-react';
import StatusBadge from '../StatusBadge';
import IntentoCard from '../IntentoCard';
import { NesDialog } from '../ui';

export default function IntentoDetail({ id }) {
  const url = `/api/intentos/${encodeURIComponent(id)}`;
  const { data, loading, error, retry } = useApi(url);

  const [logGate, setLogGate] = useState(null);
  const logUrl = logGate
    ? `/api/intentos/${encodeURIComponent(id)}/gate/${encodeURIComponent(logGate.gate_name)}/logs`
    : null;
  const logsApi = useApi(logUrl);
  const logs = logsApi.data && Array.isArray(logsApi.data.logs) ? logsApi.data.logs : [];

  const current = `Intento #${id}`;

  if (loading) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} />
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
        <Breadcrumbs current={current} />
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
        <Breadcrumbs current={current} />
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Intento sin datos.</p>
        </div>
      </section>
    );
  }

  const mission = intento.mission || null;
  const item = intento.checklist_item || null;
  const project = (mission && mission.project) || '';
  const missionHref = mission && mission.id != null ? `/misiones/${mission.id}/` : null;

  const crumbs = [];
  if (project) {
    crumbs.push({ label: project, href: `/proyectos/${encodeURIComponent(project)}/` });
  }
  if (mission && missionHref) {
    crumbs.push({ label: mission.title || `Misión ${mission.id}`, href: missionHref });
  }

  const total = intento.gates_total || 0;
  const passed = Math.min(intento.gates_passed || 0, total || 0);

  return (
    <section className="stack">
      <Breadcrumbs crumbs={crumbs} current={current} />

      <div className="nes-container is-rounded">
        <div className="row">
          <h2 className="nes-text is-primary">{current}</h2>
          <StatusBadge status={intento.status} />
        </div>
        <p className="nes-text is-disabled">{passed}/{total} gates</p>

        {(project || mission || item) ? (
          <List>
            {project ? <li>Proyecto: {project}</li> : null}
            {mission && missionHref ? (
              <li>
                Misión:{' '}
                <a className="nes-text is-primary" href={missionHref}>
                  {mission.title || `Misión ${mission.id}`}
                </a>
              </li>
            ) : null}
            {item && item.text ? <li>Item: {item.text}</li> : null}
            <li>Sesión: {intento.session_id || '—'}</li>
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

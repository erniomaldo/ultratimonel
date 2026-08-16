// MissionDetail — mission view island (T8, F-DA-11, F-DA-15, S4/S5/S8/S9).
//
// Fetches `/api/missions/{id}` via the shared useApi hook and renders the
// mission header (title, status, progress) plus a ChecklistCard per checklist
// item (embedded intentos link to `/intentos/{id}/`, S6).
//
// Breadcrumbs resolve parents from API data (F-DA-15): `mission.project` gives
// Dashboard → project link → mission title (current).
//
// Edge states: loading / error with retry (S9) / 404 not-found (S8) / empty
// checklist "Sin checklist" (S5) — all render without crashing (NF-DA-06).

import React from 'react';
import useApi from '../../hooks/useApi';
import Breadcrumbs from '../Breadcrumbs';
import { NesBadge } from '../ui';
import ChecklistCard from '../ChecklistCard';

// Status → label/tone mirror of the legacy dashboard STATUS_LABEL/STATUS_CLASS
// (ultratimonel/dashboard/app.js). T9 centralizes this in StatusBadge.
const STATUS_META = {
  pendiente: { label: 'PENDIENTE', tone: 'warning' },
  en_progreso: { label: 'EN PROGRESO', tone: 'success' },
  completada: { label: 'COMPLETADA', tone: 'success' },
  bloqueada: { label: 'BLOQUEADA', tone: 'error' },
  running: { label: 'EJECUTANDO', tone: 'warning' },
  success: { label: 'EXITO', tone: 'success' },
  fail: { label: 'FALLIDO', tone: 'error' },
};

function statusMeta(status) {
  return STATUS_META[status] || { label: status || 'SIN ESTADO', tone: 'default' };
}

export default function MissionDetail({ id }) {
  const url = `/api/missions/${encodeURIComponent(id)}`;
  const { data, loading, error, retry } = useApi(url);

  if (loading) {
    return (
      <section className="stack">
        <Breadcrumbs current="Misión" />
        <div className="nes-container is-rounded">
          <p className="nes-text">Cargando misión…</p>
        </div>
      </section>
    );
  }

  if (error) {
    const notFound = error.status === 404;
    return (
      <section className="stack">
        <Breadcrumbs current="Misión" />
        <div className="nes-container is-rounded">
          {notFound ? (
            <>
              <p className="title">Misión no encontrada</p>
              <p className="nes-text is-disabled">
                La misión solicitada no existe (HTTP 404).
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

  const mission = data && data.mission ? data.mission : null;
  if (!mission) {
    return (
      <section className="stack">
        <Breadcrumbs current="Misión" />
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Misión sin datos.</p>
        </div>
      </section>
    );
  }

  const meta = statusMeta(mission.status);
  const total = mission.checklist_total || 0;
  const done = Math.min(mission.checklist_done || 0, total || 0);
  const checklist = Array.isArray(mission.checklist) ? mission.checklist : [];
  const project = mission.project || '';
  const projectHref = `/proyectos/${encodeURIComponent(project)}/`;
  const crumbs = project
    ? [{ label: project, href: projectHref }]
    : [];

  return (
    <section className="stack">
      <Breadcrumbs crumbs={crumbs} current={mission.title || `Misión ${id}`} />
      <div className="nes-container is-rounded">
        <div className="row">
          <h2 className="nes-text is-primary">{mission.title || 'Sin título'}</h2>
          <NesBadge text={meta.label} tone={meta.tone} />
        </div>
        <p className="nes-text is-disabled">
          {done}/{total} items · {checklist.length} en checklist
        </p>
        {mission.description ? <p className="nes-text">{mission.description}</p> : null}
      </div>

      {checklist.length === 0 ? (
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Sin checklist.</p>
        </div>
      ) : (
        checklist.map((item) => (
          <ChecklistCard key={item.id} item={item} />
        ))
      )}
    </section>
  );
}

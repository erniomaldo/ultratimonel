// MissionDetail — mission view island (T8, F-DA-11, F-DA-15, S4/S5/S8/S9;
// Ejecución 8: hierarchical routes — lives at /{proyectoName}/{misionId}/,
// REEMPLAZA /misiones/[id]/).
//
// Fetches `/api/missions/{id}` via the shared useApi hook and renders the
// mission header (title, status, progress) plus a ChecklistCard per checklist
// item. Each item links to the item route `/{project}/{missionId}/{item.id}/`
// (the intentos of that item live there — new hierarchy level).
//
// Breadcrumbs resolve from the path (the path IS the hierarchy, Ejecución 8):
// Dashboard (auto-prepended) → {project} → `Misión #<id>` (current, clickeable
// — refresca la vista, F-DA-08 post-corte pattern).
//
// Post-corte id resolution (card #154, adapted to hierarchical routes): props
// come from getStaticPaths for ids enumerated at build time; for ids created
// after the build the Python server serves the generic fallback shell without
// props, so the island reads project + mission id from
// window.location.pathname at runtime. It also fixes <title> on mount so the
// tab matches the actual id.
//
// Edge states: loading / error with retry (S9) / 404 not-found (S8) / empty
// checklist "Sin checklist" (S5) — all render without crashing (NF-DA-06).

import React, { useEffect } from 'react';
import useApi from '../../hooks/useApi';
import Breadcrumbs from '../Breadcrumbs';
import StatusBadge from '../StatusBadge';
import ChecklistCard from '../ChecklistCard';

// Fallback param resolution when the static shell has no props (post-corte
// fallback shells served for ids created after the build): /{project}/{missionId}/
function paramsFromPathname() {
  if (typeof window === 'undefined') return null;
  const m = window.location.pathname.match(/^\/([^/]+)\/([^/]+)\/?$/);
  if (!m) return null;
  return { project: decodeURIComponent(m[1]), id: decodeURIComponent(m[2]) };
}

export default function MissionDetail({ project, id }) {
  const resolved = {
    project: project != null ? String(project) : null,
    id: id != null ? String(id) : null,
  };
  if (!resolved.project || !resolved.id) {
    const fromPath = paramsFromPathname();
    if (fromPath) {
      resolved.project = resolved.project || fromPath.project;
      resolved.id = resolved.id || fromPath.id;
    }
  }

  const { project: projectSlug, id: missionId } = resolved;
  const current = missionId ? `Misión #${missionId}` : 'Misión';
  const currentHref = projectSlug && missionId
    ? `/${encodeURIComponent(projectSlug)}/${encodeURIComponent(missionId)}/`
    : '';
  const url = missionId ? `/api/missions/${encodeURIComponent(missionId)}` : null;
  const { data, loading, error, retry } = useApi(url);

  useEffect(() => {
    if (missionId) document.title = `Misión ${missionId} · Ultratimonel`;
  }, [missionId]);

  if (loading) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
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
        <Breadcrumbs current={current} currentHref={currentHref} />
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
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Misión sin datos.</p>
        </div>
      </section>
    );
  }

  const total = mission.checklist_total || 0;
  const done = Math.min(mission.checklist_done || 0, total || 0);
  const checklist = Array.isArray(mission.checklist) ? mission.checklist : [];
  // Prefer the URL project segment (path IS the hierarchy); fallback to API.
  const projectSlugFinal = projectSlug || mission.project || '';
  const projectHref = `/${encodeURIComponent(projectSlugFinal)}/`;
  const crumbs = projectSlugFinal ? [{ label: projectSlugFinal, href: projectHref }] : [];

  return (
    <section className="stack">
      <Breadcrumbs crumbs={crumbs} current={current} currentHref={currentHref} />
      <div className="nes-container is-rounded">
        <div className="row">
          <h2 className="nes-text is-primary">{mission.title || 'Sin título'}</h2>
          <StatusBadge status={mission.status} />
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
          <ChecklistCard key={item.id} item={item} project={projectSlugFinal} missionId={mission.id} />
        ))
      )}
    </section>
  );
}

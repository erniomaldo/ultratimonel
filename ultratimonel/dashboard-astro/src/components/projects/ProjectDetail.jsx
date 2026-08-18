// ProjectDetail — project view island (T7, F-DA-10, S3/S9; Ejecución 8:
// hierarchical routes — lives at /{proyectoName}/, REEMPLAZA /proyectos/[project]/).
//
// Fetches `/api/projects/{project}/missions` via the shared useApi hook and
// renders a MissionCard per mission with checklist progress. Handles loading /
// error (retry) / empty states without crashing (NF-DA-06). Each card
// navigates to `/{project}/{mission.id}/` (S4, new hierarchy).
//
// Breadcrumb: Dashboard › {project} (current, clickeable — refresca la vista).
//
// Fallback id resolution (post-build): the static shell may carry no props (the
// Python server serves the generic `fallback/proyecto/index.html` shell for
// projects created after the build), so the island reads the project slug from
// window.location.pathname at runtime and fixes <title> on mount.

import React, { useEffect } from 'react';
import useApi from '../../hooks/useApi';
import Breadcrumbs from '../Breadcrumbs';
import MissionCard from '../MissionCard';

function projectFromPathname() {
  if (typeof window === 'undefined') return null;
  const m = window.location.pathname.match(/^\/([^/]+)\/?$/);
  return m ? decodeURIComponent(m[1]) : null;
}

export default function ProjectDetail({ project }) {
  const resolvedProject = project != null ? String(project) : projectFromPathname();
  const current = resolvedProject || 'Proyecto';
  const currentHref = resolvedProject ? `/${encodeURIComponent(resolvedProject)}/` : '';
  const url = resolvedProject
    ? `/api/projects/${encodeURIComponent(resolvedProject)}/missions`
    : null;
  const { data, loading, error, retry } = useApi(url);

  useEffect(() => {
    if (resolvedProject) document.title = `${resolvedProject} · Ultratimonel`;
  }, [resolvedProject]);

  if (loading) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          <p className="nes-text">Cargando misiones…</p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          <p className="title">Error</p>
          <p className="nes-text is-error">{error.message}</p>
          <div className="row">
            <button type="button" className="nes-btn" onClick={retry}>
              Reintentar
            </button>
          </div>
        </div>
      </section>
    );
  }

  const missions = data && Array.isArray(data.missions) ? data.missions : [];

  if (missions.length === 0) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">
            Sin misiones sincronizadas para este proyecto.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="stack">
      <Breadcrumbs current={current} currentHref={currentHref} />
      <div className="row">
        <h2 className="nes-text is-primary">{resolvedProject}</h2>
        <span className="nes-text is-disabled">({missions.length})</span>
      </div>
      {missions.map((mission) => (
        <MissionCard key={mission.id} mission={mission} project={resolvedProject} />
      ))}
    </section>
  );
}

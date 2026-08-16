// ProjectsIndex — index view island (T6, F-DA-09, S1/S9).
//
// Fetches `/api/projects` via the shared useApi hook and renders a ProjectCard
// per project. Handles loading / error (retry) / empty states without crashing
// (NF-DA-06). Each card navigates to `/{project}/` (S2, Ejecución 8: the
// project route is now the top-level hierarchical route).

import React from 'react';
import useApi from '../../hooks/useApi';
import ProjectCard from '../ProjectCard';

export default function ProjectsIndex() {
  const { data, loading, error, retry } = useApi('/api/projects');

  if (loading) {
    return (
      <section className="stack">
        <div className="nes-container is-rounded">
          <p className="nes-text">Cargando proyectos…</p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="stack">
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

  const projects = data && Array.isArray(data.projects) ? data.projects : [];

  if (projects.length === 0) {
    return (
      <section className="stack">
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Sin proyectos configurados.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="stack">
      <div className="row">
        <h2 className="nes-text is-primary">Proyectos</h2>
        <span className="nes-text is-disabled">({projects.length})</span>
      </div>
      {projects.map((project) => (
        <ProjectCard key={project.project} project={project} />
      ))}
    </section>
  );
}

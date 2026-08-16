// ProjectDetail — project view island (T7, F-DA-10, S3/S9).
//
// Fetches `/api/projects/{project}/missions` via the shared useApi hook and
// renders a MissionCard per mission with checklist progress. Handles loading /
// error (retry) / empty states without crashing (NF-DA-06). Each card
// navigates to `/misiones/{id}/` (S4).

import React from 'react';
import useApi from '../../hooks/useApi';
import MissionCard from '../MissionCard';

export default function ProjectDetail({ project }) {
  const url = `/api/projects/${encodeURIComponent(project)}/missions`;
  const { data, loading, error, retry } = useApi(url);

  if (loading) {
    return (
      <section className="stack">
        <div className="nes-container is-rounded">
          <p className="nes-text">Cargando misiones…</p>
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

  const missions = data && Array.isArray(data.missions) ? data.missions : [];

  if (missions.length === 0) {
    return (
      <section className="stack">
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
      <div className="row">
        <h2 className="nes-text is-primary">{project}</h2>
        <span className="nes-text is-disabled">({missions.length})</span>
      </div>
      {missions.map((mission) => (
        <MissionCard key={mission.id} mission={mission} />
      ))}
    </section>
  );
}

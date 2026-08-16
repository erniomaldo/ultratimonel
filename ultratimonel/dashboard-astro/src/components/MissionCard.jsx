// MissionCard — card for a single mission in the project view (T7, F-DA-10, S3/S4;
// Ejecución 8: hierarchical routes — navigates to /{project}/{mission.id}/).
//
// Renders the mission title as a link, its status badge, a NES Progress bar with
// checklist progress (checklist_done / checklist_total) and a `.nes-btn` action
// to the real mission route (S4).
//
// Uses only nes-react primitives + `.nes-*` classes from the bundle — zero
// design CSS, zero inline styles (F-DA-02, NF-DA-05, ADR-6).

import React from 'react';
import { Container, Icon, List, Progress } from 'nes-react';
import StatusBadge from './StatusBadge';

export default function MissionCard({ mission, project }) {
  // project prop comes from ProjectDetail; mission.project is the API fallback.
  const projectSlug = project || mission.project;
  const href = `/${encodeURIComponent(projectSlug)}/${mission.id}/`;
  const total = mission.checklist_total || 0;
  const done = Math.min(mission.checklist_done || 0, total || 0);
  const date = (mission.last_sync || mission.created_at || '').split('T')[0] || '—';

  return (
    <Container
      title={
        <a className="nes-text is-primary" href={href}>
          {mission.title || 'Sin título'}
        </a>
      }
      rounded
    >
      <div className="row">
        <StatusBadge status={mission.status} />
      </div>
      {mission.description ? (
        <p className="nes-text">{mission.description}</p>
      ) : null}
      <Progress value={done} max={total || 1} success={total > 0 && done >= total} />
      <List>
        <li>
          <Icon icon="star" small /> {done}/{total} items
        </li>
        <li>Última sincronización: {date}</li>
      </List>
      <div className="row">
        <a className="nes-btn" href={href}>
          Ver misión
        </a>
      </div>
    </Container>
  );
}

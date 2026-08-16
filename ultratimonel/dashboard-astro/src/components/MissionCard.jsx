// MissionCard — card for a single mission in the project view (T7, F-DA-10, S3/S4).
//
// Renders the mission title as a link, its status badge, a NES Progress bar with
// checklist progress (checklist_done / checklist_total) and a `.nes-btn` action
// to the real mission route `/misiones/{id}/` (S4).
//
// Uses only nes-react primitives + `.nes-*` classes from the bundle — zero
// design CSS, zero inline styles (F-DA-02, NF-DA-05, ADR-6).

import React from 'react';
import { Container, Icon, List, Progress } from 'nes-react';
import { NesBadge } from './ui';

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

export default function MissionCard({ mission }) {
  const href = `/misiones/${mission.id}/`;
  const meta = statusMeta(mission.status);
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
        <NesBadge text={meta.label} tone={meta.tone} />
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

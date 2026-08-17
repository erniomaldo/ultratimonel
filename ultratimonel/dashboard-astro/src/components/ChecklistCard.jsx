// ChecklistCard — checklist item with embedded intentos (T8, F-DA-11, S5/S6;
// Ejecución 8: hierarchical routes — intentos link to
// /{project}/{missionId}/{item.id}/, the new item level).
//
// Renders one checklist item from `/api/missions/{id}` → `mission.checklist[]`:
// a NES Checkbox reflecting `done`, the item text, and the embedded `intentos`
// list (id, status, gates_passed/gates_total). Each intento links to the item
// route (the view of intentos for this item), and a `.nes-btn` offers the same
// navigation (S6, new hierarchy).
//
// Uses only nes-react primitives + `.nes-*` classes from the bundle — zero
// design CSS, zero inline styles (F-DA-02, NF-DA-05, ADR-6).

import React from 'react';
import { Checkbox, Icon, List } from 'nes-react';
import StatusBadge from './StatusBadge';

export default function ChecklistCard({ item, project, missionId }) {
  const intentos = Array.isArray(item.intentos) ? item.intentos : [];
  const itemHref =
    project && missionId != null
      ? `/${encodeURIComponent(project)}/${encodeURIComponent(missionId)}/${item.id}/`
      : null;

  return (
    <div className="nes-container is-rounded stack">
      <div className="row">
        <Checkbox checked={Boolean(item.done)} onSelect={() => {}} label="" />
        <span className="nes-text">{item.text || '—'}</span>
        {itemHref ? (
          <a className="nes-btn is-small" href={itemHref}>
            Ver intentos
          </a>
        ) : null}
      </div>

      {intentos.length === 0 ? (
        <p className="nes-text is-disabled">Sin intentos registrados.</p>
      ) : (
        <List>
          {intentos.map((intento) => (
            <li key={intento.id} className="row">
              <Icon icon="trophy" small />
              {itemHref ? (
                <a className="nes-text is-primary" href={itemHref}>
                  Intento #{intento.id}
                </a>
              ) : (
                <span className="nes-text">Intento #{intento.id}</span>
              )}
              <StatusBadge status={intento.status} />
              <span className="nes-text is-disabled">
                {intento.gates_passed || 0}/{intento.gates_total || 0} gates
              </span>
            </li>
          ))}
        </List>
      )}
    </div>
  );
}

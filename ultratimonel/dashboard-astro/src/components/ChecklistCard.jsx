// ChecklistCard — checklist item with embedded intentos (T8, F-DA-11, S5/S6).
//
// Renders one checklist item from `/api/missions/{id}` → `mission.checklist[]`:
// a NES Checkbox reflecting `done`, the item text, and the embedded `intentos`
// list (id, status, gates_passed/gates_total). Each intento links to the real
// intento route `/intentos/{id}/` (S6).
//
// Uses only nes-react primitives + `.nes-*` classes from the bundle — zero
// design CSS, zero inline styles (F-DA-02, NF-DA-05, ADR-6).

import React from 'react';
import { Checkbox, Icon, List } from 'nes-react';
import StatusBadge from './StatusBadge';

export default function ChecklistCard({ item }) {
  const intentos = Array.isArray(item.intentos) ? item.intentos : [];

  return (
    <div className="nes-container is-rounded stack">
      <div className="row">
        <Checkbox checked={Boolean(item.done)} onSelect={() => {}} label="" />
        <span className="nes-text">{item.text || '—'}</span>
      </div>

      {intentos.length === 0 ? (
        <p className="nes-text is-disabled">Sin intentos registrados.</p>
      ) : (
        <List>
          {intentos.map((intento) => {
            const href = `/intentos/${intento.id}/`;
            return (
              <li key={intento.id} className="row">
                <Icon icon="trophy" small />
                <a className="nes-text is-primary" href={href}>
                  Intento #{intento.id}
                </a>
                <StatusBadge status={intento.status} />
                <span className="nes-text is-disabled">
                  {intento.gates_passed || 0}/{intento.gates_total || 0} gates
                </span>
              </li>
            );
          })}
        </List>
      )}
    </div>
  );
}

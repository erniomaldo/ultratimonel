// IntentoCard — gate table + progress for the intento view (T9, F-DA-12, S7).
//
// Renders the gates of an intento as a NES Table (gate_name, StatusBadge state,
// mandatory flag, duration_ms, message) and a Progress bar for gates_passed /
// gates_total. A `.nes-btn` per gate requests its transition timeline via
// `onViewLogs(gate)` — the island owns the dialog and the fetch (F-DA-12), this
// card stays presentational.
//
// Uses only nes-react primitives + `.nes-*` classes from the bundle — zero
// design CSS, zero inline styles (F-DA-02, NF-DA-05, ADR-6).

import React from 'react';
import { Progress, Table } from 'nes-react';
import StatusBadge from './StatusBadge';

function durationLabel(ms) {
  return ms ? `${ms}ms` : '—';
}

function mandatoryLabel(mandatory) {
  return mandatory ? 'SÍ' : 'NO';
}

export default function IntentoCard({ intento, onViewLogs }) {
  const gates = Array.isArray(intento.gates) ? intento.gates : [];
  const total = intento.gates_total || 0;
  const passed = Math.min(intento.gates_passed || 0, total || 0);

  return (
    <div className="nes-container is-rounded stack">
      <div className="row">
        <h3 className="nes-text is-primary">Gates</h3>
        <span className="nes-text is-disabled">
          {passed}/{total} gates
        </span>
      </div>
      <Progress value={passed} max={total || 1} success={total > 0 && passed >= total} />

      {gates.length === 0 ? (
        <p className="nes-text is-disabled">Sin datos de gates.</p>
      ) : (
        <Table bordered>
          <thead>
            <tr>
              <th>Gate</th>
              <th>Estado</th>
              <th>Obligatorio</th>
              <th>Duración</th>
              <th>Mensaje</th>
              <th>Logs</th>
            </tr>
          </thead>
          <tbody>
            {gates.map((gate) => (
              <tr key={gate.gate_name}>
                <td className="nes-text">{gate.gate_name}</td>
                <td>
                  <StatusBadge status={gate.state} gate />
                </td>
                <td className="nes-text">{mandatoryLabel(gate.mandatory)}</td>
                <td className="nes-text">{durationLabel(gate.duration_ms)}</td>
                <td className="nes-text">{gate.message || '—'}</td>
                <td>
                  <button
                    type="button"
                    className="nes-btn is-small"
                    onClick={() => onViewLogs(gate)}
                  >
                    Ver logs
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}

// StatusBadge — centralized status mapping for intentos, missions and gates (T9, F-DA-12, S7).
//
// Replaces the duplicated STATUS_META maps that lived in MissionCard, ChecklistCard
// and MissionDetail (they mirrored STATUS_LABEL/STATUS_CLASS + GATE_CLASS from the
// legacy ultratimonel/dashboard/app.js).
//
// Props:
//   status: intento/mission status (running, success, fail, pendiente, en_progreso,
//           completada, bloqueada) OR a gate state (PASS, WARN, BLOCK, SKIP, PENDING).
//   gate:   when true, map using the gate-state table (PASS → success, WARN → warning,
//           BLOCK → error, SKIP/PENDING → disabled).
//
// Renders a NesBadge with the semantic label/tone. `statusMeta` / `gateMeta` are also
// exported for callers that only need label/tone without rendering a badge.
//
// Uses only `.nes-*` classes through NesBadge — zero design CSS, zero inline styles
// (NF-DA-05, ADR-6).

import React from 'react';
import { NesBadge } from './ui';

export const STATUS_META = {
  pendiente: { label: 'PENDIENTE', tone: 'warning' },
  en_progreso: { label: 'EN PROGRESO', tone: 'success' },
  completada: { label: 'COMPLETADA', tone: 'success' },
  bloqueada: { label: 'BLOQUEADA', tone: 'error' },
  running: { label: 'EJECUTANDO', tone: 'warning' },
  success: { label: 'EXITO', tone: 'success' },
  fail: { label: 'FALLIDO', tone: 'error' },
};

export const GATE_STATE_META = {
  PASS: { label: 'PASS', tone: 'success' },
  WARN: { label: 'WARN', tone: 'warning' },
  BLOCK: { label: 'BLOCK', tone: 'error' },
  SKIP: { label: 'SKIP', tone: 'disabled' },
  PENDING: { label: 'PENDING', tone: 'disabled' },
};

export function statusMeta(status) {
  return STATUS_META[status] || { label: status || 'SIN ESTADO', tone: 'default' };
}

export function gateMeta(state) {
  return GATE_STATE_META[state] || { label: state || '—', tone: 'default' };
}

export default function StatusBadge({ status, gate = false }) {
  const meta = gate ? gateMeta(status) : statusMeta(status);
  return <NesBadge text={meta.label} tone={meta.tone} />;
}

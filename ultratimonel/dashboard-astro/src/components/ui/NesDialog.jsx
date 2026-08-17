// NesDialog — internal UI wrapper for the NES.css `.nes-dialog` pattern (T4, F-DA-03, ADR-6).
//
// Used by the intento view to render the gate-log timeline overlay on demand.
// Composes only `.nes-*` classes from the bundle — zero design CSS (ADR-6).
//
// Props:
// - `title`: optional dialog heading.
// - `open`: when false the dialog is not rendered.
// - `onClose`: optional callback for the dialog "Cerrar" action.
// - `className`: extra `.nes-*` classes only (is-rounded, is-dark, ...).

import React from 'react';

export default function NesDialog({
  title,
  open = false,
  onClose,
  children,
  className = '',
  ...rest
}) {
  if (!open) return null;

  const classes = ['nes-dialog'];
  if (className) classes.push(className);

  return (
    <div className={classes.join(' ')} role="dialog" aria-modal="true" {...rest}>
      {title && (
        <div className="nes-dialog__header">
          <p className="title">{title}</p>
        </div>
      )}
      <div className="nes-dialog__body">{children}</div>
      {onClose && (
        <div className="nes-dialog__footer">
          <button type="button" className="nes-btn" onClick={onClose}>
            Cerrar
          </button>
        </div>
      )}
    </div>
  );
}

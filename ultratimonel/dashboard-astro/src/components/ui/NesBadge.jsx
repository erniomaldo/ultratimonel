// NesBadge — internal UI wrapper for the NES.css `.nes-badge` pattern (T4, F-DA-03, ADR-6).
//
// nes-react does not provide a Badge component, so this layer composes the
// NES.css markup directly using only `.nes-*` classes from the bundle — zero
// design CSS, zero inline styles (ADR-6).
//
// Supported props:
// - `text`: main badge text.
// - `splited`: renders the `.is-splited` variant (two halves).
// - `right`: right-hand text for the splited variant (optional).
// - `tone`: semantic color modifier on the text part: one of
//   'default' | 'primary' | 'success' | 'warning' | 'error' | 'disabled'.
// - `className`: extra `.nes-*` classes only (is-dark, is-rounded, ...).

import React from 'react';

const TONE_CLASS = {
  default: '',
  primary: 'is-primary',
  success: 'is-success',
  warning: 'is-warning',
  error: 'is-error',
  disabled: 'is-disabled',
};

export default function NesBadge({
  text,
  splited = false,
  right,
  tone = 'default',
  className = '',
  ...rest
}) {
  const toneClass = TONE_CLASS[tone] || TONE_CLASS.default;
  const classes = ['nes-badge'];
  if (splited) classes.push('is-splited');
  if (className) classes.push(className);

  return (
    <span className={classes.join(' ')} {...rest}>
      <span className="is-dark">{text}</span>
      {right !== undefined && <span className={`nes-text ${toneClass}`}>{right}</span>}
    </span>
  );
}

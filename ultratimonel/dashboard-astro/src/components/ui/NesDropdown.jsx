// NesDropdown — internal UI wrapper for the NES.css select pattern (T4, F-DA-03, ADR-6).
//
// Verified: nes.css v2.2.1 has no `.nes-dropdown` class; the select-style
// dropdown is `.nes-select`. This wrapper composes the `.nes-select` markup
// with only `.nes-*` classes from the bundle — zero design CSS (ADR-6).

import React from 'react';

export default function NesDropdown({
  label,
  options = [],
  value,
  onChange,
  placeholder,
  className = '',
  ...rest
}) {
  return (
    <label className={['nes-select', className].filter(Boolean).join(' ')}>
      <select value={value} onChange={onChange} {...rest}>
        {placeholder !== undefined && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((opt) => (
          <option key={opt.value ?? opt} value={opt.value ?? opt}>
            {opt.label ?? opt}
          </option>
        ))}
      </select>
      {label && <span className="nes-text is-disabled">{label}</span>}
    </label>
  );
}

// Breadcrumbs — navigable chain Dashboard → Proyecto → Misión → Intento (T5, F-DA-08, F-DA-15).
//
// Props:
//   crumbs:  array of parent levels, each { label, href } — rendered as real
//            `<a href>` links to the route of that level (F-DA-08).
//   current: label of the current level — rendered as plain (non-link) text.
//
// F-DA-08 enforcement: the chain always starts at `Dashboard` → `/`. When the
// island did not include it and the current level is not Dashboard itself, the
// component prepends it automatically (fix: legacy had no Dashboard level).
//
// No fetch inside — parent resolution happens in the island from API data
// (F-DA-15), keeping this component framework-agnostic.
//
// Styling uses only `.nes-*` classes from the bundle plus the structural `.row`
// helper from layout.css (NF-DA-05, ADR-6).

import React from 'react';

export default function Breadcrumbs({ crumbs = [], current = '' }) {
  const chain =
    current === 'Dashboard'
      ? []
      : crumbs.length > 0 && crumbs[0].label === 'Dashboard'
        ? crumbs
        : [{ label: 'Dashboard', href: '/' }, ...crumbs];

  const items = [
    ...chain.map((crumb, index) => ({
      key: `crumb-${index}-${crumb.label}`,
      type: 'link',
      label: crumb.label,
      href: crumb.href,
    })),
    ...(current
      ? [
          {
            key: 'crumb-current',
            type: 'current',
            label: current,
          },
        ]
      : []),
  ];

  return (
    <nav className="row" aria-label="Ruta de navegación">
      {items.map((item, index) => (
        <React.Fragment key={item.key}>
          {index > 0 && (
            <span className="nes-text is-disabled" aria-hidden="true">
              ›
            </span>
          )}
          {item.type === 'link' ? (
            <a className="nes-btn" href={item.href}>
              {item.label}
            </a>
          ) : (
            <span className="nes-text">{item.label}</span>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}

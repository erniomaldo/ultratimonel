// ProjectCard — index card for a single project (T6, F-DA-09, S1/S2).
//
// Renders the project name as the Container title, mission/completed counts in
// a NES List with icons, and a `.nes-btn` action to the real project route
// `/proyectos/{project}/` (S2). Both the title link and the button navigate.
//
// Uses only nes-react primitives + `.nes-*` classes from the bundle — zero
// design CSS, zero inline styles (F-DA-02, NF-DA-05, ADR-6).

import React from 'react';
import { Container, Icon, List } from 'nes-react';

export default function ProjectCard({ project }) {
  const href = `/proyectos/${encodeURIComponent(project.project)}/`;
  const missionCount = project.mission_count || 0;
  const completedCount = project.completed_count || 0;

  return (
    <Container
      title={
        <a className="nes-text is-primary" href={href}>
          {project.project}
        </a>
      }
      rounded
    >
      <List>
        <li>
          <Icon icon="star" small /> {missionCount} {missionCount === 1 ? 'misión' : 'misiones'}
        </li>
        <li>
          <Icon icon="trophy" small /> {completedCount}{' '}
          {completedCount === 1 ? 'completada' : 'completadas'}
        </li>
      </List>
      <div className="row">
        <a className="nes-btn" href={href}>
          Ver proyectos
        </a>
      </div>
    </Container>
  );
}

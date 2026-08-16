// ItemDetail — checklist item view island: intentos of an item (Ejecución 8,
// hierarchical routes, card #154). NUEVO nivel:
// /{proyectoName}/{misionId}/{checklistItemId}/ → intentos del item del checklist.
//
// The path IS the hierarchy: Dashboard › {proyectoName} › Misión #{misionId} ›
// Ítem #{checklistItemId} (current, clickeable — refresca la vista, F-DA-08).
//
// Fetches `/api/checklist/{item_id}/intentos` via the shared useApi hook and
// renders one card per intento: estado (StatusBadge), gates (passed/total +
// Progress), fecha (started_at/completed_at). "Ver detalle y logs" is now a
// LINK to the intento's own page — the fifth hierarchical level
// /{proyectoName}/{misionId}/{checklistItemId}/{intentoId}/ (Ejecución 9,
// card #154); the old NesDialog slot is gone. The gate-log timeline (S6/S7)
// lives inside that page. It also fetches `/api/missions/{missionId}` for
// context (mission title, item text) so the header reads naturally.
//
// Fallback id resolution (post-build): the static shell may carry no props (the
// Python server serves the generic `fallback/item/index.html` shell for items
// created after the build), so the island reads project + missionId + itemId
// from window.location.pathname at runtime. It also fixes <title> on mount so
// the tab matches the actual item.
//
// Edge states: loading / error with retry (S9) / 404 not-found (S8) / empty
// intentos — all render without crashing (NF-DA-06).

import React, { useEffect } from 'react';
import useApi from '../../hooks/useApi';
import Breadcrumbs from '../Breadcrumbs';
import StatusBadge from '../StatusBadge';
import { Icon, List, Progress } from 'nes-react';

// Fallback param resolution when the static shell has no props (post-build
// fallback shells served for entities created after the build).
function paramsFromPathname() {
  if (typeof window === 'undefined') return null;
  const m = window.location.pathname.match(/^\/([^/]+)\/([^/]+)\/([^/]+)\/?$/);
  if (!m) return null;
  return {
    project: decodeURIComponent(m[1]),
    missionId: decodeURIComponent(m[2]),
    itemId: decodeURIComponent(m[3]),
  };
}

function dateLabel(value) {
  return value ? String(value).replace('T', ' ').split('.')[0] : '—';
}

export default function ItemDetail({ project: projectProp, missionId: missionIdProp, itemId: itemIdProp }) {
  const resolved = {
    project: projectProp != null ? String(projectProp) : null,
    missionId: missionIdProp != null ? String(missionIdProp) : null,
    itemId: itemIdProp != null ? String(itemIdProp) : null,
  };
  if (!resolved.project || !resolved.missionId || !resolved.itemId) {
    const fromPath = paramsFromPathname();
    if (fromPath) {
      resolved.project = resolved.project || fromPath.project;
      resolved.missionId = resolved.missionId || fromPath.missionId;
      resolved.itemId = resolved.itemId || fromPath.itemId;
    }
  }

  const { project, missionId: mId, itemId: iId } = resolved;
  const current = iId ? `Ítem #${iId}` : 'Ítem';
  const currentHref =
    project && mId && iId
      ? `/${encodeURIComponent(project)}/${encodeURIComponent(mId)}/${encodeURIComponent(iId)}/`
      : '';
  const intentosUrl = iId ? `/api/checklist/${encodeURIComponent(iId)}/intentos` : null;
  const missionUrl = mId ? `/api/missions/${encodeURIComponent(mId)}` : null;
  const intentosApi = useApi(intentosUrl);
  const missionApi = useApi(missionUrl);

  useEffect(() => {
    if (iId) document.title = `Ítem ${iId} · Ultratimonel`;
  }, [iId]);

  if (!iId) {
    return (
      <section className="stack">
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Ítem sin identificador.</p>
        </div>
      </section>
    );
  }

  const loading = intentosApi.loading || missionApi.loading;
  const error = intentosApi.error || missionApi.error;

  if (loading) {
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          <p className="nes-text">Cargando intentos del ítem…</p>
        </div>
      </section>
    );
  }

  if (error) {
    const notFound = error.status === 404;
    return (
      <section className="stack">
        <Breadcrumbs current={current} currentHref={currentHref} />
        <div className="nes-container is-rounded">
          {notFound ? (
            <>
              <p className="title">Ítem no encontrado</p>
              <p className="nes-text is-disabled">
                El ítem solicitado no existe (HTTP 404).
              </p>
              <div className="row">
                <a className="nes-btn" href="/">
                  Ir al Dashboard
                </a>
              </div>
            </>
          ) : (
            <>
              <p className="title">Error</p>
              <p className="nes-text is-error">{error.message}</p>
              <div className="row">
                <button
                  type="button"
                  className="nes-btn"
                  onClick={() => {
                    intentosApi.retry();
                    missionApi.retry();
                  }}
                >
                  Reintentar
                </button>
              </div>
            </>
          )}
        </div>
      </section>
    );
  }

  const intentos = intentosApi.data && Array.isArray(intentosApi.data.intentos)
    ? intentosApi.data.intentos
    : [];
  const mission = missionApi.data && missionApi.data.mission ? missionApi.data.mission : null;
  const itemText = mission && Array.isArray(mission.checklist)
    ? (mission.checklist.find((it) => String(it.id) === String(iId)) || {}).text || null
    : null;

  const crumbs = [];
  if (project) crumbs.push({ label: project, href: `/${encodeURIComponent(project)}/` });
  if (project && mId) {
    crumbs.push({
      label: `Misión #${mId}`,
      href: `/${encodeURIComponent(project)}/${encodeURIComponent(mId)}/`,
    });
  }

  return (
    <section className="stack">
      <Breadcrumbs crumbs={crumbs} current={current} currentHref={currentHref} />

      <div className="nes-container is-rounded">
        <div className="row">
          <h2 className="nes-text is-primary">{current}</h2>
          <span className="nes-text is-disabled">({intentos.length})</span>
        </div>
        {mission && mission.title ? (
          <p className="nes-text is-disabled">{mission.title}</p>
        ) : null}
        {itemText ? <p className="nes-text">{itemText}</p> : null}
      </div>

      {intentos.length === 0 ? (
        <div className="nes-container is-rounded">
          <p className="nes-text is-disabled">Sin intentos registrados para este ítem.</p>
        </div>
      ) : (
        intentos.map((intento) => {
          const total = intento.gates_total || 0;
          const passed = Math.min(intento.gates_passed || 0, total || 0);
          const intentoHref =
            `/${encodeURIComponent(project)}/${encodeURIComponent(mId)}/${encodeURIComponent(iId)}/${encodeURIComponent(intento.id)}/`;
          return (
            <div key={intento.id} className="nes-container is-rounded stack">
              <div className="row">
                <h3 className="nes-text is-primary">Intento #{intento.id}</h3>
                <StatusBadge status={intento.status} />
                <span className="nes-text is-disabled">
                  {passed}/{total} gates
                </span>
              </div>
              <Progress value={passed} max={total || 1} success={total > 0 && passed >= total} />
              <List>
                <li>
                  <Icon icon="star" small /> Inicio: {dateLabel(intento.started_at)}
                </li>
                <li>
                  <Icon icon="trophy" small /> Fin: {dateLabel(intento.completed_at)}
                </li>
                <li>Sesión: {intento.session_id || '—'}</li>
              </List>
              <div className="row">
                <a className="nes-btn" href={intentoHref}>
                  Ver detalle y logs
                </a>
              </div>
            </div>
          );
        })
      )}
    </section>
  );
}

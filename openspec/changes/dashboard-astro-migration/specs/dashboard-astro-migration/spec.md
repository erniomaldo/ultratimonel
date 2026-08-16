# Dashboard Astro Migration — Astro + nes-react Dashboard

> **Capability ID:** `dashboard-astro-migration` · **Updated:** 12 Aug 2026 · **Change:** Card #148

## Purpose

Migrate the current vanilla HTML/JS dashboard (`ultratimonel/dashboard/`) to a new Astro application (`ultratimonel/dashboard-astro/`) using `@astrojs/react` islands and `nes-react` components, with real URL routing and navigable breadcrumbs (Dashboard → Proyecto → Misión → Intento). The legacy dashboard stays untouched on port 3005 while the new app runs on a separate staging port (3006 dev / 3007 build validation) with a same-origin `/api` proxy. After manual validation, a static build is served by the existing Python server on the main port and the legacy files are deprecated. The API contract `/api/*` does not change.

## Requirements

### Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| F-DA-01 | A new Astro application SHALL exist at `ultratimonel/dashboard-astro/` using `@astrojs/react` with `react`/`react-dom` and `nes-react` as UI dependencies. | MUST |
| F-DA-02 | All UI SHALL be composed from the nes-react primitives — `Container`, `Button`, `Radios`, `Checkbox`, `TextInput`, `TextArea`, `Avatar`, `Balloon`, `List`, `Table`, `Progress`, `Icon`, `Sprite`, `ControllerIcon` — wrapped by app-owned components (`ProjectCard`, `MissionCard`, `ChecklistCard`, `IntentoCard`, `StatusBadge`, `Breadcrumbs`). No manual design CSS SHALL be written; a single minimal layout/alignment stylesheet is allowed (see NF-DA-05). | MUST |
| F-DA-03 | The component mapping SHALL be: `Panel` → `Container` (NES.css `with-title` style); `TextField` → `TextInput` (single line) / `TextArea` (multi line). NES.css patterns without a React wrapper (badges, dropdown, dialog) SHALL be implemented by an internal UI layer that composes nes-react primitives with NES.css classes from the bundle, not by new design CSS. | MUST |
| F-DA-04 | The legacy dashboard (`ultratimonel/dashboard/index.html`, `app.js`) SHALL remain untouched and functional on port 3005 (`ULTRATIMONEL_DASHBOARD_PORT`, default 3005) during the whole staging period. | MUST |
| F-DA-05 | The Astro app SHALL run on separate staging ports: `3006` for `astro dev` and `3007` for build validation, both bound to `127.0.0.1`. | MUST |
| F-DA-06 | In dev, `/api/*` requests SHALL be proxied to `http://127.0.0.1:3005` so the browser always sees a single origin (no CORS). | MUST |
| F-DA-07 | The app SHALL expose exactly four real URL routes: `/` (index), `/proyectos/[project]/` (project detail), `/misiones/[id]/` (mission detail), `/intentos/[id]/` (intento detail). Each route SHALL be directly loadable/reloadable (F5 keeps the view). | MUST |
| F-DA-08 | Every page SHALL render navigable breadcrumbs with the full chain: `Dashboard` at `/`, then Proyecto → Misión → Intento as the user descends. Each crumb SHALL be an `<a href>` to the real route of the previous level (the current level is rendered as non-link text). | MUST |
| F-DA-09 | The index route SHALL fetch `/api/projects` and render the project list with mission/completed counts. | MUST |
| F-DA-10 | The project route SHALL fetch `/api/projects/{project}/missions` and render the missions of that project, including checklist progress. | MUST |
| F-DA-11 | The mission route SHALL fetch `/api/missions/{id}` and render the mission detail with its checklist items, per-item status, and the embedded intentos of each item. | MUST |
| F-DA-12 | The intento route SHALL fetch `/api/intentos/{id}` and render the intento state: per-gate states, `gates_passed`/`gates_total` progress, and mission/checklist context. Gate transition logs SHALL be fetchable per gate via `/api/intentos/{id}/gate/{name}/logs` and rendered on demand. | MUST |
| F-DA-13 | The `Press Start 2P` font (required by nes-react) SHALL be included in the layout, self-hosted (woff2 in the app) with a fallback to a system monospace font when offline. | MUST |
| F-DA-14 | Final phase: after staging validation, `astro build` output SHALL be served from the existing Python server (`dashboard_server.py`) on the main port, keeping `/api` untouched; the legacy dashboard files SHALL be deprecated from the served tree. | MUST |
| F-DA-15 | Breadcrumb parent resolution SHALL use API data only: mission page resolves its project from `/api/missions/{id}` (`mission.project`); intento page resolves project and mission from `/api/intentos/{id}` (`intento.mission.project`, `intento.mission.id`). No hardcoded navigation state SHALL be kept in memory. | MUST |

### Non-Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-DA-01 | The backend API contract SHALL NOT change: the six `/api/*` endpoints used today remain the only data source. | MUST |
| NF-DA-02 | The build SHALL be fully static (`output: 'static'`, no SSR, no Node backend in production). | MUST |
| NF-DA-03 | Both the legacy server and the staging servers SHALL bind to `127.0.0.1` only. | MUST |
| NF-DA-04 | UI copy SHALL be in Spanish, consistent with the legacy dashboard and its routes (`proyectos`, `misiones`, `intentos`, `Dashboard` root crumb). | MUST |
| NF-DA-05 | The only custom stylesheet allowed is a layout/alignment stylesheet (spacing, flex, page structure). Visual design (colors, borders, typography, components) SHALL come exclusively from NES.css/nes-react. | MUST |
| NF-DA-06 | Loading, empty, error, and not-found states SHALL render without crashing the page: API unavailable (server down), unknown project/mission/intento id, and empty lists. | MUST |
| NF-DA-07 | Staging validation SHALL be manual/smoke per view against the real API (e2e not available — `openspec/config.yaml` `e2e: false`). The existing pytest suite SHALL remain untouched and green. | MUST |

## Tool Specifications

N/A — this change is frontend-only; the MCP tool schemas and the `/api/*` JSON contract are not modified (NF-DA-01).

## Scenarios

### S1 — Index route lists projects
GIVEN the Astro dev server is running on 3006 and the legacy server on 3005
WHEN the user opens `http://127.0.0.1:3006/`
THEN the index view renders the project list fetched from `/api/projects`
AND each project shows its `mission_count` and `completed_count`
AND the breadcrumb shows `Dashboard` as the current (non-link) crumb
AND refreshing the page renders the same view

### S2 — Navigate from Dashboard to a project
GIVEN the user is on the index route
WHEN the user clicks a project card
THEN the browser navigates to `/proyectos/{project}/`
AND the breadcrumb renders `Dashboard` (link to `/`) → `<project>` (current)
AND clicking `Dashboard` returns to the index route

### S3 — Project route lists missions
GIVEN the user is on `/proyectos/{project}/`
WHEN the page loads
THEN it fetches `/api/projects/{project}/missions`
AND renders the missions with title, status and checklist progress
AND the empty state renders a NES.css-styled "no missions" message (not a crash) when `total` is 0

### S4 — Navigate from project to mission
GIVEN the user is on a project detail page
WHEN the user clicks a mission card
THEN the browser navigates to `/misiones/{id}/`
AND the breadcrumb renders `Dashboard` (link) → `<project>` (link to `/proyectos/{project}/`) → `<mission title>` (current)
AND the project name for the crumb comes from the `/api/missions/{id}` response (`mission.project`)

### S5 — Mission route renders checklist and embedded intentos
GIVEN the user is on `/misiones/{id}/`
WHEN the page loads
THEN it fetches `/api/missions/{id}`
AND renders the mission detail with its checklist items in order
AND renders per-item status and the embedded `intentos` list (id, status, `gates_passed`/`gates_total`)
AND the empty checklist state renders a "Sin checklist" message without crashing

### S6 — Navigate from mission to intento
GIVEN the user is on a mission detail page
WHEN the user clicks an intento of a checklist item
THEN the browser navigates to `/intentos/{id}/`
AND the breadcrumb renders the full chain: `Dashboard` (link) → `<project>` (link) → `<mission title>` (link to `/misiones/{mission_id}/`) → `Intento #<id>` (current)
AND the parent project/mission data comes from the `/api/intentos/{id}` response (`intento.mission`)

### S7 — Intento route renders gate states and progress
GIVEN the user is on `/intentos/{id}/`
WHEN the page loads
THEN it fetches `/api/intentos/{id}`
AND renders the intento header (`Intento #<id>`, status, `gates_passed`/`gates_total`)
AND renders each gate from `gates` with its `state` (badge), `mandatory` flag, `duration_ms` and `message`
AND a progress bar shows `gates_passed` / `gates_total`
AND clicking a gate fetches `/api/intentos/{id}/gate/{name}/logs` and renders the transition timeline

### S8 — Unknown ids render a not-found state
GIVEN a route with an id that does not exist (`/misiones/999999/` or `/intentos/999999/`)
WHEN the page loads and the API returns 404
THEN the view renders a NES.css-styled "not found" message
AND the page does not crash and navigation links remain usable

### S9 — API unavailable renders an error state
GIVEN the legacy server on 3005 is stopped
WHEN any view attempts to fetch `/api/*` and the request fails
THEN the view renders a NES.css-styled error message with a retry action
AND the page shell and breadcrumbs remain visible

### S10 — Dev proxy keeps requests same-origin
GIVEN the Astro dev server on 3006 proxies `/api` to `http://127.0.0.1:3005`
WHEN the browser requests `http://127.0.0.1:3006/api/projects`
THEN the response is served through the proxy without CORS errors in the browser console
AND no request is made directly to port 3005 from the browser

### S11 — Legacy dashboard works unchanged on 3005
GIVEN the legacy server keeps serving on 3005 (`ULTRATIMONEL_DASHBOARD_PORT`)
WHEN the user opens `http://127.0.0.1:3005/`
THEN the legacy dashboard renders and behaves as before the migration
AND no file under `ultratimonel/dashboard/` was modified

### S12 — Final replacement serves the static build from the Python server
GIVEN the staging validation passed and the change enters the final phase
WHEN `astro build` runs and `dashboard_server.py` is pointed at the build output (`dist/`) on the main port
THEN `dist/` is served as the static root
AND `/api/*` keeps working from the same server (single origin, port 3005)
AND the legacy `index.html`/`app.js` are no longer in the served tree

### S13 — No manual design CSS
GIVEN the app source is complete
WHEN the implementation is inspected
THEN the only custom stylesheet is the layout/alignment stylesheet (e.g. `src/styles/layout.css`)
AND all visual components use NES.css classes or nes-react primitives
AND no custom color, border, font, or component-design CSS exists outside the layout file

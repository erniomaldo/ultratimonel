# Dashboard Astro Migration — Astro + nes-react Dashboard

> **Capability ID:** `dashboard-astro-migration` · **Updated:** 16 Aug 2026 · **Change:** Card #148

## Purpose

Migrate the current vanilla HTML/JS dashboard (`ultratimonel/dashboard/`) to a new Astro application (`ultratimonel/dashboard-astro/`) using `@astrojs/react` islands and `nes-react` components, with real URL routing and navigable breadcrumbs (Dashboard → Proyecto → Misión → Ítem → Intento). The legacy dashboard stays untouched on port 3005 while the new app runs on a separate staging port (3006 dev / 3007 build validation) with a same-origin `/api` proxy. After manual validation, a static build is served by the existing Python server on the main port and the legacy files are deprecated. The API contract `/api/*` does not change.

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
| F-DA-07 | The app SHALL expose the real URL hierarchy: `/` (index), `/[proyectoName]/` (project detail), `/[proyectoName]/[misionId]/` (mission detail), `/[proyectoName]/[misionId]/[checklistItemId]/` (checklist item detail), and `/[proyectoName]/[misionId]/[checklistItemId]/[intentoId]/` (intento detail). Each route SHALL be directly loadable/reloadable (F5 keeps the view). The legacy flat routes (`/proyectos/[project]/`, `/misiones/[id]/`, `/intentos/[id]/`) SHALL respond 301 to their hierarchical equivalent (F-DA-18). | MUST |
| F-DA-08 | Every page SHALL render navigable breadcrumbs derived from the URL path (the path IS the hierarchy): `Dashboard` at `/`, then Proyecto → Misión → Ítem → Intento as the user descends. Each non-current crumb SHALL be an `<a href>` to the real route of the previous level; the current level SHALL be rendered as a clickable `<a href>` to its own route (clicking reloads the live view). | MUST |
| F-DA-09 | The index route SHALL fetch `/api/projects` and render the project list with mission/completed counts. | MUST |
| F-DA-10 | The project route `/[proyectoName]/` SHALL fetch `/api/projects/{project}/missions` and render the missions of that project, including checklist progress. | MUST |
| F-DA-11 | The mission route `/[proyectoName]/[misionId]/` SHALL fetch `/api/missions/{id}` and render the mission detail with its checklist items, per-item status, and the embedded intentos of each item. | MUST |
| F-DA-12 | The intento route `/[proyectoName]/[misionId]/[checklistItemId]/[intentoId]/` SHALL fetch `/api/intentos/{id}` and render the intento state: per-gate states, `gates_passed`/`gates_total` progress, and mission/checklist context. Gate transition logs SHALL be fetchable per gate via `/api/intentos/{id}/gate/{name}/logs` and rendered on demand. | MUST |
| F-DA-13 | The `Press Start 2P` font (required by nes-react) SHALL be included in the layout, self-hosted (woff2 in the app) with a fallback to a system monospace font when offline. | MUST |
| F-DA-14 | Final phase: after staging validation, `astro build` output SHALL be served from the existing Python server (`dashboard_server.py`) on the main port, keeping `/api` untouched; the legacy dashboard files SHALL be deprecated from the served tree. | MUST |
| F-DA-15 | Breadcrumb parent resolution SHALL derive from the URL path hierarchy (the path IS the hierarchy: project → mission → item → intento). API data SHALL provide labels and context (mission title, item text, project name). Fallback shells SHALL resolve the path segments from `window.location.pathname` at runtime. No hardcoded navigation state SHALL be kept in memory. | MUST |
| F-DA-16 | The checklist item level `/[proyectoName]/[misionId]/[checklistItemId]/` SHALL be a page of its own that renders the intentos of that item (id, status, `gates_passed`/`gates_total`, dates, session), each linking to its intento route. The intento level `/[proyectoName]/[misionId]/[checklistItemId]/[intentoId]/` SHALL also be a page of its own (F-DA-12). | MUST |
| F-DA-17 | Post-build fallback: when the static shell for a hierarchical route was NOT enumerated at build time (entity created after the build, or shell absent from `dist/`), the Python server SHALL serve the generic fallback shell for that level with HTTP 200 IF the entity exists in the DB and matches the URL hierarchy (same consistency check the API performs). HTTP 404 SHALL be returned only when the entity does not exist. | MUST |
| F-DA-18 | The legacy flat routes SHALL respond HTTP 301 with the exact `Location` header resolved from the DB: `/proyectos/{project}` → `/{project}/` (direct mapping), `/misiones/{id}` → `/{project}/{id}/` (project resolved by DB), `/intentos/{id}` → `/{project}/{mission}/{checklist_item}/{id}/` (resolved by DB). When the entity cannot be resolved, the server SHALL answer HTTP 404 instead of redirecting. | MUST |

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
THEN the browser navigates to `/{project}/`
AND the breadcrumb renders `Dashboard` (link to `/`) → `<project>` (current)
AND clicking `Dashboard` returns to the index route

### S3 — Project route lists missions
GIVEN the user is on `/{proyectoName}/` (e.g. `/ultratimonel/`)
WHEN the page loads
THEN it fetches `/api/projects/{project}/missions`
AND renders the missions with title, status and checklist progress
AND the empty state renders a NES.css-styled "no missions" message (not a crash) when `total` is 0

### S4 — Navigate from project to mission
GIVEN the user is on a project detail page
WHEN the user clicks a mission card
THEN the browser navigates to `/{proyectoName}/{misionId}/`
AND the breadcrumb renders `Dashboard` (link) → `<project>` (link to `/{project}/`) → `Misión #<id>` (current)
AND the mission level is derived from the URL path (`Misión #{misionId}`)

### S5 — Mission route renders checklist and embedded intentos
GIVEN the user is on `/{proyectoName}/{misionId}/`
WHEN the page loads
THEN it fetches `/api/missions/{id}`
AND renders the mission detail with its checklist items in order
AND renders per-item status and each item links to `/{proyectoName}/{misionId}/{checklistItemId}/`
AND the empty checklist state renders a "Sin checklist" message without crashing

### S6 — Navigate from mission through item to intento
GIVEN the user is on a mission detail page
WHEN the user clicks a checklist item
THEN the browser navigates to `/{proyectoName}/{misionId}/{checklistItemId}/` (F-DA-16)
AND that item page renders its intentos (id, status, `gates_passed`/`gates_total`, dates, session)
WHEN the user clicks an intento card on the item page
THEN the browser navigates to `/{proyectoName}/{misionId}/{checklistItemId}/{intentoId}/`
AND the breadcrumb renders the full chain: `Dashboard` (link) → `<project>` (link) → `Misión #<id>` (link) → `Ítem #<id>` (link) → `Intento #<id>` (current)
AND the chain is derived from the URL path (F-DA-15)

### S7 — Intento route renders gate states and progress
GIVEN the user is on `/{proyectoName}/{misionId}/{checklistItemId}/{intentoId}/`
WHEN the page loads
THEN it fetches `/api/intentos/{id}`
AND renders the intento header (`Intento #<id>`, status, `gates_passed`/`gates_total`)
AND renders each gate from `gates` with its `state` (badge), `mandatory` flag, `duration_ms` and `message`
AND a progress bar shows `gates_passed` / `gates_total`
AND clicking a gate fetches `/api/intentos/{id}/gate/{name}/logs` and renders the transition timeline

### S8 — Inexistent entities render a real 404 (no fallback)
GIVEN a hierarchical route whose entity does NOT exist in the DB (e.g. `/ultratimonel/999999/`, `/ultratimonel/1454/999999/`, `/ultratimonel/1454/7226/999999/`)
WHEN the user requests the route
THEN the server answers HTTP 404 (no fallback shell is served; the API would also answer 404)
AND the view renders a NES.css-styled "not found" message without crashing, with usable navigation links
NOTE: the complementary case — entity exists in the DB but has no enumerated shell — is S14.

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

### S14 — Entity exists but has no enumerated shell → 200 with hydrated fallback
GIVEN a hierarchical route whose entity exists in the DB but whose static shell was NOT enumerated at build time (entity created after the build, or shell absent from `dist/`)
WHEN the user requests the route
THEN the Python server serves the generic fallback shell for that level with HTTP 200 (F-DA-17)
AND the island resolves the path segments from `window.location.pathname`, fetches the API data and renders the hydrated view (with `<title>` set on mount)
AND the breadcrumbs render the full chain from the URL path
AND refreshing the page renders the same view

### S15 — Legacy flat routes redirect 301 with a DB-resolved Location
GIVEN a legacy flat URL (`/proyectos/{project}/`, `/misiones/{id}/`, `/intentos/{id}/`)
WHEN the user requests the legacy route
THEN the server answers HTTP 301 with the exact `Location` header: `/{project}/`, `/{project}/{id}/`, or `/{project}/{mission}/{checklist_item}/{id}/` respectively, resolved from the DB (F-DA-18)
AND following the redirect loads the equivalent hierarchical route (HTTP 200)
AND a legacy URL whose entity does NOT exist answers HTTP 404 instead of redirecting

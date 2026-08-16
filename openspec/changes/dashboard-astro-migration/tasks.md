# Tasks: Dashboard Astro Migration (Card #148)

> **Change:** `dashboard-astro-migration` · **Date:** 2026-08-12
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/dashboard-astro-migration/spec.md) · [design.md](./design.md)
> **Branch:** `main` (current working branch; delivery PRs are created per mission at apply time per the M1–M6 partition below)

---

## Review Workload Forecast

| Task | Files changed | Est. lines | Risk |
|------|--------------|------------|------|
| T1 — Scaffold Astro + React + nes-react | 3 (package.json, tsconfig, .gitignore) | ~60 | Low |
| T2 — astro.config.mjs (port 3006, proxy /api) | 1 | ~30 | Medium |
| T3 — BaseLayout + global styles (nes.css, font) | 3 (layout, layout.css, fonts) | ~120 | Low |
| T4 — UI internal layer + useApi hook | 5 (NesBadge, NesDropdown, NesDialog, useApi, ui index) | ~180 | Medium |
| T5 — Breadcrumbs component | 1 | ~80 | Medium |
| T6 — Index view (projects) | 3 (page, ProjectsIndex, ProjectCard) | ~140 | Medium |
| T7 — Project view (missions) | 3 (page, ProjectDetail, MissionCard) | ~150 | Medium |
| T8 — Mission view (checklist) | 3 (page, MissionDetail, ChecklistCard) | ~180 | Medium |
| T9 — Intento view (gates + logs) | 4 (page, IntentoDetail, IntentoCard, StatusBadge) | ~220 | High |
| T10 — Edge states + navigation polish | 3 (error/empty/not-found in islands, useApi retry) | ~90 | Medium |
| T11 — Dual-port validation smoke tests | none (manual checks) | ~0 | Medium |
| T12 — Final replacement (Python serves dist/, deprecate legacy) | 2 (dashboard_server.py, docs) | ~60 | High |
| **Total (this change)** | **~25 new files + 2 modified** | **~1310 lines** | — |

**Forecast: ~1310 changed lines — EXCEEDS the 400-line review budget. Approved partition (Deck cards #155-160): 6 missions / 5 PRs, each PR ≤400 changed lines** (details in "Approved Delivery Partition" below):

| PR | Mission | Tasks | Est. lines | Budget check |
|----|---------|-------|-----------|--------------|
| PR1 | M1 — Fundación | T1–T4 | ~390 | ≤400 ✓ |
| PR2 | M2 — Navegación + Índice | T5–T6 | ~220 | ≤400 ✓ |
| PR3 | M3 — Proyecto + Misión | T7–T8 | ~330 | ≤400 ✓ |
| PR4 | M4 — Intento + hardening | T9–T10 | ~310 | ≤400 ✓ |
| —   | M5 — Validación dual puerto | T11 | ~0 (manual gate) | n/a (no PR) |
| PR5 | M6 — Corte | T12 | ~60 | ≤400 ✓ |

M5 (T11) is a validation gate with **no PR**: it must pass before the M6/PR5 cut. Delivery strategy and chain strategy are decided by the orchestrator per session preflight before apply.

---

## Approved Delivery Partition (M1–M6 / PR1–PR5)

Partition approved in Deck cards #155-160 (this task card: #154). It **supersedes the earlier two-PR split** (old PR1 = T1–T11, PR2 = T12). Each task below indicates its destination mission/PR. Every PR stays ≤400 changed lines; M5 is a gate without PR that blocks the final cut.

| Mission | PR | Tasks | Scope | Done when (mission-level) |
|---------|-----|-------|-------|---------------------------|
| M1 — Fundación | PR1 | T1–T4 | Scaffold Astro app + astro.config (3006/proxy) + BaseLayout/styles/font + UI internal layer/`useApi` | Toolchain resolves; dev server binds `127.0.0.1:3006` and proxies `/api` same-origin (S10); NES.css styles render in the static shell; `useApi` + `.nes-*` UI layer ready; zero design CSS (NF-DA-05) |
| M2 — Navegación + Índice | PR2 | T5–T6 | Breadcrumbs component + index route (`/`) | Breadcrumbs render for all 4 route levels (S1/S2/S4/S6); `/` lists projects with counts and links to project routes |
| M3 — Proyecto + Misión | PR3 | T7–T8 | Project detail (`/proyectos/[project]/`) + mission detail (`/misiones/[id]/`) | Missions list with checklist progress; checklist items + embedded intentos render; crumb parents resolve from API data (F-DA-15) |
| M4 — Intento + hardening | PR4 | T9–T10 | Intento detail (`/intentos/[id]/`) + edge states | Gate states/progress render; gate logs load on demand; S8/S9 edge states render without crashing; F5 keeps every route (no in-memory state) |
| M5 — Validación dual puerto | — (gate) | T11 | Smoke validation dev 3006 + build 3007 | S1–S12 pass on dev and against built `dist/`; legacy dashboard intact on 3005 with empty diff; pytest green. **Blocks M6.** |
| M6 — Corte | PR5 | T12 | Final replacement | `dist/` served on 3005 with `/api` intact (S12); MIME types correct; legacy deprecated from the served tree; README updated; pytest green |

Mission-level done criteria summarize the per-task "Done when" checkboxes below; a mission is done only when every task in it is done.

---

## Dependency Graph

```
[M1 · PR1]  T1 (scaffold) ─────► T2 (config) ────────► T3 (layout) ──► T4 (ui layer + useApi)
[M2 · PR2]  T4 ───────────────────────────────────────────► T5 (Breadcrumbs)
[M2 · PR2]  T3 + T4 ────────────► T6 (index)
[M3 · PR3]  T6 ───► T7 (project) ───► T8 (mission)
[M4 · PR4]  T8 ───► T9 (intento)
[M4 · PR4]  T9 ───► T10 (edge states)
[M5 · gate] T10 ──► T11 (dual-port validation, all views)
[M6 · PR5]  T11 ──► T12 (final replacement)
```

**Recommended sequential order:** T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12

---

## Tasks

### T1 — Scaffold Astro app + React + nes-react (F-DA-01, ADR-1)

**Misión/PR de destino:** M1 · PR1 — Fundación

**Files:** `ultratimonel/dashboard-astro/package.json`, `ultratimonel/dashboard-astro/tsconfig.json`, `.gitignore` (repo root)

**What:** Create the isolated Astro app directory with `@astrojs/react`, React 18, `nes-react`, and `nes.css`. Keep the JS toolchain away from the Python repo root (ADR-1).

**How:**
1. `mkdir ultratimonel/dashboard-astro`
2. `cd ultratimonel/dashboard-astro && npm init -y`
3. `npm install astro @astrojs/react react@^18 react-dom@^18 nes-react nes.css` — add `--legacy-peer-deps` if npm blocks on nes-react peer deps (react ^15/^16)
4. Add scripts: `"dev": "astro dev"`, `"build": "astro build"`, `"preview": "astro preview"`
5. Add `tsconfig.json` with `"jsx": "react-jsx"` (if needed)
6. Extend root `.gitignore`: `ultratimonel/dashboard-astro/node_modules/`, `ultratimonel/dashboard-astro/dist/`
7. `npm run build` with no pages yet (verify toolchain resolves; expected: empty dist or missing-pages warning)

**Done when:**
- [x] `ultratimonel/dashboard-astro/package.json` lists `astro`, `@astrojs/react`, `react@^18`, `react-dom@^18`, `nes-react`, `nes.css`
- [x] Root `.gitignore` covers `node_modules/` and `dist/` of the app
- [x] `npm install` resolves (with `--legacy-peer-deps` if required) and `astro` CLI runs

---

### T2 — astro.config.mjs: port 3006 + proxy /api (F-DA-05, F-DA-06, ADR-2, ADR-4)

**Misión/PR de destino:** M1 · PR1 — Fundación

**Files:** `ultratimonel/dashboard-astro/astro.config.mjs`

**What:** Configure static output, the React integration, the staging dev port 3006 bound to 127.0.0.1, and the `/api` proxy to the legacy server via `vite.server.proxy` (Astro has no `server.proxy` — ADR-4).

**How:**
1. Create `astro.config.mjs`:
   ```js
   import { defineConfig } from 'astro/config';
   import react from '@astrojs/react';

   const apiTarget = `http://127.0.0.1:${process.env.ULTRATIMONEL_DASHBOARD_PORT || '3005'}`;

   export default defineConfig({
     output: 'static',
     integrations: [react()],
     server: { host: '127.0.0.1', port: 3006 },
     vite: {
       server: {
         proxy: { '/api': { target: apiTarget, changeOrigin: true } },
       },
     },
   });
   ```
2. Run `npm run dev` and verify the server binds to `127.0.0.1:3006`
3. Verify proxy: with the legacy server running on 3005, `curl http://127.0.0.1:3006/api/projects` returns JSON

**Done when:**
- [x] Dev server binds `127.0.0.1:3006`
- [x] `curl 127.0.0.1:3006/api/projects` returns the same JSON as `127.0.0.1:3005/api/projects`
- [x] No CORS headers involved (same-origin via proxy — S10)

---

### T3 — BaseLayout + global styles + font (F-DA-13, NF-DA-05, ADR-6)

**Misión/PR de destino:** M1 · PR1 — Fundación

**Files:** `ultratimonel/dashboard-astro/src/layouts/BaseLayout.astro`, `ultratimonel/dashboard-astro/src/styles/layout.css`, `ultratimonel/dashboard-astro/public/fonts/` (woff2 Press Start 2P)

**What:** The layout imports the NES.css bundle globally (so the static shell has styles and the internal UI layer can use `.nes-*` classes), the single layout/alignment stylesheet, and the self-hosted Press Start 2P font with fallback.

**How:**
1. In `BaseLayout.astro` `<head>`: `import 'nes.css/css/nes.min.css';` and `import '../styles/layout.css';`
2. Add `@font-face` for Press Start 2P (woff2 in `public/fonts/`) with `font-family` fallback chain (e.g. `'Press Start 2P', ui-monospace, monospace`)
3. `layout.css`: ONLY structure/layout rules (page shell, flex, spacing). No colors, borders, or component design (NF-DA-05)
4. Body/root classes: apply `nes-*` container classes at layout level where structural (e.g., page background via `.nes-container`)

**Done when:**
- [x] Layout renders with NES.css styles in the static HTML (no JS hydration needed for base styles)
- [x] Font loads from `public/fonts/` (self-hosted) with fallback
- [x] `layout.css` contains no design CSS (grep: no `color:`, `border:`, `background:` except structural)

---

### T4 — UI internal layer + useApi hook (F-DA-03, NF-DA-06, ADR-3, ADR-6)

**Misión/PR de destino:** M1 · PR1 — Fundación

**Files:** `ultratimonel/dashboard-astro/src/hooks/useApi.js`, `ultratimonel/dashboard-astro/src/components/ui/NesBadge.jsx`, `ultratimonel/dashboard-astro/src/components/ui/NesDropdown.jsx`, `ultratimonel/dashboard-astro/src/components/ui/NesDialog.jsx`, `ultratimonel/dashboard-astro/src/components/ui/index.js`

**What:** The shared data hook centralizes loading/error/empty states; the internal UI layer wraps NES.css patterns that nes-react does not provide as React components (badges, dropdown, dialog), using only `.nes-*` classes from the `nes.css` bundle (no custom design CSS).

**How:**
1. `useApi.js`: `useApi(url)` → `{ data, loading, error, retry }`; handles HTTP errors, empty responses, and a `retry` action (S8/S9)
2. `NesBadge.jsx`: wraps `.nes-badge` (supports `.is-splited`, `.is-icon`, semantic colors via props) — used by `StatusBadge`
3. `NesDropdown.jsx`: wraps `.nes-dropdown` (select-style) if a dropdown is needed
4. `NesDialog.jsx`: wraps `.nes-dialog` for the gate-log timeline overlay
5. All components consume NES.css classes only; zero inline styles

**Done when:**
- [x] `useApi` exposes `{ data, loading, error, retry }` and is used by all islands
- [x] UI components use only `.nes-*` classes from the bundle
- [x] No design CSS written in this layer (ADR-6)

---

### T5 — Breadcrumbs component (F-DA-08, F-DA-15)

**Misión/PR de destino:** M2 · PR2 — Navegación + Índice

**Files:** `ultratimonel/dashboard-astro/src/components/Breadcrumbs.jsx`

**What:** Renders the navigable chain Dashboard → Proyecto → Misión → Intento. Each non-current crumb is an `<a href>` to the real route of the previous level; the current level is plain text. Parent data (project/mission) arrives as props from the island that resolved it from the API.

**How:**
1. Props: `{ crumbs: [{ label, href }], current }`
2. Render previous levels as `<a href>` links, current as non-link text
3. First crumb is always `Dashboard` → `/` (fix: legacy had no Dashboard level)
4. Keep the component framework-agnostic (no fetch inside — resolution happens in the island per F-DA-15)

**Done when:**
- [x] Breadcrumb renders for all 4 route levels (S1/S2/S4/S6)
- [x] Every non-current crumb is an `<a>` to the correct real route
- [x] Clicking any crumb navigates and the target route loads correctly

---

### T6 — Index view: project list (F-DA-09)

**Misión/PR de destino:** M2 · PR2 — Navegación + Índice

**Files:** `ultratimonel/dashboard-astro/src/pages/index.astro`, `ultratimonel/dashboard-astro/src/components/projects/ProjectsIndex.jsx`, `ultratimonel/dashboard-astro/src/components/ProjectCard.jsx`

**What:** The `/` route renders the project list from `/api/projects` with mission/completed counts. Breadcrumb: `Dashboard` (current).

**How:**
1. `index.astro`: static shell + `<ProjectsIndex client:load />` + `<Breadcrumbs current="Dashboard" />`
2. `ProjectsIndex.jsx`: `useApi('/api/projects')`; render `ProjectCard` per project; each card links to `/proyectos/{project}/`
3. `ProjectCard.jsx`: `Container` (with-title) + `List`/`Icon`; shows `project`, `mission_count`, `completed_count`
4. Handle `loading` / `error` (retry) / empty project list states (S9)

**Done when:**
- [x] `/` lists projects with counts (S1)
- [x] Clicking a project navigates to `/proyectos/{project}/` (S2)
- [x] Error and empty states render without crashing

---

### T7 — Project view: missions (F-DA-10)

**Misión/PR de destino:** M3 · PR3 — Proyecto + Misión

**Files:** `ultratimonel/dashboard-astro/src/pages/proyectos/[project]/index.astro`, `ultratimonel/dashboard-astro/src/components/projects/ProjectDetail.jsx`, `ultratimonel/dashboard-astro/src/components/MissionCard.jsx`

**What:** The `/proyectos/[project]/` route renders the missions of the project from `/api/projects/{project}/missions` with checklist progress. Breadcrumb: `Dashboard` → `<project>` (current).

**How:**
1. Page reads `Astro.params.project`; shell + `<ProjectDetail client:load project={project} />`
2. `ProjectDetail.jsx`: `useApi('/api/projects/' + project + '/missions')`; render `MissionCard` per mission
3. `MissionCard.jsx`: `Container` + `Progress` showing `checklist_done`/`checklist_total`; links to `/misiones/{id}/`
4. Breadcrumbs: `[{ label: 'Dashboard', href: '/' }]` + current `<project>`
5. Empty state: "no missions" NES-styled message (S3)

**Done when:**
- [x] `/proyectos/{project}/` lists missions with progress (S3)
- [x] Breadcrumb shows Dashboard link + project current (S2)
- [x] Empty and error states render without crashing

---

### T8 — Mission view: checklist + embedded intentos (F-DA-11, F-DA-15)

**Misión/PR de destino:** M3 · PR3 — Proyecto + Misión

**Files:** `ultratimonel/dashboard-astro/src/pages/misiones/[id]/index.astro`, `ultratimonel/dashboard-astro/src/components/missions/MissionDetail.jsx`, `ultratimonel/dashboard-astro/src/components/ChecklistCard.jsx`

**What:** The `/misiones/[id]/` route renders the mission from `/api/missions/{id}`: title, status, checklist items in order, per-item status and embedded intentos. Resolves the breadcrumb parent project from `mission.project`.

**How:**
1. Page reads `Astro.params.id`; shell + `<MissionDetail client:load id={id} />`
2. `MissionDetail.jsx`: `useApi('/api/missions/' + id)`
3. Resolve breadcrumbs: `mission.project` → `Dashboard` (link `/`), project (link `/proyectos/{project}/`), mission title (current)
4. `ChecklistCard.jsx`: renders `mission.checklist[]` with `Table`/`List` + `Checkbox` (done state), `text`, and embedded `intentos` (id, status, `gates_passed`/`gates_total`); each intento links to `/intentos/{id}/`
5. Empty checklist: "Sin checklist" NES-styled message (S5)

**Done when:**
- [x] `/misiones/{id}/` renders mission + checklist items + embedded intentos (S5)
- [x] Breadcrumb shows full Dashboard → project → mission chain with working links (S4)
- [x] Clicking an intento navigates to `/intentos/{id}/` (S6)

---

### T9 — Intento view: gates + progress + logs (F-DA-12)

**Misión/PR de destino:** M4 · PR4 — Intento + hardening

**Files:** `ultratimonel/dashboard-astro/src/pages/intentos/[id]/index.astro`, `ultratimonel/dashboard-astro/src/components/intentos/IntentoDetail.jsx`, `ultratimonel/dashboard-astro/src/components/IntentoCard.jsx`, `ultratimonel/dashboard-astro/src/components/StatusBadge.jsx`

**What:** The `/intentos/[id]/` route renders the intento from `/api/intentos/{id}`: header (`Intento #<id>`, status), per-gate states (`gate_name`, `state`, `mandatory`, `duration_ms`, `message`), progress bar, and on-demand gate transition logs via `/api/intentos/{id}/gate/{name}/logs`.

**How:**
1. Page reads `Astro.params.id`; shell + `<IntentoDetail client:load id={id} />`
2. `IntentoDetail.jsx`: `useApi('/api/intentos/' + id)`
3. Resolve breadcrumbs from `intento.mission`: `Dashboard` → project (link) → mission title (link `/misiones/{mission_id}/`) → `Intento #<id>` (current) (S6)
4. `IntentoCard.jsx`: `Table` of gates with `StatusBadge` (state) + `Progress` (`gates_passed`/`gates_total`)
5. Gate log: clicking a gate fetches `/api/intentos/{id}/gate/{name}/logs` and renders the timeline (from_state → to_state, reason, created_at) in a `NesDialog`/`Balloon`
6. `StatusBadge.jsx`: maps intento/gate states to `NesBadge` variants

**Done when:**
- [ ] `/intentos/{id}/` renders header, gates, progress (S7)
- [ ] Gate logs load on demand and render the transition timeline (S7)
- [ ] Full breadcrumb chain navigable (S6)

---

### T10 — Edge states + navigation polish (NF-DA-06, S8/S9)

**Misión/PR de destino:** M4 · PR4 — Intento + hardening

**Files:** islands (`ProjectsIndex`, `ProjectDetail`, `MissionDetail`, `IntentoDetail`), `useApi.js`

**What:** Guarantee loading/error/not-found/empty states everywhere and verify direct navigation (F5) keeps every route working without in-memory state.

**How:**
1. Not-found: when `/api/missions/{id}` or `/api/intentos/{id}` returns 404, islands render a NES-styled "not found" message with usable nav links (S8)
2. API down: all islands show `useApi` error state with retry (S9)
3. Empty lists: project missions (S3), mission checklist (S5) show styled empty messages
4. Direct-load each route in dev and after build; breadcrumbs must render from API-resolved data (no reliance on prior navigation)

**Done when:**
- [ ] All four edge states render without crashing on every view
- [ ] F5/reload keeps the same view on all four routes
- [ ] No in-memory navigation state required (F-DA-15)

---

### T11 — Dual-port validation: smoke tests per view (F-DA-04, F-DA-05, NF-DA-07, ADR-2)

**Misión/PR de destino:** M5 · gate (sin PR) — Validación dual puerto

**Files:** none (manual checks)

**What:** Validate the new dashboard in staging (dev 3006 and build 3007) while the legacy dashboard keeps working on 3005.

**How:**
1. Dev (3006): open `/`, `/proyectos/{project}/`, `/misiones/{id}/`, `/intentos/{id}/` against the real API via proxy — S1–S9 scenarios
2. Verify no CORS errors in the browser console (S10)
3. Legacy (3005): confirm the old dashboard still works and `git diff ultratimonel/dashboard/` is empty (S11)
4. Build: `npm run build`; serve `dist/` with `dashboard_server.py` (static root `dist/`) on 3007; repeat the smoke scenarios (S1–S9) against the build
5. Run `.venv/bin/pytest tests/ -q --tb=short` — no regressions
6. Record results in apply-progress (per-view checkboxes)

**Done when:**
- [ ] All scenarios S1–S10 pass on dev (3006)
- [ ] All scenarios pass against the built `dist/` on 3007
- [ ] Legacy dashboard works on 3005 and its diff is empty
- [ ] pytest suite green

---

### T12 — Final replacement: Python serves dist/, deprecate legacy (F-DA-14, ADR-5)

**Misión/PR de destino:** M6 · PR5 — Corte

**Files:** `ultratimonel/dashboard_server.py`, docs

**What:** After staging validation, point the existing Python server's static root at the Astro build output on the main port, keeping `/api` intact, and deprecate the legacy dashboard files from the served tree. This is the mechanism already validated on 3007 (T11), so the final phase is a root change, not new serving code.

**How:**
1. Add a static-root override to `dashboard_server.py` (e.g. env `ULTRATIMONEL_DASHBOARD_STATIC_ROOT` or handler constructor param) defaulting to the legacy `DASHBOARD_DIR`
2. `_serve_index()` serves `index.html` from the configured root (works for `dist/` build output)
3. Set the static root to `ultratimonel/dashboard-astro/dist/` on the main port (3005) — `/api/*` handlers untouched
4. Verify MIME types for `.js/.css/.html/.woff2` served correctly from `dist/` (Python 3.13 `mimetypes`)
5. Deprecate legacy: `index.html`/`app.js` leave the served tree (decision: keep files in repo but out of the tree, or remove — record in apply-progress; default keep + docs deprecation notice)
6. Update README: new commands (`cd ultratimonel/dashboard-astro && npm run dev/build`), port summary (3005 production / 3006 dev / 3007 build validation)
7. Repeat smoke scenarios S1–S12 on the main port; `.venv/bin/pytest tests/ -q --tb=short`

**Done when:**
- [ ] `dashboard_server.py` serves `dist/` on 3005 and `/api/*` still works (S12)
- [ ] MIME types correct for JS/CSS/woff2 from `dist/`
- [ ] Legacy files deprecated from the served tree (decision recorded)
- [ ] README documents the new workflow
- [ ] pytest suite green

---

## Execution Order

| Step | Task | Mission/PR | Depends on | Estimated effort |
|------|------|------------|------------|-----------------|
| 1 | T1 — Scaffold Astro app | M1/PR1 | None | ~20 min |
| 2 | T2 — astro.config (port + proxy) | M1/PR1 | T1 | ~15 min |
| 3 | T3 — Layout + styles + font | M1/PR1 | T2 | ~20 min |
| 4 | T4 — UI layer + useApi | M1/PR1 | T3 | ~40 min |
| 5 | T5 — Breadcrumbs | M2/PR2 | T4 | ~20 min |
| 6 | T6 — Index view | M2/PR2 | T3+T4 | ~30 min |
| 7 | T7 — Project view | M3/PR3 | T6 | ~30 min |
| 8 | T8 — Mission view | M3/PR3 | T7 | ~35 min |
| 9 | T9 — Intento view | M4/PR4 | T8 | ~45 min |
| 10 | T10 — Edge states + navigation | M4/PR4 | T6–T9 | ~25 min |
| 11 | T11 — Dual-port validation | M5 (gate, no PR) | T10 | ~30 min |
| 12 | T12 — Final replacement | M6/PR5 | T11 | ~45 min |

**Total estimated: ~355 min (~5.9 h). Delivery per the approved M1–M6 partition (5 PRs ≤400 lines; M5 is a gate without PR that blocks M6).**

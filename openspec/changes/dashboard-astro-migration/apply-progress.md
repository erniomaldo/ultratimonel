# Dashboard Astro Migration — Apply Progress

> **Change:** `dashboard-astro-migration` · **Updated:** 2026-08-15
> **Branch:** `feature_148_m3-proyecto-mision` · **Mission/PR:** M3 — Proyecto + Misión (PR3, card #154) · M1/PR1 y M2/PR2 en secciones previas
> **Inputs:** [tasks.md](./tasks.md) · [design.md](./design.md) · [spec.md](./specs/dashboard-astro-migration/spec.md)

---

## Ejecución 1: M1 — Fundación (T1–T4) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Dispatched state: `nextRecommended: apply`, sin blockers. Legado 3005 corriendo (pid 80794).

### T1 — Scaffold Astro app ✅ (escrito en runs previos, verificado aquí)
- [x] `ultratimonel/dashboard-astro/package.json`: astro ^7.2.2, @astrojs/react ^6.0.2, react/react-dom ^18.3.1, nes-react ^1.0.2, nes.css ^2.2.1, prop-types (peer)
- [x] `tsconfig.json` con `jsx: react-jsx` · `astro.config.mjs` presente
- [x] Root `.gitignore` cubre `ultratimonel/dashboard-astro/node_modules/` y `dist/`
- [x] `npm install` resuelto (node_modules presente) · `astro` CLI corre · `npm run build` OK

### T2 — astro.config.mjs: port 3006 + proxy /api ✅ VERIFICADO
- [x] `server: { host: '127.0.0.1', port: 3006 }` · `output: 'static'` · `integrations: [react()]`
- [x] Proxy `vite.server.proxy['/api'] → http://127.0.0.1:${ULTRATIMONEL_DASHBOARD_PORT || 3005}` (ADR-4)
- Verificación ejecutada (2026-08-15):
  - `npm run dev` → `LISTEN 127.0.0.1:3006` (pid node)
  - `curl 127.0.0.1:3005/api/projects` vs `curl 127.0.0.1:3006/api/projects` → **HTTP 200 ambos, JSON idéntico** (`diff` sin diferencias)
  - Headers 3006: `content-type: application/json; charset=utf-8`, **sin `Access-Control-Allow-Origin`** (S10 same-origin OK)
  - (HEAD request via proxy devuelve 404 del handler Python — esperado: `SimpleHTTPRequestHandler` no implementa HEAD en rutas API custom; el contrato es GET, que pasa)

### T3 — BaseLayout + global styles + font ✅ VERIFICADO
- [x] `src/layouts/BaseLayout.astro`: `import 'nes.css/css/nes.min.css'` + `import '../styles/layout.css'`; `<slot/>`; shell con `.app-shell nes-container is-rounded`
- [x] Fuente self-hosted: `public/fonts/press-start-2p-latin.woff2` (12.5 KB, woff2 latin, descargada de Google Fonts, subset latin suficiente para español) + `@font-face` con fallback `'Press Start 2P'` (F-DA-13)
- [x] `src/styles/layout.css`: SOLO estructura (shell flex, spacing, helpers `.stack`/`.row`/`.spacer`). Verificación: grep `color:|border:|background:` → **sin coincidencias**
- Verificación ejecutada:
  - `npm run build` OK → `dist/index.html` con `<link rel="stylesheet" href="/_astro/index.DM6HkSv8.css">`
  - CSS bundle contiene reglas `.nes-*` (nes-container/nes-btn/nes-badge) + `@font-face{font-family:"Press Start 2P"...src:url(/fonts/press-start-2p-latin.woff2)}`
  - `dist/fonts/press-start-2p-latin.woff2` presente en el build
  - Dev 3006: `/` HTTP 200

### T4 — UI internal layer + useApi hook ✅ VERIFICADO
- [x] `src/hooks/useApi.js`: `useApi(url)` → `{ data, loading, error, retry }`; maneja HTTP errors (`error.status`, 404 incluido), respuestas vacías → `null`, aborta fetch previo, `retry` re-dispara
- [x] `src/components/ui/NesBadge.jsx`: `.nes-badge` con `.is-splited`, `tone` semántico (`is-primary/success/warning/error/disabled`)
- [x] `src/components/ui/NesDropdown.jsx`: envuelve `.nes-select` (verificado: **nes.css v2.2.1 NO tiene `.nes-dropdown`**; el patrón select es `.nes-select` — documentado en el componente)
- [x] `src/components/ui/NesDialog.jsx`: `.nes-dialog` con `open`/`onClose`, usado por el timeline de gate logs en T9
- [x] `src/components/ui/index.js` exporta la capa
- Verificación ejecutada:
  - Página temporal `t4check.astro` + island `_UiCheck.jsx` (importaba useApi + los 3 componentes + hydration `client:load`) → `npm run build` OK, island `_UiCheck.DnJnZXKl.js` generado, `dist/t4check/index.html` con `nes-badge`/`nes-select`/`useApi`
  - Dev 3006: `/t4check/` HTTP 200
  - Archivos temporales ELIMINADOS y `dist/` rebuilded limpio
  - ADR-6: grep inline `style=` en `src/components/ui/` y `src/hooks/` → **sin coincidencias**; uso exclusivo de clases `.nes-*` del bundle

### Limpieza
- Dev server 3006 detenido · `.tmp-dev.log` borrado · Legacy 3005 intacto (`git diff ultratimonel/dashboard/` vacío — verificado por git status: solo `.gitignore` modificado + `dashboard-astro/` untracked)

---

## Ejecución 2: M2 — Navegación + Índice (T5–T6) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Rama: `feature_148_m2-navegacion` (card #154). Este run cerró el ciclo SDD de M2: marcó `tasks.md` y actualizó apply-progress. Sin commits ni PR — el trabajo queda en el working tree (regla de terminación).

### T5 — Breadcrumbs component ✅
- [x] `src/components/Breadcrumbs.jsx`: cadena navegable `Dashboard → Proyecto → Misión → Intento`; props `{ crumbs: [{ label, href }], current }`
- [x] Cada crumb no-current es `<a className="nes-btn" href={...}>` con la ruta real del nivel; el current es texto plano `.nes-text`
- [x] Prepende automáticamente `Dashboard` → `/` cuando el island no lo incluye y current ≠ Dashboard (fix: legacy no tenía nivel Dashboard) — F-DA-08
- [x] Sin fetch interno: la resolución de padres ocurre en el island desde datos API (F-DA-15); componente framework-agnostic
- [x] Solo clases `.nes-*` del bundle + helper estructural `.row` (NF-DA-05, ADR-6); cero inline styles
- Soportado para los 4 niveles (S1/S2/S4/S6) vía crumbs arbitrarios + current

### T6 — Index view: project list ✅
- [x] `src/pages/index.astro`: shell + `<Breadcrumbs current="Dashboard" />` + `<ProjectsIndex client:load />` (reemplaza el placeholder mínimo de T3)
- [x] `src/components/projects/ProjectsIndex.jsx`: `useApi('/api/projects')` → un `ProjectCard` por proyecto; header con count total; estados `loading` / `error`+retry / empty ("Sin proyectos configurados.") sin crash (S9)
- [x] `src/components/ProjectCard.jsx`: `Container` (title link) + `List`/`Icon` mostrando `project`, `mission_count`, `completed_count`; título y botón `.nes-btn` linkean a `/proyectos/{project}/` (S2)
- [x] Smoke verificado en el run de implementación: `/` HTTP 200 y JSON `/api/projects` idéntico vía proxy (mismo contrato que T2)
- [x] ADR-6: grep sin `style=` inline en los componentes nuevos

### Estado del árbol (rama `feature_148_m2-navegacion`)
- Modificado: `src/pages/index.astro`
- Untracked (M2): `src/components/Breadcrumbs.jsx`, `src/components/ProjectCard.jsx`, `src/components/projects/ProjectsIndex.jsx`
- Sin commits ni PR — working tree listo para revisión de PR2

---

## Siguiente fase
- **M3 · PR3** (T7–T8): Project detail (`/proyectos/[project]/`) + Mission detail (`/misiones/[id]/`). Depende de T6 (done).
- Estimar diff M2/PR2 ≤ 400 líneas (dentro de presupuesto D3; ~220 estimadas).

---

## Ejecución 3: M3 — Proyecto + Misión (T7–T8) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Rama: `feature_148_m3-proyecto-mision` (card #154). Este run cerró el ciclo SDD de M3: marcó `tasks.md` y actualizó apply-progress (merge, sin overwrite). Sin commits ni PR — el trabajo queda en el working tree (regla de terminación).

### T7 — Project view: missions ✅ VERIFICADO
- [x] `src/pages/proyectos/[project]/index.astro`: shell + `Breadcrumbs current={project}` (auto-pre-pone Dashboard → `/`, S2) + `<ProjectDetail client:load project={project} />`
- [x] `src/components/projects/ProjectDetail.jsx`: `useApi('/api/projects/{project}/missions')` → `MissionCard` por misión; estados loading / error+retry / empty ("Sin misiones sincronizadas para este proyecto.") sin crash (S3/S9)
- [x] `src/components/MissionCard.jsx`: `Container` (title link) + `NesBadge` estado + `Progress` (`checklist_done`/`checklist_total`, verde al completar) + `List` con items y última sync; botón `.nes-btn` → `/misiones/{id}/` (S4)
- [x] **getStaticPaths (output static):** enumera slugs de proyecto desde la DB SQLite (`node:sqlite`, mismo path que `dashboard_server.py`: `ULTRATIMONEL_DB_PATH` o `~/.hermes/ultratimonel.db`) — genera un shell estático por proyecto en `dist/`; el contenido lo carga la isla en cliente (ADR-3, sin datos congelados)
- Verificación ejecutada:
  - `npm run build` OK → `dist/proyectos/*/index.html` (13 proyectos generados; total build 158 páginas)
  - Dev 3006 + proxy: `/proyectos/ultratimonel/` HTTP 200; `/api/projects/ultratimonel/missions` JSON idéntico vía proxy
  - Smoke headless (chromium, virtual-time-budget): 43 mission cards renderizadas, progress bar `.nes-progress` presente, breadcrumb Dashboard link OK (S2/S3)

### T8 — Mission view: checklist + embedded intentos ✅ VERIFICADO
- [x] `src/pages/misiones/[id]/index.astro`: shell + `<MissionDetail client:load id={id} />` + getStaticPaths desde la DB (`SELECT id FROM missions` → 144 misiones en `dist/`)
- [x] `src/components/missions/MissionDetail.jsx`: `useApi('/api/missions/{id}')`; breadcrumbs resueltos desde `mission.project` (F-DA-15): `Dashboard` (link `/`) → proyecto (link `/proyectos/{project}/`) → título (current) (S4); header con estado + contador items; estados loading / error+retry (S9) / 404 island "Misión no encontrada" con link al Dashboard (S8) / empty checklist "Sin checklist." (S5)
- [x] `src/components/ChecklistCard.jsx`: `Checkbox` (done state) + texto del item + `List` con intentos embebidos (`Intento #<id>`, `NesBadge` estado, `gates_passed/gates_total`) — cada intento linkea a `/intentos/{id}/` (S6)
- Verificación ejecutada:
  - Dev 3006: `/misiones/1/` (checklist 14 items, 1 intento) HTTP 200; `/misiones/26/` (sin checklist) HTTP 200
  - Smoke headless (chromium): misión con items → 59 checkboxes, 1 link a `/intentos/155/`, breadcrumb proyecto `voy-rojo` OK (S4/S5/S6); misión sin checklist → "Sin checklist." (S5 empty); id inexistente → 404 sin crash (S8)
  - `/api/missions/1` contrato: `mission.project`, `mission.checklist[].intentos[].{id,status,gates_passed,gates_total}` — coincide con el consumo de los componentes

### Decisiones de implementación (ADR/Diseño)
- **getStaticPaths (output static):** el diseño (ADR-3: fetch en cliente, shells estáticos) no enumeró explícitamente las rutas dinámicas; con `output: 'static'` Astro las exige. Resolución: enumerar desde la DB SQLite en build-time (`node:sqlite`, experimental pero disponible en Node 22), generando solo el shell — los datos siguen viniendo de `/api/*` en el navegador. Si la DB no está disponible el build no falla (devuelve `[]`; dev 3006 sigue funcionando).
- **Mapa de estados:** STATUS_META local en `MissionCard`/`ChecklistCard`/`MissionDetail` espejando `STATUS_LABEL`/`STATUS_CLASS` del legacy (`app.js`); T9 lo centraliza en `StatusBadge` (según tasks).
- ADR-6 verificado: grep `style=` en los archivos nuevos → sin coincidencias; solo clases `.nes-*` + helpers estructurales de `layout.css`.

### Estado del árbol (rama `feature_148_m3-proyecto-mision`)
- Untracked (M3): `src/pages/proyectos/[project]/index.astro`, `src/pages/misiones/[id]/index.astro`, `src/components/projects/ProjectDetail.jsx`, `src/components/missions/MissionDetail.jsx`, `src/components/MissionCard.jsx`, `src/components/ChecklistCard.jsx`
- Modificado: `openspec/changes/dashboard-astro-migration/tasks.md`, `apply-progress.md`
- Sin commits ni PR — working tree listo para revisión de PR3

### Limpieza
- Dev server 3006 detenido · `.tmp-dev.log` y archivos smoke (`/home/ernesto-personal/Proyectos/ultratimonel/.tmp-*`) eliminados · Legacy 3005 intacto (pid 80794)

---

## Siguiente fase (tras M3)
- **M4 · PR4** (T9–T10): Intento detail (`/intentos/[id]/`) + edge states. Depende de T8 (done).
- **M5 · gate** (T11): validación dual puerto — bloquea M6.
- Estimar diff M3/PR3 ≤ 400 líneas (dentro de presupuesto D3; ~330 estimadas).

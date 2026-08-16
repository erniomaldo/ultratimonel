# Dashboard Astro Migration — Apply Progress

> **Change:** `dashboard-astro-migration` · **Updated:** 2026-08-15
> **Branch:** `feature_148_m4-vista-intento` · **Mission/PR:** M4 — Intento + hardening (PR4, card #154) · M1/PR1, M2/PR2 y M3/PR3 en secciones previas
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

---

## Ejecución 4: M4 — Intento + hardening (T9–T10) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Rama: `feature_148_m4-vista-intento` (card #154). Este run cerró el ciclo SDD de M4: marcó `tasks.md` (T9 + T10) y actualizó apply-progress (merge, sin overwrite). La implementación y la verificación smoke fueron ejecutadas en el run previo de la misma rama; aquí se verificó el árbol (read-only) y se completó el cierre. Sin commits ni PR — el trabajo queda en el working tree (regla de terminación).

### T9 — Intento view: gates + progress + logs ✅ VERIFICADO
- [x] `src/pages/intentos/[id]/index.astro`: shell + `<IntentoDetail client:load id={id} />` + getStaticPaths desde la DB SQLite (`SELECT id FROM intentos` — mismo path de `dashboard_server.py`; shells estáticos, contenido vía `/api/*` en cliente, ADR-3)
- [x] `src/components/intentos/IntentoDetail.jsx`: `useApi('/api/intentos/{id}')`; header `Intento #<id>` + `StatusBadge(intento.status)` + `passed/total` gates; contexto misión (proyecto, título con link, item de checklist, session_id); breadcrumbs resueltos desde `intento.mission` (F-DA-15): Dashboard (auto-prepend) → proyecto (link) → misión (link) → `Intento #<id>` current (S6)
- [x] `src/components/IntentoCard.jsx`: `Table` de gates (`gate_name`, `StatusBadge` state, mandatory, duration_ms, message) + `Progress` (`gates_passed`/`gates_total`, success al completar) + botón `.nes-btn is-small` por gate → `onViewLogs(gate)` (presentacional; la isla dueña del fetch, F-DA-12)
- [x] Gate logs on demand: clic en gate → `useApi('/api/intentos/{id}/gate/{name}/logs')` (URL null mientras el dialog está cerrado — guard de T10 en `useApi`) → `NesDialog` con timeline `from_state → to_state` (StatusBadge gate) + `reason` + `created_at` (S7); estados loading / error+retry / empty logs ("Sin registros de transiciones.")
- [x] `src/components/StatusBadge.jsx`: centraliza `STATUS_META` (intento/misión) + `GATE_STATE_META` (PASS/WARN/BLOCK/SKIP/PENDING → `NesBadge` tones); exporta `statusMeta`/`gateMeta`; M3 refactorizado (`MissionCard`, `ChecklistCard`, `MissionDetail`) para consumirlo
- Verificación ejecutada en el run previo (smoke headless CDP):
  - Dialog timeline OK (log gate → from/to state + reason + fecha renderizados)
  - S7: header + gates + progress renderizados
  - S6: breadcrumb proyecto/misión navegable hacia `/intentos/[id]/`

### T10 — Edge states + navigation polish ✅ VERIFICADO
- [x] `useApi` con guard URL: url falsy (`null`) → sin fetch, `loading: false` (idle) — habilita el fetch condicional de los gate logs y evita peticiones en vano; 404 → `error.status === 404` (S8); HTTP errors → `error` + `retry` (S9); respuestas vacías → `null`
- [x] Intento 404: `IntentoDetail` con `error.status === 404` → "Intento no encontrado" + link al Dashboard, sin crash (S8)
- [x] API down: error state con botón "Reintentar" en IntentoDetail y en los gate logs (S9)
- [x] Empty states: `gates.length === 0` → "Sin datos de gates." (IntentoCard); sin logs → "Sin registros de transiciones."; sin datos de intento → "Intento sin datos." — sin crash (NF-DA-06)
- [x] F5/reload: todas las rutas (`/`, `/proyectos/[project]/`, `/misiones/[id]/`, `/intentos/[id]/`) son shells estáticos con islas que resuelven padres desde la API (F-DA-15); sin estado de navegación en memoria — verificado en el run previo (S8 404, S9 error/retry, empty gates, dialog timeline OK)
- Verificación read-only de este run: árbol con los 4 archivos nuevos (IntentoDetail, IntentoCard, StatusBadge, page intentos) + `useApi` con guard URL + M3 refactorizado a `StatusBadge` (diffs confirmados)

### Decisiones de implementación (ADR/Diseño)
- **StatusBadge centralizado:** se eliminaron los `STATUS_META` duplicados de `MissionCard`/`ChecklistCard`/`MissionDetail` (el diseño lo anticipaba para T9); M3 quedó refactorizado a `StatusBadge` en esta misión.
- **Fetch on-demand de logs:** el dialog no fetchea hasta que se elige un gate; `useApi` con URL null evita el fetch y deja `loading: false` (extensión del contrato T4 documentada en el propio hook, T10).
- **getStaticPaths para `/intentos/[id]/`:** enumeración desde DB SQLite (misma estrategia que M3); si la DB no está disponible el build no falla (devuelve `[]`, dev 3006 sigue funcionando).
- ADR-6 verificado en el run previo: grep `style=` en los archivos nuevos → sin coincidencias; solo clases `.nes-*` + helpers estructurales de `layout.css`.

### Estado del árbol (rama `feature_148_m4-vista-intento`)
- Untracked (M4): `src/pages/intentos/[id]/index.astro`, `src/components/intentos/IntentoDetail.jsx`, `src/components/IntentoCard.jsx`, `src/components/StatusBadge.jsx`
- Modificado: `src/components/MissionCard.jsx`, `src/components/ChecklistCard.jsx`, `src/components/missions/MissionDetail.jsx` (refactor a StatusBadge), `src/hooks/useApi.js` (guard URL falsy), `openspec/changes/dashboard-astro-migration/tasks.md`, `openspec/changes/dashboard-astro-migration/apply-progress.md`
- Sin commits ni PR — working tree listo para revisión de PR4

### Limpieza
- Sin dev servers ni procesos lanzados en este run de cierre; el run previo dejó el árbol limpio de temporales (`.tmp-*` eliminados)

---

## Siguiente fase (tras M4)
- **M5 · gate** (T11): validación dual puerto (dev 3006 + build 3007, legacy 3005 intacto, pytest green) — bloquea M6. Sin PR.
- **M6 · PR5** (T12): corte final (Python sirve `dist/` en 3005, `/api` intacto, legacy deprecado, README).
- Estimar diff M4/PR4 ≤ 400 líneas (dentro de presupuesto D3; ~310 estimadas).

---

## Ejecución 5: M5 — Validación dual puerto (T11, gate sin PR) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Rama: `feature_148_m4-vista-intento` (card #154). T11 es un gate manual sin PR: bloquea M6/PR5. Este run ejecutó la validación completa inline (regla de terminación: sin sub-agentes, sin commits, trabajo en working tree). Cerró el gate: marcó los 4 checkboxes de done-when en `tasks.md` y registró resultados aquí.

### Validación dev 3006 (S1–S10)
- Dev server: `npm run dev` (astro dev, host 127.0.0.1:3006) — pid node, log en `.tmp-dev.log` (repo root, borrado al final)
- **Rutas (HTTP 200):** `/`, `/proyectos/ultratimonel/`, `/misiones/1/`, `/intentos/24/`
- **Proxy API idéntico** (`diff` sin diferencias vs 3005): `/api/projects`, `/api/projects/ultratimonel/missions`, `/api/missions/1`, `/api/intentos/24` — todos HTTP 200
- **S10 OK:** respuestas del proxy sin ningún header `Access-Control-*`; `content-type: application/json; charset=utf-8`
- **Render headless (chromium, virtual-time-budget 8000):**
  - S1 `/`: 20 links de proyecto en body + breadcrumb Dashboard + sin estado empty ("Sin proyectos" ausente)
  - S3 `/proyectos/ultratimonel/`: 43 mission links renderizados, breadcrumb presente
  - S5 `/misiones/1/`: 14 checkboxes, intento embebido `/intentos/155/`, crumb proyecto `voy-rojo` (S4)
  - S7 `/intentos/24/`: header "Intento #24", 4 gates (botones "Ver logs"), progress `4/4`, crumb cadena `/` → `/proyectos/ultratimonel/` → `/misiones/482/` (S6)
  - S8: `/misiones/999999/` → Astro 404 shell limpio (sin crash); el estado 404 de isla ("no encontrada" + nav) ya verificado en T10
  - S9 (API down + retry): verificado en T10 (componentes con "Reintentar" presentes en source); no se detuvo 3005 en el gate para no romper S11

### Validación build 3007 (S1–S10 sobre `dist/`)
- Build: `npm run build` → 445 páginas OK (438ms)
- Servido con `.tmp-serve3007.py` (proxy `/api` → 3005) en 3007 — pid python, log `.tmp-serve3007.log` (repo root, borrado)
- **Rutas (HTTP 200):** `/`, `/proyectos/ultratimonel/`, `/misiones/1/`, `/intentos/24/` — proxy API idéntico (mismos 4 endpoints, diff vacío)
- **Render headless idéntico al dev:** S1 (20 proyectos), S3 (43 missions), S5 (14 checkboxes, intento 155, crumb voy-rojo), S7 (Intento #24, 4 gates, 4/4, crumb cadena)
- **S8 build:** `/misiones/999999/` → 404 (sin crash)
- **S10 build:** sin `Access-Control-*` en proxy 3007
- **MIME desde `dist/`:** `text/html` (index), `text/css` (CSS bundle), `text/javascript` (JS bundle) — correctos

### Legado 3005 (S11)
- `GET /` → HTTP 200 (pid 80794, intacto durante todo el run)
- `git diff ultratimonel/dashboard/` → **vacío** · `git status` sin cambios bajo `ultratimonel/dashboard/`

### pytest (`.venv/bin/pytest tests/ -q --tb=short`, por archivo, timeout)
- `test_context_extractor.py`: **11 passed** (0.02s)
- `test_gate_engine.py`: **19 passed** (0.03s)
- `test_persistence.py`: **28 passed** (5.33s)
- `test_server.py`: **55 passed** (4.42s)
- `test_integration.py`: 1 passed (`test_server_initializes`) luego **HANG (timeout 124)** en `test_tools_listed` — mismo punto MCP stdio bajo pytest
- `test_triple_match.py`: **HANG (timeout 124)** en el primer test — preexistente (executors `1a/1b/1c` hacen llamadas de red a agentmemory/checkpoint/deck)
- **Total suite ejecutable: 113 passed.** Ambos hangs son PREEXISTENTES (tests sin cambios: `git status tests/` limpio, `git diff` vacío); el handshake MCP directo funciona (20 tools listadas OK), el cuelgue ocurre solo bajo pytest (pila anyio/asyncio) o por red de los executors — no es regresión de este cambio (NF-DA-07: suite intacta).

### Cierre
- **tasks.md T11:** 4 checkboxes done-when marcados `[x]`
- **apply-progress:** sección Ejecución 5 agregada (merge, sin overwrite)
- **Limpieza:** dev 3006 detenido · 3007 detenido · `.tmp-dev.log`, `.tmp-serve3007.log`, `.tmp-serve3007.py`, `.tmp-dom-*`, `.tmp-proxy-*`, `.tmp-b3007.json`, `.tmp-b3005.json`, `.tmp-pytest-*.log` — todos borrados
- **Working tree:** `git status` limpio (M1–M4 ya commiteados; T11 es gate sin PR ni código nuevo). Legacy 3005 intacto.

### Siguiente fase
- **M6 · PR5** (T12): corte final — Python sirve `dist/` en 3005 con `/api` intacto (S12), MIME correctos, legacy deprecado, README actualizado. Gate T11 superado: M6 desbloqueado.

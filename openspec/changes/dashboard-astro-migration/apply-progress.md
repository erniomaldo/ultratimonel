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

---

## Ejecución 6: M6 — Corte final (T12, PR5) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Rama: `feature_148_m6-corte` (card #154). Este run ejecutó T12 completo inline (regla de terminación: sin sub-agentes, sin commits, trabajo en working tree). Dispatcher nativo: `apply: ready`, sin blockers. `strict_tdd: false` (no aplica). Marcó los 5 checkboxes de done-when en `tasks.md` y registró resultados aquí (merge, sin overwrite).

### Código — `ultratimonel/dashboard_server.py` (root estático configurable)

- **Override de static root:** `ULTRATIMONEL_DASHBOARD_STATIC_ROOT` (env) + `resolve_static_root(port)`.
  Orden de resolución: (1) env → override explícito; (2) puerto principal `3005` → `ultratimonel/dashboard-astro/dist/` (corte, ADR-5); (3) cualquier otro puerto → legacy `DASHBOARD_DIR`.
  El default del override es el legacy (`dashboard/`) — item 1 del task; el "seteado en el puerto principal" es el default por-puerto (3005 → dist/) — item 3.
- **`_serve_index()`** sirve `index.html` desde `STATIC_ROOT` (funciona con `dist/index.html` del build Astro).
- **`translate_path()`** resuelve estáticos (`/_astro/*`, `/fonts/*`, `/static/*`, rutas de página) desde `STATIC_ROOT`; el resto del routing (`/api/*`, `do_GET`) queda INTACTO.
- **`create_server()`** resuelve `STATIC_ROOT` por puerto y loguea warning si el root no existe (deploy sin build → 404 consciente, no silencioso).
- `run_server()` imprime el root servido (`📂 Static:`).
- Verificación de resolución: `resolve_static_root(3005) → dist`, `(3008) → dashboard`, `(3007) → dashboard`, env → override.

### Decisión de deprecación legacy (item 5, default del task)

**Mantener** `ultratimonel/dashboard/index.html` + `app.js` en el repo, **fuera del árbol servido** (el puerto principal sirve `dist/`; `/app.js` → 404). Nota de deprecación en README.md/README.en.md (sección Dashboard) y en el árbol de arquitectura (`~~DEPRECATED~~`). No se tocó ningún archivo bajo `ultratimonel/dashboard/` (`git diff` de ese dir vacío). Rollback trivial: restaurar root legacy (ADR-5).

### Decisión de corte en el puerto principal (regla de terminación)

El proceso legacy 3005 (pid 80794) **no se reinició** en este run: el cambio de puerto principal queda en código (default por-puerto 3005 → dist/) y queda documentado para que el deploy real lo efectúe (restart del server 3005 con el código nuevo = sirve dist/). La validación del corte se hizo en **3008** con el handler real y el nuevo root (`ULTRATIMONEL_DASHBOARD_STATIC_ROOT=…/dashboard-astro/dist`), el mismo mecanismo que usará producción.

### Smoke S1–S12 (validación 3008 con dist/ + handler real)

- **Rutas 200 + `text/html`:** `/`, `/proyectos/ultratimonel/`, `/misiones/1/`, `/intentos/24/` (S1–S7 shells)
- **MIME desde `dist/` (item 4, Python 3.13 mimetypes):**
  - `/_astro/*.css` → `text/css` ✓
  - `/_astro/*.js` → `text/javascript` ✓
  - `/` (index) → `text/html` ✓
  - `/fonts/press-start-2p-latin.woff2` → `font/woff2` ✓
- **`/api/*` intacto (S12):** `/api/projects`, `/api/projects/ultratimonel/missions`, `/api/missions/1`, `/api/intentos/24` → **JSON idéntico** (diff vacío vs 3005), mismo origen, sin CORS. `/api/missions/999999` → 404.
- **Legacy fuera del árbol servido (S12):** `/app.js` → 404, `/dashboard/app.js` → 404.
- **Render headless (chromium, virtual-time-budget 8000):** `/` nes-btn OK · `/proyectos/ultratimonel/` nes-progress OK · `/misiones/1/` checkbox/empty OK · `/intentos/24/` "Intento #24" OK (mismos marcadores que T11 sobre el mismo `dist/`).
- **Contenido shell:** `index.html` del build (title "Ultratimonel Dashboard", `app-shell`, `_astro/*.js`) — no el fallback "Dashboard UI not found".

### pytest (`.venv/bin/pytest tests/ -q --tb=short`, por archivo, timeout)

- `test_context_extractor.py`: **11 passed** (0.01s)
- `test_gate_engine.py`: **19 passed** (0.03s)
- `test_persistence.py`: **28 passed** (5.22s)
- `test_server.py`: **55 passed** (3.79s)
- `test_integration.py`: 1 passed (`test_server_initializes`) luego **HANG** (timeout) — preexistente, mismo punto MCP stdio bajo pytest que en T11
- `test_triple_match.py`: **HANG** en el primer test (timeout) — preexistente (executors 1a/1b/1c con red a agentmemory/checkpoint/deck)
- **Total suite ejecutable: 113 passed.** Ambos hangs PREEXISTENTES e inalterados (sin cambios en `tests/` en este run; verificado en Ejecución 5). NF-DA-07: suite intacta, sin regresiones.

### Documentación (item 6)

- `README.md` + `README.en.md`: sección Dashboard reescrita — tabla de puertos (3005 producción / 3006 dev / 3007 validación build), comandos `cd ultratimonel/dashboard-astro && npm run dev/build`, root estático por puerto + `ULTRATIMONEL_DASHBOARD_STATIC_ROOT`, nota de deprecación legacy. Fila de features actualizada (Astro + NES.css). Env var agregada a la tabla de configuración. Árbol de arquitectura con `dashboard-astro/` + legacy marcado deprecado.

### Estado del árbol (rama `feature_148_m6-corte`)

- Modificado: `ultratimonel/dashboard_server.py`, `README.md`, `README.en.md`, `openspec/changes/dashboard-astro-migration/tasks.md` (T12 [x]), `apply-progress.md` (este archivo)
- Sin cambios bajo `ultratimonel/dashboard/` · sin commits ni PR — working tree listo para revisión de PR5 (M6)

### Limpieza

- Server de prueba 3008 detenido · `.tmp-t12-3008.log` borrado · sin `.tmp-*` restantes · Legacy 3005 (pid 80794) sigue vivo e intacto (HTTP 200 verificado al cierre)

### Siguiente fase

- **Verify** del cambio completo (`sdd-verify`): dispatcher `verify: ready`; `archive` seguirá `blocked` hasta completar tasks (ya todos done) y pasar verify.

---

## Ejecución 7: Post-corte — Fix 404 shells + breadcrumb actual (card #154) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Rama: `feature_148_m6-corte` (card #154). Fix de 2 bugs reales reportados en producción (3005 ya sirve dist/): `/intentos/296/` y `/intentos/297/` → HTTP 404 (isla ni se montaba) y breadcrumb de `/misiones/1454/` con el TÍTULO largo como nivel actual no navegable. Ejecutado inline (regla de terminación: sin sub-agentes, sin commits, trabajo en working tree). No había task nuevo en `tasks.md` (T1–T12 ya done); este run registra el fix en apply-progress como Ejecución 7.

### Solución elegida para el 404 (opción b + fallback dedicado)

El build sigue siendo `output: 'static'` (ADR-2/ADR-5): `getStaticPaths` no puede enumerar ids creados después del build. Solución: **shell fallback dedicado por tipo + server Python como guardián**:

1. **Astro — id en runtime (opción b):** las islas `MissionDetail.jsx` / `IntentoDetail.jsx` resuelven el id con `prop ?? window.location.pathname` (regex `/\/misiones\/([^/]+)\//`, `/\/intentos\/([^/]+)\//`). Un mismo shell sirve para CUALQUIER id; la isla además fija `document.title` en mount para que el tab coincida con el id real.
2. **Astro — shells fallback dedicados:** `src/pages/intentos/fallback.astro` y `src/pages/misiones/fallback.astro` (isla `client:load` SIN prop `id` → resuelve del pathname). Emiten `dist/intentos/fallback/index.html` y `dist/misiones/fallback/index.html` SIEMPRE, incluso con DB vacía en build (a diferencia de copiar una shell enumerada).
3. **Python — guardián (S8 intacto):** en `do_GET`, para `/intentos/{id}` y `/misiones/{id}` (solo id numérico) con shell faltante en `dist/`:
   - `_entity_exists(table, id)` = misma check que el API (SELECT por id en `missions`/`intentos`) → si el id existe (API habría respondido 200), sirve el fallback shell con 200;
   - si el id NO existe en DB (API → 404, ej. `/misiones/999999/`) → **404 real** (`<h1>Not found</h1>`).
   - Si la shell enumerada existe → `super().do_GET()` normal (los ids del build ni tocan DB).

### Fix breadcrumb

- `Breadcrumbs.jsx`: nueva prop `currentHref` — cuando está seteada, el nivel actual se renderiza como `<a class="nes-btn" href={currentHref}>` (navegable, mismo href que la vista → click = recarga completa, "refresca").
- `/misiones/{id}/`: nivel actual ahora `Misión #1454` (formato `Misión #{id}`, NO el título largo) + `currentHref="/misiones/{id}/"`.
- `/intentos/{id}/`: nivel actual `Intento #{id}` (ya era) + `currentHref="/intentos/{id}/"`. Crumb de misión en el breadcrumb de intento ahora `Misión #{mission.id}` (antes `mission.title`).
- Jerarquía completa: `Dashboard › {proyecto} › Misión #{id} › Intento #{id}`; niveles intermedios (Dashboard, proyecto) navegan normal.

### Evidencia de smokes (build nuevo + server de prueba 3011, handler real)

- `npm run build` (dashboard-astro): **450 pages OK**, incluye `dist/intentos/fallback/index.html` y `dist/misiones/fallback/index.html` (isla con `props="{}"`).
- Servidor: `.venv/bin/python3 ultratimonel/dashboard_server.py 3011` con `ULTRATIMONEL_DASHBOARD_STATIC_ROOT=…/dashboard-astro/dist` (puerto no-3005, producción intacta).
- **HTTP status (curl):** `/intentos/296/` → 200 · `/intentos/297/` → 200 · `/intentos/155/` → 200 · `/intentos/24/` → 200 · `/misiones/1454/` → 200 · `/intentos/fallback/` → 200 · `/misiones/fallback/` → 200 · **`/misiones/999999/` → 404** · `/intentos/999999/` → 404 (S8). API: `/api/intentos/296` → 200, `/api/missions/999999` → 404.
- **Render headless chromium (dump-dom + virtual-time-budget 10000):**
  - `/intentos/296/` (fallback): `<title>Intento 296 · Ultratimonel</title>`; breadcrumb `Dashboard › ultratimonel › Misión #1454 › Intento #296` (3 links navegables); marcadores de contenido (`Intento #296`, `Proyecto: ultratimonel`, `gates`, `Sesión:`) presentes → isla montada e hidratada.
  - `/misiones/1454/` (enumerada): breadcrumb `Dashboard › ultratimonel › Misión #1454` con `href="/misiones/1454/"` (nivel actual = `Misión #1454`, clickeable); título contenido `M6 — Corte…` presente en header (no en breadcrumb).
  - `/intentos/155/` (enumerada): breadcrumb `Dashboard › voy-rojo › Misión #1 › Intento #155` (regresión OK).
  - Prueba dirigida de fallback misión: moviendo temporalmente `dist/misiones/1454/index.html` fuera → `/misiones/1454/` → 200 con shell fallback, isla hidrató (`Misión #1454` breadcrumb + contenido `M6 — Corte`) → restaurado.

### Estado del árbol (rama `feature_148_m6-corte`)

- Modificado: `ultratimonel/dashboard_server.py`, `ultratimonel/dashboard-astro/src/components/Breadcrumbs.jsx`, `ultratimonel/dashboard-astro/src/components/missions/MissionDetail.jsx`, `ultratimonel/dashboard-astro/src/components/intentos/IntentoDetail.jsx`, `apply-progress.md` (este archivo)
- Nuevos: `ultratimonel/dashboard-astro/src/pages/intentos/fallback.astro`, `ultratimonel/dashboard-astro/src/pages/misiones/fallback.astro`
- `tasks.md`: sin cambios (no había task para este fix). Sin commits ni PR — working tree listo.

### Limpieza

- Server de prueba 3011 detenido · `.tmp-dash-test.log`, `.tmp-render-*.html`, `.tmp-fallback-m1454.html`, `.tmp-logs/` borrados · Producción 3005 (pid 2143265) NO reiniciada, intacta (HTTP 200 verificado al cierre).

### Siguiente fase

- **Verify** del cambio completo (`sdd-verify`) cubrirá este fix (S8/404 + shells post-corte) junto con el resto del cambio; luego `archive`.

---

## Ejecución 8: Rutas jerárquicas — reestructuración completa de URLs (card #154) ✅

Preflight: A1 (interactivo) · B3 (openspec + engram) · C2 (un solo PR) · D3=400 líneas.
Rama: `feature_148_m6-corte` (card #154). El usuario aprobó explícitamente (2026-08-15) la estructura de URLs jerárquicas — slugs EXACTOS, sin variaciones — que reemplaza el esquema plano F-DA-15:

- `/` → lista de proyectos (ya existía, se mantiene)
- `/[proyectoName]/` → misiones del proyecto (slug con guiones, ej. `/ultratimonel/`, `/voy-rojo/`). REEMPLAZA `/proyectos/[project]/`
- `/[proyectoName]/[misionId]/` → checklist de la misión. REEMPLAZA `/misiones/[id]/`
- `/[proyectoName]/[misionId]/[checklistItemId]/` → intentos del item del checklist (nivel NUEVO)

Ejecutado inline (regla de terminación: sin sub-agentes, sin commits, trabajo en working tree). No había task nuevo en `tasks.md` (T1–T12 ya done); este run registra la reestructuración como Ejecución 8. **RESTRICCIÓN RESPETADA:** nada leído/ejecutado bajo `~/.hermes` (ni sqlite3 ni project_maps); datos de dominio SOLO vía API del server 3005; el build (getStaticPaths con node:sqlite) resuelve la DB por sí mismo.

### Decisión del usuario (registrada)

Rutas jerárquicas aprobadas 2026-08-15 reemplazan el esquema plano F-DA-15. Nota agregada en `design.md` sección 2.3 (sin reescribir el documento). El path ES la jerarquía: los breadcrumbs se derivan del path (Dashboard › {proyectoName} › Misión #{misionId} › Ítem #{checklistItemId}) con nivel actual como `<a>` clickeable que refresca (patrón `currentHref` de Ejecución 7).

### Código — páginas Astro nuevas (estructura jerárquica)

- **`src/pages/[proyectoName]/index.astro`** (nuevo, REEMPLAZA `proyectos/[project]/`): `getStaticPaths` enumera `SELECT DISTINCT project FROM missions` (node:sqlite en build-time). Shell + isla `<ProjectDetail client:load project={proyectoName} />`.
- **`src/pages/[proyectoName]/[misionId]/index.astro`** (nuevo, REEMPLAZA `misiones/[id]/`): enumera `SELECT id, project FROM missions`. Shell + `<MissionDetail client:load project id />`.
- **`src/pages/[proyectoName]/[misionId]/[checklistItemId]/index.astro`** (NUEVO nivel): enumera `checklist_items JOIN missions` (item_id, mission_id, project). Shell + `<ItemDetail client:load project missionId itemId />`.
- **Fallbacks por tipo (post-build):** `src/pages/fallback/proyecto.astro`, `fallback/mision.astro`, `fallback/item.astro` → emiten SIEMPRE `dist/fallback/{tipo}/index.html` (isla sin props; resuelve los segmentos del pathname en runtime y fija `<title>` en mount). Reemplazan a `intentos/fallback.astro` y `misiones/fallback.astro` (borrados).
- **Borradas las páginas planas:** `proyectos/[project]`, `misiones/[id]` (+ fallback), `intentos/[id]` (+ fallback) — sus rutas ahora redirigen 301.

### Código — componentes (links internos a estructura nueva, cero links viejos)

- **`ItemDetail.jsx` (NUEVO):** vista de intentos por ítem — cards de intentos (estado, gates, progreso, fecha, sesión) con slot al detalle que reutiliza `<IntentoDetail />` dentro de un `NesDialog` (logs on-demand, S6/S7). Breadcrumb completo con `currentHref`.
- **`ProjectDetail.jsx`:** ahora renderiza su propio Breadcrumbs (Dashboard → proyecto actual clickeable) + pasa `project` a `MissionCard`.
- **`MissionDetail.jsx`:** breadcrumb `Dashboard › {project} › Misión #{id}` (actual clickeable con `currentHref`), links de proyecto → `/{project}/`; pasa `project`+`missionId` a `ChecklistCard`.
- **`IntentoDetail.jsx`:** ya no es página; se usa como slot de detalle. Breadcrumbs a rutas nuevas (project → `/{project}/`, misión → `/{project}/{mission.id}/`); nivel actual (Intento) como texto (no tiene ruta propia).
- **`MissionCard.jsx`:** href `/{project}/{mission.id}/` (usa prop `project` o `mission.project`).
- **`ChecklistCard.jsx`:** ítem + botón "Ver intentos" → `/{project}/{missionId}/{item.id}/`; intentos embebidos linkean a la misma ruta del ítem.
- **`ProjectCard.jsx`:** href `/{project.project}/`; botón renombrado "Ver misiones".
- **`Breadcrumbs.jsx`:** comentario actualizado; lógica intacta (currentHref ya soportado).

### Código — `ultratimonel/dashboard_server.py` (redirects 301 + guard fallback jerárquico)

- **`_match_legacy_redirect(path)`:** rutas planas → 301 a la nueva estructura:
  - `/proyectos/{project}` → `/{project}/` (mapeo directo)
  - `/misiones/{id}` → `/{project}/{id}/` (resuelve `project` por DB)
  - `/intentos/{id}` → `/{project}/{mission}/{checklist_item}/` (resuelve por DB)
  - Si la entidad NO se resuelve → **404** (marcador `LEGACY_UNRESOLVED`), no redirect.
- **`_mission_project(id)` / `_intento_location(id)`:** consultas DB para resolver project/mission/item de la ruta destino.
- **`_match_hierarchical_route(path)`:** niveles `proyecto` (1 segmento, sin `.`), `mision` (2, id numérico), `item` (3, ids numéricos). Nonsense → static serving normal → 404 real (S8).
- **`_hierarchical_shell_exists(level, *segments)`:** shell enumerada en `dist/{proyecto}/{mision}/{item}/index.html`.
- **`_entity_exists_hierarchical(level, *segments)`:** guard del fallback — mismo check que el API, con consistencia jerárquica: proyecto existe (project_maps.json o `missions.project`); misión existe Y `project` coincide; ítem existe Y `mission_id` Y `project` coinciden.
- **`_serve_hierarchical_fallback(level, *segments)`:** sirve `dist/fallback/{tipo}/index.html` cuando la entidad existe; si no → 404. El fallback de ítem se sirve aunque la shell no exista en dist.
- `do_GET`: `/api/*` → API; `/` → index; legacy 301; fallback jerárquico; `super().do_GET()`.
- Docstring actualizado (jerarquía + redirects + fallback).

### Evidencia de smokes (build nuevo + server de prueba 3012, handler real)

- `npm run build` (dashboard-astro): **1088 pages OK**, incluye `dist/{proyecto}/`, `dist/{proyecto}/{mision}/`, `dist/{proyecto}/{mision}/{item}/` y `dist/fallback/{proyecto,mision,item}/index.html`. Las rutas planas YA NO existen en dist.
- Servidor: `.venv/bin/python3 ultratimonel/dashboard_server.py 3012` con `ULTRATIMONEL_DASHBOARD_STATIC_ROOT=…/dashboard-astro/dist` (puerto no-3005, producción intacta).
- **HTTP status (curl):** `/` → 200 · `/ultratimonel/` → 200 · `/ultratimonel/1454/` → 200 · `/ultratimonel/1454/7226/` → 200 · `/voy-rojo/` → 200 · `/voy-rojo/1/` → 200 · `/voy-rojo/1/8/` → 200.
- **404 (S8):** `/ultratimonel/999999/` → 404 · `/ultratimonel/1454/999999/` → 404 · `/voy-rojo/1/24/` → 404 (ítem no pertenece a esa misión — jerarquía inconsistente) · `/misiones/999999/` → 404 · `/intentos/999999/` → 404.
- **Redirects 301 verificados (Location exacta):** `/proyectos/ultratimonel/` → `/ultratimonel/` · `/misiones/1454/` → `/ultratimonel/1454/` · `/intentos/296/` → `/ultratimonel/1454/7226/` · `/intentos/155/` → `/voy-rojo/1/8/` · `/intentos/24/` → `/ultratimonel/482/2285/`.
- **Fallback post-build (id real, ítem 7226):** moviendo temporalmente `dist/ultratimonel/1454/7226/` → `/ultratimonel/1454/7226/` → **200** con shell `fallback/item` (title "Ítem · Ultratimonel") → restaurado. Idem misión 1454 (shell movida → 200 fallback misión) y proyecto `/solcrm/` (existe en project_maps sin misiones → 200 fallback proyecto).
- **Render headless chromium (dump-dom + virtual-time-budget 10000):**
  - `/ultratimonel/1454/7226/` (enumerada): `<title>Ítem 7226 · Ultratimonel</title>`; breadcrumb `Dashboard › ultratimonel › Misión #1454 › Ítem #7226` (links a `/ultratimonel/`, `/ultratimonel/1454/`, y nivel actual con href `…/7226/` que refresca); **Intento #296–#299 presentes** con 3 EXITO + 1 EJECUTANDO, progreso, Inicio/Fin/Sesión y botón "Ver detalle y logs".
  - `/ultratimonel/1454/7226/` (fallback, shell movida): mismo resultado hidratado (title + 4 intentos + currentHref) → restaurado.
  - `/ultratimonel/` (proyecto): breadcrumb `Dashboard › ultratimonel` + links de misiones `href="/ultratimonel/{id}/"`.
  - `/ultratimonel/1454/` (misión): link de ítem `href="/ultratimonel/1454/7226/"` + botón "Ver intentos".
- **API intacta (S12):** `/api/projects`, `/api/projects/ultratimonel/missions`, `/api/missions/1454`, `/api/checklist/7226/intentos`, `/api/intentos/299` → 200; `/api/missions/999999` → 404.
- **pytest:** `tests/test_server.py` → **55 passed** (3.76s). Sin cambios en `tests/`; suite intacta (NF-DA-07).

### Estado del árbol (rama `feature_148_m6-corte`)

- Nuevos: `src/pages/[proyectoName]/index.astro`, `src/pages/[proyectoName]/[misionId]/index.astro`, `src/pages/[proyectoName]/[misionId]/[checklistItemId]/index.astro`, `src/pages/fallback/{proyecto,mision,item}.astro`, `src/components/checklist/ItemDetail.jsx`
- Modificados: `ultratimonel/dashboard_server.py`, `src/components/{MissionCard,ChecklistCard,ProjectCard}.jsx`, `src/components/projects/{ProjectDetail,ProjectsIndex}.jsx`, `src/components/missions/MissionDetail.jsx`, `src/components/intentos/IntentoDetail.jsx`, `src/components/Breadcrumbs.jsx` (comentario), `design.md` (nota 2.3), `apply-progress.md` (este archivo)
- Borrados: `src/pages/proyectos/`, `src/pages/misiones/`, `src/pages/intentos/` (incluye fallbacks viejos)
- `tasks.md`: sin cambios. Sin commits ni PR — working tree listo.

### Limpieza

- Server de prueba 3012 detenido · `.tmp-e8-*.log`, `.tmp-e8-*.html`, `.tmp-e8-chromium.err` borrados · Producción 3005 (pid 2143265) NO reiniciada, intacta (HTTP 200 verificado al cierre).

### Siguiente fase

- **Verify** del cambio completo (`sdd-verify`) deberá cubrir la nueva jerarquía (S1–S12 adaptados a rutas jerárquicas + redirects 301 + fallbacks por tipo); luego `archive`.

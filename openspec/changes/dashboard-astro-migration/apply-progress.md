# Dashboard Astro Migration — Apply Progress

> **Change:** `dashboard-astro-migration` · **Updated:** 2026-08-15
> **Branch:** `feature_148_m1-fundacion` · **Mission/PR:** M1 — Fundación (PR1, card #154)
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

## Siguiente fase
- **M2 · PR2** (T5–T6): Breadcrumbs + index view. `index.astro` actual es un placeholder mínimo (T3 shell) que T6 reemplaza con `<ProjectsIndex client:load />`.
- Estimar diff M1/PR1 ≤ 400 líneas (dentro de presupuesto D3).

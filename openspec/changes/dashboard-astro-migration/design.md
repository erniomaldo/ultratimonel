# Design: Dashboard Astro Migration (Card #148)

> **Change:** `dashboard-astro-migration` · **Date:** 2026-08-12 · **Capability:** `dashboard-astro-migration`
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/dashboard-astro-migration/spec.md)

---

## 1. Architecture Decision Records

### ADR-1: Misma repo, subdirectorio aislado `ultratimonel/dashboard-astro/` (no repo separado)

**Contexto:** El proposal deja pendiente la ubicación de la app: `ultratimonel/dashboard-astro/` o `web/` en raíz. También surge la pregunta de si conviene un repo separado. El repo es Python puro (pyproject.toml, requirements.txt, pytest) y este cambio introduce el primer toolchain JS (npm, node_modules, Astro).

**Alternativas consideradas:**
1. Repo separado (`ultratimonel-dashboard`) — versiona el frontend aparte; pero desacopla el contrato `/api` de su consumidor, complica PRs cross-repo, y agrega infraestructura para una app de un dashboard local de ~4 vistas.
2. Raíz del repo (`package.json` en la raíz) — mezcla node_modules/package-lock con el repo Python y contamina el pipeline pytest/CI existente.
3. Subdirectorio aislado `ultratimonel/dashboard-astro/` — el package.json, node_modules, astro.config y `dist/` viven dentro de un solo directorio; el repo Python permanece intacto en la raíz.

**Decisión:** Opción 3. La app Astro vive en `ultratimonel/dashboard-astro/`, espejo de la ubicación legacy `ultratimonel/dashboard/` y junto al módulo que sirve el API (`ultratimonel/dashboard_server.py`). No se toca la raíz del repo ni el pipeline pytest. El `.gitignore` del repo se extiende para excluir `ultratimonel/dashboard-astro/node_modules/` y `ultratimonel/dashboard-astro/dist/`.

**Consecuencias:**
- El toolchain JS queda aislado: `cd ultratimonel/dashboard-astro && npm install`.
- La raíz sigue siendo Python puro; `openspec/config.yaml` (`strict_tdd: false`, pytest) no cambia.
- El contrato de consumo del API se versiona junto al server que lo expone.
- Todo el código del cambio es nuevo en un directorio; el diff legacy queda en cero hasta la fase final (ADR-5).

---

### ADR-2: Puertos staging — dev 3006 + validación del build 3007 (mecanismo Python, no `astro preview`)

**Contexto:** El proposal fija "doble puerto sin romper": legacy 3005 intacto (`DEFAULT_PORT = 3005`, env `ULTRATIMONEL_DASHBOARD_PORT` en `dashboard_server.py`); app Astro en staging 3006/3007. La decisión pendiente era "3006 (dev) y 3007 (preview) o simplificar a uno solo". Verificado en la doc actual de Astro: la opción `server` se usa para `astro dev` y `astro preview` pero solo expone `host`/`port`/`allowedHosts`/`headers` — no hay proxy de preview; el proxy es `vite.server.proxy` y aplica únicamente al dev server.

**Alternativas consideradas:**
1. `astro preview` en 3007 — no proxya `/api` de forma soportada; la vista no tendría datos salvo build con fetch en build-time (rechazada: datos stale e incompatibles con la estrategia de datos de ADR-3).
2. Un script Node de preview con proxy — introduce backend Node de tooling; el proposal exige "sin backend Node/SSR para producción" y preferimos una sola vía de validación.
3. **3007 = servir `dist/` con el mismo handler Python** (`dashboard_server.py` con root estático apuntando a `dist/`) — pre-valida EXACTAMENTE el mecanismo de la fase final (ADR-5), da same-origin `/api` sin CORS, y no agrega tooling Node.

**Decisión:** Mantener dos puertos staging: **3006** (`astro dev`, host `127.0.0.1`, proxy `/api` → 3005, ADR-4) y **3007** como validación del build servido por el handler Python apuntado a `dist/`. `astro preview` queda disponible solo como smoke estático opcional (sin datos); no es el camino canónico de 3007. Config del dev server:

```js
// ultratimonel/dashboard-astro/astro.config.mjs
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

export default defineConfig({
  output: 'static',
  integrations: [react()],
  server: { host: '127.0.0.1', port: 3006 },
  vite: {
    server: {
      proxy: {
        '/api': { target: 'http://127.0.0.1:3005', changeOrigin: true },
      },
    },
  },
});
```

**Consecuencias:**
- El navegador solo ve un origen: `127.0.0.1:3006` (dev) o `127.0.0.1:3007` (build), nunca 3005 directamente (S10).
- La validación en 3007 usa el mismo código de serving que la producción: si funciona en 3007, la fase final es un cambio de raíz estática, no un cambio de mecanismo (mitiga el riesgo MIME/rutas del proposal).
- `astro preview` documentado como utilidad de render estático, no como destino de validación funcional.

---

### ADR-3: Integración `@astrojs/react` + islands `client:load` + fetch de datos en cliente

**Contexto:** El proposal recomienda islands React hidratados con `client:load` y fetch en cliente contra `/api` same-origin; quedaba pendiente confirmar la estrategia de datos. Los datos del dashboard son dinámicos (misiones sincronizadas desde Deck, intentos creados por el server MCP): un fetch en build-time congelaría el contenido en cada `astro build`.

**Alternativas consideradas:**
1. Fetch en build-time (Astro frontmatter `fetch()`) — produce HTML estático completo, pero datos stale hasta el próximo build; inviable para una herramienta operativa.
2. SSR/on-demand (adapter Node) — viola NF-DA-02 ("sin Node backend en producción") y agrega runtime que no existe hoy.
3. **Fetch en cliente dentro de islands `client:load`** — cada vista es un shell estático (ruta + breadcrumb skeleton) y la isla React que renderiza el contenido fetches `/api/*` en el navegador. `output: 'static'`, cero Node en producción.

**Decisión:** Opción 3. Páginas `.astro` estáticas con un island React por vista (`client:load`), fetch en cliente vía un hook compartido `useApi`. React se pincha en `^18.3` (no 19): nes-react declara peer deps `react ^15 || ^16` (paquete de 7 años, class components + prop-types); React 18 conserva compatibilidad con estos patrones con menor riesgo que React 19.

**Consecuencias:**
- El HTML inicial se sirve inmediato; la data llega con hidratación (comportamiento aceptado, equivalente al SPA actual).
- Un solo hook `useApi` centraliza loading/error/empty states (NF-DA-06, S8/S9).
- Resolución de breadcrumbs parents por datos del API (F-DA-15): `/api/missions/{id}` expone `mission.project`; `/api/intentos/{id}` expone `intento.mission.{id,title,project}`.

---

### ADR-4: Proxy `/api` en dev vía `vite.server.proxy` (Astro no expone `server.proxy`)

**Contexto:** El proposal dejaba pendiente "confirmar sintaxis `server.proxy` de Astro (delega a Vite)". Verificado en la referencia de configuración actual de Astro: **no existe `server.proxy`**; la opción `server` solo configura `host`/`port`/`allowedHosts`/`headers`. La configuración Vite se pasa por la opción top-level `vite`, y el proxy de dev server es `vite.server.proxy` (API estándar de Vite).

**Decisión:** Usar `vite.server.proxy` como se muestra en ADR-2: `/api` → `http://127.0.0.1:3005`. El proxy aplica solo a `astro dev` (3006). Para el build (3007) el same-origin lo garantiza el handler Python que sirve `dist/` y `/api` juntos (ADR-2/ADR-5), no un proxy.

**Consecuencias:**
- Documentación correcta desde el inicio: nada de `server.proxy` (inexistente).
- El target del proxy se configura vía env (`ULTRATIMONEL_DASHBOARD_PORT`) para respetar puertos custom del legacy; default `3005`.
- Sin cabeceras CORS en staging: el navegador nunca consulta 3005 directamente (S10, perfil de seguridad del proposal).

---

### ADR-5: Servicio final — `dashboard_server.py` sirve `dist/` como raíz estática; deprecación del legacy

**Contexto:** El proposal recomienda que el build estático sea servido por el server Python existente en el puerto principal, manteniendo `/api`. Queda pendiente "cómo servir el build final (decisión exacta)". El handler actual (`DashboardHandler(SimpleHTTPRequestHandler)`) ya resuelve estáticos desde `DASHBOARD_DIR` y tiene `_serve_index()` para la entrada SPA.

**Decisión:** En la fase final, el handler apunta su **root estático a `dist/`** (p.ej. override por env `ULTRATIMONEL_DASHBOARD_STATIC_ROOT` o constructor param), manteniendo intactos los handlers `/api/*`. `_serve_index()` sigue sirviendo `index.html` pero desde `dist/` (el build de Astro genera `dist/index.html`). Los archivos legacy (`index.html`, `app.js`) dejan de estar en el árbol servido. Este mismo mecanismo, con root `dist/`, es el que se valida primero en 3007 (ADR-2): la fase final no introduce serving nuevo, solo cambia el root estático del puerto principal.

**Consecuencias:**
- Un solo mecanismo de serving probado dos veces (3007 → 3005): mitigación directa del riesgo "reemplazo final rompe serving estático (MIME, rutas)".
- MIME: `SimpleHTTPRequestHandler` + `mimetypes` de Python 3.13 cubre `.js/.css/.html/.woff2/.svg/.png` (verificar en T12).
- El server sigue siendo Python stdlib, sin backend Node (NF-DA-02, out-of-scope del proposal).
- `index.html`/`app.js` legacy se deprecan (no se eliminan del repo necesariamente; quedan fuera del árbol servido). Decisión de eliminación física en apply-time.
- Rollback trivial: restaurar el root estático legacy.

---

### ADR-6: Estilos — dependencia `nes.css` directa + política de CSS mínimo de layout

**Contexto:** nes-react (v1.0.2, MIT, 7 años) compila los estilos de NES.css DENTRO de su bundle JS (`dist/index.es.js` importa `../nes.css/scss/nes.scss` + `custom.scss`): las clases llegan inyectadas por JS al hidratar la isla. Eso significa: (a) el shell estático no tendría estilos NES hasta la hidratación; (b) la capa interna de badges/dropdown/dialog (F-DA-03) necesita clases `.nes-*` en CSS real; (c) depender de inyección por JS es frágil para el build estático.

**Decisión:** Depender también de `nes.css` como paquete directo (`npm install nes.css`) e importar su CSS una vez en el layout global (`import 'nes.css/css/nes.min.css'`). Los estilos pasan a ser un asset CSS del build (funciona en el shell estático y en 3007/3005), y la capa interna usa clases `.nes-*` del mismo paquete. El bundle inyectado por nes-react se mantiene (duplicación idempotente del base, aceptada y documentada). Fuente `Press Start 2P` self-hosted en `public/fonts/` con fallback (F-DA-13).

**Política de CSS (NF-DA-05):**
- Permitido: `src/styles/layout.css` — spacing, flex, estructura de página, alineación.
- Prohibido: CSS custom de diseño visual (colores, bordes, tipografías, sombras, componentes). Todo lo visual sale de NES.css/nes-react.
- La capa interna (`src/components/ui/`) usa clases del bundle `nes.css` (`.nes-badge`, `.nes-dropdown`, `.nes-dialog`) — eso NO es CSS manual.

**Consecuencias:**
- Estilos presentes desde el primer render (estático y dinámico).
- Duplicación controlada: css de `nes.css` + css inyectado por nes-react; base idéntica, override menor de `custom.scss` del paquete; impacto de bytes bajo para herramienta local.
- `node-sass` de nes-react es solo build-time del paquete; no se compila en consumo (los dist están prebuilt) — no instalar/rebuild nativo.

---

## 2. Component Design

### 2.1 Estructura de archivos (`ultratimonel/dashboard-astro/`)

```
ultratimonel/dashboard-astro/
├── package.json                  # astro, @astrojs/react, react@^18, react-dom@^18, nes-react, nes.css
├── astro.config.mjs              # ADR-2: output static, integrations react, server 3006, vite proxy
├── tsconfig.json                 # (opcional) JSX react-jsx
├── public/
│   └── fonts/                    # Press Start 2P woff2 (self-host) — F-DA-13
├── src/
│   ├── styles/
│   │   └── layout.css            # único CSS custom: layout/alineación (NF-DA-05)
│   ├── layouts/
│   │   └── BaseLayout.astro      # head: nes.css import, font-face, layout.css; <slot/>
│   ├── pages/
│   │   ├── index.astro                           # F-DA-09 → <ProjectsIndex client:load />
│   │   ├── proyectos/[project]/index.astro       # F-DA-10 → <ProjectDetail client:load />
│   │   ├── misiones/[id]/index.astro             # F-DA-11 → <MissionDetail client:load />
│   │   └── intentos/[id]/index.astro             # F-DA-12 → <IntentoDetail client:load />
│   ├── components/
│   │   ├── ui/                                   # capa interna NES.css (F-DA-03, ADR-6)
│   │   │   ├── NesBadge.jsx                      # .nes-badge (.is-splited/.is-icon)
│   │   │   ├── NesDropdown.jsx                   # .nes-dropdown
│   │   │   └── NesDialog.jsx                     # .nes-dialog (si aplica)
│   │   ├── Breadcrumbs.jsx                       # F-DA-08/F-DA-15
│   │   ├── StatusBadge.jsx                       # envuelve NesBadge + estado del intento/gate
│   │   ├── ProjectCard.jsx                       # Container with-title + List/Icon
│   │   ├── MissionCard.jsx                       # Container + Progress (checklist_done/total)
│   │   ├── ChecklistCard.jsx                     # Table/List + Checkbox + intentos embebidos
│   │   ├── IntentoCard.jsx                       # Table gate states + NesBadge + Progress
│   │   ├── projects/ProjectsIndex.jsx            # island vista índice
│   │   ├── projects/ProjectDetail.jsx            # island vista proyecto
│   │   ├── missions/MissionDetail.jsx            # island vista misión
│   │   └── intentos/IntentoDetail.jsx            # island vista intento (+ gate logs)
│   └── hooks/
│       └── useApi.js                             # fetch /api/* + states loading/error/empty (S8/S9)
```

### 2.2 Mapeo de primitivas nes-react → vistas

| Vista | Primitivas nes-react principales | Capa interna |
|-------|----------------------------------|--------------|
| Índice | `Container` (with-title), `List`, `Icon` | `StatusBadge`, `ProjectCard` |
| Proyecto | `Container`, `Progress`, `Table` | `MissionCard`, `StatusBadge` |
| Misión | `Container`, `Table`, `Checkbox`, `Progress`, `Balloon` | `ChecklistCard`, `StatusBadge` |
| Intento | `Container`, `Table`, `Progress`, `Button`, `Icon`, `Balloon` | `IntentoCard`, `NesBadge`, `NesDialog` |
| Global | — | `Breadcrumbs`, `useApi` |

No existen `Panel` ni `TextField` (verificado en `dist/index.d.ts`): panel con título = `Container` con estilo `with-title`; campos = `TextInput`/`TextArea`.

### 2.3 Breadcrumbs (F-DA-08, F-DA-15)

> **NOTA (Ejecución 8, 2026-08-15, card #154):** el usuario aprobó explícitamente
> rutas **jerárquicas** que reemplazan el esquema plano F-DA-15 de esta sección
> (`/proyectos/[project]/`, `/misiones/[id]/`, `/intentos/[id]/`). La estructura
> vigente desde esa fecha es:
> `/`, `/{proyectoName}/`, `/{proyectoName}/{misionId}/`,
> `/{proyectoName}/{misionId}/{checklistItemId}/`. Las rutas planas redirigen
> 301 a su equivalente jerárquico (server Python). Los breadcrumbs se derivan
> del path (el path ES la jerarquía) y el nivel actual se renderiza como
> `<a>` clickeable que refresca. Las tablas/diagramas de las secciones 2.3 y 3.x
> quedan como registro histórico del diseño original; la implementación actual
> sigue la estructura jerárquica.

| Ruta | Crumbs | Resolución del parent |
|------|--------|-----------------------|
| `/` | `Dashboard` (actual) | — |
| `/proyectos/[project]/` | `Dashboard` → `<project>` (actual) | slug de la URL |
| `/misiones/[id]/` | `Dashboard` → `<project>` → `<mision>` (actual) | `/api/missions/{id}` → `mission.project` |
| `/intentos/[id]/` | `Dashboard` → `<project>` → `<mision>` → `Intento #<id>` (actual) | `/api/intentos/{id}` → `intento.mission.{project,id,title}` |

Cada crumb no-actual es `<a href>` a la ruta real: `/`, `/proyectos/{project}/`, `/misiones/{mission_id}/`. El nivel "Dashboard" se agrega (el legacy no lo tenía — fix explícito del proposal).

---

## 3. Data Flow Diagrams

### 3.1 Vista índice (dev)
```
Browser 127.0.0.1:3006/ → page.astro shell estático
ProjectsIndex (island client:load) → fetch('/api/projects')
  → Vite dev proxy → 127.0.0.1:3005/api/projects → JSON → render ProjectCard[]
```

### 3.2 Vista proyecto
```
/proyectos/{project}/ → shell + params {project}
ProjectDetail → fetch(`/api/projects/${project}/missions`) → proxy → 3005 → JSON → render MissionCard[] + Progress
```

### 3.3 Vista misión (resuelve breadcrumb parent)
```
/misiones/{id}/ → shell + params {id}
MissionDetail → fetch(`/api/missions/${id}`) → proxy → 3005
  → mission.project → Breadcrumbs: Dashboard → /proyectos/{project}/ → Misión
  → mission.checklist[] (+ intentos embebidos) → ChecklistCard[]
```

### 3.4 Vista intento (resuelve breadcrumb chain + logs)
```
/intentos/{id}/ → shell + params {id}
IntentoDetail → fetch(`/api/intentos/${id}`) → proxy → 3005
  → intento.mission {project,id,title} → Breadcrumbs: ... → /misiones/{mission_id}/ → Intento #id
  → intento.gates[] → IntentoCard (estados + Progress)
  → onClick gate → fetch(`/api/intentos/${id}/gate/${name}/logs`) → timeline (NesDialog/Balloon)
```

### 3.5 Build validación / producción
```
astro build → dist/
dashboard_server.py (static_root=dist/) → sirve dist/* en el puerto + /api/* desde los handlers actuales
Browser → 127.0.0.1:3007 (validación) o 3005 (producción) → same-origin, sin proxy
```

---

## 4. Risk Matrix

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | nes-react es librería chica/inactiva; no cubre todos los patrones NES.css (badges, dropdown, dialog) | Medium | Medium | Capa interna `components/ui/` compone nes-react + clases del bundle `nes.css` (ADR-6, F-DA-03) |
| R2 | Compatibilidad nes-react con React moderno (peer deps ^15/^16) | Medium | Medium | Pin `react@^18.3` (ADR-3); class components + prop-types soportados; validar hidratación en T5-T8 |
| R3 | "Sin clases CSS manuales" choca con layout/alineación | Medium | Medium | Política explícita NF-DA-05 + ADR-6: un solo `layout.css` de estructura, cero diseño visual custom |
| R4 | Primer toolchain JS en repo Python: build, node_modules, CI | Medium | Medium | App aislada en `ultratimonel/dashboard-astro/` (ADR-1); pipeline pytest intacto; `.gitignore` cubre node_modules/dist |
| R5 | Proxy `/api` mal configurado rompe staging | Low | Medium | `vite.server.proxy` documentado (ADR-4); smoke S10 antes de validación funcional; target vía env `ULTRATIMONEL_DASHBOARD_PORT` |
| R6 | Reemplazo final rompe serving estático (MIME, rutas) | Medium | Medium | Mecanismo de serving validado primero en 3007 con el mismo handler (ADR-2/ADR-5); check MIME `.woff2` en T12 |
| R7 | Datos stale si se hiciera fetch build-time | Low | High | Fetch en cliente (ADR-3); nunca fetch en build |
| R8 | e2e no disponible (`e2e: false`) | Medium | Medium | Smoke tests manuales por vista contra API real en staging (T11, NF-DA-07) |
| R9 | Fuente Press Start 2P requiere red | Low | Low | Self-host woff2 en `public/fonts/` + fallback sistema (F-DA-13) |

---

## 5. Test Impact Analysis

### 5.1 Existing tests

| Test | Change needed? | Reason |
|------|---------------|--------|
| Suite pytest (`tests/`, `.venv/bin/pytest`) | No | Cambio frontend-only; backend/API intactos (NF-DA-01) |

### 5.2 Verification steps (sin unit tests — validación manual/smoke por vista)

1. `cd ultratimonel/dashboard-astro && npm install` — resuelve astro/react/nes-react/nes.css sin errores de peer dep (npm 7+: `--legacy-peer-deps` si warnings bloquean)
2. `npm run dev` — dev server en `127.0.0.1:3006`
3. Smoke dev: abrir `/`, `/proyectos/{project}/`, `/misiones/{id}/`, `/intentos/{id}/` (S1-S7) + verificar consola sin errores CORS (S10)
4. Estados límite: id inexistente (S8), server 3005 detenido (S9), proyecto sin misiones (S3), misión sin checklist (S5)
5. `npm run build` → `dist/`
6. `dashboard_server.py` con `static_root=dist/` en 3007 → repetir smoke (S1-S10) contra el build
7. Verificar legacy: `http://127.0.0.1:3005/` sigue funcionando (S11); `git diff` de `ultratimonel/dashboard/` vacío
8. Fase final (T12): cambiar root estático a `dist/` en 3005 → repetir smoke + verificar `/api` (S12); deprecar legacy
9. `.venv/bin/pytest tests/ -q --tb=short` — sin regresiones

---

## 6. Implementation Order

Delivery partition (approved, Deck cards #155-160; task card #154): **T1–T4 → M1/PR1**, **T5–T6 → M2/PR2**, **T7–T8 → M3/PR3**, **T9–T10 → M4/PR4**, **T11 → M5 (validation gate, no PR)**, **T12 → M6/PR5**. Each PR stays ≤400 changed lines; M5 must pass before the M6/PR5 cut. Per-mission done criteria live in `tasks.md` ("Approved Delivery Partition").

1. Scaffold app Astro + React + nes-react + nes.css + fuente (T1) — **M1/PR1**
2. `astro.config.mjs` — puerto 3006, host, proxy `/api` (T2) — **M1/PR1**
3. Layout + `layout.css` + import global `nes.css` (T3) — **M1/PR1**
4. Capa interna `ui/` + `useApi` (T4) — **M1/PR1**
5. Breadcrumbs componente (T5) — **M2/PR2**
6. Vista índice (T6) — **M2/PR2**
7. Vista proyecto (T7) — **M3/PR3**
8. Vista misión (T8) — **M3/PR3**
9. Vista intento + gate logs (T9) — **M4/PR4**
10. Estados límite y pulido de navegación (T10) — **M4/PR4**
11. Validación dual puerto: smoke por vista (T11) — **M5 (gate, sin PR)**
12. Reemplazo final: `dashboard_server.py` sirve `dist/`, deprecación legacy (T12) — **M6/PR5**

---

## 7. Open Questions

1. **Puerto 3007 — RESUELTA (ADR-2):** validación del build servida por el handler Python con `static_root=dist/` (pre-valida la fase final); `astro preview` queda como utilidad estática opcional sin proxy de `/api`.
2. **Proxy `/api` en Astro — RESUELTA (ADR-4):** `vite.server.proxy` (la opción `server` de Astro no expone `proxy`; aplica solo a `astro dev`).
3. **Serving del build final — RESUELTA (ADR-5):** `dashboard_server.py` con root estático `dist/`, manteniendo `/api`; mismo mecanismo validado en 3007.
4. **Ubicación de la app — RESUELTA (ADR-1):** `ultratimonel/dashboard-astro/`, misma repo, subdirectorio aislado.
5. **Estrategia de datos — RESUELTA (ADR-3):** fetch en cliente (islands `client:load`) contra `/api` same-origin; `output: 'static'`; pin React 18.
6. **Eliminación física del legacy — PENDIENTE (apply-time):** `index.html`/`app.js` quedan fuera del árbol servido en T12; decidir si se eliminan del repo o se conservan como referencia (default: conservar, marcar deprecado en docs).

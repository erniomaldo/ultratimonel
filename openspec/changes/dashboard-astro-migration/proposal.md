# dashboard-astro-migration — Migración del dashboard a Astro + nes-react

> Card #148 · Fuente: investigación documentada (Collective Ultratimonel, página Migración-Astro)

## Problema

El dashboard web de Ultratimonel (`ultratimonel/dashboard/`) es un SPA de
HTML/JS vanilla sin enrutamiento real: un único `index.html` + `app.js` que
intercambia vistas en memoria (`VIEW.MISSIONS`, `VIEW.CHECKLIST_ITEMS`,
`VIEW.INTENTOS`, `VIEW.INTENTO_DETAIL`) y un sidebar de proyectos. Esto genera
tres problemas concretos:

1. **Sin rutas reales**: no hay URLs por vista. No se puede compartir ni
   recargar un detalle (F5 pierde el estado de navegación). Los breadcrumbs
   actuales son texto renderizado con `onClick` en memoria, no enlaces
   navegables; el nivel "Dashboard" ni siquiera aparece.
2. **UI imperativa y frágil**: `app.js` construye HTML por string concatenado
   (654 líneas) mezclando clases manuales de NES.css, estilos inline y CSS
   custom. Cualquier cambio de UI requiere tocar render functions y CSS a mano.
3. **Sin capa de componentes**: no hay componentes reutilizables; el mismo
   patrón (badge de estado, card de misión, barra de progreso) se repite por
   copia/pega en cada render.

La investigación ya documentada propone migrar el dashboard a **Astro** con
componentes **React de nes-react** (bschulte/nes-react), eliminando las clases
CSS manuales.

## Objetivo

Migrar el dashboard actual a una aplicación Astro con componentes React de
nes-react, con enrutamiento real y breadcrumbs navegables (Dashboard → Proyecto
→ Misión → Intento), corriendo en un puerto de staging separado sin romper el
dashboard actual, y listo para reemplazarlo en el puerto principal una vez
validado.

## Scope

### In-scope

- Nueva app Astro (`@astrojs/react`) con componentes de `nes-react`
  (Container, Button, TextInput, TextArea, Checkbox, Radios, Table, Progress,
  Icon, Balloon, List, Avatar, Sprite, ControllerIcon). **Sin clases CSS
  manuales** salvo un mínimo de estilos de layout/alineación de la app.
- Migrar las 4 vistas:
  1. Índice de proyectos (dashboard / lista desde sidebar)
  2. Detalle de proyecto (misiones del proyecto)
  3. Detalle de misión (checklist items + estado)
  4. Detalle de intento (estados por gate, progreso, timeline de logs de gate
     si aplica)
- Enrutamiento real por URL con breadcrumbs navegables en cada nivel:
  `Dashboard → Proyecto → Misión → Intento`, cada nivel enlazando a la ruta
  real del nivel anterior (no texto plano).
- **Doble puerto sin romper**: el dashboard actual sigue en su puerto
  (default `3005`, env `ULTRATIMONEL_DASHBOARD_PORT`); la app Astro corre en
  puerto de staging separado (`3006` dev / `3007` preview) con proxy de `/api`
  hacia el server Python.
- Consumo del mismo API JSON (sin cambios): `/api/projects`,
  `/api/projects/{project}/missions`, `/api/missions/{id}`,
  `/api/checklist/{item_id}/intentos`, `/api/intentos/{id}`,
  `/api/intentos/{id}/gate/{name}/logs`.
- Fase final de reemplazo: build estático de Astro servido en el puerto
  principal manteniendo el mismo server Python (`dashboard_server.py`) como
  origen para `/api` + estáticos (a confirmar en design).

### Out-of-scope

- NO tocar `ultratimonel/dashboard/index.html` ni `app.js` durante el staging
  (se deprecan solo en el reemplazo final).
- NO modificar `dashboard_server.py` ni sus endpoints `/api/*` en este change
  (solo se evalúa en design cómo servir el build final).
- NO cambiar lógica de negocio, gates, persistencia ni el server MCP.
- NO introducir backend Node/SSR para producción (el server sigue siendo
  Python stdlib).
- NO migrar el plugin preflight ni el cliente MCP.

## Definiciones

- **Astro**: framework web server-first, archivos `.astro`, cero JS por
  defecto; permite integraciones de UI frameworks (React vía `@astrojs/react`).
- **nes-react**: librería de componentes React que envuelve NES.css
  (bschulte/nes-react, MIT). Exporta: `Container`, `Button`, `Radios`,
  `Checkbox`, `TextInput`, `TextArea`, `Avatar`, `Balloon`, `List`, `Table`,
  `Progress`, `Icon`, `Sprite`, `ControllerIcon`. Incluye los estilos de
  NES.css vía su bundle (no requiere CDN manual).
- **Nota de mapeo**: no existen `Panel` ni `TextField` como componentes; el
  panel con título se logra con `Container` (estilo `with-title` de NES.css) y
  los campos con `TextInput`/`TextArea`. Para patrones de NES.css sin wrapper
  React (badges, dropdown, dialog), se crea una capa interna mínima de
  componentes propios que compone nes-react + clases de NES.css del bundle.
- **Islands**: componentes React hidratados en el cliente vía directivas
  (`client:load`); el resto de la página se sirve como HTML estático.

## Proposed Solution

### Reactivo 1 — App Astro con componentes nes-react

- Scaffold: `npx astro add react` → `@astrojs/react` + `react`/`react-dom`.
- Dependencias: `astro`, `@astrojs/react`, `react`, `react-dom`, `nes-react`.
- Tipografía: incluir la fuente `Press Start 2P` (requerida por nes-react,
  Google Fonts o self-host) en el `<head>` del layout.
- Componentes propios mínimos (`src/components/`): `ProjectCard`, `MissionCard`,
  `ChecklistCard`, `IntentoCard`, `StatusBadge`, `Breadcrumbs` — todos
  construidos con primitivas de nes-react (sin CSS custom de diseño).

### Reactivo 2 — Enrutamiento real + breadcrumbs navegables

Rutas Astro (`src/pages/`):

| Ruta | Vista | Breadcrumb |
|------|-------|------------|
| `/` | Índice de proyectos | `Dashboard` |
| `/proyectos/[project]/` | Detalle de proyecto (misiones) | `Dashboard → Proyecto` |
| `/misiones/[id]/` | Detalle de misión (checklist) | `Dashboard → Proyecto → Misión` |
| `/intentos/[id]/` | Detalle de intento (gates) | `Dashboard → Proyecto → Misión → Intento` |

Cada crumb es un `<a href>` a la ruta real del nivel anterior. Al entrar a un
detalle, la ruta lleva el dato del proyecto/misión necesario para construir los
enlaces (o se resuelve desde el API).

### Reactivo 3 — Doble puerto sin romper

- Dashboard actual: intacto en `3005` (`ULTRATIMONEL_DASHBOARD_PORT`).
- App Astro: `astro dev` en puerto staging `3006`; `astro preview` en `3007`
  (configurable vía `server`/env).
- Proxy de `/api` → `http://localhost:3005` durante dev/preview para que las
  vistas consuman el mismo API sin CORS.
- Validación manual del nuevo dashboard en staging antes del reemplazo.

### Reactivo 4 — Reemplazo final (puerto principal)

- Build estático (`astro build`) servido desde el server Python existente:
  `dashboard_server.py` sirve `dist/` como raíz estática y mantiene `/api`
  (decisión exacta de serving en design: servir `dist/` desde el root del
  handler actual, reutilizando `SimpleHTTPRequestHandler`).
- Deprecación del legacy: `index.html` + `app.js` quedan fuera del árbol
  servido.

## Decisiones confirmadas / pendientes

| Decisión | Estado | Rationale |
|----------|--------|-----------|
| Framework: Astro + `@astrojs/react` | Confirmada | Investigación Migración-Astro; islands para interacción; cero JS por defecto |
| UI: componentes `nes-react` | Confirmada | Envuelve NES.css ya usado; sin clases manuales |
| API backend sin cambios | Confirmada | El frontend migra; el contrato `/api/*` permanece |
| Staging: puerto 3006/3007 | Resuelta (design, ADR-2) | dev 3006 + validación del build en 3007 con el handler Python sobre `dist/`; `astro preview` solo como utilidad estática |
| Proxy `/api` en Astro | Resuelta (design, ADR-4) | `vite.server.proxy` (Astro no expone `server.proxy`); aplica solo a `astro dev` |
| Serving del build final | Resuelta (design, ADR-5) | `dist/` servido por `dashboard_server.py` en 3005, manteniendo `/api`; mismo mecanismo validado en 3007 |
| Ubicación de la app | Resuelta (design, ADR-1) | `ultratimonel/dashboard-astro/`, misma repo, subdirectorio aislado |
| Estrategia de datos | Resuelta (design, ADR-3) | fetch en cliente en islands `client:load` contra `/api` same-origin; `output: 'static'`; React 18 |

## Impact

- **Breaking changes**: No (hasta el reemplazo final; el API y el dashboard
  actual siguen funcionando durante todo el staging).
- **Database migrations**: No.
- **API changes**: No (mismo contrato JSON).
- **Dependencies (nuevas)**: `astro`, `@astrojs/react`, `react`, `react-dom`,
  `nes-react` (+ fuente `Press Start 2P`). Es el primer toolchain JS del repo
  (hoy es Python puro + pytest).
- **Archivos afectados**: nuevos — `package.json`, `astro.config.mjs`,
  `src/pages/*.astro`, `src/components/*.jsx`, layout. Legado intacto:
  `ultratimonel/dashboard/index.html`, `app.js`. Solo en fase final se evalúa
  tocar `dashboard_server.py` (servir `dist/`).
- **Fuera de alcance**: backend Python, MCP server, plugin preflight, tests de
  server (pytest) — se agrega validación manual/smoke para el frontend.

## Seguridad

Mismo perfil que el dashboard actual (herramienta local, `127.0.0.1`, sin
autenticación, solo GET, sin PII):

- El server Python se enlaza a `127.0.0.1` (configurable). El dev server de
  Astro debe enlazarse también a localhost durante staging.
- El proxy `/api` mantiene same-origin: el navegador solo ve el puerto de
  staging; no se exponen cabeceras CORS.
- Sin exposición a red externa; si en el futuro se expone, aplicar la misma
  nota de riesgo que `dashboard-refactor` (agregar autenticación).

## Riesgos

| Riesgo | Nivel | Mitigación |
|--------|-------|------------|
| nes-react es una librería chica y poco activa; no cubre todos los patrones de NES.css (badges, dropdown, dialog) | Medio | Capa interna de componentes propios que compone nes-react + clases del bundle NES.css; no escribir CSS de diseño custom |
| "Sin clases CSS manuales" choca con layout/alineación | Medio | Permitir un CSS mínimo de layout (spacing/flex) separado del diseño visual; criterio explícito en spec |
| Primer toolchain JS en un repo Python: build, node_modules, CI | Medio | Aislar la app en su propio directorio; documentar comandos; no tocar el pipeline pytest |
| Proxy `/api` mal configurado rompe staging | Bajo | Verificar same-origin en dev y preview antes de la validación funcional |
| Reemplazo final puede romper serving estático (MIME, rutas) | Medio | Validar `astro build` + servir `dist/` en un puerto de prueba antes de tocar el puerto principal |
| e2e no disponible (config openspec: `e2e: false`) | Medio | Smoke tests manuales por vista contra el API real en staging |
| Fuente Press Start 2P requiere red o self-host | Bajo | Self-host del woff2 en la app o fallback a fuente del sistema |

## Fases de implementación

| Fase | Tema | Archivos | Esfuerzo |
|------|------|----------|----------|
| 1 | Scaffold Astro + React + nes-react, puerto staging 3006 + proxy `/api` | package.json, astro.config.mjs, layout | 30 min |
| 2 | Layout + vistas estáticas con nes-react (4 rutas, breadcrumbs) | src/pages, src/components | 60 min |
| 3 | Data fetching + render dinámico de las 4 vistas contra el API | src/components, hooks/fetch | 60 min |
| 4 | Enrutamiento real + breadcrumbs navegables completos | src/pages, Breadcrumbs | 30 min |
| 5 | Validación dual puerto: smoke tests por vista en staging | — (manual) | 30 min |
| 6 | Reemplazo final: build + serving en puerto principal + deprecación legacy | dashboard_server.py, docs | 45 min |
| **Total** | | | **~255 minutos** |

## Partición de entrega aprobada (M1–M6 / PR1–PR5)

La implementación se entrega en 6 misiones y 5 PRs de ≤400 líneas cambiadas
cada uno (aprobado en cards #155-160 del Deck; task card #154). Cada misión
tiene criterios "done" propios y su propio PR de revisión; M5 es un gate de
validación **sin PR** que bloquea el corte final:

| Misión | PR | Tareas | Contenido |
|--------|-----|--------|-----------|
| M1 — Fundación | PR1 | T1–T4 | Scaffold Astro + config 3006/proxy + layout/estilos + capa UI/`useApi` |
| M2 — Navegación + Índice | PR2 | T5–T6 | Breadcrumbs + vista índice (`/`) |
| M3 — Proyecto + Misión | PR3 | T7–T8 | Detalle de proyecto + detalle de misión |
| M4 — Intento + hardening | PR4 | T9–T10 | Detalle de intento + estados límite |
| M5 — Validación dual puerto | — (gate) | T11 | Smoke dev 3006 + build 3007; legacy intacto en 3005 |
| M6 — Corte | PR5 | T12 | Reemplazo final en 3005 + deprecación legacy |

Detalle completo (criterios done por misión y mapeo por tarea): `tasks.md`.

## Artefactos generados

- `proposal.md` (este archivo)
- `specs/dashboard-astro-migration/spec.md` — requerimientos SHALL (F-DA-xx,
  NF-DA-xx) con escenarios GIVEN/WHEN/THEN por vista y por breadcrumb (S1–S13)
- `design.md` — ADRs: ubicación de la app (ADR-1), puertos staging (ADR-2),
  estrategia de datos (ADR-3), proxy `/api` (ADR-4), serving final (ADR-5),
  estilos (ADR-6)
- `tasks.md` — tareas T1–T12 con trazabilidad a specs y design, organizadas en
  la partición de entrega aprobada M1–M6 / PR1–PR5

---

## Nota de actualización (2026-08-15/16, card #154)

La implementación adoptó **jerarquía de URLs** + **fallbacks post-build** +
**redirects 301** (decisión del usuario 2026-08-15), desviándose del esquema
plano original de este documento:

- Estructura vigente: `/`, `/{proyectoName}/`, `/{proyectoName}/{misionId}/`,
  `/{proyectoName}/{misionId}/{checklistItemId}/` y
  `/{proyectoName}/{misionId}/{checklistItemId}/{intentoId}/` (el 4º nivel —
  detalle del intento como página propia — agregado el 2026-08-16).
- Las rutas planas (`/proyectos/*`, `/misiones/*`, `/intentos/*`) responden 301
  hacia su equivalente jerárquico; el server Python resuelve la `Location` por DB.
- Fallbacks post-build: entidad existente sin shell enumerado en el build → 200
  con shell genérico hidratado; entidad inexistente → 404 real.

El cuerpo de este documento (Reactivos 1–4) describe el diseño original plano;
la especificación y el diseño vigentes (`spec.md`, `design.md`,
`apply-progress.md`) documentan la estructura jerárquica real.

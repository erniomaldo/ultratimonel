# plugin-preflight-sync — Sincronización repo/runtime del plugin preflight

## Problema

El plugin `ultratimonel-preflight` (v2.0.0) fue parchado en **runtime** el
28 de julio con el hook `post_tool_call` (`_post_turn_guard`) sin reflejarse
en el repositorio. Esto creó un **desincronización runtime/repo**:

- El agente instalada corría v2.0.0 con `_post_turn_guard` (bloqueo inescapable
  tras `end_turn`, 1 ciclo por respuesta).
- El repo contenía una versión anterior sin este hook.
- Cualquier deploy posterior desde el repo habría **sobrescrito** el fix de
  runtime, perdiendo el bloqueo post-turn.

## Contexto del patch 28-jul

El parche de runtime añadió:
1. Hook `post_tool_call` → `_post_turn_guard`: bloquea todas las tools tras
   `end_turn()` hasta que se llame a `begin_turn()` (1 ciclo por respuesta).
2. Variables de estado global: `_turn_ended`, `_turn_active`.
3. `register()` actualizado para registrar los 4 hooks.
4. `plugin.yaml` versionado a 2.0.0 con `post_tool_call` en `provides_hooks`.

## Scope del fix

Este change documenta retrospectivamente el fix ya implementado en los commits:
- `776fc47` — port de post_turn_guard del runtime al repo
- `d9327be` — docs(readme): regla anti-desync
- `ad1225b` — chore: ignore .atl/ tooling cache

El fix porta la fuente sincronizada desde el runtime **AL** repo, estableciendo
el repo como única fuente de verdad.

## Decisiones confirmadas

| Decisión | Rationale |
|----------|-----------|
| El plugin vive en `ultratimonel/` dentro del repo | Si se copia a la config del agente, deja de actualizarse cuando el repo avanza (desync) |
| El deploy copía **desde** el repo **hacia** la instalación del agente | La instalación es destino, no fuente; cualquier cambio va primero al repo |
| `_post_turn_guard` es obligatorio | Sin él, el agente puede llamar tools después de `end_turn()`, rompiendo el ciclo 1-ciclo-por-respuesta |
| `GRACE_TURNS=3` por defecto (env var) | Permite los primeros N turnos sin bloquear por gates fallando, para auto-corrección del agente |

## Evidencia verificada

- `ultratimonel/plugin_preflight.py` es idéntico a la versión que corría en runtime
  (copia instalada del agente, `__init__.py`). Diff vacio verificado.
- `py_compile` OK en ambos archivos del plugin (`plugin_preflight.py`,
  `ultratimonel_client.py`).
- Suite de tests existente: 75/75 pasan en esta rama (tests del server,
  persistence, gate_engine, triple_match, context_extractor, integration).

## Qué falta por verificar

- Tests unitarios específicos para el plugin (`plugin_preflight.py`) — no existen
  en `tests/`. El plugin se prueba implícitamente via integración runtime.
- Verificar que el agente carga el plugin desde el repo tras deploy (no desde
  cache externo).

## Artefactos generados

- `specs/plugin-preflight/spec.md` — requerimientos SHALL derivados del código
- `design.md` — ADR-007 a ADR-010 (source-of-truth, double assert_gates, grace
  turns, post-turn guard)
- `tasks.md` — tareas retrospectivas organizadas por fase PAC
- `apply-progress.md` — estado de la primera ejecución
- `verify-report.md` — evidencia real y gap analysis

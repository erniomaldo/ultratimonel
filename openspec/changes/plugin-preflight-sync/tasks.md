# Plugin Preflight Sync — Tasks (retrospectivo)

## Fase 1 — Definición (OpenSpec)

- [x] 1.1 proposal.md — problema del desync runtime/repo, contexto del patch 28-jul, scope del fix, decisiones confirmadas
- [x] 1.2 specs/plugin-preflight/spec.md — reqs SHALL derivados del código (4 hooks, bloqueo sin gates, grace turns, 4/4 complete_intento, title lock, 1 ciclo por respuesta, env var, inyección de contexto) con escenarios WHEN/THEN
- [x] 1.3 design.md — ADR-007 a ADR-010 (source-of-truth repo vs runtime, double assert_gates, grace turns, post-turn guard) con rationale y alternativas
- [x] 1.4 tasks.md — este archivo

## Fase 2 — Implementación (SDD)

- [x] 2.1 Port de `post_turn_guard` desde runtime al repo (`ultratimonel/plugin_preflight.py`)
- [x] 2.2 Versionar `plugin.yaml` a v2.0.0 con `post_tool_call` en `provides_hooks`
- [x] 2.3 Verificar `py_compile` en `plugin_preflight.py` y `ultratimonel_client.py`
- [x] 2.4 Verificar diff vacío entre repo y runtime (si runtime disponible)
- [x] 2.5 Ejecutar suite de tests existente (75/75 passing)
- [x] 2.6 Docs(readme): regla anti-desync explícita — plugin vive en repo, deploy desde repo hacia instalación
- [x] 2.7 Chore: ignore `.atl/` tooling cache

## Fase 3 — Verificación

- [ ] 3.1 Tests unitarios del plugin (`tests/test_plugin_preflight.py`) — NO existen actualmente
- [ ] 3.2 Verificar carga del plugin desde repo tras deploy (no desde cache externo)
- [ ] 3.3 Verificar que `_post_turn_guard` bloquea tools después de `end_turn` en integración runtime

## Fase 4 — Deploy

- [ ] 4.1 Revisión PM
- [ ] 4.2 Merge a main
- [ ] 4.3 Desplegar desde repo a instalación del agente (copia de `ultratimonel/plugin_preflight.py` → `~/.hermes/plugins/ultratimonel-preflight/__init__.py`)

## Notas

- Las tareas 2.1-2.7 ya están commiteadas en esta rama (commits 776fc47, d9327be, ad1225b).
- Las tareas de Fase 3 son gaps identificados: no hay tests unitarios del plugin
  y no se ha verificado la carga desde repo tras deploy.

# Proposal: Ultratimonel v2 — Architecture, 12 MCP Tools, Schema v2, Dashboard

## Intent
Ultratimonel v1 (MVP, archivado en `openspec/changes/archive/2026-06-28-ultratimonel-mvp/`) implementó el pre-flight protocol con 3 MCP tools y 3 gates (1a, 1b, 1e). Este change documenta —en orden PAC— la evolución a v2 ya commiteada en `8620b67`:

- Schema v2 de SQLite (missions, checklist_items, intentos + migración desde v1)
- **12 MCP tools totales** (3 originales + 9 nuevas: server, map_list, map_add, map_remove, map_setup, map_sync, sync_tasks, sync_all, mission_list)
- Gate 1c (Collectives) en el triple match, secuencia final **1a → 1b → 1c → 1e**
- Dashboard web embebido (puerto 3005) con jerarquía Proyecto → Misión → Checklist → Intento → Gates
- Externalización de la config de proyectos a `project_maps.json` (deprecación de `KNOWN_PROJECTS` hardcodeado)
- Fix de deadlock en `persistence.py` (Lock → RLock) para soportar llamadas anidadas como `list_missions()` → `list_checklist_items()`

Este change **NO introduce código nuevo**; el commit `8620b67` ya lo implementó. Su propósito es cerrar el gap de artifacts SDD exigido por el **PAC** (Nota #2380 — Protocolo de Aplicación de Cambio), alineando el repositorio con la regla "PRD aprobado antes de implementación".

## Scope

### In
1. **Schema v2 SQLite** — 4 tablas nuevas (`checklist_items`, `intentos`) + refactor de `missions` para usar `deck_task_id` como clave natural; migración v1 → v2 con detección de schema preexistente.
2. **12 MCP tools** (3 originales + 9 nuevas): `assert_gates`, `check_gate`, `complete_gate`, `server`, `map_list`, `map_add`, `map_remove`, `map_setup`, `map_sync`, `sync_tasks`, `sync_all`, `mission_list`.
3. **Gate 1c (Collectives)** integrado al triple match; el orden pasa a ser 1a → 1b → 1c → 1e.
4. **Dashboard web** en puerto 3005 (controlable vía `mcp_ultratimonel__server(action)`) con API REST jerárquica: `/api/projects`, `/api/projects/{p}/missions`, `/api/missions/{id}`, `/api/checklist/{item_id}/intentos`, `/api/intentos/{id}`, `/api/intentos/{id}/gate/{name}/logs`.
5. **`config_loader.py`** + `project_maps.json.template` — la config de proyectos deja de estar hardcodeada en `context_extractor.py`.
6. **Fix de deadlock** en `persistence.py`: `threading.Lock()` → `threading.RLock()` para soportar composición de métodos que toman el lock.
7. **HTTP_TIMEOUT** subido de 40s a 300s (preparación para escalar a 50+ proyectos; 20 proyectos sincronizan en ~74s).
8. **Tests v2**: 74/74 pasan (era 66/73 con 7 legacy fallando).
9. **Specs actualizadas**: `mission-gate`, `triple-match`, `gate-persistence`, `soul-enforce` sincronizadas al estado del 19 de julio (la copia en main databa del 28 de junio).
10. **Docs actualizados**: `README.md`, `docs/01-plan-general.md`, `docs/02-triple-match.md`, `docs/05-preflight-flow.md`.

### Out
- Push del branch a `origin` (queda para Fase 3 del PAC).
- Apertura de PR (queda para Fase 3 del PAC).
- `judgment-day` sobre commit 8620b67 (queda pendiente; el PAC lo declara obligatorio antes de Fase 3, pero el usuario detuvo el flujo en Paso 3).
- Update de las páginas de Nextcloud Collective (id 17: Inicio, Arquitectura, Decisiones) que actualmente describen 3 tools en vez de 12.
- Tests de integración (sigue el warning del verify anterior; pendiente histórico).
- Autenticación del dashboard (puerto interno; asumido en localhost o vía tunnel).
- Sync bidireccional Deck ↔ missions (solo one-way Deck → missions está implementado).

## Capabilities

### New (delta specs)
- `mission-gate` — extiende a **12 tools** y agrega F-MG-10 a F-MG-14 (server, map_list, map_add, map_remove, map_setup/sync) + F-MG-15 a F-MG-17 (sync_tasks, sync_all, mission_list).
- `triple-match` — gate 1c agregado; secuencia 1a → 1b → 1c → 1e.
- `gate-persistence` — schema v2 (4 tablas nuevas: `missions` con `deck_task_id` como natural key, `checklist_items`, `intentos`) + RLock para composición.
- `dashboard` (nueva) — jerarquía UI/API del dashboard.
- `project-maps` (nueva) — externalización de config, contrato de `project_maps.json`, hot-reload via `reload_project_maps()`.

### Modified
- `soul-enforce` — sin cambios funcionales; solo alineación de fecha de spec.

## Approach
Este change sigue el **orden inverso del flujo normal del PAC**: el código (commit 8620b67) se hizo primero, y los artifacts SDD se generan ahora para documentarlo. Tres fases:

1. **Fase 1 — Documentación retroactiva (este change)**: escribir `proposal.md`, `design.md`, `tasks.md`, `specs/*.md` que reflejan fielmente el commit 8620b67. Verificar que cada requirement de las specs tenga evidencia en el código.
2. **Fase 2 — Verificación y validación (siguiente paso del PAC, no incluido)**: correr `sdd-verify` + `judgment-day` sobre 8620b67. El PAC Nota #2380 declara esto obligatorio: *"Validación Obligatoria: Nunca saltar `judgment-day` en Fase 2"*.
3. **Fase 3 — Deploy (no incluida)**: cherry-pick o rebase de 8620b67 a `feature_v2-architecture`, push del branch, abrir PR, revisión manual del PM.

Este change **solo completa la Fase 1**.

## Affected Areas
- `ultratimonel/persistence.py` — schema migration v1 → v2, RLock fix, nuevos métodos (`upsert_mission`, `upsert_checklist_item`, `list_missions`, `create_intento`, etc.)
- `ultratimonel/server.py` — 9 nuevos MCP tools
- `ultratimonel/triple_match.py` — gate 1c, `HTTP_TIMEOUT` 40 → 300, `reload_project_maps()`
- `ultratimonel/context_extractor.py` — deprecación de `KNOWN_PROJECTS`, carga vía `config_loader.load_project_maps()`
- `ultratimonel/config_loader.py` (nuevo)
- `ultratimonel/dashboard_server.py` (nuevo) + `ultratimonel/dashboard/` (nuevo, frontend)
- `ultratimonel/mcp_client.py` — `deck_get_card` en `TOOL_NAMES`
- `tests/test_persistence.py`, `tests/test_context_extractor.py` — tests reescritos para v2
- `README.md`, `docs/01`, `docs/02`, `docs/05` — sincronización de docs
- `openspec/specs/mission-gate`, `triple-match`, `gate-persistence`, `soul-enforce` — sincronización al 19 jul

## Risks
| Risk | Mitigation |
|------|-----------|
| Migración v1 → v2 falla en DB existente | `_is_v1_style_missions_table()` detecta schema preexistente antes de aplicar DDL v2 |
| `RLock` reintroducido a `Lock` por error humano | Comentario explícito en `__init__` documentando la razón |
| Dashboard binding 3005 choca con otro servicio | Variable de entorno `ULTRATIMONEL_DASHBOARD_PORT` (default 3005) |
| `project_maps.json` malformado hace fallar el server | `config_loader.py` con try/except; devuelve `{}` y logging |
| 300s timeout afecta suite de tests | Tests mockean `call_mcp_tool`; no se ven afectados. Verificado: 74/74 en 20s |
| Cambio retroactivo contradice la regla "OpenSpec antes de código" del PAC | **Aceptado por el usuario** — la remediación es generar los artifacts ahora, no revertir el código. Lección registrada en AgentMemory. |
| Página de inicio del Collective 17 dice "3 tools" (incorrecto) | Pendiente; no bloquea este change. Acción de seguimiento fuera de scope. |

## Rollback Plan
1. **Code rollback (si se decide revertir 8620b67)**: `git revert 8620b67` — el schema v2 es backwards-compatible con v1 gracias a la migración; revertir a 8620b67~1 recupera schema v1 + lock simple.
2. **Docs rollback**: `git revert <sdds-commit>` (cuando se commitee) — no afecta código.
3. **Dashboard stop**: `mcp__ultratimonel__server(action="stop")` + borrado de `dashboard_server.py` + `ultratimonel/dashboard/`. No afecta el MCP server principal.
4. **Schema rollback**: backup pre-migración registrado en `schema_version` table. Permite downgrade manual con DDL inverso.

## Dependencies
- Python ≥ 3.13.5 (verificado)
- `fastmcp` (ya en `requirements.txt`)
- `httpx` (ya en `requirements.txt`)
- SQLite 3.46.1 (stdlib)
- `http.server` (stdlib) — para el dashboard, no requiere FastAPI/uvicorn
- Nextcloud MCP (externo) — vía `mcp__nextcloud__*` tools
- agentmemory MCP (externo)
- agentcheckpoint MCP (externo)
- **No nuevas dependencias** añadidas por este change.

## Success Criteria
1. ✅ Tests: 74/74 pasan en <30s (verificado)
2. ✅ `assert_gates()` ejecuta 4 gates (1a, 1b, 1c, 1e) en <8s p99
3. ✅ Dashboard arranca en :3005 y lista 20 proyectos con `mission_count` real
4. ✅ `sync_all()` sincroniza 20 proyectos en <120s (medido: 74.5s)
5. ✅ `project_maps.json` editable sin tocar código
6. ✅ Bugfix documentado: deadlock prevenido por RLock (verificado por test que reproduce el escenario)
7. ⏳ `sdd-verify`: TBD (queda para Fase 2 del PAC)
8. ⏳ `judgment-day`: TBD (obligatorio por PAC, no corrido por directiva del usuario)
9. ✅ Specs sincronizadas con el código al 19 jul 2026
10. ✅ Working tree de la rama `feature_v2-architecture` limpio tras este change

## PAC Compliance
- **Nota de referencia:** #2380 "Protocolo de Aplicación de Cambio (PAC)" — categoría "Protocolos Maestros"
- **Fase actual:** 1 (Definición) — generación de artifacts
- **Fase 2:** pendiente — implementación ya hecha fuera de orden, `judgment-day` no corrido
- **Fase 3:** pendiente — push, PR, revisión PM
- **Triple persistencia cumplida:** checkpoint `ultratimonel:v2-sdd-docs` + memory `mem_mrxy872k_04bf564aa192` + card #126 en board 21

## Traceability
- Code commit: `8620b67` (ya en `main`, ahead of origin/main by 1)
- Working branch: `feature_v2-architecture` (creada en este change, clean)
- Card Deck: #126 (board 21, stack 72)
- Checkpoint: `ultratimonel:v2-sdd-docs`
- AgentMemory: `mem_mrxy872k_04bf564aa192`
- Tests: 74/74 passing

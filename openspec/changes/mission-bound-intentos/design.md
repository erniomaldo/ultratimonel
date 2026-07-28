# Mission-Bound Intentos — Design

## ADR-001: Protocol enforcement (SOUL.md, sin código)
**Contexto:** El agente puede llamar a `record_intento()` sin misión porque el protocolo no lo exige. El Paso 5 permite `mission_id=0` como "intento genérico".
**Decisión:** Agregar Paso 4b que exige misión antes de registrar. Eliminar el fallback `mission_id=0` del Paso 5.
**Consecuencia:** El agente debe identificar o crear una card Deck antes de registrar progreso. Si no hay card, no hay intento.

## ADR-002: Tool validation server-side (server.py, opencode)
**Contexto:** Incluso si el protocolo lo exige, el agente podría omitir el paso. No hay validación en el server.
**Decisión:** `record_intento()` rechaza `mission_id <= 0` o `checklist_item_id <= 0` con un error que instruye usar `sync_tasks()` primero.
**Consecuencia:** El server es el guardián final. El error incluye la acción correctiva (sync_tasks).

## ADR-003: Plugin bouncer extension (PR futuro)
**Contexto:** El plugin bouncer bloquea `record_intento()` si gates no PASS, pero no valida misión.
**Decisión:** En un PR futuro, extender el pre_tool_call para validar que `mission_id > 0` y que exista en la tabla missions.
**Consecuencia:** Doble capa de seguridad: server + plugin. El plugin cachea la validación para no pegar a DB cada vez.

## ADR-004: DB-level referential integrity via PRAGMA foreign_keys
**Contexto:** SQLite desactiva foreign keys por defecto. Las tablas `intentos` y `checklist_items` declaran `REFERENCES missions(id)` pero no se aplican. Si todas las capas application-side fallan, la DB acepta datos huérfanos.
**Decisión:** Activar `PRAGMA foreign_keys = ON` en cada conexión de escritura en `persistence.py`. Agregar FOREIGN KEY para `checklist_item_id → checklist_items(id)` en la tabla `intentos`.
**Consecuencia:** La DB se convierte en la última línea de defensa. Cualquier intento con `mission_id` o `checklist_item_id` que no exista falla con `SQLITE_CONSTRAINT_FOREIGNKEY`.

## ADR-005: Turn-scoped intento lifecycle (plugin, __init__.py)
**Contexto:** El plugin bouncer (`~/.hermes/plugins/ultratimonel-preflight/__init__.py`) valida gates de entrada para `record_intento()`, pero `complete_intento()` no verifica que el `intento_id` cerrado pertenezca al turno actual. Esto permite cerrar un intento creado en otro turno, rompiendo la atomicidad del ciclo registrar→completar dentro de un mismo turno.
**Decisión:** En `complete_intento()`, agregar validación que cruce `intento_id` con el `turno_actual` almacenado en sesión. Si el intento no fue registrado durante el turno vigente, rechazar con error explícito.
**Consecuencia:** El ciclo de vida del intento (record → complete) queda encerrado al turno. No se pueden cerrar intentos fantasma de turnos previos ni futuros.

## ADR-006: Consolidated intent flow — 5+ MCP calls down to 2 per turn
**Contexto:** Cada turno actual ejecuta hasta 7 llamadas MCP (assert_gates + record_intento + complete_gate ×4), generando overhead de red, latencia acumulada y mayor superficie de fallo. El agente también mantiene estado manual (gates pass/fail) entre llamadas.
**Decisión:** Introducir dos herramientas consolidadas: `begin_turn(mission_id)` crea un intento con scope de turno y retorna `intento_id`; `end_turn(intento_id)` completa ese intento y valida que pertenece al turno actual. El server internaliza gates, turn-scoping y completado en una sola operación por extremo.
**Consecuencia:** Reducción de 5+ a 2 llamadas MCP por turno. Menos latencia, menos puntos de fallo, estado gestionado por el server. El plugin bouncer debe adaptarse para validar en `begin_turn` en lugar de interceptar cada llamada individual.

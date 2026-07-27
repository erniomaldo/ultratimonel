# endTurn Bouncer — Design

## ADR-001: Activación condicional del bouncer
**Contexto:** La validación debe ser opcional para no romver call sites existentes.
**Decisión:** Los parámetros `session_id` y `project` son strings vacíos por defecto. Solo cuando ambos son non-empty se ejecuta la validación.
**Consecuencia:** Backward compatible. Sin cambios en llamadas existentes.

## ADR-002: Consulta directa a SQLite vs cache del plugin
**Contexto:** El plugin preflight tiene su propio cache de gates. El bouncer server-side podría usar ese cache o consultar la BD directamente.
**Decisión:** Consulta directa a `list_gate_states()` en SQLite. El cache del plugin puede estar desactualizado; la BD es la fuente de verdad.
**Consecuencia:** Lectura adicional a SQLite por cada `complete_intento()` con validación.

## ADR-003: Filtrado mandatory + PASS/SKIP
**Contexto:** No todas las gates son mandatory; algunas pueden estar en SKIP sin ser bloqueantes.
**Decisión:** El filtro es `mandatory=True AND state NOT IN ("PASS", "SKIP")`. SKIP no bloquea.
**Consecuencia:** El bouncer ignora gates no-mandatory y gates saltadas intencionalmente.

## ADR-004: Error response con lista de gates fallando
**Contexto:** El agente necesita saber qué gates fallaron para auto-corregirse.
**Decisión:** El error response incluye `status: "blocked"` y un mensaje con cada gate_name(state): mensaje.
**Consecuencia:** Mensaje legible para el agente, pero no hay campo estructurado `blocking_gates` (solo texto).

## ADR-005: Validación en tool handler, no en persistence layer
**Contexto:** La validación podría estar en `persistence.complete_intento()` o en el tool handler MCP.
**Decisión:** La validación está en el tool handler. `persistence.complete_intento()` solo persiste.
**Consecuencia:** La capa de datos se mantiene pura. Si otro código llama directo a persistence, se salta el bouncer.

## ADR-006: Dedup de gate_state vía MAX(id) en list_gate_states()
**Contexto:** El plugin preflight ejecuta `assert_gates()` en cada turno (pre_llm_call) y escribe en la misma DB. El agente también ejecuta `assert_gates()` (Paso 1 del protocolo). Esto crea entradas duplicadas en `gate_state` para el mismo session_id+gate_name. `list_gate_states()` retornaba todas, y el endTurn bouncer encontraba WARN aunque el último estado fuera PASS.
**Decisión:** Cambiar la query de `list_gate_states()` para usar `WHERE id IN (SELECT MAX(id) ... GROUP BY gate_name)`, devolviendo solo la última fila por gate para el session+project dado.
**Consecuencia:** El bouncer siempre ve el estado más reciente. Las filas históricas se conservan para auditoría en `gate_logs`.

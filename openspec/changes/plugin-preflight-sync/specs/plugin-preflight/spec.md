# Plugin Preflight v2.0.0 — Especificación

## Alcance

Requisitos derivados del código de `ultratimonel/plugin_preflight.py` y
`ultratimonel/plugin.yaml` (v2.0.0). Estos son los comportamientos que el
plugin DEBE implementar para cumplir con el patrón Nikhil Verma de mandatory
tool contracts.

---

## Hooks — 4 hooks obligatorios

El plugin debe registrar exactamente 4 hooks via `register(ctx)`:

| Hook | Función | Obligatorio |
|------|---------|-------------|
| `on_session_start` | `_on_session_start` | Sí |
| `pre_llm_call` | `_pre_llm_call` | Sí |
| `pre_tool_call` | `_gates_bouncer` | Sí |
| `post_tool_call` | `_post_turn_guard` | Sí |

---

## Req-1: on_session_start — inicialización de estado

**SHALL** resetear `_turn_count = 0`, `_turn_ended = False`, `_turn_active =
False`.

**SHALL** ejecutar `ultratimonel_client.assert_gates(session_id, "[session_start]", "plugin")` al iniciar sesión.

**SHALL** cachear el resultado en `_last_gates_result`, `_last_session_id`,
`_last_gates_parsed`.

### Escenario

WHEN se inicia una nueva sesión Hermes
THEN `_turn_count` comienza en 0
AND `_turn_ended` es False
AND los gates iniciales se cachean para uso de `pre_tool_call`

---

## Req-2: pre_llm_call — ejecución de gates por turno

**SHALL** incrementar `_turn_count` en cada llamada.

**SHALL** ejecutar `assert_gates(session_id, message[:500], "plugin")` en cada
llamada (excepto primer turno si ya hay gates cacheadas de `on_session_start`).

**SHALL** cachear el resultado en `_last_gates_result`, `_last_session_id`,
`_last_gates_parsed`.

**SHALL** inyectar resumen de gates via `{"context": summary}` cuando:
- El resumen contiene "BLOCK" o "WARN" (detectado por `gates_summary_has_issues`)
- Es el primer turno (`is_first_turn=True`)

**MAY** retornar `None` cuando no hay issues y no es primer turno.

### Escenario

WHEN un mensaje llega sin que se hayan ejecutado gates en esta sesión
THEN `_last_gates_parsed` es None
AND `pre_tool_call` bloqueará tools críticas (ver Req-4)

WHEN el agente omite incluir el nombre del proyecto en el mensaje
THEN los gates salen SKIP (proyecto unknown)
AND `pre_tool_call` bloquea tools de escritura porque no hay 4/4 PASS

---

## Req-3: Bloqueo sin gates — primer turno

**SHALL** bloquear cualquier tool en `TOOLS_REQUIRING_VERIFIED_GATES` cuando
`_last_gates_parsed is None`.

El mensaje de bloqueo **DEVE** instruir al agente a ejecutar `assert_gates()`
con el nombre del proyecto antes de usar la herramienta.

### Escenario

WHEN se llama `complete_intento` en el primer turno sin gates previas
THEN `_gates_bouncer` retorna action=block con mensaje explicativo
AND la tool NO se ejecuta

---

## Req-4: Grace turns — tolerancia inicial

**SHALL** permitir ejecución de tools críticas durante los primeros `GRACE_TURNS`
turnos (por defecto 3, configurable via env var `ULTRATIMONEL_GRACE_TURNS`).

**SHALL** empezar a bloquear cuando `_turn_count > GRACE_TURNS` y gates no
están todas PASS/SKIP.

### Escenario

WHEN `_turn_count <= GRACE_TURNS`
THEN las tools críticas se permiten aunque gates estén BLOCK/WARN
AND el agente tiene turns para auto-corregirse

WHEN `_turn_count > GRACE_TURNS` Y hay gates mandatory en BLOCK/WARN
THEN `_gates_bouncer` retorna action=block con detalle de gates fallando
AND la tool NO se ejecuta

---

## Req-5: 4/4 complete_intento — patrón endTurn

**SHALL** bloquear `mcp__ultratimonel__complete_intento` cuando `gates_passed <
4`.

**SHALL** bloquear `mcp__ultratimonel__complete_intento` cuando el argumento
`gates_passed != 4`.

El mensaje de bloqueo **DEVE** indicar que se requieren los 4 gates en PASS.

### Escenario

WHEN el agente intenta completar un intento con solo 3/4 gates PASS
THEN `_gates_bouncer` retorna action=block
AND el mensaje indica `solo 3/4 gates han pasado`

WHEN el agente pasa `gates_passed=3` a `complete_intento` cuando hay 4/4 PASS
THEN `_gates_bouncer` bloquea porque `requested != 4`

---

## Req-6: Title lock — deck_update_card

**SHALL** bloquear `mcp__nextcloud__deck_update_card` cuando el argumento
`title` es non-empty.

**SHALL** permitir la tool cuando solo se pasa `description` (sin `title`).

### Escenario

WHEN el agente intenta actualizar una card Deck con `title="Nuevo título"`
THEN `_gates_bouncer` retorna action=block
AND el mensaje indica usar `card_update_description` para cambios de descripción

---

## Req-7: 1 ciclo por respuesta — post_turn_guard

**SHALL** bloquear todas las tools después de que se ejecuta `end_turn`.

**SHALL** permitir `begin_turn` solo si `_turn_active == False` (no duplicado).

**SHALL** establecer `_turn_ended = True` y `_turn_active = False` cuando se
ejecuta `end_turn`.

**SHALL** establecer `_turn_active = True` y `_turn_ended = False` cuando se
ejecuta `begin_turn` exitosamente.

### Escenario

WHEN el agente llama `begin_turn → trabajo → end_turn → trabajo2` en la misma respuesta
THEN `trabajo2` es bloqueada por `_post_turn_guard` con mensaje "TOOL BLOCKED INESCAPABLE"

WHEN el agente llama `begin_turn → begin_turn` en la misma respuesta
THEN el segundo `begin_turn` es bloqueado (turno ya activo)

WHEN una respuesta nueva llega tras `end_turn` de la anterior
THEN `begin_turn` en la nueva respuesta es permitido (flags limpiados entre respuestas)

---

## Req-8: Env var — GRACE_TURNS configurable

**MAY** leer `ULTRATIMONEL_GRACE_TURNS` del entorno.

**SHALL** usar valor por defecto 3 si la variable no está definida.

### Escenario

WHEN `ULTRATIMONEL_GRACE_TURNS=5` está configurada
THEN los primeros 5 turnos permiten execution de tools críticas sin bloquear

---

## Req-9: Inyección de contexto — visibilidad para auto-corrección

**SHALL** siempre inyectar resumen de gates cuando hay BLOCK o WARN.

**SHALL** inyectar resumen en el primer turno independientemente del estado.

El agente necesita visibilidad para auto-corregirse (patrón Nikhil:
self-correction). El `pre_tool_call` bloquea igual, pero la inyección permite
que el agente sepa qué corregir.

### Escenario

WHEN las gates muestran BLOCK en el resumen
THEN `pre_llm_call` retorna `{"context": summary}` con el detalle de bloqueo
AND el agente puede auto-corregirse antes del próximo tool call

---

## Req-10: Tools que requieren gates verificados

**SHALL** aplicar bouncer a exactamente estas tools:

```
TOOLS_REQUIRING_VERIFIED_GATES = {
    "mcp__ultratimonel__complete_intento",
    "mcp__ultratimonel__record_intento",
    "mcp__nextcloud__deck_update_card",
    "mcp__nextcloud__nc_webdav_write_file",
    "mcp__nextcloud__nc_webdav_delete_resource",
    "write_file",
    "patch",
}
```

Tools fuera de este set **MAY** ejecutarse sin verificación de gates.

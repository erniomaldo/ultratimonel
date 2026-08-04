---
name: ultratimonel-ciclo-basico
description: "Usa para turnos trazados: mission_list→begin_turn→end_turn."
version: 1.0.0
license: MIT
tags: [ultratimonel, protocol, begin_turn, end_turn, trazabilidad, session_id]
---

# Ciclo Básico Ultratimonel — sin experimentar

## Trigger

Cualquier turno que deba registrarse en ultratimonel (trabajo real vinculado a una misión de Deck). Cargar ANTES de intentar begin_turn — evita la experimentación con session_id.

## Pasos (orden estricto)

1. `tool_search("ultratimonel mission begin_turn")` → `tool_describe` las tools MCP
2. `mcp__ultratimonel__mission_list(project)` → obtén `mission_id` y `checklist_item_id` (ambos > 0)
3. **session_id** — resuelve en este orden, sin buscar más allá:
   - `echo $HERMES_SESSION_ID` → si devuelve algo, úsalo
   - Si vacío/undefined → **`"default"`** (probado OK 2026-07-29, intento #151)
   - `"current"` solo como legacy (sesiones Matrix 2026-06)
4. `tool_call(mcp__ultratimonel__begin_turn, {session_id, project, mission_id, checklist_item_id, message?, sender?})` → guarda `intento_id`
   - **begin_turn es autocontenido**: ejecuta los 4 gates internamente (assert fresco) y persiste el snapshot en el intento. NO requiere `assert_gates()` manual.
   - `message` y `sender` son opcionales (contexto del assert); llamadas sin ellos siguen funcionando.
5. Trabajar con tools normales
6. `tool_call(mcp__ultratimonel__end_turn, {intento_id, status:"success"})` → **siempre finaliza** (success o fail con gates_detail); nunca deja el turno atascado
7. Presentar resultados al usuario (SIEMPRE al final)

## Ejemplo real (JSON)

```json
{
  "name": "mcp__ultratimonel__begin_turn",
  "arguments": {
    "session_id": "default",
    "project": "ultratimonel",
    "mission_id": 482,
    "checklist_item_id": 2333
  }
}
// → {"status":"ok","intento_id":155,"turno":1}

{
  "name": "mcp__ultratimonel__end_turn",
  "arguments": {"intento_id": 155, "status": "success"}
}
// → {"status":"ok"}
```

## Precedentes verificados (7 sesiones auditadas 2026-07-28 → 2026-07-30)

| Sesión | Modelo | session_id | Resultado |
|---|---|---|---|
| 20260728_161629_c6704b | kwaipilot kat-coder | `$HERMES_SESSION_ID` | ✅ intento 81, "Eres la mamada" |
| 20260728_211911_d823f0 | deepseek-v4-flash | `$HERMES_SESSION_ID` | ✅ intento 136 |
| 20260730_182025_09505b | deepseek-v4-flash | `$HERMES_SESSION_ID` | ✅ intento 155 |
| 20260729_141558_e92dfe | deepseek-v4-flash | `"default"` | ✅ intento 151 |
| 20260730_200925_ec2276 | deepseek-v4-flash | sin misión → reportó sin registrar | ✅ comportamiento correcto |
| 20260728_195917_5906f4 | kwaipilot kat-coder | id de sesión | ❌ múltiples ciclos + sqlite3 directo |
| 20260729_135927_a88bea | deepseek-v4-flash | — | ❌ write_file directo a skill (bypass write_approval) |

**Lección:** el modelo no determina el éxito — el procedimiento sí. Los flujos limpios siguieron los pasos 1-7; los fallos improvisaron.

## Anti-pitfalls

- ❌ `sqlite3` directo a `~/.hermes/ultratimonel.db` — BLOQUEADO por deny patterns. Por algo existe el bloqueo.
- ❌ Buscar session_id en `sessions.json` / filesystem / env dumps — es un workaround.
- ❌ Inventar `mission_id`/`checklist_item_id` — salen de `mission_list`.
- ❌ Múltiples begin_turn/end_turn en el mismo turno (bug conocido en plugin post_tool_call).
- ❌ Cortar procesos background de opencode: el `timeout` del terminal NO mata procesos background (validado 2026-08-02); para dejar terminar a opencode usar `background=true, notify_on_complete=true, timeout=600` + waits encadenados de 60s (`process action='wait'`) hasta `"status": "exited"`. Nunca reiniciar ni matar mientras corre.
- ❌ Escribir skills con `write_file` — solo `skill_manage()` (pasa por write_approval).
- ❌ Cambiar de rama (checkout/branch) sin autorización explícita del usuario — quien administra y autoriza cambios de rama es SIEMPRE el usuario. En ciclos con opencode: el prompt dice "trabaja en la rama actual, NO hagas checkout".
- Si algo falla: **DETENTE, reporta, no parchees** (regla explícita del usuario).

## Verificación

- `begin_turn` → `{"status":"started","intento_id":N,"gates_captured":4,"gates_passed_so_far":N,"overall":"PASS"}` → OK (gates ejecutados frescos)
- `end_turn` → `{"status":"ok","final_status":"success|fail","gates_passed":N,"gates_total":4,"gates":[...]}` → ciclo completo
- `end_turn` **NUNCA bloquea**: si los gates no pasan, completa con `final_status:"fail"` + `gates_detail` (evidencia) y limpia el turno
- `begin_turn` **auto-limpia huérfanos**: si quedó un intento `running` de un ciclo anterior (crash, reinicio), lo cierra como fail antes de crear el nuevo
- El antiguo error "belongs to turn N, but current turn is N+1" (turn count desync) fue **arreglado** con turn-scoping por intento_id + auto-recovery (2026-08-03)

## Relacionados

- `protocolo-de-trazabilidad` — el protocolo completo (v4.1+ incluye esta resolución de session_id)
- `operational-safety` — checklist pre-destrucción

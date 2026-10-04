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

0. **Preflight de skills** (ANTES de todo):
   - `skill_view(name='protocolo-de-trazabilidad')` — flujo completo PAC
   - `skill_view(name='ultratimonel-preflight')` — orden de carga
   - Buscar y cargar **Notes de Nextcloud** del proyecto (NO collectives):
     `mcp__nextcloud__nc_notes_search_notes(query="PAC ultratimonel")`
     `mcp__nextcloud__nc_notes_search_notes(query="ultratimonel")`
   - Cargar al menos la Note del PAC (nota #2380)
1. `tool_search("ultratimonel mission begin_turn")` → `tool_describe` las tools MCP
2. `mcp__ultratimonel__mission_list(project)` → obtén `mission_id` y `checklist_item_id` (ambos > 0)
3. **session_id** — resuelve en este orden, sin buscar más allá:
   - `echo $HERMES_SESSION_ID` → si devuelve algo, úsalo
   - Si vacío/undefined → **`"default"`** (probado OK 2026-07-29, intento #151)
   - `"current"` solo como legacy (sesiones Matrix 2026-06)
4. `tool_call(mcp__ultratimonel__begin_turn, {session_id, project, mission_id, quest_id, message?, sender?})` → guarda `intento_id`
   - **`quest_id` es el 4º posicional canónico** (el alias legacy `checklist_item_id` sigue aceptado).
   - **Guard de quest (falla hard, cero efectos):** si la quest ya está `done` la llamada devuelve `{"error", "code": "quest_done"}` ANTES de cualquier mutación; si no existe: `missing_quest`. Toma la SIGUIENTE quest unchecked o agrega una con `quest_add`.
   - **begin_turn es autocontenido**: ejecuta los 4 gates internamente (assert fresco) y persiste el snapshot en el intento. NO requiere `assert_gates()` manual.
   - `message` y `sender` son opcionales (contexto del assert); llamadas sin ellos siguen funcionando.
5. Trabajar con tools normales
6. `tool_call(mcp__ultratimonel__end_turn, {intento_id, status:"success"})` → **siempre finaliza** (success o fail con gates_detail); nunca deja el turno atascado
   - **`end_turn` es la ÚNICA vía de cierre de quest:** marca la quest del intento `unchecked→checked` (Deck + réplica) y responde compacto (`quest_id`, `quest_done: true|false`). No existe tool de "marcar completado".
7. Presentar resultados al usuario (SIEMPRE al final)

## Tools nuevas (post-migración #189)

- **Escrituras Deck-first** (bridge interno → réplica): `mission_create`, `mission_update_title`, `mission_update_description` (no toca checklist), `quest_add`, `quest_update` (ambas setean el item en unchecked).
- **Sync:** `sync_task(mission_id)` recupera UNA misión desde Deck; `sync_tasks(project)` = barrido; `sync_all` = **deprecado** (registrado con marca).
- **Salidas compactas por default:** `mission_list` (sin descriptions), `mission_get`, `checklist_item_get`; `end_turn` sin `result_data`. No hay flag verbose global.
- **NO existe** tool para marcar quest completado — por diseño: eso es exclusivo de `end_turn`.

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
- ❌ Prohibido monitorear opencode por terminal (`sleep`, cadenas de `process action='wait'`, polling manual). El patrón vigente es **solo MCP**, contra el server por-repo que levanta el humano con `opencode hermes` (puerto de `<repo>/.env.hermes`; instancias MCP por repo: ultratimonel 4597 · voy-rojo 4598 · agenda-base 4599 → tools `mcp__opencode_<repo>__*`).
- **Monitoreo y fin de run — vía MCP:**
  1. `opencode_wait(sessionId, timeoutSeconds=120–600)` → bloquea server-side; retorna al pasar a `idle`.
  2. `opencode_check(sessionId, detailed=true)` → confirmar `idle` + último mensaje coherente.
  Si cicla (mensajes repetidos / no avanza): **reportar al humano**, no matar.
- **Reporte de consumo por run — SIEMPRE al terminar cada run, en UN SOLO RENGLÓN**:
  `input: X | output: Y | costo: $Z | mensajes: N` (X/Y en tokens, $Z en USD, N = nº mensajes).
- **Cómo obtenerlo (procedimiento exacto, sin experimentar):** `opencode_message_list(sessionId, limit=N)` → cada mensaje trae pie `_cost:` con input/output/reasoning y el costo real (`info.cost`). ❌ NO usar `sqlite3` directo a `opencode.db` ni `opencode export`: con MCP el dato sale de la tool.
- **Reglas local vs remoto (lo que SÍ y lo que NO):**
  - SÍ: reportar el costo REAL que reporta opencode si es > $0 (remoto).
  - SÍ: si el costo real es $0 (modelo local), reportar la referencia kwaipilot (= Qwen3.6 Plus ≤256K: $0.50/M entrada, $3.00/M salida, $0.05 cache-read; tabla completa en ~/lsitaprecios.md): `input_M×0.50 + output_M×3.00 + cache_read_M×0.05` (output incluye reasoning).
  - NO: comparar con deepseek ni otros modelos (ruido). NO tablas largas ni multi-renglón — el formato es UN renglón.
- ❌ Escribir skills con `write_file` — solo `skill_manage()` (pasa por write_approval).
- ❌ Cambiar de rama (checkout/branch) sin autorización explícita del usuario — quien administra y autoriza cambios de rama es SIEMPRE el usuario. En ciclos con opencode: el prompt dice "trabaja en la rama actual, NO hagas checkout".
- Si algo falla: **DETENTE, reporta, no parchees** (regla explícita del usuario).

## Delegación a opencode — límites de Hermes (2026-08-11, regla del usuario)

Cuando esté claro que el trabajo se delega a opencode (código en abec-plataforma):

- **NUNCA pasar código a opencode**: ni parches, ni especificaciones de código completo, ni "ayudas" proactivas. Eso es "codificar disfrazado" y mete basura/sesgo a cada sesión.
- **Git es de Hermes (PAC v2, nota #2380):** opencode NUNCA hace commit/push/PR — las operaciones git (rama, commit, push, PR) las ejecuta Hermes como auxiliar del PM; los prompts a opencode llevan «no ejecutes git».
- Hermes SOLO: coordina (prompts MÍNIMOS de contrato — qué desviación corregir, SIN cómo), monitorea vía MCP (`opencode_wait`; ante ciclado **reporta al humano**, no mata) y lleva trazabilidad (begin_turn/end_turn).
- **NO leer código del repo en turnos de delegación**: leer archivos crea sesgo en el contexto de Hermes y le quita el atributo de sabio. La verificación la reporta opencode (tsc/lint/curl) y el QA lo hace el usuario.
- opencode pedirá ayuda SOLO si no puede resolver con sus propios medios (skills en ~/.config/opencode/skills/); entonces Hermes resuelve con herramienta/skill — pero NUNCA con un parche de código al repo.
- Tras cada run: reporte de consumo/costo SIEMPRE (sección Reporte de consumo por run).

## Verificación

- `begin_turn` → `{"status":"started","intento_id":N,"gates_captured":4,"gates_passed_so_far":N,"overall":"PASS"}` → OK (gates ejecutados frescos)
- `end_turn` → `{"status":"ok","final_status":"success|fail","gates_passed":N,"gates_total":4,"gates":[...]}` → ciclo completo
- `end_turn` **NUNCA bloquea**: si los gates no pasan, completa con `final_status:"fail"` + `gates_detail` (evidencia) y limpia el turno
- `begin_turn` **auto-limpia huérfanos**: si quedó un intento `running` de un ciclo anterior (crash, reinicio), lo cierra como fail antes de crear el nuevo
- El antiguo error "belongs to turn N, but current turn is N+1" (turn count desync) fue **arreglado** con turn-scoping por intento_id + auto-recovery (2026-08-03)

## Relacionados

- `protocolo-de-trazabilidad` — el protocolo completo (v4.1+ incluye esta resolución de session_id)
- `operational-safety` — checklist pre-destrucción

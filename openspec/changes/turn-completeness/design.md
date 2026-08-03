# Turn Completeness — Design

## ADR-001: Persistencia de gates en intentos — columna JSON vs tabla separada

**Contexto:** Los intentos necesitan persistir el estado detallado de cada gate
(nombre, estado, mensaje) en el momento del cierre del turno. La tabla
`gate_state` ya existe y contiene el estado actual, pero no un snapshot
point-in-time por intento.

**Alternativas consideradas:**

1. **Columna JSON `gates_detail` en `intentos`**: Snapshot autocontenido en la
   misma fila. Fácil de queryar (`SELECT gates_detail FROM intentos WHERE id=?`).
   Duplica datos de gate_state pero eso es aceptable porque es un snapshot, no
   estado live.

2. **Tabla separada `intentos_gates`**: Normalizada, sin duplicación. Requiere
   JOIN para queryar (`SELECT * FROM intentos i JOIN intentos_gates ig ON...`).
   Más complejo, más operaciones de DB.

3. **Query desde gate_state en runtime**: No persistir nada extra. El dashboard
   ya hace esto (`get_intento_with_gates`). Pero no hay forma de saber qué gates
   tenía el intento EN EL MOMENTO del cierre vs el estado actual (que puede
   haber cambiado).

**Decisión:** Opción 1. Columna JSON `gates_detail` en `intentos`.

**Rationale:**
- Los intentos son snapshots point-in-time de un turno; la duplicación es
  intencional y semánticamente correcta.
- Query simple: el dashboard puede leer `gates_detail` directamente sin JOINs.
- Backward compatible: columna nullable, intentos existentes no se rompen.
- Evita complejidad innecesaria de tabla separada para un dato que no cambia
  después del cierre.

**Consecuencias:**
- Schema migra de v2 a v3 con ADD COLUMN.
- `begin_turn` captura gates y los serializa a JSON al crear el intento.
- `end_turn` actualiza `gates_detail` con el estado final antes de cerrar.
- Dashboard puede leer directamente `gates_detail` sin necesidad de JOIN con
  gate_state (aunque puede hacerlo para enriquecer).

---

## ADR-002: Captura de gates en begin_turn sin llamada extra

**Contexto:** `begin_turn` debe capturar los gates del estado actual para
persistirlos en el intento, pero no debe hacer llamadas extras a MCP servers
ni ejecutar gates nuevamente.

**Alternativas consideradas:**

1. **Leer de `gate_state` existente**: Usar `persistence.list_gate_states()`
   que ya existe y devuelve el estado más reciente por gate. Sin llamadas extras.

2. **Ejecutar assert_gates nuevamente**: Redundante, consume tiempo del agente,
   puede producir resultados diferentes si el contexto cambió.

3. **Esperar a end_turn para capturar**: El snapshot sería del momento del
   cierre, no del inicio. Se pierde la información de gates en el momento
   begin_turn.

**Decisión:** Opción 1. Leer de `gate_state` existente via `list_gate_states()`.

**Rationale:**
- `list_gate_states()` ya existe, es eficiente (usa MAX(id) per gate_name).
- Los gates ya fueron ejecutados por el plugin preflight o por assert_gates
  previo; no hay razón para ejecutarlos de nuevo.
- El snapshot en begin_turn captura el estado inicial; end_turn actualiza con
  el estado final.

**Consecuencias:**
- `begin_turn` es una operación pura de lectura + escritura a intentos.
- No hay latencia adicional por llamadas MCP.
- Si no hay gates previos, `gates_detail` será `[]` y begin_turn igual crea
  el intento (el agente ejecutará gates durante el trabajo).

---

## ADR-003: Turn-scoping server-side — estado global vs DB

**Contexto:** `end_turn` debe validar que el intento que se cierra pertenece al
turno actual (mismo session_id + project). Esto evita el bug de turn count
desync (#482) donde un turno podía cerrar el intento de otro turno.

**Alternativas consideradas:**

1. **Estado global module-level**: Variables `_active_intento_id`,
   `_active_session_id`, `_active_project` en server.py. Simple, rápido, pero
   no survive reinicios de proceso y requiere locking para threaded access.

2. **Tabla `turns` en DB**: Persistir el turno activo en DB. Más robusto pero
   más complejo; requiere nueva tabla y migración.

3. **Validar solo por intento_id**: `end_turn` recibe el intento_id y verifica
   que existe. Pero no previene que un turno cierre el intento de otro turno
   si se conoce el ID.

**Decisión:** Opción 1. Estado global module-level con RLock para thread-safety.

**Rationale:**
- El plugin preflight ya maneja su propio estado de turno (`_turn_active`,
  `_turn_ended`) a nivel de proceso. El estado del server complementa esto.
- Simple y suficiente para el caso de uso: un solo proceso server, turnos
  secuenciales.
- No requiere migración de DB adicional (solo la columna gates_detail).
- Compatible con el patrón existente donde el plugin es la fuente principal
  de enforcement de turno.

**Consecuencias:**
- Se agregan globals `_active_intento`, `_turn_lock` (RLock) en server.py.
- `begin_turn` establece el estado; `end_turn` lo lee y lo limpia.
- Si el proceso se reinicia, el estado se pierde (acceptable: no hay intentos
  'zombie' porque el agente detectaría el fallo).
- El plugin preflight sigue siendo la capa principal de enforcement.

---

## ADR-004: Bouncer endTurn en end_turn vs complete_intento

**Contexto:** `complete_intento` ya tiene un bouncer que valida gates cuando se
pasan `session_id` y `project`. `end_turn` debe tener la misma validación.

**Alternativas consideradas:**

1. **Reutilizar el bouncer de `complete_intento`**: Llamada interna a la lógica
   existente. DRY pero acopla end_turn a complete_intento.

2. **Función separada `_validate_gates_for_completion()`**: Extraer la lógica
   del bouncer a una función reutilizable. Ambas tools la llaman.

3. **Copiar la lógica en end_turn**: Duplicación simple pero clara.

**Decisión:** Opción 2. Función separada `_validate_gates_for_completion()`.

**Rationale:**
- DRY: la lógica de validación vive en un solo lugar.
- Claridad: cada tool tiene su propia responsabilidad, comparten la utilidad.
- Mantenibilidad: si cambia el criterio de validación, se actualiza en un solo
  lugar.

**Consecuencias:**
- Se extrae `_validate_gates_for_completion(session_id, project)` de
  `complete_intento`.
- `end_turn` llama a la misma función.
- `complete_intento` mantiene su interface pública sin cambios.

---

## ADR-006: Firma clásica de end_turn(intento_id, status) con resolución interna desde DB

**Contexto:** La primera iteración de `end_turn` usaba la firma expandida
`(session_id, project, mission_id, checklist_item_id)` — los cuatro campos
que el agente orquestador ya conoce y que se pasan a `begin_turn`. Sin embargo,
esto delega responsabilidad al orquestador: cada llamada requiere pasar 4 args
cuando solo el `intento_id` es estrictamente necesario.

**Alternativas consideradas:**

1. **Firma clásica `end_turn(intento_id, status)`:** Solo el intento_id como
   identificador. Todos los datos de definición se resuelven tras bambalinas
   desde la DB via `get_intento()`. El orquestador solo sabe el ID que recibió
   al iniciar el turno.

2. **Firma expandida `(session_id, project, mission_id, checklist_item_id)`:**
   La que se implementó primero. Más explícita pero más verbosa y frágil: si
   algún arg falla o se pasa incorrectamente, el bouncer de gates no puede
   validar correctamente. Ha demostrado fallar en práctica.

3. **Firma híbrida `(intento_id, session_id, project)`:** Medio término. Aún
   requiere pasar datos que el orquestador ya no debería necesitar conocer.

**Decisión:** Opción 1. Firma clásica `end_turn(intento_id: int, status: str = "success")`.

**Rationale:**
- **No delegar datos de definición al orquestador.** El agente solo necesita
  el `intento_id` que recibió de `begin_turn()`. Todo lo demás (session_id,
  project) se resuelve desde la DB con una sola llamada `get_intento()`.
- **Protocolo documentado:** La firma clásica es consistente con el patrón
  existente de otras tools (`complete_intento(intento_id, ...)`).
- **Turn-scoping preservado:** Se valida que el `intento_id` pasado coincida
  con el turno activo (variable `_active_intento`) antes de resolver desde DB.
- **Bouncer de gates preservado:** Con session_id y project resueltos desde DB,
  la validación de gates obligatorios funciona igual que antes.
- **Backward compat:** `complete_intento` mantiene su firma expandida con
  session_id/project opcionales para quienes quieran usarla directamente.

**Consecuencias:**
- `end_turn` ahora llama a `persistence.get_intento(intento_id)` en el paso 3
  para derivar session_id y project.
- Los tests que llamaban `end_turn("sess", "proj", m, c)` se actualizan a
  `end_turn(intento_id)`.
- El mensaje de error de scoping cambia de "session/project mismatch" a
  "intento_id mismatch".

---

## ADR-005: Migración v2→v3 — ADD COLUMN vs rebuild

**Contexto:** La tabla `intentos` necesita una nueva columna `gates_detail`.

**Alternativas consideradas:**

1. **ADD COLUMN**: `ALTER TABLE intentos ADD COLUMN gates_detail TEXT NULL`.
   Rápido, no pierde datos, estándar SQL.

2. **Rebuild de tabla**: Crear tabla nueva, migrar datos, drop old. Innecesario
   para agregar una columna nullable.

3. **No migrar, usar JSON en otra tabla**: Ir contra el diseño de snapshot.

**Decisión:** Opción 1. `ALTER TABLE` via migration function.

**Rationale:**
- Estándar SQL, rápido, no rompe datos existentes.
- Columna nullable: intentos creados antes de v3 funcionan normal.
- La migración se ejecuta en `_init_db()` cuando `current_ver == SCHEMA_VERSION`
  (asegura que la columna existe incluso en DBs ya actualizadas).

**Consecuencias:**
- `SCHEMA_VERSION` pasa de 2 a 3.
- `DDL_V3_ADDITIONS` contiene el ALTER TABLE.
- `_init_db()` aplica las adiciones v3 cuando corresponde.

---

## ADR-007: EndTurn nunca bloquea — completa con fail; Recuperación de turnos huérfanos

**Contexto:** El bouncer estricto en `end_turn` (ADR-004) causaba un estado
IRRECUPERABLE en producción: cuando los gates mandatory salían WARN o BLOCK,
`end_turn` retornaba `{"status": "blocked"}` y DEJABA el intento en estado
`running` + el turno activo persistido en memoria. El siguiente `begin_turn`
fallaba con "Turno ya activo", requiriendo intervención manual (`delete_intento`).

Síntomas observados:
1. `end_turn(intento_id)` con gates mandatory en WARN → `{status: blocked}` + intento running + turno activo persistido
2. Siguiente `begin_turn` falla: "Turno ya activo (intento #N). Cierra el turno actual."
3. Warning "Failed to capture final gate states" — la captura de gates fallaba en runtime
4. Los gates del server salen WARN porque servicios externos no responden desde la capa de conexión del server — ESO ES ACEPTABLE: el sistema debe registrar el fallo y seguir

**Filosofía del usuario:** El bouncer estricto es DESEADO como RESULTADO (registrar
el fallo), pero NO debe dejar el estado roto. `end_turn` debe SIEMPRE finalizar
el turno: completar el intento con `final_status` real (`"success"` o `"fail"`)
+ `gates_passed` reales + `gates_detail`, y LIMPIAR el estado de turno activo —
pase lo que pase. El fallo de gates se refleja en `final_status=fail`, NUNCA en
un bloqueo permanente del flujo. Firma clásica: `end_turn(intento_id, status="success")`.

**Alternativas consideradas:**

1. **Eliminar bouncer completamente**: `end_turn` siempre completa con el estado
   real de los gates. Si los gates no pasan → `final_status=fail`. Si pasan →
   `final_status=success`. El registro del fallo vive en `gates_detail` y
   `final_status`, nunca en un bloqueo.

2. **Mantener bouncer pero auto-completar**: El bouncer sigue existiendo pero en
   lugar de retornar blocked, completa el intento como fail y limpia el turno.

3. **Recuperación solo en begin_turn**: `begin_turn` detecta turnos huérfanos y
   los cierra como fail antes de iniciar uno nuevo. `end_turn` mantiene el bouncer.

4. **Recuperación dual (elegida)**: Ambas capas se protegen mutuamente —
   `end_turn` nunca bloquea (completa siempre), y `begin_turn` auto-limpia
   turnos huérfanos como defensa adicional contra estados corruptos.

**Decisión:** Opción 4. Recuperación dual con dos capas de defensa:

### Capa 1: end_turn nunca bloquea

- Se elimina el camino `return {"status": "blocked", ...}` de `end_turn`
- Los gates se capturan siempre (try/except en captura y validación)
- Si la captura falla → se registra WARN y se completa con lo que haya (`gates_detail=[]`)
- Se valida gates para logging (también try/except) — si hay fallidos, se loguea pero se completa igual
- `final_status = "success"` solo si `gates_passed >= 4`, sino `"fail"`
- `complete_intento_with_gates()` siempre se ejecuta
- `_clear_active_intento()` siempre se ejecuta al final
- Scoping relajado: si el intento solicitado no es `_active_intento` pero está
  `running` en DB, se recupera auto-completando el activo como fail y cerrando el solicitado

### Capa 2: begin_turn auto-limpia turnos huérfanos

- Si hay un turno activo que no corresponde a la nueva solicitud, se detecta
  como huérfano y se completa como `fail` con `gates_passed=0`
- Se usa `_resolve_requesting_intento()` para verificar si existe un intento
  running en DB para la sesión/proyecto solicitados
- Si no hay coincidencia → auto-cleanup del activo anterior

**Rationale:**
- **NUNCA dejar estado roto.** El sistema siempre queda en un estado recuperable.
- **Firma clásica preservada.** `end_turn(intento_id, status="success")` sin cambios.
- **Defensa en profundidad.** Dos capas de recuperación (end_turn + begin_turn)
  protegen contra diferentes escenarios de corrupción de estado.
- **Registros claros.** Los fallos de gates se reflejan en `final_status=fail` y
  `gates_detail`, no en bloqueos del flujo. El operador puede inspeccionar los
  gates fallidos sin que el sistema quede atascado.
- **Tolerante a fallos de infraestructura.** Si los servicios externos (agentmemory,
  checkpoint, nextcloud) no responden, los gates salen WARN y el turno se cierra
  como fail — el siguiente turno puede iniciar normal.

**Consecuencias:**
- `end_turn` ahora tiene 3 llamadas a DB en el camino feliz: `get_intento`,
  `list_gate_states` (captura), `_validate_gates_for_completion` → `list_gate_states`
  (validación), `complete_intento_with_gates`.
- Ambos métodos (`capture` y `validation`) tienen try/except para no bloquear.
- `begin_turn` ahora llama a `_resolve_requesting_intento()` y posiblemente a
  `complete_intento()` para cleanup huérfano antes de crear el nuevo intento.
- Tests actualizados: `test_end_turn_blocked_by_block_gate` → verifica fail en vez de blocked.
- Nuevos tests: WARN gates, gate capture failure, orphan recovery, begin after fail.

**Comportamiento post-fix:**

| Escenario | Antes (ROTO) | Después (FIXED) |
|-----------|-------------|----------------|
| Gates PASS 4/4 | success + limpio | success + limpio |
| Gates WARN 3/4 mandatory | **blocked + running** | fail + limpio |
| Gates BLOCK 1 mandatory | **blocked + running** | fail + limpio |
| list_gate_states falla | error + running | fail (gates=[]) + limpio |
| Turno huérfano en memoria | begin_turn bloquea | begin_turn auto-limpia |
| end_turn de intento running no-activo | scoping error | recovery: cierra el running |

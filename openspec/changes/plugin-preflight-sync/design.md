# Plugin Preflight Sync — Design

## ADR-007: Source-of-truth — repo vs runtime

**Contexto:** El plugin `ultratimonel-preflight` vive en el repositorio de
`ultratimonel` (`ultratimonel/plugin_preflight.py`), pero se instala copiando
el archivo a la carpeta de plugins del agente
(`~/.hermes/plugins/ultratimonel-preflight/__init__.py`). El 28-jul el plugin
fue parchado en runtime sin reflejarse en el repo, creando un desync.

**Alternativas consideradas:**
1. Plugin vive en la config del agente (carpeta de plugins) — simple pero causa
   desync cuando el repo avanza.
2. Plugin vive en el repo y se carga directamente desde ahí — requiere que el
   agente soporte paths relativos al proyecto.
3. Plugin vive en el repo y se despliega copiando desde el repo a la instalación
   — mantiene el repo como fuente de verdad, la instalación como destino.

**Decisión:** Opción 3. El plugin DEBE vivir en el repo de ultratimonel (donde
se descarga el proyecto). La instalación del agente carga desde el repo
mediante copia de despliegue. Copiarlo a la config del agente como fuente hace
que deje de actualizarse cuando el repo avanza (desync). El repo es la única
fuente de verdad; la instalación del agente debe cargar desde el repo.

**Consecuencias:**
- Cualquier fix al plugin va primero al repo (commit + PR).
- El deploy siempre copía **desde** el repo **hacia** `~/.hermes/plugins/`.
- Si se detecta desync, el fix es portar del runtime AL repo, no al revés.
- La regla anti-desync está documentada en README.md sección Plugin preflight.

---

## ADR-008: Double assert_gates — plugin y agente

**Contexto:** Tanto el plugin preflight (`pre_llm_call`) como el agente (Paso 1
del protocolo SOUL.md) ejecutan `assert_gates()` de forma independiente. Ambos
escriben en la misma DB SQLite (`ULTRATIMONEL_DB_PATH`). Esto crea entradas
duplicadas en `gate_state` para el mismo session_id+gate_name.

**Alternativas consideradas:**
1. Solo el agente ejecuta assert_gates — el plugin solo lee. Simple pero el
   plugin no puede cachear gates para pre_tool_call sin ejecutarlas.
2. Solo el plugin ejecuta assert_gates — el agente se salta Paso 1. Rompe el
   protocolo SOUL.md establecido.
3. Ambos ejecutan assert_gates y la DB maneja duplicados — redundante pero
   consistente con el diseño de doble verificación.

**Decisión:** Opción 3. Ambos ejecutan assert_gates independientemente. El
plugin necesita su propia ejecución para cachear gates y alimentar
`pre_tool_call`. El agente necesita ejecutarlas para su protocolo interno.
La DB maneja duplicados; `list_gate_states()` usa `MAX(id)` para devolver solo
el estado más reciente (ver ADR-006 en change endturn-bouncer).

**Consecuencias:**
- Lectura/escritura adicional a SQLite por cada turno (plugin + agente).
- El plugin puede ver WARN si su subprocess no tiene acceso a los mismos MCP
  servers que el agente. Para evitar inconsistencias, `list_gate_states()` usa
  `MAX(id)`.
- La redundancia es intencional: doble verificación aumenta la robustez del
  enforcement.

---

## ADR-009: Grace turns — tolerancia para auto-corrección

**Contexto:** Cuando el agente no ejecuta `assert_gates()` correctamente (p.
ej. omite el nombre del proyecto en el mensaje), los gates salen SKIP o BLOCK.
Si el plugin bloquea inmediatamente, el agente nunca tiene oportunidad de
corregirse.

**Alternativas consideradas:**
1. Bloqueo inmediato sin grace turns — enforcement estricto pero el agente se
   queda trabado si comete un error.
2. Grace turns configurable (N turnos) — permite auto-corrección antes del
   bloqueo.
3. Solo warn sin bloqueo — demasiado permisivo, pierde el enforcement.

**Decisión:** Opción 2. `GRACE_TURNS=3` por defecto, configurable via env var
`ULTRATIMONEL_GRACE_TURNS`. Los primeros N turnos permiten execution de tools
críticas aunque gates no estén PASS. Después de N turnos, el bouncer bloquea
si hay gates mandatory en BLOCK/WARN.

**Consecuencias:**
- El agente tiene hasta 3 turnos (por defecto) para auto-corregirse sin
  interrupción.
- Después de grace turns, el enforcement es estricto: tools críticas bloqueadas
  si gates no están PASS/SKIP.
- La variable de entorno permite ajustar el valor según el entorno (p. ej.
  producción vs desarrollo).

---

## ADR-010: Post-turn guard — bloqueo inescapable tras end_turn

**Contexto:** El patrón de turno correcto es `begin_turn → trabajo → end_turn`
(1 ciclo por respuesta). Sin enforcement, el agente puede:
- Llamar `begin_turn` duplicado en la misma respuesta
- Llamar `end_turn` sin trabajo intermedio
- Llamar tools después de `end_turn` (rompiendo el ciclo)

**Alternativas consideradas:**
1. Validación solo server-side en `complete_intento()` — el bouncer del plugin
   no puede bloquear tools arbitrarias, solo las que conoce.
2. Hook `post_tool_call` en el plugin — corre en el runtime de Hermes, tiene
   acceso a todas las tool calls, puede bloquear cualquier tool.
3. Validación en el protocolo SOUL.md — depende de la disciplina del agente,
   no hay enforcement técnico.

**Decisión:** Opción 2. Hook `post_tool_call` → `_post_turn_guard`. Corre en
el runtime de Hermes, tiene visibilidad de TODAS las tool calls. Detecta
`end_turn` para marcar `_turn_ended=True`, bloquea cualquier tool tras eso
hasta que se llame a `begin_turn` (nuevo ciclo). También bloquea
`begin_turn` duplicado en la misma respuesta.

**Consecuencias:**
- Bloqueo inescapable: el agente NO puede saltarse `_post_turn_guard` porque
  corre en el runtime de Hermes, no en el código del agente.
- Patrones bloqueados:
  - `begin_turn → begin_turn` (duplicado en misma respuesta)
  - `begin_turn → end_turn` (sin trabajo intermedio)
  - `begin_turn → trabajo → end_turn → trabajo2` (tool tras end_turn)
- Regla: 1 ciclo por respuesta. Entre respuestas: end_turn de la anterior,
  begin_turn de la nueva ✅.

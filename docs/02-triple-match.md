# Triple Match: 1a + 1b + 1e

> **Propósito:** Los 3 gates base que Ultratimonel debe verificar antes de permitir generación.

## Gate 1a — AgentMemory Recall

**Qué hace:** Busca memoria relevante del sender/tópico actual.

**Tool:** `mcp_agentmemory_memory_smart_search(query, limit)`

**Frecuencia:** Cada mensaje.

**Respuesta esperada:**
- Preferencias del usuario
- Decisiones pasadas sobre el tema
- Correcciones anteriores
- Contexto de sesiones previas

**Si falla (no hay resultados):** Continúa — es normal en primer contacto.

---

## Gate 1b — Checkpoint Status

**Qué hace:** Obtiene el estado del proyecto/contexto activo desde AgentCheckpoint.

**Tool:** `mcp_checkpoint_get_state(key=active_project)`

**Frecuencia:** Cada mensaje.

**Respuesta esperada:**
- Proyecto activo actual
- Última acción completada
- Fase del workflow actual
- Datos de sesión persistentes

**Si falla (no hay checkpoint):** Crea checkpoint inicial con estado "nuevo".

---

## Gate 1e — Deck Scan

**Qué hace:** Escanea las cards abiertas/pendientes del proyecto activo en Nextcloud Deck.

**Tool:** `mcp_nextcloud_deck_get_boards()` + `deck_get_stacks()`

**Frecuencia:** Cada mensaje.

**Respuesta esperada:**
- Cards pendientes del proyecto
- Cards bloqueadas
- Cards en progreso
- Labels y prioridades

**Si falla (proyecto sin Deck):** Omite — no todos los proyectos tienen board asociado.

---

## Flujo de Ejecución

```
1. Identificar sender y tópico del mensaje
2. [1a] AgentMemory recall(query=sender+topic)
3. [1b] Checkpoint get_state(key=project)
4. [1e] Deck scan(project)
5. Compilar contexto unificado
6. [Si aplica] mcp-capabilities search(query)
7. Generar respuesta con contexto completo
8. Post-generación: guardar checkpoint actualizado
```

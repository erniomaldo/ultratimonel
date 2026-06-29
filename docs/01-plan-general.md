# Plan 2+1: Ultratimonel + Pre-flight Enforcement

> **Estado:** Borrador · **Última actualización:** 28 Jun 2026
> **Propósito:** Hacer que Hermes consulte memoria/estado ANTES de inferir, sin depender de que "recuerde" hacerlo.

## Estrategia General

Dos capas independientes que se refuerzan mutuamente:

### Capa 1 — Ultratimonel (MCP Mission Gate)
Un MCP server que registra tools para verificar el estado del contexto antes de permitir generación.

### Capa 2 — SOUL.md Enforcement
Reglas duras en la identidad del agente (SOUL.md) que exigen llamar a las gates de Ultratimonel antes de generar.

## Gates Definidas

| ID | Gate | Fuente | ¿MVP? |
|----|------|--------|:-----:|
| 1a | AgentMemory recall | `mcp_agentmemory_memory_recall` | ✅ |
| 1b | Checkpoint status | `mcp_checkpoint_get_state` | ✅ |
| 1b.1 | mcp-capabilities search | `search_capabilities()` vía mcp-capabilities-server | 🔜 Post-MVP |
| 1c | Session search | `session_search` (solo si no cubierto por 1b.1) | ❌ Condicional |
| 1d | Skills match | Skills del contexto (solo si no cubierto por 1b.1) | ❌ Condicional |
| 1e | Deck scan | `mcp_nextcloud_deck_get_boards` | ✅ |

**Triple match ideal mínimo:** 1a + 1b + 1e

## Frecuencia de Ejecución

- **2a:** Al inicio de cada sesión ✅
- **2b:** Antes de cada mensaje ✅ (más costoso pero más resistente a inferencia)
- **2c:** Al detectar cambio de proyecto — no aplica con 2a+2b

## Comportamiento ante Falla

- **3a:** Bloquear generación si un gate no pasa ✅
- **3b:** Ejecutar gates automáticamente ✅
- **3c:** Advertir al usuario si falta contexto ✅

## Integración

- **4a:** SOUL.md (siempre cargado) ✅
- **4b:** AGENTS.md ❌
- **4c:** Ambos ❌

## Estrategia de Respaldo

Si el LLM logra ignorar las gates de SOUL.md, se activa la estrategia n8n:
→ `🧠 Mi Mundo` → *Estrategia n8n > Hermes — Pre-flight Context Pipeline*

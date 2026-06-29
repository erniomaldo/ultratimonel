# Pre-flight Flow

> **Propósito:** Diagrama de flujo completo del pipeline pre-mensaje.

## Secuencia

```
[Usuario envía mensaje]
        │
        ▼
┌─────────────────────────────────────────────┐
│        PRE-FLIGHT PROTOCOL                   │
├─────────────────────────────────────────────┤
│                                              │
│  1. Extraer sender + tópico + proyecto       │
│     del mensaje actual                       │
│                                              │
│  2. [GATE 1a] AgentMemory recall             │
│     ├── smart_search(sender+topic)           │
│     └── ¿Resultados? → inyectar contexto     │
│                                              │
│  3. [GATE 1b] Checkpoint get_state           │
│     ├── get_state(active_project)            │
│     └── ¿Checkpoint existe? → cargar estado  │
│         ¿No existe? → crear nuevo            │
│                                              │
│  4. [GATE 1e] Deck scan                     │
│     ├── get_boards → filtrar proyecto        │
│     │   get_stacks → cards pendientes        │
│     └── Inyectar cards relevantes            │
│                                              │
│  5. [GATE 1b.1 - opcional] mcp-capabilities │
│     ├── search_capabilities(task_query)      │
│     └── Inyectar tools relevantes            │
│                                              │
│  6. Compilar CONTEXT ENVELOPE final          │
│     ┌──────────────────────────┐             │
│     │ • Memory snippets        │             │
│     │ • Checkpoint state       │             │
│     │ • Deck cards             │             │
│     │ • Relevant tools         │             │
│     └──────────────────────────┘             │
│                                              │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│        GENERACIÓN                            │
│  (solo después de que todos los gates        │
│   obligatorios pasaron)                      │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│        POST-GENERACIÓN                       │
│  - Guardar checkpoint actualizado            │
│  - (Opcional) refresh_index en              │
│    mcp-capabilities si hubo cambios          │
└─────────────────────────────────────────────┘
```

## Estados de Gate

| Estado | Significado | Acción |
|--------|-------------|--------|
| ✅ PASS | Gate completado | Continuar |
| ⏭️ SKIP | Gate no aplica | Continuar |
| ⚠️ WARN | Gate falló pero no crítico | Advertir y continuar |
| ❌ BLOCK | Gate falló y es obligatorio | NO generar — ejecutar gate o informar |

## Variables de Contexto

```
SESSION.sender = "erniomaldo"
SESSION.topic = "ultratimonel gates"
SESSION.project = "ultratimonel"
SESSION.gates_passed = [1a, 1b, 1e]
SESSION.gates_blocked = []
SESSION.memory_context = [...]
SESSION.checkpoint_state = {...}
SESSION.deck_cards = [...]
SESSION.tools_available = [...]
```

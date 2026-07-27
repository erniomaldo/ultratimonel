# Ultratimonel — Pre-flight Gate Enforcement + Missions + Dashboard

**Ultratimonel** es un servidor MCP (Model Context Protocol) que implementa el
protocolo **pre-flight** para Hermes Agent. Actúa como un "guardia de
seguridad" que se ejecuta **antes de cada generación** del LLM, verificando que
el agente haya consultado memoria, checkpoint, steering docs y el tablero de
tareas antes de responder.

Además del enforcement de gates, Ultratimonel proporciona:

- **Dashboard web** (NES.css) para visualizar misiones y gates
- **Sistema de Misiones** sincronizado con Nextcloud Deck
- **endTurn Bouncer** — validación server-side en `complete_intento()`
- **Card update** seguro — actualiza descripciones sin pisar títulos

---

## Cómo funciona

### El plugin pre-flight (SOUL.md)

Ultratimonel NO es opcional en el flujo de Hermes. El archivo
[SOUL.md](../../SOUL.md) contiene el **Protocolo de Respuesta — Hábito
Irrompible** que exige ejecutar `assert_gates()` al inicio de CADA mensaje.
Sin esto, el agente no tiene contexto de memoria, checkpoint ni tareas
activas.

```
[Mensaje del usuario]
        │
        ▼
┌──────────────────────────────────────────┐
│  1. assert_gates() — OBLIGATORIO         │
│     ├── Gate 1a: AgentMemory             │
│     ├── Gate 1b: Checkpoint              │
│     ├── Gate 1c: Steering Docs (opcional)│
│     └── Gate 1e: Deck (tareas activas)   │
├──────────────────────────────────────────┤
│  2. Generación del LLM (si gates PASS)   │
├──────────────────────────────────────────┤
│  3. complete_intento() — endTurn bouncer │
│     └── Valida gates en DB antes de      │
│         marcar intento como completado    │
└──────────────────────────────────────────┘
```

Si `assert_gates()` retorna algún gate en estado BLOCK, el protocolo impide
la generación. El agente **no puede responder** hasta que resuelva los gates
bloqueantes.

---

## Integración con Hermes Agent

Para usar Ultratimonel con el stack completo (plugin preflight + SOUL.md), se
requiere:

### 1. MCP Server en config.yaml

```yaml
mcp_servers:
  ultratimonel:
    command: /path/to/ultratimonel/.venv/bin/python3
    args:
      - /path/to/ultratimonel/main.py
    timeout: 120
    env:
      ULTRATIMONEL_DB_PATH: /home/usuario/.hermes/ultratimonel.db
      ULTRATIMONEL_CHECKPOINT_COMMAND: agentcheckpoint
      ULTRATIMONEL_CHECKPOINT_ARGS: ''
      ULTRATIMONEL_NEXTCLOUD_COMMAND: /path/to/ultratimonel/.venv/bin/python3
      ULTRATIMONEL_NEXTCLOUD_ARGS: /path/to/http-to-stdio/http_to_stdio_mcp.py
      ULTRATIMONEL_NEXTCLOUD_URL: https://tudominio.com/mcp
      ULTRATIMONEL_NEXTCLOUD_TIMEOUT: '600'
      ULTRATIMONEL_NEXTCLOUD_HEADERS: '{"Authorization": "Bearer tu-token"}'
    idle_timeout_seconds: 900
    max_lifetime_seconds: 86400
```

### 2. Plugin preflight (`ultratimonel-preflight`)

El plugin implementa el patrón **Nikhil Verma de mandatory tool contracts**.
Requiere 3 archivos en `~/.hermes/plugins/ultratimonel-preflight/`:

| Archivo | Propósito |
|---------|-----------|
| `plugin.yaml` | Declaración del plugin (nombre, versión, hooks) |
| `__init__.py` | Lógica: `pre_llm_call` ejecuta gates, `pre_tool_call` bouncer bloquea tools sin gates PASS |
| `ultratimonel_client.py` | Cliente MCP stdio para comunicación con el server ultratimonel |

**plugin.yaml:**
```yaml
name: ultratimonel-preflight
version: 1.1.0
description: >-
  Implementa el patrón Nikhil Verma de mandatory tool contracts en Hermes.
  pre_tool_call bouncer bloquea tools críticas si assert_gates no se ha
  ejecutado o si las 4 gates no están PASS.
author: "Ultratimonel"
provides_hooks:
  - on_session_start
  - pre_llm_call
  - pre_tool_call
```

### 3. Activar en config.yaml

```yaml
plugins:
  enabled:
    - ultratimonel-preflight
  entries:
    ultratimonel-preflight:
      allow_tool_override: false
```

### 4. Protocolo SOUL.md

El archivo `~/.hermes/SOUL.md` debe incluir el **Protocolo de Respuesta —
Hábito Irrompible** que exige ejecutar `assert_gates()` al inicio de cada
mensaje y `record_intento()` + `complete_intento()` al finalizar.

Ver `scripts/deploy_soul.sh` para despliegue automatizado.

### 5. Flujo completo por turno

```
1. Plugin (automático): pre_llm_call → assert_gates() → inyecta contexto gates
2. Agente: Paso 1 → assert_gates() refresca contexto
3. Agente: Trabajo del turno (tools, respuestas)
4. Agente: Paso 5 → record_intento() + complete_intento()
5. Plugin (automático): pre_tool_call bouncer → bloquea si gates no PASS
```

Nota: el plugin y el agente ejecutan `assert_gates()` de forma independiente.
Ambos escriben en la misma DB (`ULTRATIMONEL_DB_PATH`). El agente ve las gates
PASS desde el MCP server de Hermes; el plugin puede ver WARN si su subprocess
no tiene acceso a los mismos MCP servers. Para evitar inconsistencias,
`list_gate_states()` usa `MAX(id)` para devolver solo el estado más reciente
(ver ADR-006).

---

## Gates

| Gate | Fuente | Mandatory | Propósito |
|------|--------|-----------|-----------|
| **1a** | `mcp_agentmemory_memory_smart_search` | ✅ Sí | Recuperar memoria relevante del proyecto/sender |
| **1b** | `mcp_checkpoint_get_state` | ✅ Sí | Obtener checkpoint de estado del proyecto activo |
| **1c** | `mcp_nextcloud_collectives_get_pages` | ❌ No | Cargar steering docs desde Nextcloud Collective |
| **1e** | `mcp_nextcloud_deck_get_boards` | ✅ Sí | Listar tareas activas desde Nextcloud Deck |

### Estados

| Estado | Significado | Acción |
|--------|-------------|--------|
| `PASS` | Gate completó exitosamente | Continuar |
| `SKIP` | Gate no aplica / N/A | Continuar |
| `WARN` | Gate falló (no crítico) | Advertir + continuar |
| `BLOCK` | Gate falló (mandatory) | **Detener generación** |

---

## Tools (16)

Ultratimonel expone 16 MCP tools:

### Núcleo (Gates)

| Tool | Descripción |
|------|-------------|
| `assert_gates(message, session_id, sender)` | Ejecuta los 4 gates y retorna resultados estructurados |
| `check_gate(name, session_id)` | Lee el estado de un gate desde SQLite |
| `complete_gate(name, session_id, reason)` | Marca manualmente un gate como PASS (solo desde BLOCK/WARN) |

### Dashboard

| Tool | Descripción |
|------|-------------|
| `server(action)` | Controla el servidor web del dashboard (start/stop/status) |

### Project Maps

| Tool | Descripción |
|------|-------------|
| `map_list()` | Lista proyectos configurados en `project_maps.json` |
| `map_add(project, deck_board_name, collective_name, ...)` | Agrega o actualiza un proyecto |
| `map_remove(project)` | Elimina un proyecto |
| `map_setup()` | Descubre boards/collectives disponibles para mapeo |
| `map_sync()` | Verifica que los IDs de boards sigan existiendo |

### Misiones / Deck Sync

| Tool | Descripción |
|------|-------------|
| `sync_tasks(project)` | Sincroniza cards de Deck → tabla missions para un proyecto |
| `sync_all()` | Sincroniza todos los proyectos mapeados |
| `mission_list(project)` | Lista misiones (Deck tasks) de un proyecto |

### Intentos (ciclos assert_gates)

| Tool | Descripción |
|------|-------------|
| `record_intento(session_id, project, mission_id, checklist_item_id)` | Crea un intento para un checklist item |
| `complete_intento(intento_id, status, gates_passed, session_id, project)` | Finaliza un intento con validación endTurn bouncer |
| `delete_intento(intento_id)` | Elimina un intento por ID |

### Deck Cards

| Tool | Descripción |
|------|-------------|
| `card_update_description(card_id, description, board_id, stack_id)` | Actualiza solo la descripción de una card — NUNCA cambia el título |

---

## Arquitectura

```
ultratimonel/
├── main.py                          # Entry point (stdio transport)
├── requirements.txt                 # fastmcp, httpx
├── pyproject.toml                   # Package metadata
├── pytest.ini                       # Test config
├── project_maps.json.template       # Template para mapeo de proyectos
├── .spec -> ~/.spec                 # Symlink a spec externa
├── ultratimonel/
│   ├── __init__.py                  # Package metadata
│   ├── server.py                    # FastMCP — 16 tool handlers
│   ├── persistence.py               # SQLite layer (WAL, 9 tablas, migrations)
│   ├── gate_engine.py               # State machine: PASS/SKIP/WARN/BLOCK
│   ├── triple_match.py              # Orquestación de gates 1a→1b→1c→1e
│   ├── context_extractor.py         # Mensaje → sender/topic/project
│   ├── config_loader.py             # Carga project_maps.json externo
│   ├── mcp_client.py                # Cliente HTTP para MCP calls externos
│   ├── bridge.py                    # Bridge hacia mcp-capabilities
│   ├── dashboard_server.py          # Servidor HTTP (stdlib) del dashboard
│   └── dashboard/
│       ├── __init__.py
│       ├── index.html               # Dashboard web (NES.css v2.3.0)
│       └── app.js                   # Lógica JS del dashboard
├── scripts/
│   └── deploy_soul.sh               # Inyección de reglas SOUL.md
├── openspec/
│   ├── config.yaml                  # Configuración de OpenSpec
│   ├── specs/                       # Especificaciones SDD
│   └── changes/                     # Propuestas de cambio (PAC)
├── docs/
│   ├── 01-plan-general.md
│   ├── 02-triple-match.md
│   ├── 03-mcp-capabilities.md
│   ├── 04-soul-enforcement.md
│   ├── 05-preflight-flow.md
│   └── 06-initialization-guide.md
└── tests/
    ├── test_gate_engine.py
    ├── test_context_extractor.py
    ├── test_persistence.py
    ├── test_triple_match.py
    ├── test_server.py
    └── test_integration.py
```

---

## Base de datos

SQLite con WAL journal mode. Ruta por defecto: `~/.hermes/ultratimonel.db`
(configurable via `ULTRATIMONEL_DB_PATH`).

### 9 tablas

| Tabla | Propósito |
|-------|-----------|
| `schema_version` | Migrations (version + description) |
| `sessions` | Contexto por generación |
| `gate_state` | Estado por gate por session+project |
| `gate_logs` | Traza de auditoría de transiciones de estado |
| `checkpoints` | Snapshots de triple-match |
| `actions` | Acciones registradas por el agente |
| `missions` | Ciclo de vida de misiones (sincronizadas desde Deck) |
| `checklist_items` | Items de checklist dentro de cada misión |
| `intentos` | Intentos/ciclos de assert_gates por checklist item |

### Parámetros

- WAL journal mode
- NORMAL synchronous
- 5s busy timeout
- Migrations incrementales vía `schema_version`

---

## Dashboard

El dashboard web corre en un servidor **http.server** (stdlib, no FastAPI),
puerto por defecto **3005** (configurable via `ULTRATIMONEL_DASHBOARD_PORT`).

Interfaz NES.css v2.3.0 con:

- Lista de proyectos con estado de gates
- Tablero de misiones con progreso
- Detalle de intentos por checklist item
- Light/dark theme

```
server(action="start")   # Inicia el dashboard
server(action="stop")    # Lo detiene
server(action="status")  # Estado actual
```

---

## endTurn Bouncer

Validación server-side en `complete_intento()`. Cuando se proporcionan
`session_id` y `project`, la función consulta `list_gate_states()` en SQLite
para verificar que **todas las gates mandatory estén PASS o SKIP**.

Si alguna gate mandatory está BLOCK o WARN, la función retorna
`status: "blocked"` con la lista de gates fallando, impidiendo la
completación del intento.

**Parámetros nuevos en `complete_intento()`:**

- `session_id` (str, default `""`) — solo valida si es non-empty
- `project` (str, default `""`) — solo valida si es non-empty

Esto garantiza backward compatibility: llamadas existentes sin estos
parámetros siguen funcionando sin validación.

---

## Project Maps (configuración)

**No edites código para configurar proyectos.** Toda la configuración de
proyectos vive en `~/.hermes/ultratimonel/project_maps.json` (configurable
via `ULTRATIMONEL_PROJECT_MAPS`).

Usa las tools MCP para gestionar proyectos:

```bash
map_setup()         # Descubre boards/collectives
map_add("mi-proyecto", deck_board_name="Mi Board", ...)
map_list()
map_sync()
```

---

## Quick Start

```bash
# Entorno
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Ejecutar (stdio transport)
python main.py

# Ruta DB personalizada
ULTRATIMONEL_DB_PATH=/tmp/test.db python main.py

# Tests
python -m pytest tests/ -v
```

### Variables de entorno

| Variable | Default | Propósito |
|----------|---------|-----------|
| `ULTRATIMONEL_DB_PATH` | `~/.hermes/ultratimonel.db` | Ruta a SQLite |
| `ULTRATIMONEL_PROJECT_MAPS` | `~/.hermes/ultratimonel/project_maps.json` | Config de proyectos |
| `ULTRATIMONEL_DASHBOARD_PORT` | `3005` | Puerto del dashboard |

---

## Dependencias

- Python ≥ 3.13
- `fastmcp` — Framework MCP
- `httpx` — Cliente HTTP para calls MCP externas (Deck)
- `sqlite3` — Persistencia (stdlib)

---

## Licencia

MIT

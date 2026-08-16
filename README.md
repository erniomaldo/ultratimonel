# Ultratimonel 🛡️

<div align="center">

![Ultratimonel](docs/logo.png)

**Pre-flight gate enforcement + Missions + Dashboard para [Hermes Agent](https://hermes-agent.nousresearch.com/docs).**

Un guardián que se ejecuta **antes de cada generación del LLM** para que el agente
nunca responda sin memoria, checkpoint, steering docs ni tareas activas.

[![MCP Server](https://img.shields.io/badge/MCP%20Server-7B3FF2?logo=modelcontextprotocol&logoColor=white)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](pyproject.toml)
[![Language](https://img.shields.io/github/languages/top/erniomaldo/ultratimonel)](https://github.com/erniomaldo/ultratimonel)
[![Repo Size](https://img.shields.io/github/repo-size/erniomaldo/ultratimonel)](https://github.com/erniomaldo/ultratimonel)

🌐 **Español** · [🇺🇸 English](README.en.md)

</div>

---

## 📚 Tabla de contenidos

- [🤔 El problema](#el-problema)
- [✅ La solución](#la-solucion)
- [✨ Características](#caracteristicas)
- [🚀 Quick Start — instalación nueva](#quick-start)
- [🔄 El ciclo por turno](#ciclo-por-turno)
- [🛠️ Tools (MCP API)](#tools)
- [🗄️ Gates y estados](#gates)
- [🔌 Integración con Hermes Agent](#integracion)
- [⚙️ Configuración](#configuracion)
- [🏗️ Arquitectura](#arquitectura)
- [🗃️ Base de datos](#base-de-datos)
- [📊 Dashboard](#dashboard)
- [🧪 Desarrollo](#desarrollo)
- [📦 Dependencias](#dependencias)
- [📜 Licencia](#licencia)

---

<a id="el-problema"></a>
## 🤔 El problema

Los agentes de IA generan respuestas con **contexto incompleto**: no consultan su memoria
de proyecto, no verifican el checkpoint de estado, no leen las tareas activas. El resultado:

| Problema | Qué pasa | Consecuencia |
|----------|----------|--------------|
| Memoria no consultada | El agente responde sin saber el historial del proyecto | Respuestas que ignoran decisiones previas |
| Checkpoint ignorado | El agente no sabe en qué fase quedó el trabajo | Retoma en el lugar equivocado |
| Tareas sin leer | El agente desconoce las cards activas del tablero | Trabajo duplicado o fuera de alcance |
| Sin rendición de cuentas | Cada turno es una isla, sin trazabilidad | Imposible auditar qué se hizo y cuándo |

**Bottom line:** agentes que responden "de memoria" (o sin memoria), trabajos que se
repiten, y cero trazabilidad de qué intento completó qué tarea.

---

<a id="la-solucion"></a>
## ✅ La solución

Ultratimonel es un **servidor MCP + plugin de enforcement** que obliga al agente a pasar
por un ciclo trazado en cada turno: consultar las 4 fuentes de contexto, registrar un
**intento** vinculado a una tarea real (misión + checklist item de Nextcloud Deck), y
cerrar el turno con verificación de gates.

```
┌──────────────┐   MCP stdio    ┌──────────────────┐    SQLite WAL    ┌──────────────┐
│  Hermes      │ ──────────────→│  Ultratimonel    │ ──────────────→│              │
│  Agent       │                │  MCP Server      │                 │ ultratimonel │
│  + plugin    │ ←──────────────│  (18 tools)      │ ←──────────────│ .db (1 file) │
│  preflight   │                │                  │                 │              │
└──────────────┘                └─────────┬────────┘                 └──────────────┘
                                          │
                              ┌───────────┼───────────┐
                              ▼           ▼           ▼
                        AgentMemory   Checkpoint   Nextcloud
                        (Gate 1a)     (Gate 1b)    Deck (1e) + Collective (1c)
```

**El ciclo por turno es de 2 llamadas** (antes eran 5+):

```
begin_turn()  →  trabajo del turno  →  end_turn()  →  reporte al usuario
```

> [!IMPORTANT]
> Ultratimonel **no es opcional** en el flujo de Hermes: el plugin `ultratimonel-preflight`
> bloquea tools si los gates no están PASS, y el `post_tool_call` fuerza el ciclo
> begin → trabajo → end por respuesta. No hay "modo desactivado".

---

<a id="caracteristicas"></a>
## ✨ Características

| Área | Qué ofrece |
|------|------------|
| 🧠 **4 gates pre-flight** | 1a AgentMemory · 1b Checkpoint · 1c Steering Docs (opcional) · 1e Deck (mandatory) |
| 🔁 **Flujo consolidado** | `begin_turn()` autocontenido — ejecuta los gates internamente y crea el intento |
| 🛑 **endTurn Bouncer** | Valida gates mandatory PASS/SKIP al cerrar; `end_turn()` **nunca bloquea** (completa con `fail` + `gates_detail`) |
| 📋 **Misiones** | Sincronizadas con Nextcloud Deck: mission + checklist items + intentos trazados |
| 📊 **Dashboard web** | Astro + NES.css: proyectos, misiones, intentos y gates con breadcrumbs |
| 🔌 **Plugin v2.0** | `pre_llm_call` ejecuta gates, `pre_tool_call` bouncer, `post_tool_call` guard — **fuente de verdad en el repo** |
| 🧩 **18 tools MCP** | 16 activas + 2 legacy (~~DEPRECATED~~) — ver [Tools](#️-tools-mcp-api) |
| 💾 **SQLite WAL** | 9 tablas, migraciones incrementales, zero infraestructura |

---

<a id="quick-start"></a>
## 🚀 Quick Start — instalación nueva

### 1. Clonar e instalar

```bash
git clone https://github.com/erniomaldo/ultratimonel.git
cd ultratimonel

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Probar que arranca (stdio transport)
python main.py
```

### 2. Registrar el MCP server en `~/.hermes/config.yaml`

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

> [!NOTE]
> Los gates 1c/1e (Nextcloud) se conectan vía el bridge
> [**http-to-stdio**](https://github.com/erniomaldo/http-to-stdio) (público).
> El `initialize` del cliente MCP usa timeout de 30s para llamadas HTTP lentas.

### 3. Activar el plugin preflight

```yaml
plugins:
  enabled:
    - ultratimonel-preflight
  entries:
    ultratimonel-preflight:
      allow_tool_override: false
```

El plugin implementa el patrón **Nikhil Verma de mandatory tool contracts**.
**La fuente de verdad del plugin vive DENTRO de este repo** en `ultratimonel/`:

| Archivo en el repo | Propósito |
|--------------------|-----------|
| `ultratimonel/plugin_preflight.py` | `pre_llm_call` ejecuta gates · `pre_tool_call` bouncer bloquea tools sin gates PASS · `post_tool_call` bloquea tools después de `end_turn` (1 ciclo por respuesta) |
| `ultratimonel/ultratimonel_client.py` | Cliente MCP stdio hacia el server |
| `ultratimonel/plugin.yaml` | Declaración del plugin (nombre, versión v2.0.0, hooks) |

> [!WARNING]
> **Reglas de sincronía — léelas antes de tocar el plugin:**
> 1. **NO muevas ni copies el plugin fuera del repo.** Una copia externa
>    (p. ej. `~/.hermes/plugins/ultratimonel-preflight/`) queda desincronizada
>    cuando el repo avanza — el runtime seguiría corriendo una versión vieja.
> 2. **El repo es la única fuente autorizada.** Los cambios se hacen aquí
>    (commit + PR) y desde aquí se despliegan.
> 3. Al desplegar, `plugin_preflight.py` se copia a
>    `~/.hermes/plugins/ultratimonel-preflight/__init__.py` (mismo contenido,
>    distinto nombre de archivo dentro del paquete).

**plugin.yaml (v2.0.0):**

```yaml
name: ultratimonel-preflight
version: 2.0.0
description: >-
  Implementa el patrón Nikhil Verma de mandatory tool contracts en Hermes.
  pre_tool_call bouncer bloquea tools críticas si assert_gates no se ha
  ejecutado o si las 4 gates no están PASS. post_tool_call bloquea todas
  las tools después de end_turn para forzar el ciclo begin→trabajo→end.
author: "Ultratimonel"
provides_hooks:
  - on_session_start
  - pre_llm_call
  - pre_tool_call
  - post_tool_call
```

### 4. Instalar las skills del proyecto (para cualquier Hermes)

Las skills del flujo de trazabilidad viven **dentro de este repo** en `skills/`:

| Skill | Propósito |
|-------|-----------|
| `skills/ultratimonel-ciclo-basico/SKILL.md` | Ciclo básico: mission_list → begin_turn → end_turn (sin experimentar) |
| `skills/protocolo-de-trazabilidad/SKILL.md` | Protocolo Quad Persistence completo (begin/end, gates, checkpoints, agentmemory, Deck) |

```bash
# Copiar desde el repo (NUNCA editar la copia instalada)
cp -r skills/ultratimonel-ciclo-basico ~/.hermes/skills/
cp -r skills/protocolo-de-trazabilidad ~/.hermes/skills/
```

> [!WARNING]
> Misma regla que el plugin: la copia instalada en `~/.hermes/skills/` **no se edita** —
> los cambios se hacen en el repo y se re-copian.

### 5. Desplegar el protocolo SOUL.md

```bash
./scripts/deploy_soul.sh
```

Inyecta el **Protocolo de Respuesta — Hábito Irrompible** en `~/.hermes/SOUL.md`:
`begin_turn()` al inicio de cada mensaje y `end_turn()` al finalizar, con reporte
final al usuario. Las tools legacy `record_intento()` + `complete_intento()` están
**DEPRECATED** — no usarlas en flujos nuevos.

### 6. Verificar

```bash
python -m pytest tests/ -v          # suite completa
python main.py                      # arranca el MCP server
```

> [!TIP]
> Después de configurar, reinicia Hermes y ejecuta `mission_list("tu-proyecto")`
> para confirmar que el server responde y que las misiones de Deck están sincronizadas.

---

<a id="ciclo-por-turno"></a>
## 🔄 El ciclo por turno

```
1. Plugin (automático): pre_llm_call → assert_gates() → inyecta contexto de gates
2. Agente: begin_turn(session_id, project, mission_id, checklist_item_id)
           ├── Ejecuta los 4 gates internamente (autocontenido)
           └── Crea el intento con snapshot fresco
3. Agente: Trabajo del turno (tools, respuestas)
4. Agente: end_turn(intento_id, status="success")
           ├── Finaliza SIEMPRE con "success" o "fail" + gates_detail
           └── Nunca deja el turno atascado
5. Agente: Reporte al usuario (resumen de lo logrado, claro y directo)
6. Plugin (automático): pre_tool_call bouncer → bloquea si gates no PASS
```

**`begin_turn` es autocontenido:** ejecuta los 4 gates internamente y persiste el
snapshot en el mismo intento. No requiere `assert_gates()` manual como paso del
agente (sigue existiendo como tool, usada por el plugin en `pre_llm_call`).

**`end_turn` siempre finaliza:** nunca deja intentos `running` huérfanos;
`begin_turn` auto-limpia intentos running de sesiones anteriores (turn-scoping por
`intento_id` + auto-recovery).

> [!NOTE]
> El plugin ejecuta `assert_gates()` de forma independiente en `pre_llm_call`.
> Ambos escriben en la misma DB (`ULTRATIMONEL_DB_PATH`). Para evitar
> inconsistencias, `list_gate_states()` usa `MAX(id)` para devolver solo el
> estado más reciente (ver ADR-006).

---

<a id="tools"></a>
## 🛠️ Tools (MCP API)

Ultratimonel expone **18 tools MCP**: 16 activas + 2 legacy (~~DEPRECATED~~,
mantenidas por compatibilidad). Cada tool se auto-descubre vía el protocolo MCP.

### 🧠 Núcleo (Gates)

| Tool | Descripción |
|------|-------------|
| `assert_gates(message, session_id, sender)` | Ejecuta los 4 gates y retorna resultados estructurados (la usa el plugin en `pre_llm_call`) |
| `check_gate(name, session_id)` | Lee el estado de un gate desde SQLite (diagnóstico) |
| `complete_gate(name, session_id, reason)` | Marca manualmente un gate como PASS — solo desde BLOCK/WARN (remediación) |

### 🔁 Intentos (ciclo begin_turn / end_turn)

| Tool | Firma | Descripción |
|------|-------|-------------|
| `begin_turn(session_id, project, mission_id, checklist_item_id, message="", sender="user")` | Ejecuta los 4 gates internamente y crea el intento con snapshot fresco. **Flujo recomendado.** |
| `end_turn(intento_id, status="success")` | Finaliza SIEMPRE: `final_status` "success" o "fail" con `gates_detail` completo. Nunca deja el turno atascado. |
| `delete_intento(intento_id)` | Elimina un intento por ID (limpieza operacional) |

### 📋 Misiones / Deck Sync

| Tool | Descripción |
|------|-------------|
| `sync_tasks(project)` | Sincroniza cards de Deck → tabla missions para un proyecto |
| `sync_all()` | Sincroniza todos los proyectos mapeados |
| `mission_list(project)` | Lista misiones (Deck tasks) de un proyecto |

### 🗺️ Project Maps

| Tool | Descripción |
|------|-------------|
| `map_list()` | Lista proyectos configurados en `project_maps.json` |
| `map_add(project, deck_board_name, collective_name, ...)` | Agrega o actualiza un proyecto |
| `map_remove(project)` | Elimina un proyecto |
| `map_setup()` | Descubre boards/collectives disponibles para mapeo |
| `map_sync()` | Verifica que los IDs de boards sigan existiendo |

### 📊 Dashboard

| Tool | Descripción |
|------|-------------|
| `server(action)` | Controla el servidor web del dashboard (start/stop/status) |

### 🗂️ Deck Cards

| Tool | Descripción |
|------|-------------|
| `card_update_description(card_id, description, board_id, stack_id)` | Actualiza solo la descripción de una card — NUNCA cambia el título |

### 🗄️ Legacy / Archivadas (compatibilidad — no usar en flujos nuevos)

| Tool | Firma | Descripción |
|------|-------|-------------|
| `record_intento(session_id, project, mission_id, checklist_item_id)` | ~~DEPRECATED~~ — usa `begin_turn()` en su lugar |
| `complete_intento(intento_id, status, gates_passed, session_id, project)` | ~~DEPRECATED~~ — usa `end_turn()` en su lugar |

---

<a id="gates"></a>
## 🗄️ Gates y estados

| Gate | Fuente | Mandatory | Propósito |
|------|--------|-----------|-----------|
| **1a** | `mcp_agentmemory_memory_smart_search` | ✅ Sí | Recuperar memoria relevante del proyecto/sender |
| **1b** | `mcp_checkpoint_get_state` | ✅ Sí | Obtener checkpoint de estado del proyecto activo |
| **1c** | `mcp_nextcloud_collectives_get_pages` | ❌ No | Cargar steering docs desde Nextcloud Collective |
| **1e** | `mcp_nextcloud_deck_get_boards` | ✅ Sí | Listar tareas activas desde Nextcloud Deck |

| Estado | Significado | Acción |
|--------|-------------|--------|
| `PASS` | Gate completó exitosamente | Continuar |
| `SKIP` | Gate no aplica / N/A | Continuar |
| `WARN` | Gate falló (no crítico) | Advertir + continuar |
| `BLOCK` | Gate falló (mandatory) | **Detener generación** |

> [!NOTE]
> **Grace Period:** el plugin tiene `ULTRATIMONEL_GRACE_TURNS=3` (default 3).
> Durante los primeros 3 turnos de la sesión el bouncer no bloquea aunque los
> gates fallen; a partir del turno 4 es estricto.

---

<a id="integracion"></a>
## 🔌 Integración con Hermes Agent

### Protocolo SOUL.md

El archivo `~/.hermes/SOUL.md` debe incluir el **Protocolo de Respuesta —
Hábito Irrompible** que exige `begin_turn()` al inicio de cada mensaje y
`end_turn()` al finalizar, con reporte final al usuario (paso 6 del protocolo).
Ver `scripts/deploy_soul.sh` para despliegue automatizado.

### endTurn Bouncer

Validación server-side del cierre de turno. En el flujo recomendado vive en
`end_turn()`; también está disponible en `complete_intento()` (legacy). Cuando
se proporcionan `session_id` y `project`, consulta `list_gate_states()` en
SQLite para verificar que **todas las gates mandatory estén PASS o SKIP**.

Si alguna gate mandatory está BLOCK o WARN, retorna `status: "blocked"` (en
`end_turn()` el intento se completa como `fail` con `gates_detail` — nunca
bloquea permanentemente).

---

<a id="configuracion"></a>
## ⚙️ Configuración

### Project Maps

**No edites código para configurar proyectos.** Toda la configuración vive en
`~/.hermes/ultratimonel/project_maps.json` (configurable via
`ULTRATIMONEL_PROJECT_MAPS`). Usa las tools MCP:

```bash
map_setup()         # Descubre boards/collectives
map_add("mi-proyecto", deck_board_name="Mi Board", ...)
map_list()
map_sync()
```

### Variables de entorno

| Variable | Default | Propósito |
|----------|---------|-----------|
| `ULTRATIMONEL_DB_PATH` | `~/.hermes/ultratimonel.db` | Ruta a SQLite |
| `ULTRATIMONEL_PROJECT_MAPS` | `~/.hermes/ultratimonel/project_maps.json` | Config de proyectos |
| `ULTRATIMONEL_DASHBOARD_PORT` | `3005` | Puerto del dashboard |
| `ULTRATIMONEL_DASHBOARD_STATIC_ROOT` | legacy `ultratimonel/dashboard/` (puerto principal 3005: `dashboard-astro/dist/`) | Root estático del dashboard — override para staging/validación |

---

<a id="arquitectura"></a>
## 🏗️ Arquitectura

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
│   ├── server.py                    # FastMCP — 18 tool handlers (16 activas + 2 legacy)
│   ├── persistence.py               # SQLite layer (WAL, 9 tablas, migrations)
│   ├── gate_engine.py               # State machine: PASS/SKIP/WARN/BLOCK
│   ├── triple_match.py              # Orquestación de gates 1a→1b→1c→1e
│   ├── context_extractor.py         # Mensaje → sender/topic/project
│   ├── config_loader.py             # Carga project_maps.json externo
│   ├── mcp_client.py                # Cliente HTTP para MCP calls externos
│   ├── bridge.py                    # Bridge hacia mcp-capabilities
│   ├── dashboard_server.py          # Servidor HTTP (stdlib) del dashboard
│   ├── plugin_preflight.py          # Plugin v2.0.0 (pre/post_tool_call guards)
│   ├── ultratimonel_client.py       # Cliente MCP stdio del plugin
│   ├── plugin.yaml                  # Declaración del plugin
│   ├── dashboard-astro/             # Dashboard nuevo (Astro, build → dist/) — ADR-1
│   └── dashboard/
│       ├── __init__.py
│       ├── index.html               # Dashboard legacy (~~DEPRECATED~~, fuera del árbol servido)
│       └── app.js                   # Lógica JS legacy (~~DEPRECATED~~, fuera del árbol servido)
├── scripts/
│   └── deploy_soul.sh               # Inyección de reglas SOUL.md
├── skills/
│   ├── ultratimonel-ciclo-basico/   # Ciclo básico (mission_list → begin/end_turn)
│   └── protocolo-de-trazabilidad/   # Protocolo Quad Persistence completo
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

<a id="base-de-datos"></a>
## 🗃️ Base de datos

SQLite con **WAL journal mode**. Ruta por defecto: `~/.hermes/ultratimonel.db`
(configurable via `ULTRATIMONEL_DB_PATH`).

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

**Parámetros:** WAL journal mode · NORMAL synchronous · 5s busy timeout ·
migraciones incrementales vía `schema_version`.

---

<a id="dashboard"></a>
## 📊 Dashboard

El dashboard web corre en un servidor **http.server** (stdlib, no FastAPI),
puerto principal **3005** (configurable via `ULTRATIMONEL_DASHBOARD_PORT`).
El puerto principal sirve el build de Astro (`ultratimonel/dashboard-astro/dist/`)
con los handlers `/api/*` intactos en el mismo origen (S12).

### Puertos

| Puerto | Rol | Cómo se levanta |
|--------|-----|-----------------|
| **3005** | **Producción** — sirve `dist/` (build Astro) + `/api` same-origin | `python ultratimonel/dashboard_server.py` (o `server(action="start")`) |
| **3006** | Dev — Astro dev server, proxy `/api` → 3005 | `cd ultratimonel/dashboard-astro && npm run dev` |
| **3007** | Validación del build — mismo handler Python sobre `dist/` | `ULTRATIMONEL_DASHBOARD_STATIC_ROOT=…/dist python ultratimonel/dashboard_server.py 3007` |

### Comandos (frontend Astro)

```bash
cd ultratimonel/dashboard-astro
npm run dev      # dev server en 127.0.0.1:3006 (proxy /api → 3005)
npm run build    # genera dist/ (lo que sirve el puerto principal 3005)
```

### Root estático y deprecación legacy

- El root estático se resuelve por puerto: **3005 → `dashboard-astro/dist/`**;
  cualquier otro puerto sirve `ultratimonel/dashboard/` salvo override.
- `ULTRATIMONEL_DASHBOARD_STATIC_ROOT` sobreescribe el root (staging/validación).
- Los archivos legacy `ultratimonel/dashboard/index.html` y `app.js` están
  **DEPRECATED** — fuera del árbol servido en el puerto principal. Se conservan
  en el repo como referencia y para rollback trivial (restaurar el root legacy).

```python
server(action="start")   # Inicia el dashboard
server(action="stop")    # Lo detiene
server(action="status")  # Estado actual
```

---

<a id="desarrollo"></a>
## 🧪 Desarrollo

```bash
# Entorno
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Tests
python -m pytest tests/test_gate_engine.py tests/test_server.py tests/test_persistence.py -q
# 76 passed

# Ruta DB personalizada (para pruebas aisladas)
ULTRATIMONEL_DB_PATH=/tmp/test.db python main.py
```

Los cambios de diseño siguen el flujo **OpenSpec/SDD** (`openspec/changes/`) con
validación adversarial (`judgment-day`) y trazabilidad triple (intentos en
ultratimonel, checkpoints, agentmemory). Ver `docs/` para la documentación
detallada del diseño.

---

<a id="dependencias"></a>
## 📦 Dependencias

- Python ≥ 3.13
- `fastmcp` — Framework MCP
- `httpx` — Cliente HTTP para calls MCP externas (Deck)
- **`http-to-stdio`** — bridge HTTP→stdio para conectar a Nextcloud MCP:
  [github.com/erniomaldo/http-to-stdio](https://github.com/erniomaldo/http-to-stdio) (público)
- `sqlite3` — Persistencia (stdlib)

---

<a id="licencia"></a>
## 📜 Licencia

MIT — ver [pyproject.toml](pyproject.toml).

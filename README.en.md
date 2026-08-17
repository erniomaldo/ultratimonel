# Ultratimonel 🛡️

<div align="center">

![Ultratimonel](docs/logo.png)

**Pre-flight gate enforcement + Missions + Dashboard for [Hermes Agent](https://hermes-agent.nousresearch.com/docs).**

A guard that runs **before every LLM generation** so the agent never responds
without memory, checkpoint, steering docs, or active tasks.

[![MCP Server](https://img.shields.io/badge/MCP%20Server-7B3FF2?logo=modelcontextprotocol&logoColor=white)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](pyproject.toml)
[![Language](https://img.shields.io/github/languages/top/erniomaldo/ultratimonel)](https://github.com/erniomaldo/ultratimonel)
[![Repo Size](https://img.shields.io/github/repo-size/erniomaldo/ultratimonel)](https://github.com/erniomaldo/ultratimonel)

🌐 [🇪🇸 Español](README.md) · **English**

</div>

---

## 📚 Table of Contents

- [🤔 The problem](#the-problem)
- [✅ The solution](#the-solution)
- [✨ Features](#features)
- [🚀 Quick Start — fresh install](#quick-start)
- [🔄 The per-turn cycle](#per-turn-cycle)
- [🛠️ Tools (MCP API)](#tools)
- [🗄️ Gates and states](#gates-and-states)
- [🔌 Hermes Agent integration](#hermes-agent-integration)
- [⚙️ Configuration](#configuration)
- [🏗️ Architecture](#architecture)
- [🗃️ Database](#database)
- [📊 Dashboard](#dashboard)
- [🧪 Development](#development)
- [📦 Dependencies](#dependencies)
- [📜 License](#license)

---

<a id="the-problem"></a>
## 🤔 The problem

AI agents generate responses with **incomplete context**: they don't consult
project memory, don't check the state checkpoint, don't read active tasks.
The result:

| Problem | What happens | Consequence |
|---------|--------------|-------------|
| Memory not consulted | The agent answers without project history | Responses that ignore past decisions |
| Checkpoint ignored | The agent doesn't know where work left off | Resumes in the wrong place |
| Tasks not read | The agent is unaware of active board cards | Duplicated or out-of-scope work |
| No accountability | Every turn is an island, no traceability | Impossible to audit what was done and when |

**Bottom line:** agents answering "from memory" (or without it), repeated work,
and zero traceability of which attempt completed which task.

---

<a id="the-solution"></a>
## ✅ The solution

Ultratimonel is an **MCP server + enforcement plugin** that forces the agent
through a traced cycle every turn: consult the 4 context sources, register an
**intento** (attempt) linked to a real task (mission + checklist item from
Nextcloud Deck), and close the turn with gate verification.

```
┌──────────────┐   MCP stdio    ┌──────────────────┐    SQLite WAL    ┌──────────────┐
│  Hermes      │ ──────────────→│  Ultratimonel    │ ──────────────→│              │
│  Agent       │                │  MCP Server      │                 │ ultratimonel │
│  + preflight │ ←──────────────│  (20 tools)      │ ←──────────────│ .db (1 file) │
│  plugin      │                │                  │                 │              │
└──────────────┘                └─────────┬────────┘                 └──────────────┘
                                          │
                              ┌───────────┼───────────┐
                              ▼           ▼           ▼
                        AgentMemory   Checkpoint   Nextcloud
                        (Gate 1a)     (Gate 1b)    Deck (1e) + Collective (1c)
```

**The per-turn cycle is 2 calls** (previously 5+):

```
begin_turn()  →  turn work  →  end_turn()  →  report to the user
```

> [!IMPORTANT]
> Ultratimonel is **not optional** in the Hermes flow: the
> `ultratimonel-preflight` plugin blocks tools when gates are not PASS, and
> `post_tool_call` enforces the begin → work → end cycle per response.
> There is no "disabled mode".

---

<a id="features"></a>
## ✨ Features

| Area | What it offers |
|------|----------------|
| 🧠 **4 pre-flight gates** | 1a AgentMemory · 1b Checkpoint · 1c Steering Docs (optional) · 1e Deck (mandatory) |
| 🔁 **Consolidated flow** | `begin_turn()` is self-contained — runs gates internally and creates the intento |
| 🛑 **endTurn Bouncer** | Validates mandatory gates PASS/SKIP on close; `end_turn()` **never blocks** (completes with `fail` + `gates_detail`) |
| 📋 **Missions** | Synced with Nextcloud Deck: mission + checklist items + traced intentos |
| 📊 **Web dashboard** | NES.css v2.3.0, light/dark theme, missions with progress, intento details |
| 🔌 **Plugin v2.0** | `pre_llm_call` runs gates, `pre_tool_call` bouncer, `post_tool_call` guard — **source of truth lives in this repo** |
| 🧩 **20 MCP tools** | 17 active + 3 legacy (~~DEPRECATED~~) — see [Tools](#️-tools-mcp-api) |
| 💾 **SQLite WAL** | 9 tables, incremental migrations, zero infrastructure |

---

<a id="quick-start"></a>
## 🚀 Quick Start — fresh install

### 1. Clone and install

```bash
git clone https://github.com/erniomaldo/ultratimonel.git
cd ultratimonel

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Sanity check (stdio transport)
python main.py
```

### 2. Register the MCP server in `~/.hermes/config.yaml`

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
> Gates 1c/1e (Nextcloud) connect through the
> [**http-to-stdio**](https://github.com/erniomaldo/http-to-stdio) bridge (public).
> The MCP client `initialize` uses a 30s timeout for slow HTTP calls.

### 3. Enable the preflight plugin

```yaml
plugins:
  enabled:
    - ultratimonel-preflight
  entries:
    ultratimonel-preflight:
      allow_tool_override: false
```

The plugin implements the **Nikhil Verma mandatory tool contracts** pattern.
**The plugin's source of truth lives INSIDE this repo** in `ultratimonel/`:

| File in repo | Purpose |
|--------------|---------|
| `ultratimonel/plugin_preflight.py` | `pre_llm_call` runs gates · `pre_tool_call` bouncer blocks tools without PASS gates · `post_tool_call` blocks tools after `end_turn` (1 cycle per response) |
| `ultratimonel/ultratimonel_client.py` | MCP stdio client towards the server |
| `ultratimonel/plugin.yaml` | Plugin declaration (name, version v2.0.0, hooks) |

> [!WARNING]
> **Sync rules — read before touching the plugin:**
> 1. **Do NOT move or copy the plugin outside the repo.** An external copy
>    (e.g. `~/.hermes/plugins/ultratimonel-preflight/`) desyncs when the repo
>    advances — the runtime would keep running an old version.
> 2. **The repo is the only authorized source.** Changes are made here
>    (commit + PR) and deployed from here.
> 3. When deploying, `plugin_preflight.py` is copied to
>    `~/.hermes/plugins/ultratimonel-preflight/__init__.py` (same content,
>    different filename inside the package).

**plugin.yaml (v2.0.0):**

```yaml
name: ultratimonel-preflight
version: 2.0.0
description: >-
  Implements the Nikhil Verma mandatory tool contracts pattern in Hermes.
  pre_tool_call bouncer blocks critical tools if assert_gates has not run
  or if the 4 gates are not PASS. post_tool_call blocks all tools after
  end_turn to enforce the begin→work→end cycle.
author: "Ultratimonel"
provides_hooks:
  - on_session_start
  - pre_llm_call
  - pre_tool_call
  - post_tool_call
```

### 4. Install the project skills (for any Hermes)

The traceability-flow skills live **inside this repo** in `skills/`:

| Skill | Purpose |
|-------|---------|
| `skills/ultratimonel-ciclo-basico/SKILL.md` | Basic cycle: mission_list → begin_turn → end_turn (no experimentation) |
| `skills/protocolo-de-trazabilidad/SKILL.md` | Full Quad Persistence protocol (begin/end, gates, checkpoints, agentmemory, Deck) |

```bash
# Copy from the repo (NEVER edit the installed copy)
cp -r skills/ultratimonel-ciclo-basico ~/.hermes/skills/
cp -r skills/protocolo-de-trazabilidad ~/.hermes/skills/
```

> [!WARNING]
> Same rule as the plugin: the installed copy in `~/.hermes/skills/` is **not
> edited** — changes are made in the repo and re-copied.

### 5. Deploy the SOUL.md protocol

```bash
./scripts/deploy_soul.sh
```

Injects the **Response Protocol — Unbreakable Habit** into `~/.hermes/SOUL.md`:
`begin_turn()` at the start of every message and `end_turn()` to finish, with a
final report to the user. The legacy tools `record_intento()` +
`complete_intento()` are **DEPRECATED** — do not use them in new flows.

### 6. Verify

```bash
python -m pytest tests/ -v          # full suite
python main.py                      # starts the MCP server
```

> [!TIP]
> After configuring, restart Hermes and run `mission_list("your-project")` to
> confirm the server responds and Deck missions are synced.

---

<a id="per-turn-cycle"></a>
## 🔄 The per-turn cycle

```
1. Plugin (automatic): pre_llm_call → assert_gates() → injects gate context
2. Agent: begin_turn(session_id, project, mission_id, checklist_item_id)
          ├── Runs the 4 gates internally (self-contained)
          └── Creates the intento with a fresh snapshot
3. Agent: Turn work (tools, responses)
4. Agent: end_turn(intento_id, status="success")
          ├── Always finishes with "success" or "fail" + gates_detail
          └── Never leaves the turn stuck
5. Agent: Report to the user (clear, direct summary of what was done)
6. Plugin (automatic): pre_tool_call bouncer → blocks if gates not PASS
```

**`begin_turn` is self-contained:** it runs the 4 gates internally and persists
the snapshot in the same intento. It does not require a manual `assert_gates()`
step from the agent (the tool still exists — the plugin uses it in
`pre_llm_call`).

**`end_turn` always finishes:** it never leaves orphaned `running` intentos;
`begin_turn` auto-cleans running intentos from previous sessions (turn-scoping
by `intento_id` + auto-recovery).

> [!NOTE]
> The plugin runs `assert_gates()` independently in `pre_llm_call`. Both write
> to the same DB (`ULTRATIMONEL_DB_PATH`). To avoid inconsistencies,
> `list_gate_states()` uses `MAX(id)` to return only the latest state
> (see ADR-006).

---

<a id="tools"></a>
## 🛠️ Tools (MCP API)

Ultratimonel exposes **20 MCP tools**: 17 active + 3 legacy (~~DEPRECATED~~,
kept for compatibility). Every tool is auto-discovered via the MCP protocol.

### 🧠 Core (Gates)

| Tool | Description |
|------|-------------|
| `check_gate(name, session_id)` | Reads a gate's state from SQLite (diagnostics) |
| `complete_gate(name, session_id, reason)` | Manually marks a gate PASS — only from BLOCK/WARN (remediation) |

### 🔁 Intentos (begin_turn / end_turn cycle)

| Tool | Signature | Description |
|------|-----------|-------------|
| `begin_turn(session_id, project, mission_id, checklist_item_id, message="", sender="user")` | Runs the 4 gates internally and creates the intento with a fresh snapshot. **Recommended flow.** |
| `end_turn(intento_id, status="success")` | Always finishes: `final_status` "success" or "fail" with full `gates_detail`. Never leaves the turn stuck. |
| `delete_intento(intento_id)` | Deletes an intento by ID (operational cleanup) |

### 📋 Missions / Deck Sync

| Tool | Description |
|------|-------------|
| `sync_tasks(project)` | Syncs Deck cards → missions table for a project |
| `sync_all()` | Syncs all mapped projects |
| `mission_list(project)` | Lists missions (Deck tasks) for a project |
| `mission_get(mission_id)` | Retrieves a mission by ID |
| `checklist_item_get(checklist_item_id)` | Retrieves a checklist item by ID |

### 🗺️ Project Maps

| Tool | Description |
|------|-------------|
| `map_list()` | Lists projects configured in `project_maps.json` |
| `map_add(project, deck_board_name, collective_name, ...)` | Adds or updates a project |
| `map_remove(project)` | Removes a project |
| `map_setup()` | Discovers available boards/collectives for mapping |
| `map_sync()` | Verifies board IDs still exist |

### 📊 Dashboard

| Tool | Description |
|------|-------------|
| `server(action)` | Controls the dashboard web server (start/stop/status) |

### 🗂️ Deck Cards

| Tool | Description |
|------|-------------|
| `card_update_description(card_id, description, board_id, stack_id)` | Updates only a card's description — NEVER changes the title |

### 🗄️ Legacy / Archived (compatibility — do not use in new flows)

| Tool | Signature | Description |
|------|-----------|-------------|
| `assert_gates(message, session_id, sender)` | ~~DEPRECATED~~ — use `begin_turn()` instead (runs the 4 gates internally; the plugin uses it in `pre_llm_call`) |
| `record_intento(session_id, project, mission_id, checklist_item_id)` | ~~DEPRECATED~~ — use `begin_turn()` instead |
| `complete_intento(intento_id, status, gates_passed, session_id, project)` | ~~DEPRECATED~~ — use `end_turn()` instead |

---

<a id="gates-and-states"></a>
## 🗄️ Gates and states

| Gate | Source | Mandatory | Purpose |
|------|--------|-----------|---------|
| **1a** | `mcp_agentmemory_memory_smart_search` | ✅ Yes | Retrieve relevant memory for project/sender |
| **1b** | `mcp_checkpoint_get_state` | ✅ Yes | Get state checkpoint for the active project |
| **1c** | `mcp_nextcloud_collectives_get_pages` | ❌ No | Load steering docs from Nextcloud Collective |
| **1e** | `mcp_nextcloud_deck_get_boards` | ✅ Yes | List active tasks from Nextcloud Deck |

| State | Meaning | Action |
|-------|---------|--------|
| `PASS` | Gate completed successfully | Continue |
| `SKIP` | Gate not applicable / N/A | Continue |
| `WARN` | Gate failed (non-critical) | Warn + continue |
| `BLOCK` | Gate failed (mandatory) | **Stop generation** |

> [!NOTE]
> **Grace Period:** the plugin ships `ULTRATIMONEL_GRACE_TURNS=3` (default 3).
> During the first 3 turns of a session the bouncer does not block even if
> gates fail; from turn 4 onward it is strict.

---

<a id="hermes-agent-integration"></a>
## 🔌 Hermes Agent integration

### SOUL.md protocol

The `~/.hermes/SOUL.md` file must include the **Response Protocol — Unbreakable
Habit** requiring `begin_turn()` at the start of every message and `end_turn()`
to finish, with a final report to the user (protocol step 6). See
`scripts/deploy_soul.sh` for automated deployment.

### endTurn Bouncer

Server-side validation of turn closing. In the recommended flow it lives in
`end_turn()`; it is also available in `complete_intento()` (legacy). When
`session_id` and `project` are provided, it queries `list_gate_states()` in
SQLite to verify that **all mandatory gates are PASS or SKIP**.

If any mandatory gate is BLOCK or WARN, it returns `status: "blocked"` (in
`end_turn()` the intento completes as `fail` with `gates_detail` — it never
blocks permanently).

---

<a id="configuration"></a>
## ⚙️ Configuration

### Project Maps

**Do not edit code to configure projects.** All configuration lives in
`~/.hermes/ultratimonel/project_maps.json` (configurable via
`ULTRATIMONEL_PROJECT_MAPS`). Use the MCP tools:

```bash
map_setup()         # Discovers boards/collectives
map_add("my-project", deck_board_name="My Board", ...)
map_list()
map_sync()
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ULTRATIMONEL_DB_PATH` | `~/.hermes/ultratimonel.db` | SQLite path |
| `ULTRATIMONEL_PROJECT_MAPS` | `~/.hermes/ultratimonel/project_maps.json` | Project config |
| `ULTRATIMONEL_DASHBOARD_PORT` | `3005` | Dashboard port |

---

<a id="architecture"></a>
## 🏗️ Architecture

```
ultratimonel/
├── main.py                          # Entry point (stdio transport)
├── requirements.txt                 # fastmcp, httpx
├── pyproject.toml                   # Package metadata
├── pytest.ini                       # Test config
├── project_maps.json.template       # Template for project mapping
├── .spec -> ~/.spec                 # Symlink to external spec
├── ultratimonel/
│   ├── __init__.py                  # Package metadata
│   ├── server.py                    # FastMCP — 20 tool handlers (17 active + 3 legacy)
│   ├── persistence.py               # SQLite layer (WAL, 9 tables, migrations)
│   ├── gate_engine.py               # State machine: PASS/SKIP/WARN/BLOCK
│   ├── triple_match.py              # Gate orchestration 1a→1b→1c→1e
│   ├── context_extractor.py         # Message → sender/topic/project
│   ├── config_loader.py             # Loads external project_maps.json
│   ├── mcp_client.py                # HTTP client for external MCP calls
│   ├── bridge.py                    # Bridge towards mcp-capabilities
│   ├── dashboard_server.py          # HTTP (stdlib) dashboard server
│   ├── plugin_preflight.py          # Plugin v2.0.0 (pre/post_tool_call guards)
│   ├── ultratimonel_client.py       # Plugin's MCP stdio client
│   ├── plugin.yaml                  # Plugin declaration
│   └── dashboard/
│       ├── __init__.py
│       ├── index.html               # Web dashboard (NES.css v2.3.0)
│       └── app.js                   # Dashboard JS logic
├── scripts/
│   └── deploy_soul.sh               # SOUL.md rules injection
├── skills/
│   ├── ultratimonel-ciclo-basico/   # Basic cycle (mission_list → begin/end_turn)
│   └── protocolo-de-trazabilidad/   # Full Quad Persistence protocol
├── openspec/
│   ├── config.yaml                  # OpenSpec configuration
│   ├── specs/                       # SDD specifications
│   └── changes/                     # Change proposals (PAC)
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

<a id="database"></a>
## 🗃️ Database

SQLite with **WAL journal mode**. Default path: `~/.hermes/ultratimonel.db`
(configurable via `ULTRATIMONEL_DB_PATH`).

| Table | Purpose |
|-------|---------|
| `schema_version` | Migrations (version + description) |
| `sessions` | Per-generation context |
| `gate_state` | Per-gate state per session+project |
| `gate_logs` | Audit trail of state transitions |
| `checkpoints` | Triple-match snapshots |
| `actions` | Agent-registered actions |
| `missions` | Mission lifecycle (synced from Deck) |
| `checklist_items` | Checklist items inside each mission |
| `intentos` | Assert-gates cycles per checklist item |

**Parameters:** WAL journal mode · NORMAL synchronous · 5s busy timeout ·
incremental migrations via `schema_version`.

---

<a id="dashboard"></a>
## 📊 Dashboard

The web dashboard runs on an **http.server** (stdlib, not FastAPI) server,
default port **3005** (configurable via `ULTRATIMONEL_DASHBOARD_PORT`).

NES.css v2.3.0 interface with:

- Project list with gate status
- Mission board with progress
- Intento details per checklist item
- Light/dark theme

```python
server(action="start")   # Starts the dashboard
server(action="stop")    # Stops it
server(action="status")  # Current status
```

---

<a id="development"></a>
## 🧪 Development

```bash
# Environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Tests
python -m pytest tests/test_gate_engine.py tests/test_server.py tests/test_persistence.py -q
# 76 passed

# Custom DB path (isolated testing)
ULTRATIMONEL_DB_PATH=/tmp/test.db python main.py
```

Design changes follow the **OpenSpec/SDD** flow (`openspec/changes/`) with
adversarial validation (`judgment-day`) and triple traceability (intentos in
ultratimonel, checkpoints, agentmemory). See `docs/` for detailed design docs.

---

<a id="dependencies"></a>
## 📦 Dependencies

- Python ≥ 3.13
- `fastmcp` — MCP framework
- `httpx` — HTTP client for external MCP calls (Deck)
- **`http-to-stdio`** — HTTP→stdio bridge to connect to Nextcloud MCP:
  [github.com/erniomaldo/http-to-stdio](https://github.com/erniomaldo/http-to-stdio) (public)
- `sqlite3` — Persistence (stdlib)

---

<a id="license"></a>
## 📜 License

MIT — see [pyproject.toml](pyproject.toml).

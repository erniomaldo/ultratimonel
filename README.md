# Ultratimonel — Pre-flight Gate Enforcement MCP Server

**Ultratimonel** is an MCP (Model Context Protocol) server that enforces a
deterministic pre-flight gate protocol in Hermes. It ensures that every LLM
generation has consulted AgentMemory (1a), Checkpoint (1b), and Deck (1e)
before generating a response.

## Quick Start

```bash
# Set up
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run (stdio transport — default for Hermes integration)
python main.py

# Run (with custom DB path)
ULTRATIMONEL_DB_PATH=/tmp/test.db python main.py

# Deploy SOUL.md rules
./scripts/deploy_soul.sh
```bash
# Run tests
pytest tests/ -v
```

## 🚫 Antipatrón: No edites código para configurar proyectos

Ultratimonel **no se configura editando archivos Python**. Toda la configuración
de proyectos vive en `project_maps.json` (por defecto en `~/.hermes/ultratimonel/project_maps.json`,
configurable via `ULTRATIMONEL_PROJECT_MAPS`).

Usa las tools MCP para gestionar proyectos:

| Tool | Acción |
|------|--------|
| `map_list()` | Listar proyectos configurados |
| `map_add(project, patterns, ...)` | Agregar o actualizar un proyecto |
| `map_remove(project)` | Eliminar un proyecto |
| `map_setup()` | Descubrir boards/collectives disponibles |
| `map_sync()` | Verificar que los IDs de boards sigan existiendo |

**Editar `context_extractor.py`, `server.py` o cualquier `.py` para agregar
proyectos es un error de diseño.** Usa las tools MCP en su lugar.

## Tools

### `assert_gates(message, session_id, sender="user")`
Run all three pre-flight gates and return structured results.

- **Input:** message string, Hermes session ID, optional sender
- **Output:** JSON with `gates[]`, `status` (PASS/BLOCK/WARN), `context`, `context_envelope`, `timestamp`
- **Execution order:** 1a AgentMemory → 1b Checkpoint → 1e Deck

### `check_gate(name, session_id)`
Read the current status of a single gate from SQLite persistence.

- **Input:** gate name (`1a`, `1b`, `1e`), session ID
- **Output:** JSON with `name`, `state`, `mandatory`, `message`, `updated_at`

### `complete_gate(name, session_id, reason)`
Explicitly mark a BLOCK or WARN gate as PASS. Only works when current state is BLOCK or WARN.

- **Input:** gate name, session ID, optional reason string
- **Output:** JSON with `name`, `state` (PASS), `updated_at`, `message`

## Gate States

| State   | Meaning                     | Generation Action           |
|---------|-----------------------------|-----------------------------|
| `PASS`  | Gate completed successfully | Continue                    |
| `SKIP`  | Gate does not apply / N/A   | Continue                    |
| `WARN`  | Gate failed (non-critical)  | Warn + continue             |
| `BLOCK` | Gate failed (mandatory)     | **Halt generation**         |

## Architecture

```
ultratimonel/
├── main.py                 # Entry point (stdio transport)
├── requirements.txt        # fastmcp, httpx
├── ultratimonel/
│   ├── __init__.py         # Package metadata
│   ├── server.py           # FastMCP tool registration
│   ├── persistence.py      # SQLite layer (WAL, migrations)
│   ├── context_extractor.py# Message → sender/topic/project
│   ├── gate_engine.py      # State machine (PASS/SKIP/WARN/BLOCK)
│   ├── triple_match.py     # 1a→1b→1e orchestration
│   └── bridge.py           # mcp-capabilities bridge stub
├── scripts/
│   └── deploy_soul.sh      # SOUL.md rule injection
└── tests/
    ├── test_gate_engine.py
    ├── test_context_extractor.py
    ├── test_persistence.py
    ├── test_triple_match.py
    └── test_integration.py
```

## Database

SQLite database at `~/.hermes/ultratimonel.db` (configurable via
`ULTRATIMONEL_DB_PATH`). Six tables:

- `schema_version` — migration tracking
- `sessions` — per-generation context
- `gate_state` — per-gate status per session+project
- `gate_logs` — audit trail of state transitions
- `checkpoints` — triple-match snapshots
- `missions` — top-level mission lifecycle

WAL journal mode, NORMAL synchronous, 5s busy timeout.

## SOUL.md Deployment

Run `scripts/deploy_soul.sh` to inject the pre-flight protocol rules
into `~/.hermes/SOUL.md`. The script:

1. Backs up the existing SOUL.md
2. Checks for the `## Protocolo Pre-flight (OBLIGATORIO)` section
3. Updates in-place or appends as needed
4. Supports `--force`, `--dry-run` flags

## Error Handling

All external MCP tool calls (AgentMemory, Checkpoint, Deck) are wrapped in
try/except with SKIP fallback. The server never crashes from external
failures. See the [SDD](openspec/) for detailed error scenarios.

## Dependencies

- Python ≥ 3.13
- `fastmcp` — MCP framework
- `httpx` — HTTP client for external MCP calls
- `sqlite3` — stdlib persistence

## License

MIT

# SDD: Ultratimonel MVP — Pre-flight Gate Enforcement

## 1. Architecture

```
┌───────────────────────────────────────────────────┐
│                   Hermes                           │
│  SOUL.md (hard rules → call gates every msg)      │
│       │                                            │
│  ┌────▼──────────────────────────────────────┐    │
│  │         Ultratimonel (FastMCP)             │    │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────┐  │    │
│  │  │Context  │ │  Gate    │ │Triple-Match│  │    │
│  │  │Extractor│ │  Engine  │ │Coordinator │  │    │
│  │  │(sender, │ │(state    │ │(1a→1b→1e)  │  │    │
│  │  │ topic,  │ │ machine) │ └──────┬─────┘  │    │
│  │  │ project)│ └───┬──────┘        │        │    │
│  │  └─────────┘     └──────┬────────┘        │    │
│  │  ┌──────────────────────▼──────────────────┐ │    │
│  │  │         SQLite Layer                    │ │    │
│  │  │  (sessions, gates, gate_logs, ckpts)    │ │    │
│  │  └─────────────────────────────────────────┘ │    │
│  └──────────────────────────────────────────────┘    │
│       │                      ▲                       │
│  ┌────▼────┐   ┌─────────────┴───────┐               │
│  │ MCP ext │   │ mcp-capabilities    │               │
│  │ tools   │   │ bridge (stub, MVP)  │               │
│  └─────────┘   └─────────────────────┘               │
└───────────────────────────────────────────────────────┘
```

**Layers:** FastMCP server (entry, tool reg), ContextExtractor (parse sender/topic/project from message), GateEngine (state machine), TripleMatchCoordinator (orchestrate 1a→1b→1e), SQLiteLayer (persistence).

---

## 2. MCP Tool Signatures (JSON Schema)

### `assert_gates()`
**Input:** `{ "message": "str", "session_id": "str" }`  
**Response:**
```json
{
  "gates": [
    {"name":"1a_agentmemory","state":"PASS","details":"3 relevant memories"},
    {"name":"1b_checkpoint","state":"BLOCK","details":"plan key missing"}
  ],
  "status": "BLOCK",
  "context": {"sender":"user","topic":"design","project":"ultratimonel"}
}
```

### `check_gate(name)`
**Input:** `{ "name": "1a|1b|1e", "session_id": "str" }`  
**Response:** `{ "name": "...", "state": "BLOCK", "details": "..." }`

### `complete_gate(name)`
**Input:** `{ "name": "...", "session_id": "str", "reason": "str" }`  
**Response:** `{ "name": "...", "state": "PASS", "message": "...", "updated_at": "..." }`

Only transitions BLOCK→PASS or WARN→PASS. No-op on PASS.

---

## 3. SQLite Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, sender TEXT, topic TEXT, project TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE gates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    name TEXT NOT NULL, state TEXT DEFAULT 'BLOCK'
        CHECK(state IN ('PASS','SKIP','WARN','BLOCK')),
    details TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, name)
);
CREATE TABLE gate_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, gate_name TEXT, from_state TEXT, to_state TEXT,
    reason TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, gate_name TEXT, raw_result TEXT,
    extracted TEXT, created_at TEXT DEFAULT (datetime('now'))
);
```

Four tables: sessions (per-gen context), gates (current state), gate_logs (audit trail), checkpoints (triple-match snapshots).

---

## 4. Gate State Machine

- **BLOCK** → generation halted. Agent calls `complete_gate(name, reason)` then re-runs `assert_gates()`.
- **PASS** → proceed.
- **WARN** → proceed with advisory note.
- **SKIP** → proceed (tool unavailable / N/A).

```
BLOCK ──complete_gate()──► PASS
PASS  ──(re-run)─────────► PASS
PASS  ──(advisory)──────► WARN
PASS  ──(N/A)───────────► SKIP
```

All transitions logged to `gate_logs`.

---

## 5. Triple-Match Flow

```
assert_gates(msg, sid)
  │
  ├─ 1. ContextExtract: parse sender, topic, project; upsert sessions table
  │
  ├─ 2. Gate 1a — AgentMemory: memory_recall(query=topic)
  │     no matches → PASS with empty list (first contact); else → PASS, store top-3 in checkpoints
  │
  ├─ 3. Gate 1b — Checkpoint: get_state(key=f"{project}:plan")
  │     missing/stale → BLOCK; else → PASS
  │
  ├─ 4. Gate 1e — Deck Scan: get_boards() → find project board → scan cards
  │     overdue → BLOCK; no open cards → WARN; else → PASS
  │
  └─ 5. Aggregate: any BLOCK → overall=BLOCK; else max(PASS,WARN,SKIP)
```

---

## 6. Context Extraction

| Field | Extraction |
|-------|-----------|
| `sender` | Hermes session metadata (tool arg) |
| `topic` | First sentence / leading noun phrase of `message` |
| `project` | Regex dict `(ultratimonel\|nocturno\|messagens\|...)` else `topic` |

---

## 7. SOUL.md Template

Inject into `~/.hermes/SOUL.md`:

```yaml
## Ultratimonel — Pre-flight Gates

Before EVERY generation, you MUST call `assert_gates()` with
`message` (user query) and `session_id` (active session).

- `BLOCK` → do NOT generate. Check each BLOCK gate, fix,
  call `complete_gate(name, reason)`, re-run `assert_gates()`.
- `WARN` → generate but prefix with gate warnings.
- `PASS` → proceed normally.

Gates: 1a=agentmemory, 1b=checkpoint, 1e=deck.

Failure to call assert_gates() is a protocol violation.
```

---

## 8. mcp-capabilities Bridge (Stub)

`bridge.py` — MVP no-op:

```python
# Post-MVP: register_capability({
#   "name":"ultratimonel",
#   "gates":["mission-gate","triple-match","soul-enforce"],
#   "tools":["assert_gates","check_gate","complete_gate"]
# })
```

In MVP, Ultratimonel is discovered via MCP tool list + SOUL.md rules.

---

## 9. Error Handling

|| Scenario | Behaviour |
||----------|-----------|
|| AgentMemory/Checkpoint timeout | Gate → WARN, detail warns |
|| AgentMemory/Checkpoint unavailable | Gate → WARN, detail warns |
|| Deck unavailable | Gate → SKIP, detail warns |
|| Deck timeout | Gate → WARN |
|| SQLite write fail | Log stderr, return PASS+warn |
|| Invalid gate name | `{"error": "unknown gate"}` |
|| `complete_gate` on non-BLOCK | No-op |

All external MCP calls wrapped in `try/except` → SKIP fallback. Ultratimonel never crashes.

---

## 10. Dependencies

| Dep | Version | Use |
|-----|---------|-----|
| Python | ≥3.13 | Runtime |
| fastmcp | latest | MCP framework |
| sqlite3 | stdlib | Persistence |
| agentmemory | existing | Gate 1a |
| checkpoint | existing | Gate 1b |
| nextcloud-deck | existing | Gate 1e |

No external deps beyond `fastmcp`. Three MCP tools already in Hermes profile.

---

*End of SDD — Ultratimonel MVP v1.0*

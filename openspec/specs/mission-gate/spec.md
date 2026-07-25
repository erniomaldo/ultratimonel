# Mission Gate — Pre-flight Gate Verification Protocol

> **Capability ID:** `mission-gate`
> **Status:** Active · **Updated:** 19 Jul 2026
> **MVP:** Yes — core capability

## 1. Purpose

Define the pre-flight gate verification protocol that Ultratimonel enforces before any LLM generation. The protocol exposes nine MCP tools that Hermes **MUST** call before generating a response to verify that requisite context (AgentMemory, Checkpoint, Collectives, Deck) has been gathered.

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F-MG-01 | The server SHALL expose an `assert_gates()` tool that runs all configured gates and returns a structured result per gate | MUST |
| F-MG-02 | The server SHALL expose a `check_gate(name)` tool that returns the current status of a single gate by name | MUST |
| F-MG-03 | The server SHALL expose a `complete_gate(name)` tool that marks a named gate as PASS | MUST |
| F-MG-04 | Each gate SHALL evaluate to exactly one of four states: `PASS`, `SKIP`, `WARN`, `BLOCK` | MUST |
| F-MG-05 | `assert_gates()` SHALL block generation (return `BLOCK`) if any mandatory gate has not passed | MUST |
| F-MG-06 | `assert_gates()` SHALL extract sender, topic, and project from the current message context | MUST |
| F-MG-07 | The protocol SHALL execute before **every** message generation (frequency: per-message) | MUST |
| F-MG-08 | The server SHALL support a configurable list of gate names and their mandatory/optional classification | MUST |
| F-MG-09 | `complete_gate(name)` SHALL reject attempts to complete a non-existent gate with a clear error | MUST |
| F-MG-10 | The server SHALL expose a `server(action)` tool to start/stop/status/restart the dashboard web server | MUST |
| F-MG-11 | The server SHALL expose a `map_list()` tool that lists all projects configured in project_maps.json | MUST |
| F-MG-12 | The server SHALL expose a `map_add(project, patterns, ...)` tool to add or update a project mapping | MUST |
| F-MG-13 | The server SHALL expose a `map_remove(project)` tool to delete a project from project_maps.json | MUST |
| F-MG-14 | The server SHALL expose `map_setup()` and `map_sync()` tools for discovery and verification of Deck boards / Collectives | MUST |

### 2.2 Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-MG-01 | `assert_gates()` SHALL complete in under 8 seconds total for all four core gates (40s timeout per gate) | MUST |
| NF-MG-02 | Per-gate timeout SHALL be 40 seconds; a timeout results in `WARN` state | MUST |
| NF-MG-03 | The server SHALL be stateless with respect to gate logic — state is delegated to `gate-persistence` | MUST |
| NF-MG-04 | `assert_gates()` calls SHALL be idempotent (repeated calls return the same result unless gate status changes) | SHOULD |
| NF-MG-05 | All tool invocations SHALL return valid JSON-RPC responses per MCP specification | MUST |

## 3. Gate States

| State | Label | Meaning | Generation Action |
|-------|-------|---------|-------------------|
| `PASS` | ✅ Pass | Gate completed successfully | Continue |
| `SKIP` | ⏭️ Skip | Gate does not apply to this context | Continue |
| `WARN` | ⚠️ Warn | Gate failed but is non-critical | Warn user, then continue |
| `BLOCK` | ❌ Block | Gate failed and is mandatory | **Halt generation** — run gate or inform user |

## 4. MCP Tool Specifications

### 4.1 `assert_gates()`

**Description:** Run all configured pre-flight gates and return a structured result for each. This is the primary entry point called by Hermes before generation.

**Input Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "message": {
      "type": "string",
      "description": "The user's raw message / query"
    },
    "session_id": {
      "type": "string",
      "description": "Active Hermes session identifier"
    },
    "sender": {
      "type": "string",
      "description": "Optional sender name (default: \"user\")"
    }
  },
  "required": ["message", "session_id"]
}
```

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["PASS", "BLOCK"],
      "description": "Overall status. PASS if all gates passed; BLOCK if any mandatory gate failed."
    },
    "gates": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name":        {"type": "string"},
          "state":       {"type": "string", "enum": ["PASS", "SKIP", "WARN", "BLOCK"]},
          "mandatory":   {"type": "boolean"},
          "duration_ms": {"type": "number"},
          "message":     {"type": "string", "description": "Human-readable result or error detail"}
        },
        "required": ["name", "state", "mandatory"]
      }
    },
    "context_envelope": {
      "type": "object",
      "description": "Aggregated context from all gates (memory snippets, checkpoint state, steering docs, deck cards)",
      "properties": {
        "memory_snippets":    {"type": "array"},
        "checkpoint_state":   {"type": "object"},
        "steering_docs":      {"type": "array"},
        "deck_cards":         {"type": "array"}
      }
    },
    "timestamp": {"type": "string", "format": "date-time"}
  },
  "required": ["status", "gates", "timestamp"]
}
```

### 4.2 `check_gate(name)`

**Description:** Query the current status of a single gate without running it.

**Input Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Gate name, e.g. '1a', '1b', '1c', '1e'"
    },
    "session_id": {
      "type": "string",
      "description": "Active session identifier"
    }
  },
  "required": ["name", "session_id"]
}
```

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "name":      {"type": "string"},
    "state":     {"type": "string", "enum": ["PASS", "SKIP", "WARN", "BLOCK", "PENDING"]},
    "mandatory": {"type": "boolean"},
    "updated_at":{"type": "string", "format": "date-time"},
    "message":   {"type": "string"}
  },
  "required": ["name", "state", "mandatory"]
}
```

### 4.3 `complete_gate(name)`

**Description:** Mark a gate as PASS explicitly. Used when the caller has satisfied the gate's requirement manually.

**Input Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Gate name to mark as passed"
    },
    "session_id": {
      "type": "string",
      "description": "Active session identifier"
    },
    "reason": {
      "type": "string",
      "description": "Human-readable reason for the transition"
    }
  },
  "required": ["name", "session_id"]
}
```

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "name":       {"type": "string"},
    "state":      {"type": "string", "enum": ["PASS"]},
    "message":    {"type": "string"},
    "updated_at": {"type": "string", "format": "date-time"}
  },
  "required": ["name", "state", "updated_at"]
}
```

### 4.4 `server(action)`

**Description:** Control the Ultratimonel Dashboard web server (FastAPI/stdio). Manages a subprocess that serves the dashboard GUI from the same SQLite DB as the gates.

**Input Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["status", "start", "stop", "restart"],
      "description": "Dashboard server action"
    }
  },
  "required": ["action"]
}
```

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "status":  {"type": "string", "description": "Server status (running/stopped)"},
    "message": {"type": "string", "description": "Human-readable result"}
  }
}
```

### 4.5 `map_list()`

**Description:** List all projects configured in project_maps.json with their patterns, deck_board_id, and collective_id.

**Input Schema:** None (no parameters)

**Output Schema:**

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "project":       {"type": "string"},
      "patterns":      {"type": "array", "items": {"type": "string"}},
      "deck_board_id": {"type": "integer"},
      "collective_id": {"type": "integer"}
    }
  }
}
```

### 4.6 `map_add(project, patterns, ...)`

**Description:** Add or update a project in project_maps.json with its keyword patterns and optional Nextcloud board/collective IDs.

**Input Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "project": {
      "type": "string",
      "description": "Project slug (e.g. \"voy-rojo\")"
    },
    "patterns": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Keywords to detect the project in user messages"
    },
    "deck_board_id": {
      "type": "integer",
      "description": "Nextcloud Deck board ID (0 if none)"
    },
    "collective_id": {
      "type": "integer",
      "description": "Nextcloud Collective ID (0 if none)"
    }
  },
  "required": ["project", "patterns"]
}
```

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "status":  {"type": "string"},
    "message": {"type": "string"}
  }
}
```

### 4.7 `map_remove(project)`

**Description:** Remove a project from project_maps.json.

**Input Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "project": {
      "type": "string",
      "description": "Project slug to remove"
    }
  },
  "required": ["project"]
}
```

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "status":  {"type": "string"},
    "message": {"type": "string"}
  }
}
```

### 4.8 `map_setup()`

**Description:** Discover available Deck boards and Collectives for mapping. Queries Nextcloud for active boards and collectives, then compares against current project_maps.json. Does NOT modify anything.

**Input Schema:** None (no parameters)

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "known_boards":        {"type": "array"},
    "unmapped_boards":     {"type": "array"},
    "known_collectives":   {"type": "array"},
    "unmapped_collectives":{"type": "array"}
  }
}
```

### 4.9 `map_sync()`

**Description:** Verify that mapped Deck boards still exist. Checks each project's deck_board_id against live Deck boards. Reports stale/deleted boards but does NOT modify anything.

**Input Schema:** None (no parameters)

**Output Schema:**

```json
{
  "type": "object",
  "properties": {
    "results":   {"type": "array"},
    "stale_ids": {"type": "array"}
  }
}
```

## 5. Scenarios

### 5.1 Happy Path — All Gates Pass

```
Given: Hermes receives a message from "erniomaldo" about project "ultratimonel"
When:  assert_gates() is called with message, session_id, sender
Then:  Each gate (1a, 1b, 1c, 1e) returns state: "PASS"
And:   overall status is "PASS"
And:   context_envelope contains memory_snippets, checkpoint_state, steering_docs, and deck_cards
```

### 5.2 Mandatory Gate Warns (First Contact)

```
Given: Gate 1a (AgentMemory recall) returns no matching memories
When:  assert_gates() completes
Then:  Gate 1a state is "PASS" with empty memory_snippets array
And:   overall status is "PASS" (empty results are not a failure — first contact scenario)
And:   generation proceeds normally with empty context
```

### 5.3 Optional Gate Warns

```
Given: Deck scan (gate 1e) times out after 40 seconds
When:  assert_gates() completes
Then:  Gate 1e state is "WARN"
And:   overall status is "PASS" (non-mandatory gates do not block)
And:   a warning message is included in the gate result
```

### 5.4 Gate Does Not Apply

```
Given: The current project has no associated Deck board
When:  Gate 1e runs
Then:  Gate 1e state is "SKIP"
And:   overall status is "PASS"
```

### 5.5 Check Gate Status

```
Given: Gate 1b has been completed in a previous assert_gates() call
When:  check_gate("1b") is called
Then:  state is "PASS"
And:   updated_at reflects the timestamp of completion
```

### 5.6 Complete Gate Explicily

```
Given: Gate 1a has not yet been run this session
When:  complete_gate("1a") is called
Then:  state becomes "PASS"
And:   subsequent check_gate("1a") returns "PASS"
```

### 5.7 Complete Non-Existent Gate

```
Given: A gate named "99z" does not exist in configuration
When:  complete_gate("99z") is called
Then:  The call returns an error: "Gate '99z' not found"
And:   no state changes are made
```

## 6. Error Handling

| Error | Condition | Response |
|-------|-----------|----------|
| `GATE_NOT_FOUND` | Referenced gate name is not in configuration | `{"error": "Gate '<name>' not found", "code": -32001}` |
| `MISSING_CONTEXT` | `message` or `session_id` missing | `{"error": "message and session_id are required", "code": -32002}` |
| `GATE_TIMEOUT` | Individual gate exceeds 40s timeout | Gate returns state `WARN` with message "Timeout after 40s" |
| `PERSISTENCE_ERROR` | SQLite write fails | Gate returns state `WARN` — state is degraded but generation continues |
| `TOOL_UNAVAILABLE` | Underlying MCP tool (memory/checkpoint/collectives/deck) unavailable | Gate returns state `SKIP` with explanation |

## 7. Gate Configuration

```yaml
gates:
  - name: "1a"
    source: "mcp_agentmemory_memory_recall"
    mandatory: true
    timeout_s: 40
  - name: "1b"
    source: "mcp_checkpoint_get_state"
    mandatory: true
    timeout_s: 40
  - name: "1c"
    source: "mcp_nextcloud_collectives_get_collectives"
    mandatory: true
    timeout_s: 40
  - name: "1e"
    source: "mcp_nextcloud_deck_get_boards"
    mandatory: true
    timeout_s: 40
```

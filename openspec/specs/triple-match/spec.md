# Triple Match — Coordinated 1a + 1b + 1e Unified Context

> **Capability ID:** `triple-match`
> **Status:** Draft · **Updated:** 28 Jun 2026
> **MVP:** Yes — core capability

## 1. Purpose

Define the orchestration of three independent context sources — AgentMemory (1a), Checkpoint (1b), and Deck scan (1e) — into a single unified context envelope that Hermes receives before generation. The triple match ensures that no generation occurs without visibility into past conversations, current project state, and pending tasks.

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F-TM-01 | The triple match SHALL execute gates in sequence: 1a → 1b → 1e | MUST |
| F-TM-02 | Gate 1a SHALL call `mcp_agentmemory_memory_smart_search` with the sender and topic as query | MUST |
| F-TM-03 | Gate 1b SHALL call `mcp_checkpoint_get_state` with the active project key | MUST |
| F-TM-04 | Gate 1e SHALL call `mcp_nextcloud_deck_get_boards` to list boards, then `mcp_nextcloud_deck_get_stacks` on the relevant board | MUST |
| F-TM-05 | The results from all three gates SHALL be compiled into a single `context_envelope` structure | MUST |
| F-TM-06 | The context envelope SHALL include: memory snippets, checkpoint state, and deck cards | MUST |
| F-TM-07 | The context envelope SHALL be returned as part of the `assert_gates()` response | MUST |
| F-TM-08 | A failure in one gate SHALL NOT prevent other gates from executing | MUST |
| F-TM-09 | Gate 1a with no results SHALL return an empty memory list (not a failure) | MUST |
| F-TM-10 | Gate 1b with no checkpoint SHALL create a default checkpoint with status "new" | MUST |
| F-TM-11 | Gate 1e with no matching board SHALL return an empty deck context (SKIP) | MUST |
| F-TM-12 | The server SHALL extract `sender`, `topic`, and `project` from the incoming `message_context` before starting the triple match | MUST |

### 2.2 Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-TM-01 | Total triple-match execution SHALL not exceed 5 seconds | MUST |
| NF-TM-02 | Each underlying tool call SHALL have an independent 2-second timeout | MUST |
| NF-TM-03 | The context envelope SHALL be serializable to JSON without loss | MUST |
| NF-TM-04 | Memory snippets SHALL be deduplicated by content hash before inclusion | SHOULD |
| NF-TM-05 | Deck cards SHALL be sorted by priority/order before inclusion | SHOULD |

## 3. Execution Flow

```
┌──────────────────────────────────────────────┐
│  assert_gates(message_context)                │
├──────────────────────────────────────────────┤
│                                               │
│  1. Parse message_context → sender, topic,    │
│     project                                   │
│                                               │
│  2. [GATE 1a] AgentMemory Recall              │
│     → smart_search(query=sender+topic)        │
│     → Returns: memory_snippets[]              │
│                                               │
│  3. [GATE 1b] Checkpoint Status               │
│     → get_state(key=project)                  │
│     → If not found: create default checkpoint │
│     → Returns: checkpoint_state{}             │
│                                               │
│  4. [GATE 1e] Deck Scan                      │
│     → get_boards() → filter by project name   │
│     → get_stacks(board_id) on matched board   │
│     → Returns: deck_cards[]                   │
│                                               │
│  5. Compile context_envelope {                │
│       memory_snippets,                        │
│       checkpoint_state,                       │
│       deck_cards                              │
│     }                                         │
│                                               │
│  6. Return structured result                  │
│                                               │
└──────────────────────────────────────────────┘
```

## 4. Context Envelope Schema

```json
{
  "context_envelope": {
    "memory_snippets": [
      {
        "id": "obs-abc123",
        "content": "...",
        "timestamp": "2026-06-28T10:00:00Z",
        "type": "preference|decision|correction|session_context"
      }
    ],
    "checkpoint_state": {
      "key": "ultratimonel",
      "value": {
        "project": "ultratimonel",
        "phase": "specs",
        "last_action": "write_specs",
        "status": "in_progress"
      },
      "version": 3,
      "updated_at": "2026-06-28T10:30:00Z"
    },
    "deck_cards": [
      {
        "id": 42,
        "title": "Implement assert_gates()",
        "stack": "In Progress",
        "priority": "high",
        "labels": ["mcp", "python"],
        "duedate": "2026-07-01"
      }
    ]
  }
}
```

## 5. Scenarios

### 5.1 Full Triple Match Successful

```
Given: A message_context with sender="erniomaldo", topic="gate implementation", project="ultratimonel"
When:  assert_gates() executes the triple match
Then:  Gate 1a returns AgentMemory snippets for topic "gate implementation"
And:   Gate 1b returns checkpoint state for "ultratimonel"
And:   Gate 1e returns deck cards for the "ultratimonel" board
And:   context_envelope contains all three data sets
And:   overall status is "PASS"
```

### 5.2 First Contact — No Memory, No Checkpoint

```
Given: This is the first interaction with this sender/topic
When:  Triple match executes
Then:  Gate 1a returns state "PASS" with empty memory_snippets array
And:   Gate 1b creates a default checkpoint {"status": "new"} and returns state "PASS"
And:   Gate 1e runs normally
And:   overall status is "PASS"
```

### 5.3 Gate 1a Timeout, Others Succeed

```
Given: AgentMemory server is slow and smart_search takes > 2 seconds
When:  Triple match executes
Then:  Gate 1a returns state "WARN" with message "Timeout after 2s"
And:   Gate 1b and 1e execute normally despite 1a timeout
And:   overall status is "PASS" (1a is mandatory but timeout → WARN, not BLOCK)
And:   context_envelope contains checkpoint_state and deck_cards but empty memory_snippets
```

### 5.4 No Deck Board for Project

```
Given: The current project "ultratimonel" has no corresponding Deck board
When:  Gate 1e executes
Then:  Gate 1e returns state "SKIP" with message "No Deck board found for project 'ultratimonel'"
And:   context_envelope.deck_cards is an empty array
And:   overall status is "PASS"
```

### 5.5 Checkpoint Not Found Creates Default

```
Given: No checkpoint exists for key "ultratimonel"
When:  Gate 1b executes
Then:  A new checkpoint is created with {"status": "new"}
And:   Gate 1b returns state "PASS"
And:   checkpoint_state reflects the newly created checkpoint
```

### 5.6 Sequential Gate Failure Isolation

```
Given: Gate 1a times out, Gate 1b returns data, Gate 1e fails with tool unavailable
When:  Triple match completes
Then:  1a: WARN, 1b: PASS, 1e: SKIP
And:   No gate failure prevents a subsequent gate from executing
And:   context_envelope contains checkpoint_state only
```

## 6. Gate-Specific Details

### 6.1 Gate 1a — AgentMemory Recall

- **Tool:** `mcp_agentmemory_memory_smart_search(query, limit)`
- **Query:** Concatenation of `sender` and `topic` from message context
- **Limit:** 10 results
- **Default:** Empty array if no results
- **Idempotent:** Yes — same query returns same results (time-bound)

### 6.2 Gate 1b — Checkpoint Status

- **Tool:** `mcp_checkpoint_get_state(key=project)`
- **Key:** The `project` field from message context
- **Not found:** Create initial checkpoint via `mcp_checkpoint_set_state(key, {"status": "new"})`
- **Idempotent:** Yes — repeated calls return same state until mutation

### 6.3 Gate 1e — Deck Scan

- **Tools:** `mcp_nextcloud_deck_get_boards()` → filter → `mcp_nextcloud_deck_get_stacks(board_id)`
- **Filtering:** Match board title against project name (case-insensitive substring match)
- **Not found:** Return SKIP + empty cards
- **Cards:** Include title, stack name, labels, priority, duedate
- **Idempotent:** Yes — same board returns same cards (until Deck is mutated)

## 7. Error Handling

| Error | Condition | Gate State | Message |
|-------|-----------|------------|---------|
| `MEMORY_UNAVAILABLE` | AgentMemory tool throws | `WARN` | "AgentMemory unavailable: <details>" |
| `CHECKPOINT_UNAVAILABLE` | Checkpoint tool throws | `WARN` | "Checkpoint unavailable: <details>" |
| `DECK_UNAVAILABLE` | Nextcloud tools throw | `SKIP` | "Deck scan skipped: <details>" |
| `TIMEOUT_1a` | smart_search > 2s timeout | `WARN` | "Timeout after 2s for gate 1a" |
| `TIMEOUT_1b` | get_state > 2s timeout | `WARN` | "Timeout after 2s for gate 1b" |
| `TIMEOUT_1e` | Deck tools > 2s combined | `WARN` | "Timeout after 2s for gate 1e" |

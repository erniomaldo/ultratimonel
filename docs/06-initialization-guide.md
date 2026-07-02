# Initialization Guide — Auto-Discovery & Population

This guide teaches a **fresh ultratimonel installation** how to auto-discover
the user's projects, boards, and tasks — and populate all three data sources
(AgentMemory, Checkpoint, Nextcloud Deck) so that `assert_gates()` returns
`PASS` with real data on every gate.

It is **100% agnostic**. It does not depend on specific project names,
board IDs, or infrastructure. The Hermes Agent discovers everything on its own.

---

## How It Works

```
deck_get_boards() → filter active → deck_get_stacks() per board
    → sync context_extractor.py maps
    → save checkpoints (Gate 1b)
    → save memories (Gate 1a)
    → verify with assert_gates()
```

---

## Step-by-Step Instructions

Give this prompt to a **fresh Hermes Agent** that just had ultratimonel installed:

> **INSTRUCTION — Initialize ultratimonel with auto-discovery**
>
> Your task is to populate ultratimonel with real project data from the
> user's Nextcloud ecosystem. Follow these steps in order.
>
> ### Step 1 — Discover boards and tasks
>
> ```bash
> deck_get_boards()
> ```
>
> From the response, keep only boards where `deletedAt === 0` (active).
> For each active board, record its `id`, `title`, and `color`.
>
> Then discover stacks and cards for each board:
>
> ```bash
> deck_get_stacks(board_id=N, include_cards=true)
> ```
>
> Record each stack's `id`, `title`, and every card's `title`, `description`,
> `archived`, `duedate`, and `labels`.
>
### Step 2 — Sync maps via `project_maps.json`

Machine-specific project maps now live in **`project_maps.json`** (gitignored)
at the repo root, not in Python code.  A template is available at
`project_maps.json.template`.

Open or create `project_maps.json` and populate it with your boards and
collectives:

```json
{
  "collectives": {
    "<slug>": <collective_id>
  },
  "decks": {
    "<slug>": <board_id>
  }
}
```

| Map section | Purpose | Example entry |
|-------------|---------|---------------|
| `collectives` | Slug → Nextcloud Collective ID | `"voy-rojo": 6` |
| `decks` | Slug → Deck board ID | `"voy-rojo": 7` |

The regex patterns in `KNOWN_PROJECTS` (inside `context_extractor.py`)
still detect the project name from user messages — you only need to add
a pattern there if the board/collective slug is not already covered.

**Slug rules:** lower-case title, spaces → hyphens, strip special chars.

Compare against the real boards from Step 1. For every active board that
is **not yet mapped** in `project_maps.json`:

1. Derive a slug from the board title
2. If no regex matches it yet, add an entry to `KNOWN_PROJECTS`
   in `context_extractor.py`
3. Add an entry to the `decks` section of `project_maps.json`
4. If a matching Nextcloud Collective exists, add to the `collectives` section

> **Note:** Changes to `project_maps.json` and `context_extractor.py` both
> take effect after the MCP server restarts (next session or `/reload-mcp`).
> The JSON file is gitignored — each machine has its own.
>
> ### Step 3 — Populate Checkpoints (Gate 1b)
>
> For **each** project in `PROJECT_DECK_MAP`:
>
> ```
> mcp_checkpoint_force_set_state(
>     key="ultratimonel:<slug>",
>     value='{"status":"active","boards":[<board_id>]}'
> )
> ```
>
> ### Step 4 — Populate AgentMemory (Gate 1a)
>
> For **each** project:
>
> ```
> mcp_agentmemory_memory_save(
>     content="Project <name>: board ID <N>, stacks: <list>, <N> total cards",
>     type="project",
>     concepts="<slug>,deck"
> )
> ```
>
> ### Step 5 — Optional: Collectives (Gate 1c)
>
> ```
> mcp_nextcloud_collectives_get_collectives()
> ```
>
> If collectives exist that correspond to mapped projects, add their IDs
> to `PROJECT_COLLECTIVE_MAP`.
>
> ### Step 6 — Verify
>
> For **each** mapped project, run:
>
> ```
> mcp_ultratimonel_assert_gates(
>     message="Review project <slug>",
>     session_id="init-<slug>"
> )
> ```
>
| Gate | Expected | Meaning |
|------|----------|---------|
| 1a | PASS | AgentMemory has a record for this project |
| 1b | PASS | Checkpoint exists for this project |
| 1c | PASS or SKIP | Collective mapped (optional) |
| 1e | PASS | Deck board has cards |
| **Status** | **PASS** | All mandatory gates cleared |
>
> If a gate returns WARN or BLOCK, re-run the corresponding step and retry.
>
> ### Step 7 — Report
>
> Deliver a summary to the user:
>
> - **Projects mapped:** N
> - **Boards discovered:** N
> - **Stacks & cards:** N stacks, N cards total
> - **Checkpoints saved:** N
> - **Memories saved:** N
> - **Gate status per project:** all PASS ✅
>
> ---
>
> **TL;DR:** `deck_get_boards` → filter active → `deck_get_stacks` →
> sync `context_extractor.py` → checkpoints → memories → `assert_gates`.
> The Hermes discovers everything on its own.

---

## Adding a New Project Later

When the user needs to onboard a new project:

1. **Create board**: `deck_create_board(title, color)` if it doesn't exist
2. **Create stacks**: `deck_create_stack(board_id, title, order)` for columns
3. **Add cards**: `deck_create_card(board_id, stack_id, title, description)`
4. **Sync maps**: add to `project_maps.json` (decks + collectives) and optionally `KNOWN_PROJECTS` in `context_extractor.py` if a new regex is needed
5. **Checkpoint**: `mcp_checkpoint_force_set_state(key="ultratimonel:<slug>", ...)`
6. **Memory**: `mcp_agentmemory_memory_save(content=..., type="project", ...)`
7. **Verify**: `assert_gates(message="<slug>", session_id="verify-<slug>")`

---

## Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Board is soft-deleted | `deletedAt !== 0` | Skip — board doesn't exist |
| Maps out of sync | Gate 1e returns SKIP | Sync `project_maps.json` with real boards |
| No checkpoint | Gate 1b returns WARN | Run Step 3 |
| No memory | Gate 1a returns WARN | Run Step 4 |
| Context extractor stale | Project not detected | Restart MCP server after editing |
| Wrong slug | Project detection fails | Check regex in KNOWN_PROJECTS |

---

## Files Referenced

| File | Purpose |
|------|---------|
| `project_maps.json` | Machine-specific project→board/collective mappings (gitignored) |
| `ultratimonel/context_extractor.py` | Project regex patterns (KNOWN_PROJECTS) and map loader |
| `~/.hermes/ultratimonel.db` | Gate state persistence (SQLite) |
| `~/.hermes/config.yaml` | MCP server registration |

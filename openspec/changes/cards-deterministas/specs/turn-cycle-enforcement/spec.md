# Delta for turn-cycle-enforcement

> NEW capability. Base main spec does NOT exist yet: `cards-solo-ultratimonel` is verified but not archived, so all requirements are declared ADDED (no invented base).
>
> **Sequencing (M4)**: if `cards-solo-ultratimonel` archives first, its base spec becomes the baseline and this delta's ADDED-vs-MODIFIED split must be re-checked before apply. Requirement IDs `TCE1–TCE4` stay stable regardless.

## ADDED Requirements

### Requirement TCE1: Single State Channel and Order Validation

The cycle `begin_turn → work → end_turn` SHALL be the only state channel. State-mutating work MUST NOT occur before `begin_turn` or after `end_turn`.

#### Scenario: Work before begin_turn is rejected

- GIVEN no active turn
- WHEN a state-mutating tool is called before `begin_turn`
- THEN the call is rejected with a clear error
- AND no state is mutated

#### Scenario: Duplicate begin_turn is rejected

- GIVEN an active turn already started in the same response
- WHEN a second `begin_turn` is issued
- THEN the second call is rejected
- AND the original turn remains active

#### Scenario: State tool after end_turn is rejected

- GIVEN `end_turn` just closed the turn
- WHEN another state-mutating tool is called before the next `begin_turn`
- THEN the call is rejected until a new turn starts

### Requirement TCE2: Attempt Budget

Each quest SHALL have a bounded attempt budget **once it is armed**. After arming, when the budget is exhausted, further attempts MUST fail hard with a clear error and MUST NOT mutate state.

**Authoritative budget model (this closes the backfill lockout):**

- `attempts_authorized = 0` **and** no `attempt_grants` row for the quest ⇒ **legacy / unbounded** (budget NOT enforced). This is the post-migration backfill state and the deliberate rollout guard: existing live quests keep working after cutover (design Migration step 2).
- The **first authorization grant** sets `attempts_authorized > 0`, which **arms** the budget for that quest.
- Once armed: `attempts_used >= attempts_authorized` ⇒ fail hard with `code="attempt_budget_exhausted"`, no mutation.
- `0` only ever means "not yet armed"; it never means "exhausted". Backfill MUST NOT be read as a zero-budget quest.
- The check and the increment MUST be **one atomic operation** (M1): a single `UPDATE … SET attempts_used = attempts_used + 1 WHERE id = ? AND attempts_used < attempts_authorized`, failing when 0 rows are affected. There MUST be no window between check and increment.

#### Scenario: Attempt within budget is allowed (armed)

- GIVEN a quest whose budget is armed and `attempts_used` is below `attempts_authorized`
- WHEN `begin_turn` is called
- THEN the intento is created
- AND `attempts_used` is incremented atomically (check-then-increment in one statement)

#### Scenario: Legacy quest without a grant is allowed and then armed

- GIVEN a quest backfilled with `attempts_authorized = 0` and no `attempt_grants` row
- WHEN `begin_turn` is called
- THEN the intento is created (budget not enforced)
- AND the first authorization grant sets `attempts_authorized > 0`, arming the budget for that quest

#### Scenario: Exhausted armed budget blocks hard

- GIVEN a quest whose budget is armed and `attempts_used` equals `attempts_authorized`
- WHEN a new attempt is requested
- THEN the call fails with a budget-exhausted error
- AND no intento is created and no state is mutated

### Requirement TCE3: Closure Ownership

`end_turn` SHALL be the only **agent-facing** operation that flips a quest `done` false→true, and it MUST do so **only when the turn verdict is `success`**. A `fail` verdict finalizes the intento (recording the verdict on the intento) and leaves the quest `done=false`, so the attempt budget — not a premature close — governs whether another attempt is allowed. Closure and intento finalization happen in the single closure transaction with the bitácora append (design D4).

**External closers (reconciliation):** quests can also be closed outside the turn surface — a manual close in the Deck UI, or a replica update applied by `sync_task`. Those are not agent tools and are not forbidden. The system MUST reconcile them: a quest observed as `done=true` on the next `begin_turn` fails with `quest_done` (TSP2), is NOT reopened, and does NOT charge a new attempt.

#### Scenario: end_turn with a success verdict closes the quest

- GIVEN a turn bound to a quest with `done=false`
- WHEN `end_turn` runs with a success verdict
- THEN the quest `done` becomes `true`
- AND the intento is finalized with its own verdict

#### Scenario: end_turn with a fail verdict does NOT close the quest

- GIVEN a turn bound to a quest with `done=false`
- WHEN `end_turn` runs with a fail verdict
- THEN the intento is finalized as failed
- AND the quest remains `done=false`, so a later attempt may be made within budget

#### Scenario: No other agent tool closes a quest

- GIVEN the full agent-facing tool catalog
- WHEN it is enumerated
- THEN no tool other than `end_turn` sets a quest `done` to `true`

#### Scenario: Externally closed quest is reconciled, not reopened

- GIVEN a quest closed outside the turn surface (dependent Deck UI close, or a `sync_task` replica update)
- WHEN `begin_turn` is called for that quest
- THEN `begin_turn` fails with `quest_done`
- AND the quest is not reopened and no attempt is charged

### Requirement TCE4: Binding Validation

`begin_turn` SHALL bind the intento to `{session_id, project, mission_id, quest_id}` (`quest_id` is the canonical public name; see the alias rule in design I1). `end_turn` MUST reject an intento whose binding does not match the active turn, and MUST recover an orphaned `running` intento as `fail`.

#### Scenario: Matching binding closes the turn

- GIVEN an active intento whose binding matches the request
- WHEN `end_turn` is called
- THEN the turn closes normally

#### Scenario: Mismatched binding is rejected

- GIVEN an intento whose binding does not match the active turn
- WHEN `end_turn` targets it
- THEN the call is rejected with a binding-mismatch error

#### Scenario: Orphaned running intento is recovered

- GIVEN a `running` intento with no matching active turn
- WHEN a new turn starts
- THEN the orphan is completed as `fail`
- AND the system remains recoverable

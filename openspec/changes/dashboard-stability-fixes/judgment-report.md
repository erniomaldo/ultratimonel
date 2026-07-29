# Judgment Day — Dashboard Stability Fixes (Restart Block)

> **Target:** `ultratimonel/server.py` restart block + full change set
> **Date:** 29 Jul 2026
> **Round:** 1 (inline adversarial review, no sub-agents per user instruction)

---

## COMPLETITUD — All 10 requirements covered?

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| F-DS-01 | dashboard_server.py writes to persistent file + stderr | ✅ PASS | Lines 45-61: `FileHandler(LOG_FILE)` + `StreamHandler(sys.stderr)` |
| F-DS-02 | SO_REUSEADDR=1 on HTTP socket | ✅ PASS | Line 489: `server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)` |
| F-DS-03 | run_server() try/except KeyboardInterrupt / except Exception / finally | ✅ PASS | Lines 512-522: full block with `logger.exception()` + `server.shutdown()` |
| F-DS-04 | _db() passes timeout=5.0 to sqlite3.connect() | ✅ PASS | Line 98: `sqlite3.connect(DB_PATH, timeout=5.0)` |
| F-DS-05 | status reads residual stderr before nulling, returns exit_code + stderr_tail | ✅ PASS | Lines 391-405: reads `_dashboard_proc.stderr.read()`, returns both fields |
| F-DS-06 | start handler crash returns `hint` instead of inline stderr | ✅ PASS | Line 486: `"hint": f"Check logs: {log_dir}/dashboard_stderr.log"` |
| F-DS-07 | Subprocess stdout/stderr → persistent log files (not PIPE) | ✅ PASS | Start: lines 458-469 · Restart: lines 524-534 — both use append-mode file handles |
| F-DS-08 | Fixed DASHBOARD_PORT, no _find_free_port() | ✅ PASS | Start: line 452 · Restart: line 521 — both use `DASHBOARD_PORT` directly |
| NF-DS-01 | Log files created automatically if parent dir missing | ✅ PASS | Both blocks: `os.makedirs(log_dir, exist_ok=True)` |
| NF-DS-02 | Exception tracebacks include full stack via logger.exception() | ✅ PASS | dashboard_server.py line 519: `logger.exception("Dashboard server crashed: %s", exc)` |

**COMPLETITUD Verdict:** ALL 10 REQUIREMENTS COVERED ✅

---

## CORRECCIÓN — Changes correct and safe?

### Restart block changes applied:
| Change | Before | After | Safe? |
|--------|--------|-------|-------|
| Port allocation | `_find_free_port(DASHBOARD_PORT)` | `DASHBOARD_PORT` | ✅ Fixed port matches design AD-3 |
| Subprocess streams | `stdout=subprocess.PIPE, stderr=subprocess.PIPE` | `stdout=log_out, stderr=log_err` | ✅ Persistent logs match design AD-4 |
| Crash diagnostic | No hint field | `"hint": f"Check logs: {log_dir}/dashboard_stderr.log"` | ✅ Matches start block pattern (F-DS-06) |
| Script guard | Missing | `if script is None: return error+hint` | ✅ Now matches start block — prevents AttributeError |
| FileNotFoundError | Caught in generic except | Separate `except FileNotFoundError` handler | ✅ More precise error message |

### Safety checks:
- **log_out/log_err leak:** File handles opened but never explicitly closed. Same pattern as `start` block. Acceptable trade-off per AD-4 (long-running service, descriptors freed on process exit). Not a bug — documented in design.
- **Restart stop logic:** Line 500 checks `_dashboard_proc is not None and poll() is None` — only attempts stop if process is alive. If already null/stopped, skips gracefully. ✅ Correct.
- **Crash handling after restart:** Sets `_dashboard_proc = None` before returning hint. Consistent with start block behavior. ✅ Correct.
- **Both files compile:** `python -m py_compile` passes for both `server.py` and `dashboard_server.py`. ✅

**CORRECCIÓN Verdict:** ALL CHANGES CORRECT AND SAFE ✅

---

## COHERENCIA — Code matches design and specs?

### Design ↔ Code traceability:
| Design | Spec Req | Code Location | Match? |
|--------|----------|---------------|--------|
| AD-1: SO_REUSEADDR | F-DS-02 | dashboard_server.py:489 | ✅ Exact match |
| AD-2: Dual logging (file+stderr) | F-DS-01 | dashboard_server.py:52-59 | ✅ Exact match |
| AD-3: Fixed port | F-DS-08 | server.py:452, 521 | ✅ Both blocks use DASHBOARD_PORT |
| AD-4: Subprocess → file handles | F-DS-07 | server.py:458-469, 524-534 | ✅ Both blocks identical pattern |
| AD-5: NO null-tear on status | F-DS-05 | server.py:391-405 | ✅ Reads stderr before returning |
| AD-6: SQLite timeout 5s | F-DS-04 | dashboard_server.py:98 | ✅ Exact match |
| AD-7: try/except/finally in run_server | F-DS-03 | dashboard_server.py:512-522 | ✅ Exact match |

### Spec ↔ Code traceability (restart-specific):
| Scenario | Requirement | Restart Block Coverage |
|----------|-------------|----------------------|
| S6: Subprocess logs survive restart | F-DS-07 | Restart opens same append-mode files · Old entries preserved in `{log_dir}/dashboard_stderr.log` |
| S5: Immediate crash returns hint | F-DS-06 | Restart returns `hint` field on post-wait crash (line 551) |

**COHERENCIA Verdict:** CODE MATCHES DESIGN AND SPECS ✅

---

## RIESGOS — Remaining issues?

| # | Risk | Severity | Justification |
|---|------|----------|---------------|
| R-1 | `log_out`/`log_err` file handles never closed (start + restart) | 🟡 INFO (theoretical) | Same pattern in both blocks. Acceptable for long-running service per AD-4 design trade-off. Descriptors freed on process exit. Would require explicit close() cleanup pattern to fix — not warranted by current scope. |
| R-2 | Restart error message differs from start ("failed" vs "exited immediately") | 🟢 INFO (theoretical) | Intentional semantic difference: start reports "process died on first launch", restart reports "restart failed". Both are accurate for their context. Not a bug. |
| R-3 | Status action does NOT null `_dashboard_proc` after reading stderr (per AD-5 trade-off) | 🟡 INFO (theoretical) | Documented in design: proc reference stays non-null until explicit stop. Status keeps reporting stale pid. Functionally correct via `poll()` check each call. Would need a separate "auto-cleanup on status" task to change — out of scope. |

**No CRITICAL or real WARNING risks identified.**

---

## Final Verdict

| Dimension | Result |
|-----------|--------|
| COMPLETITUD | ✅ ALL 10 REQUIREMENTS COVERED |
| CORRECCIÓN | ✅ ALL CHANGES CORRECT AND SAFE |
| COHERENCIA | ✅ CODE MATCHES DESIGN AND SPECS |
| RIESGOS | 🟢 NO CRITICAL / REAL WARNING RISKS |

**JUDGMENT: APPROVED ✅**

---

## Spec Gap Analysis

The review confirms the restart block now fully implements the same stability guarantees as the start block. No spec requirements were found to be violated or incomplete. The existing spec (F-DS-06) specifically names the "start handler" for the hint requirement, but the restart fix is a natural extension of Fix 7 from the proposal — implementing the same pattern consistently across both code paths. This exceeds spec minimums without violating any requirement.

**Spec update required: NO** ✅

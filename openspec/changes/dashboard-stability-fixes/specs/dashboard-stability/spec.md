# Dashboard Stability — Spec

> **Change:** `dashboard-stability-fixes`
> **Status:** Draft · **Updated:** 2026-08-03

## 1. Purpose

Define the stability fixes for the dashboard server and its parent process (`server.py`). These changes address six audit gaps: missing persistent logging, no port-reuse on restart, null-state tear-down on crash, unbounded SQLite locks, ephemeral subprocess pipes, and unstable port allocation.

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F-DS-01 | `dashboard_server.py` SHALL write logs to a persistent file at `~/.hermes/logs/dashboard.log` (configurable via `ULTRATIMONEL_LOG_DIR`) AND continue writing to `sys.stderr` | MUST |
| F-DS-02 | The HTTP server socket SHALL set `SO_REUSEADDR=1` so the port is immediately reclaimable after an ungraceful exit | MUST |
| F-DS-03 | `run_server()` SHALL use a `try/except KeyboardInterrupt / except Exception / finally` block that calls `server.shutdown()` and logs each transition | MUST |
| F-DS-04 | `_db()` SHALL pass `timeout=5.0` to `sqlite3.connect()` to prevent indefinite blocking on lock contention | MUST |
| F-DS-05 | The status endpoint (`action=status`) SHALL read residual stderr from the dashboard subprocess log file before nulling its reference, and return both `exit_code` and `stderr_tail` (last 2000 chars) in the JSON response | MUST |
| F-DS-06 | On immediate post-start crash, **both** the start **and** restart handlers SHALL return a `hint` field pointing to the log file path (`dashboard_stderr.log`) instead of an inline `stderr` string | MUST |
| F-DS-07 | The dashboard subprocess SHALL write stdout and stderr to persistent log files (`dashboard_stdout.log`, `dashboard_stderr.log`) under `{db_dir}/logs/` (fallback: `~/.hermes/logs/`) instead of `subprocess.PIPE` | MUST |
| F-DS-08 | The dashboard port SHALL be the fixed `DASHBOARD_PORT` value rather than a dynamically discovered free port, relying on SO_REUSEADDR for restart reliability | MUST |

### 2.2 Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-DS-01 | Log files SHALL be created automatically if the parent directory does not exist | SHOULD |
| NF-DS-02 | Exception tracebacks in `run_server()` SHALL include full stack via `logger.exception()` | MUST |
| NF-DS-03 | File handles for subprocess log files SHALL be closed in all code paths (success and error) using try/finally or context managers | MUST |

## 3. Scenarios

### Scenario 1: Dashboard log file is written and readable after restart

**GIVEN** the dashboard server has started at least once
**WHEN** a request is served or an error occurs
**THEN** the event is appended to `~/.hermes/logs/dashboard.log`
**AND** the same event is emitted to stderr for live observation

### Scenario 2: Server rebinds port immediately after crash

**GIVEN** the dashboard server crashed without calling `shutdown()` (e.g. OOM, signal)
**WHEN** `run_server()` is invoked again on the same host and port
**THEN** the new process binds successfully within one second
**AND** no `OSError: [Errno 98] Address already in use` is raised

### Scenario 3: SQLite lock does not block indefinitely

**GIVEN** another process holds a write lock on the dashboard database
**WHEN** `_db()` opens a connection to execute a query
**THEN** the connection attempt times out after 5 seconds and raises `sqlite3.OperationalError`
**AND** the server remains running (does not crash or hang)

### Scenario 4: Status reports stderr before nulling subprocess reference

**GIVEN** the dashboard subprocess has exited with a non-zero code
**WHEN** `server(action='status')` is called
**THEN** the response JSON contains both `exit_code` and `stderr_tail`
**AND** `_dashboard_proc` is set to `None` only after its stderr log file has been read

### Scenario 5: Immediate crash returns log hint, not inline stderr

**GIVEN** the dashboard process exits within the 0.5 s startup window
**WHEN** `server(action='start')` completes and detects the early exit
**THEN** the response contains a `hint` field with the path to `dashboard_stderr.log`
**AND** no `stderr` field is returned inline

### Scenario 6: Subprocess logs survive server restart

**GIVEN** the dashboard subprocess has been running for some time
**WHEN** the parent Hermes server restarts and spawns a new dashboard process
**THEN** old log entries remain in `{log_dir}/dashboard_stderr.log` and `{log_dir}/dashboard_stdout.log`
**AND** the new process appends to the same files (append mode)

### Scenario 7: Restart handler returns log hint on crash

**GIVEN** the dashboard process exits within the 0.5 s startup window after a restart
**WHEN** `server(action='restart')` completes and detects the early exit
**THEN** the response contains a `hint` field with the path to `dashboard_stderr.log`
**AND** no inline stderr is returned

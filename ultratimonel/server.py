"""
server.py - FastMCP server with tools for gates, dashboard, and project maps.

Tools:
  - assert_gates(message, session_id)  -> ~~DEPRECATED~~ run all gates (use begin_turn)
  - check_gate(name, session_id)       -> read gate status from SQLite
  - complete_gate(name, session_id, reason) -> BLOCK->PASS / WARN->PASS
  - server(action)                     -> control dashboard web UI
  - map_list()                         -> list configured projects
  - map_add(...)                       -> add/update a project
  - map_remove(project)                -> remove a project
  - map_setup()                        -> discover boards/collectives
  - map_sync()                         -> verify board IDs are live

ANTIPATRON: No agregues proyectos, boards o collectives aqui.
Toda la config de proyectos vive en project_maps.json y se gestiona
exclusivamente via las tools MCP map_*.
Editar server.py para configurar proyectos es un error de diseno.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone

from fastmcp import FastMCP

from .context_extractor import extract_context, is_known_project
from .gate_engine import (
    GATE_CONFIG_MAP,
    DEFAULT_GATES,
    GateConfig,
    GateResult,
    aggregate,
    can_complete,
    run_gate,
    PASS,
    BLOCK,
    WARN,
    SKIP,
)
from .persistence import Persistence
from .triple_match import (
    run_triple_match,
    build_context_envelope,
)

logger = logging.getLogger(__name__)

# ── Server setup ────────────────────────────────────────────────────────

app = FastMCP("ultratimonel")

# Persistence layer — shared across tools
db_path = os.environ.get(
    "ULTRATIMONEL_DB_PATH",
    os.path.expanduser("~/.hermes/ultratimonel.db"),
)
persistence = Persistence(db_path)

# ── Dashboard process management ──────────────────────────────────────────

DASHBOARD_PORT = int(os.environ.get("ULTRATIMONEL_DASHBOARD_PORT", "3005"))
_dashboard_proc: subprocess.Popen | None = None
_dashboard_port: int = DASHBOARD_PORT


def _dashboard_script() -> str | None:
    """Return the path to dashboard_server.py, or None if not found."""
    here = os.path.dirname(__file__)
    candidate = os.path.join(here, "dashboard_server.py")
    if os.path.isfile(candidate):
        return candidate
    return None


def _find_free_port(start: int = 3005, max_tries: int = 20) -> int:
    """Find the first free port starting from `start`."""
    import socket

    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start  # give up, let it fail later


#
# ── Turn state (server-side turn-scoping) ───────────────────────────────
# Complements plugin_preflight.py's _turn_active/_turn_ended.
# Used by begin_turn/end_turn to validate意图 belongs to current turn.
#

import threading as _threading

_turn_lock = _threading.RLock()
_active_intento: dict | None = None  # {intento_id, session_id, project}


def _get_active_intento() -> dict | None:
    """Return the active intento info under lock."""
    with _turn_lock:
        return _active_intento.copy() if _active_intento else None


def _set_active_intento(intento_id: int, session_id: str, project: str) -> None:
    """Set the active intento under lock."""
    global _active_intento
    with _turn_lock:
        _active_intento = {
            "intento_id": intento_id,
            "session_id": session_id,
            "project": project,
        }


def _clear_active_intento() -> None:
    """Clear the active intento under lock."""
    global _active_intento
    with _turn_lock:
        _active_intento = None


def _validate_gates_for_completion(
    session_id: str, project: str
) -> tuple[bool, list[str]]:
    """Validate that all mandatory gates are PASS/SKIP/PENDING.

    Returns:
        (allowed, failed_details) — allowed=True means completion is permitted.
    """
    gates = persistence.list_gate_states(session_id, project)
    failed = [
        f"{g.get('gate_name', '?')}({g.get('state', 'UNKNOWN')}): {g.get('message', '')}"
        for g in gates
        if g.get("mandatory") and g.get("state") not in ("PASS", "SKIP", "PENDING")
    ]
    return (len(failed) == 0, failed)


def _resolve_requesting_intento(
    session_id: str, project: str
) -> int | None:
    """Resolve the intento_id that should be considered 'requesting' for a
    begin_turn call. Returns the latest running intento for this session+project,
    or None if none exists. Used by begin_turn to detect orphaned turns."""
    try:
        # Find the most recent running intento for this session+project
        with persistence._conn() as conn:
            row = conn.execute(
                """SELECT id FROM intentos
                   WHERE session_id = ? AND project = ? AND status = 'running'
                   ORDER BY started_at DESC LIMIT 1""",
                (session_id, project),
            ).fetchone()
            return row["id"] if row else None
    except Exception as exc:
        logger.warning("Failed to resolve requesting intento: %s", exc)
        return None


#
# ── Tool handlers ───────────────────────────────────────────────────────


@app.tool()
def check_gate(
    name: str,
    session_id: str,
) -> str:
    """Return the current status of a single gate.

    Args:
        name:       Gate name, e.g. "1a", "1b", "1e".
        session_id: Active session identifier.

    Returns:
        JSON string with gate name, state, mandatory, message, updated_at.
    """
    if name not in GATE_CONFIG_MAP:
        return json.dumps(
            {
                "error": f"Gate '{name}' not found",
                "valid_gates": list(GATE_CONFIG_MAP.keys()),
            }
        )

    try:
        # We need the project — try from latest session
        session = persistence.get_session(session_id)
        project = session["project"] if session else "unknown"

        state = persistence.get_gate_state(session_id, project, name)
        if state is None:
            return json.dumps(
                {
                    "name": name,
                    "state": "PENDING",
                    "mandatory": GATE_CONFIG_MAP[name].mandatory,
                    "message": "Gate has not been run yet in this session",
                    "updated_at": "",
                }
            )

        return json.dumps(
            {
                "name": state["gate_name"],
                "state": state["state"],
                "mandatory": bool(state["mandatory"]),
                "message": state.get("message", ""),
                "updated_at": state.get("updated_at", ""),
            }
        )
    except Exception as exc:
        logger.exception("check_gate failed")
        return json.dumps(
            {
                "error": f"Failed to check gate: {exc}",
            }
        )


@app.tool()
def complete_gate(
    name: str,
    session_id: str,
    reason: str = "",
) -> str:
    """Manually mark a gate as PASS.

    Only transitions BLOCK→PASS or WARN→PASS.  No-op on PASS/SKIP.

    Args:
        name:       Gate name to complete.
        session_id: Active session identifier.
        reason:     Human-readable reason for the transition.

    Returns:
        JSON string with from_state, to_state, name.
    """
    if name not in GATE_CONFIG_MAP:
        return json.dumps(
            {
                "error": f"Gate '{name}' not found",
                "valid_gates": list(GATE_CONFIG_MAP.keys()),
            }
        )

    try:
        session = persistence.get_session(session_id)
        project = session["project"] if session else "unknown"

        current = persistence.get_gate_state(session_id, project, name)
        current_state = current["state"] if current else BLOCK
        now = datetime.now(timezone.utc).isoformat()

        if current_state not in (BLOCK, WARN):
            return json.dumps(
                {
                    "name": name,
                    "state": current_state,
                    "message": f"Gate '{name}' is already {current_state} — no change needed",
                    "updated_at": now,
                }
            )

        # Persist transition
        persistence.upsert_gate_state(
            session_id=session_id,
            project=project,
            gate_name=name,
            state=PASS,
            mandatory=GATE_CONFIG_MAP[name].mandatory,
            message=reason or "Manually completed",
        )
        persistence.log_transition(
            session_id=session_id,
            gate_name=name,
            from_state=current_state,
            to_state=PASS,
            reason=reason,
        )

        return json.dumps(
            {
                "name": name,
                "state": PASS,
                "message": f"Gate '{name}' transitioned {current_state} → PASS",
                "updated_at": now,
            }
        )

    except Exception as exc:
        logger.exception("complete_gate failed")
        return json.dumps(
            {
                "error": f"Failed to complete gate: {exc}",
            }
        )


# ── Dashboard server tool ──────────────────────────────────────────────────


def _dashboard_log_dir() -> str:
    """Return the log directory for dashboard subprocess logs.

    Uses the parent directory of db_path when it is a real directory
    (not "/" or empty). Falls back to ~/.hermes/logs otherwise.
    """
    parent = os.path.dirname(db_path)
    if parent and parent != "/":
        return os.path.join(parent, "logs")
    return os.path.expanduser("~/.hermes/logs")


def _read_stderr_tail(log_dir: str) -> str:
    """Read the last 2000 chars of dashboard_stderr.log, or empty string."""
    log_path = os.path.join(log_dir, "dashboard_stderr.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content[-2000:] if content else ""
    except OSError:
        return ""


@app.tool()
def server(action: str) -> str:
    """Control the Ultratimonel Dashboard web server.

    Manages a subprocess running the http.server (stdlib) dashboard GUI.
    The dashboard reads from the same SQLite DB as the gates.
    Subprocess stdout/stderr are appended to persistent log files.

    Args:
        action: One of "status", "start", "stop", "restart".

    Returns:
        JSON string with port, pid, url, and running status.
        On crash, returns a `hint` field pointing to the log file.
        On status after exit, returns `exit_code` and `stderr_tail`.
    """
    global _dashboard_proc, _dashboard_port

    action = action.strip().lower()
    script = _dashboard_script()

    def _status_dict(running: bool, pid: int | None = None) -> dict:
        return {
            "action": action,
            "running": running,
            "port": _dashboard_port,
            "pid": pid
            or (
                _dashboard_proc.pid
                if _dashboard_proc and _dashboard_proc.poll() is None
                else None
            ),
            "url": f"http://localhost:{_dashboard_port}",
            "script": script,
        }

    def _spawn_dashboard(port: int) -> tuple[subprocess.Popen | None, str | None]:
        """Spawn the dashboard subprocess with persistent log files.

        Returns (proc, error_hint) — proc is None on failure, error_hint
        points to the stderr log file for crash diagnosis.
        """
        global _dashboard_port
        # Usar puerto fijo — dashboard_server.py tiene SO_REUSEADDR
        _dashboard_port = DASHBOARD_PORT
        python = sys.executable

        log_dir = _dashboard_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        log_out_path = os.path.join(log_dir, "dashboard_stdout.log")
        log_err_path = os.path.join(log_dir, "dashboard_stderr.log")

        log_out = None
        log_err = None
        try:
            log_out = open(log_out_path, "a", encoding="utf-8")
            log_err = open(log_err_path, "a", encoding="utf-8")
            _dashboard_proc = subprocess.Popen(
                [python, script, str(port)],
                stdin=subprocess.DEVNULL,
                stdout=log_out,
                stderr=log_err,
                env={**os.environ, "ULTRATIMONEL_DB_PATH": db_path},
            )
        except FileNotFoundError:
            return None, f"Python not found: {python}"
        except Exception as exc:
            return None, f"Failed to start dashboard: {exc}"
        finally:
            # CRÍTICO 2: cerrar handles en TODOS los paths (éxito y error)
            if log_out is not None:
                try:
                    log_out.close()
                except OSError:
                    pass
            if log_err is not None:
                try:
                    log_err.close()
                except OSError:
                    pass

        # Brief wait to catch immediate crashes
        import time
        time.sleep(0.5)
        ret = _dashboard_proc.poll()
        if ret is not None:
            _dashboard_proc = None
            return None, f"Check logs: {log_err_path}"

        return _dashboard_proc, None

    # ── status ───────────────────────────────────────────────────────
    if action == "status":
        if _dashboard_proc is None:
            return json.dumps(_status_dict(False))
        ret = _dashboard_proc.poll()
        if ret is not None:
            # CRÍTICO 1: leer stderr_tail del archivo de log, no del PIPE
            # (que es None cuando se usa stderr=log_err file)
            log_dir = _dashboard_log_dir()
            stderr_tail = _read_stderr_tail(log_dir)
            _dashboard_proc = None
            return json.dumps({
                **_status_dict(False),
                "exit_code": ret,
                "stderr_tail": stderr_tail,
            })
        return json.dumps(_status_dict(True))

    # ── stop ─────────────────────────────────────────────────────────
    if action == "stop":
        if _dashboard_proc is None:
            return json.dumps(
                {**_status_dict(False), "message": "Dashboard not running"}
            )
        ret = _dashboard_proc.poll()
        if ret is not None:
            _dashboard_proc = None
            return json.dumps(
                {
                    **_status_dict(False),
                    "message": "Dashboard was already stopped",
                    "exit_code": ret,
                }
            )
        try:
            _dashboard_proc.send_signal(signal.SIGINT)
            _dashboard_proc.wait(timeout=5)
        except Exception:
            try:
                _dashboard_proc.kill()
                _dashboard_proc.wait(timeout=2)
            except Exception:
                pass
        _dashboard_proc = None
        return json.dumps({**_status_dict(False), "message": "Dashboard stopped"})

    # ── start ────────────────────────────────────────────────────────
    if action == "start":
        if _dashboard_proc is not None and _dashboard_proc.poll() is None:
            return json.dumps(
                {**_status_dict(True), "message": "Dashboard already running"}
            )

        if script is None:
            return json.dumps(
                {
                    "error": "dashboard_server.py not found",
                    "hint": "Expected at ultratimonel/dashboard_server.py",
                }
            )

        proc, hint = _spawn_dashboard(_dashboard_port)
        if proc is None:
            return json.dumps({
                "error": f"Dashboard exited immediately (code ?)",
                "hint": hint or "Unknown error",
            })

        return json.dumps(
            {
                **_status_dict(True),
                "message": f"Dashboard started on http://localhost:{_dashboard_port}",
            }
        )

    # ── restart ──────────────────────────────────────────────────────
    if action == "restart":
        # Stop first
        if _dashboard_proc is not None and _dashboard_proc.poll() is None:
            try:
                _dashboard_proc.send_signal(signal.SIGINT)
                _dashboard_proc.wait(timeout=5)
            except Exception:
                try:
                    _dashboard_proc.kill()
                    _dashboard_proc.wait(timeout=2)
                except Exception:
                    pass
            _dashboard_proc = None

        if script is None:
            return json.dumps(
                {
                    "error": "dashboard_server.py not found",
                    "hint": "Expected at ultratimonel/dashboard_server.py",
                }
            )

        proc, hint = _spawn_dashboard(_dashboard_port)
        if proc is None:
            return json.dumps({
                "error": "Restart failed",
                "hint": hint or "Unknown error",
            })

        return json.dumps(
            {
                **_status_dict(True),
                "message": f"Dashboard restarted on http://localhost:{_dashboard_port}",
            }
        )

    # ── unknown action ───────────────────────────────────────────────
    return json.dumps(
        {
            "error": f"Unknown action: '{action}'",
            "valid_actions": ["status", "start", "stop", "restart"],
        }
    )


# ── Project map management tools ──────────────────────────────────────────
# ⛟ Estas tools son la ÚNICA forma de gestionar proyectos.
# No edites context_extractor.py ni ningún otro .py para agregar proyectos.


@app.tool()
def map_list() -> str:
    """List all projects configured in project_maps.json.

    Returns:
        JSON array of project entries with patterns, deck_board_id, collective_id.
    """
    from .context_extractor import get_project_maps

    maps = get_project_maps()
    return json.dumps(maps, ensure_ascii=False, default=str)


@app.tool()
def map_add(
    project: str,
    patterns: list[str],
    deck_board_id: int = 0,
    collective_id: int = 0,
) -> str:
    """Add or update a project in project_maps.json.

    Args:
        project:     Project slug (e.g. "voy-rojo").
        patterns:    List of keywords to detect the project in user messages.
        deck_board_id: Nextcloud Deck board ID (0 or omit if none).
        collective_id: Nextcloud Collective ID (0 or omit if none).

    Returns:
        JSON with success status and path of the written file.
    """
    from .config_loader import load_project_maps, save_project_maps, resolve_maps_path
    from .context_extractor import reload_project_maps

    if not project.strip():
        return json.dumps({"error": "Project name is required"})
    if not patterns or not any(p.strip() for p in patterns):
        return json.dumps({"error": "At least one pattern is required"})

    maps_path = resolve_maps_path()
    maps = load_project_maps(maps_path)

    maps[project] = {
        "patterns": [p.strip().lower() for p in patterns if p.strip()],
        "deck_board_id": deck_board_id if deck_board_id > 0 else None,
        "collective_id": collective_id if collective_id > 0 else None,
    }

    save_project_maps(maps, maps_path)
    reload_project_maps(maps_path)

    return json.dumps(
        {
            "status": "ok",
            "project": project,
            "path": maps_path,
            "total_projects": len(maps),
        },
        ensure_ascii=False,
    )


@app.tool()
def map_remove(project: str) -> str:
    """Remove a project from project_maps.json.

    Args:
        project: Project slug to remove.

    Returns:
        JSON with success or error.
    """
    from .config_loader import load_project_maps, save_project_maps, resolve_maps_path
    from .context_extractor import reload_project_maps

    if not project.strip():
        return json.dumps({"error": "Project name is required"})

    maps_path = resolve_maps_path()
    maps = load_project_maps(maps_path)

    if project not in maps:
        return json.dumps(
            {
                "error": f"Project '{project}' not found",
                "known_projects": list(maps.keys()),
            }
        )

    del maps[project]
    save_project_maps(maps, maps_path)
    reload_project_maps(maps_path)

    return json.dumps(
        {
            "status": "ok",
            "removed": project,
            "path": maps_path,
            "total_projects": len(maps),
        },
        ensure_ascii=False,
    )


@app.tool()
def map_setup() -> str:
    """Discover available Deck boards and Collectives for mapping.

    Queries Nextcloud for active boards and collectives, then compares
    against current project_maps.json. Does NOT modify anything.

    Returns:
        JSON with known and unmapped boards/collectives.
    """
    from .context_extractor import get_project_maps
    from .mcp_client import call_mcp_tool, TOOL_NAMES

    maps = get_project_maps()
    mapped_deck_ids = {
        v.get("deck_board_id")
        for v in maps.values()
        if v.get("deck_board_id") is not None
    }
    mapped_collective_ids = {
        v.get("collective_id")
        for v in maps.values()
        if v.get("collective_id") is not None
    }

    result: dict[str, object] = {}

    # Discover Deck boards
    boards_data, boards_err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_get_boards"],
        {},
        timeout=8.0,
    )
    if boards_data:
        board_list = (
            boards_data
            if isinstance(boards_data, list)
            else boards_data.get("boards", boards_data.get("result", []))
        )
        known_boards = []
        new_boards = []
        for b in board_list:
            bid = b.get("id")
            title = b.get("title", "?")
            deleted = b.get("deletedAt", 0)
            entry = {"id": bid, "title": title, "deletedAt": deleted}
            if deleted == 0:
                if bid in mapped_deck_ids:
                    known_boards.append(entry)
                else:
                    new_boards.append(entry)
        result["deck_boards"] = {
            "known": known_boards,
            "unmapped": new_boards,
        }
    else:
        result["deck_boards"] = {"error": boards_err or "unavailable"}

    # Discover Collectives
    # Use the get_collectives MCP tool if available
    coll_data, coll_err = call_mcp_tool(
        "nextcloud",
        "collectives_get_collectives",
        {},
        timeout=8.0,
    )
    if coll_data:
        coll_list = (
            coll_data
            if isinstance(coll_data, list)
            else coll_data.get("collectives", coll_data.get("result", []))
        )
        known_colls = []
        new_colls = []
        for c in coll_list:
            cid = c.get("id")
            title = c.get("title", "?")
            entry = {"id": cid, "title": title}
            if cid in mapped_collective_ids:
                known_colls.append(entry)
            else:
                new_colls.append(entry)
        result["collectives"] = {
            "known": known_colls,
            "unmapped": new_colls,
        }
    else:
        result["collectives"] = {"error": coll_err or "unavailable"}

    result["current_maps"] = {
        project: {
            "patterns": cfg.get("patterns", []),
            "deck_board_id": cfg.get("deck_board_id"),
            "collective_id": cfg.get("collective_id"),
        }
        for project, cfg in maps.items()
    }
    result["total_mapped"] = len(maps)

    return json.dumps(result, ensure_ascii=False, default=str)


@app.tool()
def map_sync() -> str:
    """Verify mapped Deck boards still exist and flag stale entries.

    Checks each project's deck_board_id against live Deck boards.
    Reports stale/deleted boards but does NOT modify anything.

    Returns:
        JSON with verification results.
    """
    from .context_extractor import get_project_maps
    from .mcp_client import call_mcp_tool, TOOL_NAMES

    maps = get_project_maps()
    if not maps:
        return json.dumps(
            {"status": "ok", "message": "No projects mapped", "stale": []}
        )

    boards_data, boards_err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_get_boards"],
        {},
        timeout=8.0,
    )

    if boards_data is None:
        return json.dumps({"error": f"Cannot reach Nextcloud Deck: {boards_err}"})

    board_list = (
        boards_data
        if isinstance(boards_data, list)
        else boards_data.get("boards", boards_data.get("result", []))
    )
    live_board_ids = {b.get("id") for b in board_list}

    stale = []
    healthy = []
    for project, cfg in maps.items():
        bid = cfg.get("deck_board_id")
        if bid is None:
            continue
        if bid in live_board_ids:
            healthy.append({"project": project, "deck_board_id": bid})
        else:
            stale.append({"project": project, "deck_board_id": bid})

    return json.dumps(
        {
            "status": "ok",
            "total_projects": len(maps),
            "healthy": healthy,
            "stale": stale,
            "total_stale": len(stale),
        },
        ensure_ascii=False,
        default=str,
    )


# ── Sync tools: Deck → missions ────────────────────────────────────────────


@app.tool()
def sync_tasks(project: str) -> str:
    """Sync Deck cards from Nextcloud → missions table for a project.

    Fetches all stacks/cards from the project's mapped Deck board,
    extracts checklists, and upserts into the missions + checklist_items tables.

    Args:
        project: Project slug (e.g. "voy-rojo").

    Returns:
        JSON with sync results (missions created/updated, errors).
    """
    from .context_extractor import get_project_maps
    from .mcp_client import call_mcp_tool, TOOL_NAMES

    maps = get_project_maps()
    cfg = maps.get(project)
    if not cfg:
        return json.dumps({"error": f"Project '{project}' not found in project_maps"})
    board_id = cfg.get("deck_board_id")
    if not board_id:
        return json.dumps({"error": f"Project '{project}' has no deck_board_id mapped"})

    # Get stacks with cards from Deck
    stacks_data, err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_get_stacks"],
        {"board_id": board_id, "include_cards": True},
        timeout=15.0,
    )
    if stacks_data is None:
        return json.dumps({"error": f"Cannot reach Deck: {err}"})

    stacks = (
        stacks_data
        if isinstance(stacks_data, list)
        else stacks_data.get("stacks", stacks_data.get("result", []))
    )

    created = 0
    updated_count = 0
    errors = []

    for stack in stacks:
        stack_name = stack.get("title", "?")
        cards = stack.get("cards", [])
        if not cards:
            continue

        for card in cards:
            try:
                card_id = card.get("id")
                if not card_id:
                    continue
                title = card.get("title", "Sin título")
                description = card.get("description", "")

                # Get card detail for checklist info
                card_detail, detail_err = call_mcp_tool(
                    "nextcloud",
                    TOOL_NAMES["nextcloud"]["deck_get_card"],
                    {
                        "board_id": board_id,
                        "stack_id": stack.get("id"),
                        "card_id": card_id,
                    },
                    timeout=8.0,
                )

                # Infer checklist_total from description parsing
                # Deck stores checklist as "n/N" or markdown checkboxes - we count items
                checklist_total = 0
                checklist_done = 0
                checklist_items_data = []

                if card_detail and isinstance(card_detail, dict):
                    # Look for checklist in extended data
                    items_data = card_detail.get("checklistItems", [])
                    if items_data and isinstance(items_data, list):
                        checklist_total = len(items_data)
                        checklist_done = sum(
                            1
                            for it in items_data
                            if it.get("status") == "done" or it.get("checked")
                        )
                        for idx, item in enumerate(items_data):
                            checklist_items_data.append(
                                {
                                    "index": idx,
                                    "text": item.get(
                                        "description",
                                        item.get("text", f"Item {idx + 1}"),
                                    ),
                                    "done": 1
                                    if item.get("status") == "done"
                                    or item.get("checked")
                                    else 0,
                                }
                            )

                # Fallback: if stacks didn't provide description, use card_detail's full description
                # so the markdown checkbox parser below can still extract checklists.
                if not description and isinstance(card_detail, dict):
                    description = card_detail.get("description", "") or ""

                # No checklist items from Deck API? Parse description for markdown checkboxes
                if checklist_total == 0 and description:
                    lines = description.strip().split("\n")
                    for line in lines:
                        line = line.strip()
                        # Match - [ ] or - [x] style checkboxes
                        if line.startswith("- [") or line.startswith("* ["):
                            done = 1 if ("[x]" in line or "[X]" in line) else 0
                            text = (
                                line.split("]", 1)[1].strip() if "]" in line else line
                            )
                            checklist_items_data.append(
                                {
                                    "index": checklist_total,
                                    "text": text,
                                    "done": done,
                                }
                            )
                            checklist_total += 1
                            if done:
                                checklist_done += 1

                # Map stack title → mission status
                status_map = {
                    "backlog": "pendiente",
                    "pendiente": "pendiente",
                    "to do": "pendiente",
                    "en progreso": "en_progreso",
                    "in progress": "en_progreso",
                    "doing": "en_progreso",
                    "done": "completada",
                    "hecho": "completada",
                    "completada": "completada",
                    "completado": "completada",
                }
                status = status_map.get(stack_name.lower().strip(), "pendiente")

                # Upsert mission
                mission_id = persistence.upsert_mission(
                    deck_task_id=card_id,
                    project=project,
                    title=title,
                    description=description,
                    status=status,
                    checklist_total=checklist_total,
                    checklist_done=checklist_done,
                )
                if mission_id == 0:
                    errors.append(f"Card {card_id}: upsert returned 0")
                    continue

                # Upsert checklist items
                for item_data in checklist_items_data:
                    persistence.upsert_checklist_item(
                        mission_id=mission_id,
                        item_index=item_data["index"],
                        text=item_data["text"],
                        done=item_data["done"],
                    )

                created += 1

            except Exception as exc:
                errors.append(f"Card {card.get('id', '?')}: {exc}")
                logger.exception("sync_tasks card error")

    return json.dumps(
        {
            "project": project,
            "board_id": board_id,
            "synced": created,
            "errors": errors,
            "total_errors": len(errors),
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def sync_all() -> str:
    """Sync Deck cards → missions for ALL mapped projects.

    Iterates all projects with deck_board_id and runs sync_tasks on each.

    Returns:
        JSON with per-project sync results.
    """
    from .context_extractor import get_project_maps

    maps = get_project_maps()
    results = {}
    total_synced = 0
    total_errors = 0

    for project, cfg in maps.items():
        bid = cfg.get("deck_board_id")
        if not bid:
            continue
        try:
            result = json.loads(sync_tasks(project))
            results[project] = {
                "status": "ok" if not result.get("errors") else "warn",
                "synced": result.get("synced", 0),
                "errors": result.get("errors", []),
            }
            total_synced += result.get("synced", 0)
            total_errors += len(result.get("errors", []))
        except Exception as exc:
            results[project] = {"status": "error", "error": str(exc)}
            total_errors += 1

    return json.dumps(
        {
            "status": "ok",
            "projects_synced": len(results),
            "total_synced": total_synced,
            "total_errors": total_errors,
            "details": results,
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def mission_list(project: str, include_description: bool = True) -> str:
    """List missions (Deck tasks) for a project.

    Args:
        project: Project slug.
        include_description: If True (default), returns full payload
            including description and nested checklist_items (backward compatible).
            When False, returns lightweight {id, title, status} per mission.

    Returns:
        JSON with missions list.
    """
    missions = persistence.list_missions(project)

    if not include_description:
        light_missions = [
            {"id": m["id"], "title": m["title"], "status": m["status"]}
            for m in missions
        ]
        payload = {
            "project": project,
            "missions": light_missions,
            "total": len(light_missions),
        }
    else:
        payload = {
            "project": project,
            "missions": missions,
            "total": len(missions),
        }

    return json.dumps(payload, ensure_ascii=False, default=str)


@app.tool()
def mission_get(mission_id: int) -> str:
    """Retrieve a single mission by ID with minimal fields."""
    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Mission {mission_id} not found"})
    item_ids = [ci["id"] for ci in persistence.list_checklist_items(mission["id"])]
    return json.dumps(
        {"id": mission["id"], "title": mission["title"], "checklist_item_ids": item_ids},
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def checklist_item_get(checklist_item_id: int) -> str:
    """Retrieve a single checklist item by ID."""
    item = persistence.get_checklist_item_by_id(checklist_item_id)
    if not item:
        return json.dumps({"error": f"Checklist item {checklist_item_id} not found"})
    return json.dumps(item, ensure_ascii=False, default=str)


@app.tool()
def begin_turn(
    session_id: str,
    project: str,
    mission_id: int = 0,
    checklist_item_id: int = 0,
    message: str = "",
    sender: str = "user",
) -> str:
    """Begin a new turn: execute gates fresh and create an intento.

    This is the first call of the consolidated 2-call turn workflow:
      begin_turn → trabajo → end_turn

    begin_turn EJECUTA INTERNAMENTE los 4 gates (1a/1b/1c/1e) de forma fresca,
    persistiendo los resultados en gate_state y capturándolos en el intento.
    Esto elimina la necesidad de llamar assert_gates manualmente antes del turno.

    If an orphaned turn exists (active in memory but not matching this request),
    it is auto-completed as "fail" so the new turn can proceed — this prevents
    IRRECOVERABLE state where a crashed/blocked previous turn blocks all future turns.

    Args:
        session_id:         Active Hermes session identifier.
        project:            Project slug (e.g. "voy-rojo").
        mission_id:         Numeric mission ID (same as record_intento).
        checklist_item_id:  Numeric checklist item ID (same as record_intento).
        message:            The user's raw message / query (used for context extraction).
        sender:             Optional sender name (default: "user").

    Returns:
        JSON string with intento_id, status, and real fresh gate counts.
    """
    # 1. Check for orphaned/active turn — auto-cleanup if needed
    active = _get_active_intento()
    if active is not None:
        if active["intento_id"] != _resolve_requesting_intento(session_id, project):
            # Orphaned turn: complete it as fail so we can proceed
            logger.warning(
                "Orphaned turno detected (intento #%d). Auto-completing as fail.",
                active["intento_id"],
            )
            try:
                persistence.complete_intento(
                    intento_id=active["intento_id"],
                    status="fail",
                    gates_passed=0,
                )
            except Exception as exc:
                logger.error("Failed to auto-complete orphaned intento #%d: %s", active["intento_id"], exc)
            _clear_active_intento()

    # 2. Ejecutar los 4 gates de forma fresca
    context = extract_context(message, session_id, sender=sender)

    # El project explícito manda sobre el extraído del topic. Se resuelve
    # ANTES de ejecutar los gates para que 1c/1e corran contra el project
    # correcto (no contra "unknown" cuando el message no lo menciona).
    resolved_project = project if project else context["project"]
    context["project"] = resolved_project

    try:
        persistence.upsert_session(
            session_id=session_id,
            sender=context["sender"],
            topic=context["topic"],
            project=context["project"],
        )
    except Exception as exc:
        logger.warning("Session persistence failed (degraded): %s", exc)

    try:
        gate_results = run_triple_match(context)
    except Exception as exc:
        logger.warning("Gate execution failed (degraded): %s", exc)
        gate_results = []

    # 3. Agregar info de mandatory a cada resultado
    for r in gate_results:
        cfg = GATE_CONFIG_MAP.get(r.name)
        if cfg:
            r.mandatory = cfg.mandatory

    overall, gate_dicts = aggregate(gate_results)
    context_envelope = build_context_envelope(gate_results)

    # 4. Persistir cada gate state fresco
    try:
        for r in gate_results:
            persistence.upsert_gate_state(
                session_id=session_id,
                project=resolved_project,
                gate_name=r.name,
                state=r.state,
                mandatory=r.mandatory,
                duration_ms=int(r.duration_ms),
                message=r.message,
                result_data=r.result_data,
            )

        # Solo persistir misión si es un proyecto conocido
        if is_known_project(resolved_project):
            gates_passed = sum(1 for r in gate_results if r.state in (PASS, SKIP))
            persistence.upsert_action(
                session_id=session_id,
                project=resolved_project,
                gates_passed=gates_passed,
                gates_total=len(DEFAULT_GATES),
            )
        else:
            logger.info(
                "Skipping mission persistence: project '%s' is not a known project",
                resolved_project,
            )
    except Exception as exc:
        logger.warning("Gate state persistence failed (degraded): %s", exc)

    # 5. Crear intento con los gates frescos
    intento_id = persistence.create_intento(
        session_id=session_id,
        project=resolved_project,
        mission_id=mission_id,
        checklist_item_id=checklist_item_id,
    )

    # 6. Persistir snapshot de gates en el intento
    if gate_results:
        try:
            persistence.capture_gates_for_intento(intento_id, gate_dicts)
        except Exception as exc:
            logger.warning("Failed to capture gates for intento #%d: %s", intento_id, exc)

    # 7. Registrar como turno activo
    _set_active_intento(intento_id, session_id, resolved_project)

    gates_passed = sum(1 for r in gate_results if r.state in (PASS, SKIP))
    return json.dumps(
        {
            "status": "started",
            "intento_id": intento_id,
            "gates_captured": len(gate_results),
            "gates_passed_so_far": gates_passed,
            "overall": overall,
            "context": {
                "sender": context["sender"],
                "topic": context["topic"],
                "project": resolved_project,
            },
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def end_turn(
    intento_id: int,
    status: str = "success",
) -> str:
    """End the current turn: validate gates and complete the intento.

    This is the second (and final) call of the consolidated 2-call turn workflow:
      begin_turn → trabajo → end_turn

    The classical signature accepts only the intento_id — all definitional
    data (session_id, project) is resolved internally from the DB so the
    orchestrating agent never has to pass it.

    end_turn NEVER blocks permanently. When gates do not pass, it completes
    the intento with final_status="fail" and real gate detail, then clears
    the active turn state — always leaving the system in a recoverable state.

    Args:
        intento_id: Numeric intento ID returned by begin_turn().
        status:     Final status hint ('success' or 'fail'). Used for logging;
                    actual completion status derives from gate validation.

    Returns:
        JSON string with completion status, gates_passed count, and gate detail.
    """
    global _active_intento

    # 1. Resolve session_id + project from the DB (no delegation to orchestrator)
    intento = persistence.get_intento(intento_id)
    if intento is None:
        return json.dumps(
            {
                "status": "error",
                "error": f"Intento #{intento_id} not found in database.",
            },
            ensure_ascii=False,
            default=str,
        )

    session_id = intento["session_id"]
    project = intento["project"]

    # 2. Turn-scoping: validate against active turn OR allow recovery of running intentos
    active = _get_active_intento()
    if active is not None and active["intento_id"] != intento_id:
        # Not the exact active turno — check if it's a running intento we can recover
        if intento.get("status") == "running":
            logger.warning(
                "Turn-scoping mismatch (active=#%d, requested=#%d). "
                "Auto-recovering running intento #%d.",
                active["intento_id"],
                intento_id,
                intento_id,
            )
            # Complete the orphaned running intento so we can proceed
            try:
                persistence.complete_intento(
                    intento_id=active["intento_id"],
                    status="fail",
                    gates_passed=0,
                )
            except Exception as exc:
                logger.error("Failed to auto-complete active intento #%d during recovery: %s", active["intento_id"], exc)
            _clear_active_intento()
        else:
            return json.dumps(
                {
                    "status": "error",
                    "error": (
                        f"Turn-scoping mismatch: turno activo es intento #{active['intento_id']} "
                        f"pero se solicitó cerrar intento #{intento_id}."
                    ),
                },
                ensure_ascii=False,
                default=str,
            )

    # 3. Capturar estado final de gates (always attempt, never block)
    try:
        final_gates = persistence.list_gate_states(session_id, project)
    except Exception as exc:
        logger.warning("Failed to capture final gate states: %s", exc)
        final_gates = []

    # 4. Validate gates for logging (does NOT block completion)
    try:
        allowed, failed_details = _validate_gates_for_completion(session_id, project)
    except Exception as exc:
        logger.warning("Gate validation failed (degraded): %s", exc)
        allowed, failed_details = True, []
    if not allowed:
        detail = "\n".join(f"  🔴 {f}" for f in failed_details)
        logger.warning(
            "end_turn #%d: %d mandatory gate(s) did not pass. Completing as fail.\n%s",
            intento_id,
            len(failed_details),
            detail,
        )

    # 5. Contar gates passed
    gates_passed = sum(1 for g in final_gates if g.get("state") in ("PASS", "SKIP"))
    final_status = "success" if gates_passed >= 4 else "fail"

    # 6. Completar intento con detalle completo (NEVER blocks — always completes)
    try:
        persistence.complete_intento_with_gates(
            intento_id=intento_id,
            status=final_status,
            gates_passed=gates_passed,
            gates_detail=final_gates,
        )
    except Exception as exc:
        logger.error("Failed to complete intento #%d: %s", intento_id, exc)
        return json.dumps(
            {
                "status": "error",
                "error": f"Failed to persist intento completion: {exc}",
                "intento_id": intento_id,
            },
            ensure_ascii=False,
            default=str,
        )

    # 7. Limpiar estado de turno activo
    _clear_active_intento()

    return json.dumps(
        {
            "status": "ok",
            "intento_id": intento_id,
            "final_status": final_status,
            "gates_passed": gates_passed,
            "gates_total": len(final_gates) if final_gates else 4,
            "gates": final_gates,
        },
        ensure_ascii=False,
        default=str,
    )


#
# ── Legacy / archived tools ─────────────────────────────────────────────
# Deprecated in favor of the consolidated 2-call flow
# (begin_turn → trabajo → end_turn). Kept for compatibility only.
#


@app.tool()
def assert_gates(
    message: str,
    session_id: str,
    sender: str = "user",
) -> str:
    """~~DEPRECATED~~ Run all pre-flight gates and return structured results.

    DEPRECATED — use begin_turn() instead (consolidated 2-call flow:
    begin_turn → trabajo → end_turn). begin_turn executes the 4 gates
    internally (fresh assert) and persists the snapshot in the intento;
    it is the replacement for this tool.

    Do NOT use assert_gates as an agent step: the plugin bouncer treats it
    as if it were the gate step, when begin_turn already runs them.

    Kept for compatibility — the plugin still invokes it in pre_llm_call.

    Executes:
      1. Context extraction (sender, topic, project)
      2. Triple-match (1a AgentMemory → 1b Checkpoint → 1e Deck)
      3. Aggregation (determine overall PASS/BLOCK/WARN)
      4. Persistence (store gate state, update mission)

    Args:
        message:    The user's raw message / query.
        session_id: Active Hermes session identifier.
        sender:     Optional sender name (default: "user").

    Returns:
        JSON string with:
          - gates:    list of per-gate results
          - overall:  PASS | BLOCK | WARN
          - context:  extracted sender, topic, project
          - context_envelope: aggregated memory, checkpoint, deck data
          - timestamp
    """
    # 1. Extract context
    context = extract_context(message, session_id, sender=sender)

    try:
        persistence.upsert_session(
            session_id=session_id,
            sender=context["sender"],
            topic=context["topic"],
            project=context["project"],
        )
    except Exception as exc:
        logger.warning("Session persistence failed (degraded): %s", exc)

    # 2. Run triple match
    gate_results = run_triple_match(context)

    # 3. Aggregate
    overall, gate_dicts = aggregate(gate_results)
    context_envelope = build_context_envelope(gate_results)

    # 4. Persist results
    # ⛔ Solo persistimos misión si el proyecto es conocido.
    # Si project == "unknown" (fallback sin match), skip para evitar
    # contaminar la DB con proyectos fantasma.
    project = context["project"]
    gates_passed = sum(1 for r in gate_results if r.state in (PASS, SKIP))
    try:
        for r in gate_results:
            persistence.upsert_gate_state(
                session_id=session_id,
                project=project,
                gate_name=r.name,
                state=r.state,
                mandatory=r.mandatory,
                duration_ms=int(r.duration_ms),
                message=r.message,
                result_data=r.result_data,
            )

        # Solo persistir acción si es un proyecto conocido
        if is_known_project(project):
            persistence.upsert_action(
                session_id=session_id,
                project=project,
                gates_passed=gates_passed,
                gates_total=len(DEFAULT_GATES),
            )
        else:
            logger.info(
                "Skipping mission persistence: project '%s' is not a known project",
                project,
            )
    except Exception as exc:
        logger.warning("Gate state persistence failed (degraded): %s", exc)

    # 5. Build response
    response = {
        "gates": gate_dicts,
        "status": overall,
        "context": {
            "sender": context["sender"],
            "topic": context["topic"],
            "project": context["project"],
        },
        "context_envelope": context_envelope,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return json.dumps(response, ensure_ascii=False, default=str)


@app.tool()
def record_intento(
    session_id: str,
    project: str,
    mission_id: int,
    checklist_item_id: int,
) -> str:
    """Create an intento (assert_gates cycle) for a specific checklist item.

    DEPRECATED — use begin_turn() instead (consolidated 2-call flow:
    begin_turn → trabajo → end_turn). Mantenida por compatibilidad.

    Args:
        session_id: Active Hermes session identifier.
        project:    Project slug (e.g. "voy-rojo").
        mission_id: Numeric mission ID from the missions table.
        checklist_item_id: Numeric checklist item ID.

    Returns:
        JSON string with the new intento id.
    """
    intento_id = persistence.create_intento(
        session_id=session_id,
        project=project,
        mission_id=mission_id,
        checklist_item_id=checklist_item_id,
    )
    return json.dumps(
        {
            "status": "ok",
            "intento_id": intento_id,
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def card_update_description(
    card_id: int,
    description: str,
    board_id: int,
    stack_id: int,
) -> str:
    """Update only the description of a Deck card — NEVER changes the title.

    Args:
        card_id: Numeric card ID.
        description: New description content (markdown).
        board_id: Numeric board ID.
        stack_id: Numeric stack ID.

    Returns:
        JSON string confirming update.
    """
    from .mcp_client import call_mcp_tool, TOOL_NAMES

    # Fetch current card detail to preserve the title
    card, err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_get_card"],
        {"board_id": board_id, "card_id": card_id, "stack_id": stack_id},
        timeout=8.0,
    )
    if card is None:
        return json.dumps({"error": f"Cannot fetch card {card_id}: {err}"})

    # Extract current title — never overwrite it
    if isinstance(card, dict):
        card_data = card
    elif isinstance(card, list) and len(card) > 0:
        card_data = card[0]
    else:
        return json.dumps(
            {"error": "Unexpected response shape from Deck", "raw": str(card)[:200]}
        )

    if (
        isinstance(card_data, dict)
        and "content" in card_data
        and isinstance(card_data["content"], list)
    ):
        for item in card_data["content"]:
            if item.get("type") == "text" and item.get("text"):
                try:
                    parsed = json.loads(item["text"])
                    card_data = parsed
                    break
                except (json.JSONDecodeError, TypeError):
                    pass

    current_title = card_data.get("title", "")
    if not current_title:
        return json.dumps({"error": "Could not determine current card title"})

    # Update only description — title explicitly preserved
    result, update_err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_update_card"],
        {
            "board_id": board_id,
            "card_id": card_id,
            "stack_id": stack_id,
            "title": current_title,
            "description": description,
        },
        timeout=8.0,
    )
    if result is None:
        return json.dumps({"error": f"Failed to update card: {update_err}"})

    return json.dumps(
        {
            "status": "ok",
            "card_id": card_id,
            "title_preserved": current_title,
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def delete_intento(intento_id: int) -> str:
    """Delete an intento by its id.

    Args:
        intento_id: Numeric intento ID to delete.

    Returns:
        JSON string confirming deletion.
    """
    deleted = persistence.delete_intento(intento_id)
    return json.dumps(
        {
            "status": "deleted" if deleted else "not_found",
            "intento_id": intento_id,
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def complete_intento(
    intento_id: int,
    status: str = "running",
    gates_passed: int = 0,
    session_id: str = "",
    project: str = "",
) -> str:
    """Update an intento with gate results after assert_gates completes.

    DEPRECATED — use end_turn() instead (consolidated 2-call flow:
    begin_turn → trabajo → end_turn). Mantenida por compatibilidad.

    Args:
        intento_id:      Numeric intento ID to update.
        status:          Final status (running, success, fail, etc.).
        gates_passed:    Number of gates that passed.
        session_id:      Optional session ID for gate validation.
        project:         Optional project slug for gate validation.

    Returns:
        JSON string confirming completion, or blocked if gates fail.

    Note:
        endTurn bouncer (Nikhil pattern): when session_id + project are
        provided, validates that ALL mandatory gates are PASS/SKIP in the
        database before allowing completion. Rejects if any gate is BLOCK/WARN.
    """
    # ── endTurn bouncer: validate mandatory gates against DB ────────────
    if session_id and project:
        allowed, failed_details = _validate_gates_for_completion(session_id, project)
        if not allowed:
            detail = "\n".join(f"  🔴 {f}" for f in failed_details)
            return json.dumps(
                {
                    "status": "blocked",
                    "error": (
                        f"endTurn Bouncer: {len(failed_details)} mandatory gate(s) did not pass.\n{detail}\n\n"
                        "Fix blocking gates and retry."
                    ),
                    "intento_id": intento_id,
                },
                ensure_ascii=False,
                default=str,
            )

    persistence.complete_intento(
        intento_id=intento_id,
        status=status,
        gates_passed=gates_passed,
    )
    return json.dumps(
        {
            "status": "ok",
            "intento_id": intento_id,
            "gates_passed": gates_passed,
        },
        ensure_ascii=False,
        default=str,
    )

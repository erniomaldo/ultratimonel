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
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams, ListToolsRequest

from . import compact
from . import deck_bridge
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


class SingleChannelResultMiddleware(Middleware):
    """Serve every tool result through exactly one channel: ``content[0].text``.

    Why (card #218, quest 12): every tool here returns a JSON string, but
    FastMCP 3.4.2 `Tool.convert_result` (`fastmcp/tools/base.py:285-340`)
    serializes that same string twice — once as `content` and, because a
    ``-> str`` return annotation is a non-object schema, again as
    ``structuredContent={"result": <the same JSON, escaped>}`` plus
    ``_meta.fastmcp.wrap_result``. The payload crosses the wire three times.

    The JSON text channel is the single one because that is the only channel
    the clients we ship read (`ultratimonel_client.py`,
    `plugin_preflight.py`, `tests/test_integration.py` all do
    ``json.loads(content[0]["text"])``). Dropping the text payload would
    silently break the pre-flight gate plugin; dropping the structured copy
    costs nothing because nothing we ship reads it.

    This is a server-level concern, resolved once: the middleware applies to
    all tools, present and future. `on_list_tools` removes the generated
    `outputSchema` so the advertised contract matches the single-channel
    response (MCP expects `structuredContent` when a tool declares one).
    `on_call_tool` keeps the text content verbatim and drops the duplicated
    `structuredContent` and the `wrap_result` marker.
    """

    async def on_list_tools(
        self,
        context: MiddlewareContext[ListToolsRequest],
        call_next: CallNext[ListToolsRequest, list],
    ) -> list:
        tools = await call_next(context)
        return [tool.model_copy(update={"output_schema": None}) for tool in tools]

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        # Keep text content and isError; drop the duplicated structured copy
        # and the wrap marker. Any other meta is preserved untouched.
        meta = dict(result.meta) if result.meta else None
        if meta:
            fastmcp_meta = dict(meta.get("fastmcp") or {})
            fastmcp_meta.pop("wrap_result", None)
            if fastmcp_meta:
                meta["fastmcp"] = fastmcp_meta
            else:
                meta.pop("fastmcp", None)
            meta = meta or None
        return ToolResult(
            content=result.content,
            is_error=result.is_error,
            meta=meta,
        )


app.add_middleware(SingleChannelResultMiddleware())

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


def _gates_from_intento_snapshot(intento: dict | None) -> list[dict]:
    """Return the intento's FRESH gate snapshot, or ``[]`` (fail closed).

    ``begin_turn`` captures the freshly executed gates into the intento's
    ``gates_detail`` (``capture_gates_for_intento``). The session-scoped
    ``list_gate_states`` is latest-per-gate and can be STALE when ``begin_turn``
    degraded before writing fresh state, so it must never decide the final
    verdict (W-f/W-g). A missing, empty, or unparseable snapshot yields ``[]``
    so ``end_turn`` fails closed.
    """
    if not isinstance(intento, dict):
        return []
    raw = intento.get("gates_detail")
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    return [g for g in raw if isinstance(g, dict)]


def _pending_quest_count(mission_id: int) -> int:
    """Count the mission's open quests, degrading to 0 when unreadable.

    ``begin_turn`` reports the pending count as part of its turn delta. A
    degraded replica must never abort the turn, so an unreadable checklist
    yields 0 pending instead of raising.
    """
    if not mission_id:
        return 0
    try:
        items = persistence.list_checklist_items(mission_id)
        return sum(1 for item in items if isinstance(item, dict) and not item.get("done"))
    except Exception as exc:
        logger.warning(
            "Pending quest count unavailable for mission #%s: %s", mission_id, exc
        )
        return 0


def _turn_full_state(intento: dict) -> dict:
    """Full mission snapshot for the ``full`` escape hatch (quest 11).

    Default responses carry only the turn delta. A caller that needs the whole
    mission state asks for it explicitly (``full=True``) instead of paying
    for it on every turn. This is the compatibility path: nothing is removed
    from reach, it is only no longer the default.
    """
    mission_id = intento.get("mission_id") or 0
    state = {
        "session_id": intento.get("session_id"),
        "project": intento.get("project"),
        "mission": None,
        "checklist": [],
    }
    if not mission_id:
        return state
    try:
        mission = persistence.get_mission(mission_id)
    except Exception as exc:
        logger.warning("Full-state mission lookup failed for #%s: %s", mission_id, exc)
        return state
    if not isinstance(mission, dict):
        return state
    state["mission"] = {
        "id": mission.get("id"),
        "title": mission.get("title", ""),
        "status": mission.get("status", ""),
        "description": mission.get("description", ""),
        "checklist_total": mission.get("checklist_total", 0),
        "checklist_done": mission.get("checklist_done", 0),
        "deck_stack_id": mission.get("deck_stack_id"),
    }
    try:
        items = persistence.list_checklist_items(mission_id)
        state["checklist"] = [
            compact.compact_quest(item) for item in items if isinstance(item, dict)
        ]
    except Exception as exc:
        logger.warning("Full-state checklist lookup failed for #%s: %s", mission_id, exc)
    return state


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
def map_list(full: bool = False) -> str:
    """List all projects configured in project_maps.json.

    Compact by default (card #218, quest 10): each project maps to
    ``{deck_board_id, collective_id}`` only. The detection ``patterns`` — the
    bulk of the payload — are omitted because they are only needed for
    configuration, not for resolving a project's board. Pass ``full=True`` to
    get the complete configured entry.

    Args:
        full: If True, returns the full payload including ``patterns``.
            Defaults to False (compact).

    Returns:
        JSON object keyed by project slug. Compact values keep
        ``deck_board_id`` so callers can still resolve a project's board
        without opting into the full payload.
    """
    from .context_extractor import get_project_maps

    maps = get_project_maps()
    if full:
        return json.dumps(maps, ensure_ascii=False, default=str)

    compact_maps = {
        project: {
            "deck_board_id": cfg.get("deck_board_id"),
            "collective_id": cfg.get("collective_id"),
        }
        for project, cfg in maps.items()
    }
    return json.dumps(compact_maps, ensure_ascii=False, default=str)


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
def sync_tasks(project: str, prune: bool = False) -> str:
    """Sync Deck cards from Nextcloud → missions table and report drift.

    Fetches all stacks/cards from the project's mapped Deck board, extracts
    quests (markdown checkbox lines in the card description; ``done`` = ``[x]``),
    and upserts into the missions + checklist_items tables.

    Always reports drift: missions in the replica whose card is missing from a
    complete Deck read (``missing_in_deck``) and cards that were in Deck but not
    refreshed (``skipped``, each with its cause). ``prune=True`` additionally
    deletes the proven orphans. Pruning never happens over a failed, partial,
    or unresolvable Deck read: a false orphan destroys real work.

    Args:
        project: Project slug (e.g. "voy-rojo").
        prune: Delete replica missions proven absent from a complete Deck read.
            Defaults to False (report drift only, delete nothing).

    Returns:
        JSON with ``synced``, ``pruned``, ``missing_in_deck``, ``skipped`` and
        ``errors`` (plus counters and ``read_complete``).
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
        # Failed read: nothing is synced, nothing is pruned, and the failure is
        # reported in the same shape as a successful run.
        return json.dumps(
            {
                "project": project,
                "board_id": board_id,
                "synced": 0,
                "pruned": [],
                "missing_in_deck": [],
                "skipped": [],
                "errors": [f"Cannot reach Deck: {err}"],
                "total_errors": 1,
                "total_pruned": 0,
                "total_missing_in_deck": 0,
                "total_skipped": 0,
                "prune_requested": prune,
                "read_complete": False,
            },
            ensure_ascii=False,
            default=str,
        )

    # A successful read is not the same as a COMPLETE read. Pruning deletes
    # real work when a card is merely invisible because the read was partial,
    # so every shape problem below marks the read incomplete and forbids
    # pruning (requirement 4: a false orphan is worse than an extra card).
    read_complete = True
    read_issues: list[str] = []

    if isinstance(stacks_data, list):
        stacks = stacks_data
    elif isinstance(stacks_data, dict):
        if isinstance(stacks_data.get("stacks"), list):
            stacks = stacks_data["stacks"]
        elif isinstance(stacks_data.get("result"), list):
            stacks = stacks_data["result"]
        else:
            read_complete = False
            read_issues.append("Deck response has no 'stacks'/'result' list")
            stacks = []
    else:
        read_complete = False
        read_issues.append(
            f"Deck response has unexpected shape: {type(stacks_data).__name__}"
        )
        stacks = []

    created = 0
    updated_count = 0
    errors = []
    skipped: list[dict] = []
    seen_card_ids: set[int] = set()

    for stack in stacks:
        if not isinstance(stack, dict) or stack.get("id") is None:
            read_complete = False
            read_issues.append("Stack without id in Deck read")
            continue
        stack_name = stack.get("title", "?")
        cards = stack.get("cards") or []
        if not isinstance(cards, list):
            read_complete = False
            read_issues.append(f"Stack {stack.get('id')}: 'cards' is not a list")
            continue
        if not cards:
            continue

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
        status = status_map.get(str(stack_name).lower().strip())

        for card in cards:
            try:
                if not isinstance(card, dict) or not card.get("id"):
                    read_complete = False
                    read_issues.append("Card without id in Deck read")
                    skipped.append(
                        {
                            "deck_task_id": None,
                            "title": card.get("title") if isinstance(card, dict) else None,
                            "reason": "card_unreadable",
                        }
                    )
                    continue
                card_id = card.get("id")
                # Membership is known as soon as the card id is: record it
                # before any skip so a skipped card is never a false orphan.
                seen_card_ids.add(card_id)
                title = card.get("title", "Sin título")

                if card.get("archived"):
                    skipped.append(
                        {
                            "deck_task_id": card_id,
                            "title": title,
                            "reason": "archived",
                        }
                    )
                    continue

                if status is None:
                    skipped.append(
                        {
                            "deck_task_id": card_id,
                            "title": title,
                            "reason": f"stack_unmapped: {stack_name}",
                        }
                    )
                    continue

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

                # A card we cannot read is a card we cannot refresh. Report it
                # as skipped with its cause instead of silently keeping stale
                # data, and treat the read as partial so nothing is pruned.
                if detail_err or not isinstance(card_detail, dict):
                    read_complete = False
                    read_issues.append(
                        f"Card {card_id}: detail unavailable ({detail_err or 'empty'})"
                    )
                    skipped.append(
                        {
                            "deck_task_id": card_id,
                            "title": title,
                            "reason": f"card_read_failed: {detail_err or 'unavailable'}",
                        }
                    )
                    continue

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
                    # Single authoritative quest parser (deck_bridge.extract_quests):
                    # same done/text/index semantics as the legacy inline parser.
                    for quest in deck_bridge.extract_quests(description):
                        done = 1 if quest["done"] else 0
                        checklist_items_data.append(
                            {
                                "index": checklist_total,
                                "text": quest["text"],
                                "done": done,
                            }
                        )
                        checklist_total += 1
                        if done:
                            checklist_done += 1

                # Map stack title → mission status (computed per stack above).

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
                    skipped.append(
                        {
                            "deck_task_id": card_id,
                            "title": title,
                            "reason": "upsert_failed",
                        }
                    )
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

    # ── Drift report (always computed, prune or not) ──────────────────────
    # A mission is drift when the replica still holds it but a complete Deck
    # read no longer knows its card. Without a complete read we cannot tell
    # "not in Deck" from "I could not read it", so no orphan is ever inferred.
    missing_in_deck: list[dict] = []
    if read_complete:
        for mission in persistence.list_missions(project):
            deck_task_id = mission.get("deck_task_id")
            if deck_task_id is None:
                continue
            if deck_task_id not in seen_card_ids:
                missing_in_deck.append(
                    {
                        "mission_id": mission.get("id"),
                        "deck_task_id": deck_task_id,
                        "title": mission.get("title"),
                    }
                )
    else:
        errors.append(
            "drift_undetermined: Deck read incomplete ("
            + "; ".join(read_issues[:5])
            + ")"
        )

    # ── Prune (explicit, and only over a complete read) ──────────────────
    pruned: list[int] = []
    if prune:
        if not read_complete:
            errors.append("prune_skipped: incomplete Deck read, nothing deleted")
        else:
            for entry in missing_in_deck:
                mission_id = entry["mission_id"]
                try:
                    if persistence.prune_mission(mission_id):
                        pruned.append(mission_id)
                    else:
                        errors.append(
                            f"prune {mission_id}: mission row not found"
                        )
                except Exception as exc:
                    errors.append(f"prune {mission_id}: {exc}")
                    logger.exception("sync_tasks prune error")

    return json.dumps(
        {
            "project": project,
            "board_id": board_id,
            "synced": created,
            "pruned": pruned,
            "missing_in_deck": missing_in_deck,
            "skipped": skipped,
            "errors": errors,
            "total_errors": len(errors),
            "total_pruned": len(pruned),
            "total_missing_in_deck": len(missing_in_deck),
            "total_skipped": len(skipped),
            "prune_requested": prune,
            "read_complete": read_complete,
        },
        ensure_ascii=False,
        default=str,
    )


def _resolve_stack_for_card(
    board_id: int,
    mission: dict,
) -> tuple[int | None, str | None, str | None]:
    """Resolve the Deck stack that actually holds a mission's card (D7).

    Prefers the replicated ``deck_stack_id`` (design D9). When it is missing —
    which is the case for every mission until its first ``sync_task`` — this
    locates the card among the board's stacks (the same shape ``sync_tasks``
    consumes) so the correct stack is discovered and can be backfilled.

    W-g: the card MUST be located among the board's stacks. When it is not,
    this returns an error instead of guessing the pending/first stack, so a
    wrong ``deck_stack_id`` can never be backfilled. Returns
    ``(stack_id, stack_title, err)``; ``stack_title`` is ``None`` when the
    cached stack id was used (its title is not known without a lookup).
    """
    cached = mission.get("deck_stack_id")
    if cached:
        return int(cached), None, None

    from .mcp_client import call_mcp_tool, TOOL_NAMES

    data, err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_get_stacks"],
        {"board_id": board_id, "include_cards": True},
        timeout=15.0,
    )
    if data is None:
        return None, None, err or "unavailable"

    stacks = (
        data
        if isinstance(data, list)
        else data.get("stacks", data.get("result", []))
    )

    card_id = mission.get("deck_task_id")
    for stack in stacks:
        for card in (stack.get("cards") or []):
            if card.get("id") == card_id:
                return int(stack["id"]), stack.get("title"), None

    return None, None, "card not found in any board stack"


# Deck stack title → mission status (same vocabulary as sync_tasks). Deck is the
# source of truth, so sync_task derives the replica status from the card's
# current stack instead of echoing the stale local value (W-b/W3).
_STACK_STATUS_MAP = {
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


def _status_from_stack_title(stack_title: str | None, fallback: str) -> str:
    """Map a Deck stack title to the mission status vocabulary.

    Falls back to the supplied value when the title is unknown or unrecognized
    (e.g. the stack id came from the replica cache).
    """
    if not stack_title:
        return fallback
    return _STACK_STATUS_MAP.get(str(stack_title).strip().lower(), fallback)


@app.tool()
def sync_task(mission_id: int) -> str:
    """Recover exactly ONE mission (and its quests) from Deck (design D7).

    ``sync_task`` is the explicit single-mission recovery path. It resolves the
    mission's ``deck_task_id`` and stack internally, reads the authoritative
    card, and refreshes only that mission's replica fields and quests. It never
    syncs any other mission. On a successful read it backfills
    ``missions.deck_stack_id`` so later writes skip the ``deck_get_stacks``
    lookup (design D9).

    Args:
        mission_id: Local mission id.

    Returns:
        JSON {mission_id, deck_task_id, status, quests_synced}.
        An unknown ``mission_id`` fails with a not-found error and modifies no
        replica rows.
    """
    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps(
            {"error": f"Mission {mission_id} not found"},
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps({"error": err}, ensure_ascii=False, default=str)

    stack_id, stack_title, err = _resolve_stack_for_card(board_id, mission)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}"},
            ensure_ascii=False,
            default=str,
        )

    card, err = deck_bridge.read_card(
        board_id, stack_id, mission["deck_task_id"]
    )
    if card is None:
        return json.dumps(
            {"error": f"Cannot read Deck card: {err}"},
            ensure_ascii=False,
            default=str,
        )

    title = card.get("title") or mission.get("title", "")
    description = card.get("description", "") or ""
    quests = deck_bridge.extract_quests(description)
    checklist_total = len(quests)
    checklist_done = sum(1 for q in quests if q["done"])

    # Derive the status from the card's Deck stack (source of truth) instead of
    # echoing the stale replica value. When the stack id was cached its title is
    # unknown, so the replica value is the only available fallback.
    status = _status_from_stack_title(
        stack_title, mission.get("status", "pendiente")
    )

    # Refresh ONLY this mission's replica fields (Deck already is the truth).
    persistence.upsert_mission(
        deck_task_id=mission["deck_task_id"],
        project=mission.get("project", ""),
        title=title,
        description=description,
        status=status,
        checklist_total=checklist_total,
        checklist_done=checklist_done,
    )

    # Backfill deck_stack_id (D9) ONLY now that the card was located, so future
    # writes skip the stack lookup. A guessed stack is never persisted (W-g).
    try:
        persistence.set_mission_deck_stack_id(mission_id, stack_id)
    except Exception as exc:
        logger.warning("sync_task: deck_stack_id backfill failed: %s", exc)

    # Reconcile the replica with Deck: drop rows whose quest was removed there
    # (item_index >= len(parsed_quests)), then upsert the surviving set (W3).
    try:
        persistence.delete_checklist_items_beyond(mission_id, len(quests))
    except Exception as exc:
        logger.warning("sync_task: stale quest reconciliation failed: %s", exc)

    # Refresh this mission's quests (upsert by item_index, like sync_tasks).
    quests_synced = 0
    for idx, quest in enumerate(quests):
        persistence.upsert_checklist_item(
            mission_id=mission_id,
            item_index=idx,
            text=quest["text"],
            done=1 if quest["done"] else 0,
        )
        quests_synced += 1

    return json.dumps(
        {
            "mission_id": mission_id,
            "deck_task_id": mission["deck_task_id"],
            "status": status,
            "quests_synced": quests_synced,
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def sync_all() -> str:
    """~~DEPRECATED~~ Sync Deck cards → missions for ALL mapped projects.

    DEPRECATED — use ``sync_task(mission_id)`` for explicit single-mission
    recovery. ``sync_all`` is kept registered and invocable for compatibility
    (same marker pattern as ``assert_gates``); it MUST NOT be removed. It still
    iterates all projects with a deck_board_id and runs ``sync_tasks`` on each.

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
def mission_list(
    project: str,
    include_description: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> str:
    """List missions (Deck tasks) for a project, optionally paginated.

    Compact by default (design D4): each mission is represented by
    ``{id, title, status}`` only — no description and no nested
    ``checklist_items``. Pass ``include_description=True`` to opt in to the full
    payload (e.g. the dashboard). There is no global ``verbose`` toggle.

    Pagination (card #218, quest 10): with no ``limit`` every mission is
    returned, preserving the original behavior. ``limit`` selects a page size
    (must be a positive integer) and ``offset`` skips that many missions
    (default 0). ``total`` is always the real number of missions for the
    project, independent of the page size, so callers can page without a
    second counting call. An ``offset`` past ``total`` returns an empty page
    with the correct ``total``.

    Args:
        project: Project slug.
        include_description: If True, returns the full payload including
            description and nested checklist_items. Defaults to False (compact).
        limit: Optional page size (positive integer). Defaults to None (all).
        offset: Missions to skip before the page. Defaults to 0.

    Returns:
        JSON with missions list and the real ``total``.
    """
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return json.dumps(
                {
                    "error": "limit must be a positive integer (>= 1)",
                    "code": "invalid_limit",
                },
                ensure_ascii=False,
            )
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return json.dumps(
            {
                "error": "offset must be a non-negative integer (>= 0)",
                "code": "invalid_offset",
            },
            ensure_ascii=False,
        )

    all_missions = persistence.list_missions(project)
    total = len(all_missions)

    if limit is None:
        page = all_missions[offset:] if offset else all_missions
    else:
        page = all_missions[offset : offset + limit]

    if include_description:
        rendered = page
    else:
        rendered = [compact.compact_mission(m) for m in page]

    payload = {
        "project": project,
        "missions": rendered,
        "total": total,
    }

    return json.dumps(payload, ensure_ascii=False, default=str)


@app.tool()
def mission_get(mission_id: int) -> str:
    """Retrieve a single mission by ID with minimal fields.

    ``deck_stack_id`` is returned verbatim (``null`` when the replica has not
    backfilled it yet) so a caller can resolve the Deck board+stack without an
    extra lookup. It is never guessed or filled in here.
    """
    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Mission {mission_id} not found"})
    item_ids = [ci["id"] for ci in persistence.list_checklist_items(mission["id"])]
    return json.dumps(
        {
            "id": mission["id"],
            "title": mission["title"],
            "checklist_item_ids": item_ids,
            "deck_stack_id": mission.get("deck_stack_id"),
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def checklist_item_get(checklist_item_id: int) -> str:
    """Retrieve a single checklist item (quest) by ID, compact by default (D4)."""
    item = persistence.get_checklist_item_by_id(checklist_item_id)
    if not item:
        return json.dumps({"error": f"Checklist item {checklist_item_id} not found"})
    return json.dumps(compact.compact_quest(item), ensure_ascii=False, default=str)


@app.tool()
def quest_list(mission_id: int, include_done: bool = True) -> str:
    """Return the complete checklist of a mission in ONE call.

    Answers "where are we?" for a mission without one call per quest
    (card Deck #194): every quest is returned as ``{id, text, done}`` in
    checklist order. Pure read from the local replica — never touches Deck,
    never changes the schema, and never completes a quest.

    Args:
        mission_id: Mission (Deck task) id.
        include_done: If False, omit quests already done. Defaults to True.

    Returns:
        JSON with the mission id, ``quests`` and ``total`` (after filtering),
        or an error object when the mission does not exist.
    """
    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Mission {mission_id} not found"})
    quests = [
        compact.compact_quest(ci)
        for ci in persistence.list_checklist_items(mission_id)
    ]
    if not include_done:
        quests = [q for q in quests if not q["done"]]
    return json.dumps(
        {"mission_id": mission_id, "quests": quests, "total": len(quests)},
        ensure_ascii=False,
        default=str,
    )


# ── Mission / quest write tools (Deck-first, replica refresh) ──────────────
#
# Every write goes to Nextcloud Deck (the source of truth) through the internal
# ``deck_bridge`` BEFORE the local SQLite replica is touched. A bridge failure
# returns an error and performs NO local write (design D1/D9, Req
# "Deck Is the Source of Truth via the Internal Bridge").

# Stack titles treated as the "pending" bucket when creating a mission.
_PENDING_STACK_TITLES = {"backlog", "pendiente", "to do", "todo", "pending"}


def _resolve_board_id(project: str) -> tuple[int | None, str | None]:
    """Resolve a project's Deck board id from the project maps."""
    from .context_extractor import get_project_maps

    cfg = get_project_maps().get(project)
    if not cfg:
        return None, f"Project '{project}' not found in project_maps"
    board_id = cfg.get("deck_board_id")
    if board_id is None:
        return None, f"Project '{project}' has no deck_board_id mapped"
    return int(board_id), None


def _fetch_stacks(board_id: int) -> tuple[list | None, str | None]:
    """Fetch the board's stacks from Deck. Returns ``(stacks, err)``."""
    from .mcp_client import call_mcp_tool, TOOL_NAMES

    data, err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_get_stacks"],
        {"board_id": board_id, "include_cards": False},
        timeout=8.0,
    )
    if data is None:
        return None, err or "unavailable"
    stacks = (
        data
        if isinstance(data, list)
        else data.get("stacks", data.get("result", []))
    )
    return stacks, None


def _resolve_stack_id(
    board_id: int,
    mission: dict | None = None,
) -> tuple[int | None, str | None]:
    """Resolve a Deck stack id for a mission.

    Prefers the mission's replicated ``deck_stack_id`` (design D9) and falls
    back to a ``deck_get_stacks`` lookup when it is missing/``NULL``.
    """
    if mission:
        stack_id = mission.get("deck_stack_id")
        if stack_id:
            return int(stack_id), None

    stacks, err = _fetch_stacks(board_id)
    if stacks is None:
        return None, err
    if not stacks:
        return None, "no stacks found on board"

    for stack in stacks:
        title = str(stack.get("title", "")).strip().lower()
        if title in _PENDING_STACK_TITLES:
            return int(stack["id"]), None
    return int(stacks[0]["id"]), None


def _refresh_mission_replica_from_card(
    mission: dict,
    card: dict,
    status: str | None = None,
    *,
    adopt_ids: dict[int, int] | None = None,
) -> tuple[int, dict[int, int], str | None]:
    """Refresh ONE mission's replica from an authoritative post-write card.

    ``card`` is the payload the bridge produced from the single card read it
    already performs for the write (``{"title", "description", "quests"}``):
    exactly what Deck holds after the acknowledged write. That is the
    mission-scoped refresh this operation needs — no project-wide sweep, no
    second read and no per-quest Deck call (no N+1).

    The mission row (title, description, quest counters) and every quest row
    are refreshed from that payload, and replica quests Deck no longer has are
    pruned.

    ``adopt_ids`` maps an ``item_index`` to the id the server already composed
    into that line's marker (``quest_add``). Those rows are written at the
    exact id so the marker and the replica handle can never diverge.

    Returns ``(mission_id, {item_index: replica_quest_id}, err)``. On success
    ``err`` is ``None``; when the local refresh fails it returns the error
    string so the caller can report "Deck written, replica stale" instead of a
    clean success.
    """
    quests = card.get("quests") or []
    title = card.get("title") or mission.get("title", "") or ""
    description = card.get("description", "") or ""
    checklist_total = len(quests)
    checklist_done = sum(1 for quest in quests if quest.get("done"))
    replicated_status = status or mission.get("status", "pendiente") or "pendiente"
    forced_ids = adopt_ids or {}

    try:
        mission_id = int(mission.get("id") or 0)
    except (TypeError, ValueError):
        mission_id = 0

    quest_ids: dict[int, int] = {}
    try:
        stored_id = persistence.upsert_mission(
            deck_task_id=mission["deck_task_id"],
            project=mission.get("project", ""),
            title=title,
            description=description,
            status=replicated_status,
            checklist_total=checklist_total,
            checklist_done=checklist_done,
        )
        if not mission_id:
            try:
                mission_id = int(stored_id or 0)
            except (TypeError, ValueError):
                mission_id = 0
        if not mission_id:
            return 0, {}, "mission row not found after upsert"

        persistence.delete_checklist_items_beyond(mission_id, checklist_total)
        for idx, quest in enumerate(quests):
            forced_id = forced_ids.get(idx)
            if forced_id is not None:
                quest_id = persistence.upsert_checklist_item_with_id(
                    item_id=forced_id,
                    mission_id=mission_id,
                    item_index=idx,
                    text=quest["text"],
                    done=1 if quest["done"] else 0,
                )
            else:
                quest_id = persistence.upsert_checklist_item(
                    mission_id=mission_id,
                    item_index=idx,
                    text=quest["text"],
                    done=1 if quest["done"] else 0,
                )
            quest_ids[idx] = quest_id
    except Exception as exc:  # reported to the caller, never hidden
        logger.warning("replica refresh from Deck card failed: %s", exc)
        return mission_id, quest_ids, str(exc)

    return mission_id, quest_ids, None


def _deck_write_refresh_failure(
    *,
    deck_written_what: str,
    mission_id: int,
    refresh_error: str,
    extra: dict | None = None,
) -> str:
    """Build the explicit fail-closed response for a stale replica.

    The Deck write already happened, so this can never be reported as a clean
    success: the payload says WHAT Deck holds and that the replica is behind,
    so the caller can reconcile with ``sync_task``.
    """
    response = {
        "status": "error",
        "code": "replica_refresh_failed",
        "deck_written": True,
        "deck_written_what": deck_written_what,
        "replica_refresh_error": refresh_error,
        "replica_stale": True,
        "reconcile_with": f"sync_task({mission_id})",
        "error": (
            f"{deck_written_what}. The local replica could not be refreshed "
            f"({refresh_error}), so it is now stale; run "
            f"sync_task({mission_id}) to reconcile."
        ),
    }
    if extra:
        response.update(extra)
    return json.dumps(response, ensure_ascii=False, default=str)


@app.tool()
def mission_create(project: str, title: str, description: str = "") -> str:
    """Create a Deck-backed mission (Deck-first), then refresh the replica.

    Writes the Deck card through the internal bridge BEFORE creating the local
    replica row. No quest is created (design D2/D9, Req 1).

    Args:
        project: Project slug (e.g. "voy-rojo").
        title: Mission title (Deck card title).
        description: Optional prose description.

    Returns:
        JSON {mission_id, deck_task_id, title, status}.
    """
    board_id, err = _resolve_board_id(project)
    if err:
        return json.dumps({"error": err}, ensure_ascii=False, default=str)

    stack_id, err = _resolve_stack_id(board_id)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}"},
            ensure_ascii=False,
            default=str,
        )

    # No quest is created (D2/D9, Req 1): omit checkbox lines from the prose so
    # the description can never inject a quest into the freshly created card.
    clean_description = deck_bridge.clean_prose(description)

    card_id, err = deck_bridge.create_card(
        board_id, stack_id, title, clean_description
    )
    if card_id is None:
        return json.dumps(
            {"error": f"Deck bridge unavailable: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    mission_id = persistence.upsert_mission(
        deck_task_id=card_id,
        project=project,
        title=title,
        description=clean_description,
        status="pendiente",
    )
    if not mission_id:
        return json.dumps(
            {
                "status": "error",
                "code": "replica_refresh_failed",
                "deck_written": True,
                "deck_task_id": card_id,
                "deck_written_what": f"Deck card {card_id} created",
                "replica_refresh_error": "mission row not stored",
                "replica_stale": True,
                "reconcile_with": "sync_task(<mission_id>)",
                "error": (
                    f"Deck card {card_id} was created, but the local replica "
                    "was not refreshed (mission row not stored). The replica "
                    "is now stale; sync the mission before using its id."
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    return json.dumps(
        {
            "mission_id": mission_id,
            "deck_task_id": card_id,
            "title": title,
            "status": "pendiente",
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def mission_update_title(mission_id: int, title: str) -> str:
    """Update a mission's title (Deck-first), then refresh the replica.

    An unknown ``mission_id`` fails with a not-found error and performs NO
    Deck call (Req 1).

    Args:
        mission_id: Local mission id.
        title: New mission title (Deck card title).

    Returns:
        JSON {mission_id, title, status}. When Deck accepted the title but the
        replica refresh failed, returns an explicit error (``code:
        replica_refresh_failed``, ``deck_written: true``).
    """
    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps(
            {"error": f"Mission {mission_id} not found"},
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps({"error": err}, ensure_ascii=False, default=str)

    stack_id, err = _resolve_stack_id(board_id, mission)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}"},
            ensure_ascii=False,
            default=str,
        )

    record, err = deck_bridge.update_title_record(
        board_id, stack_id, mission["deck_task_id"], title
    )
    if record is None:
        return json.dumps(
            {"error": f"Deck bridge unavailable: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    status = mission.get("status", "pendiente")
    _replica_id, _quest_ids, refresh_error = _refresh_mission_replica_from_card(
        mission, record, status
    )
    if refresh_error is not None:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} title updated to {title!r}"
            ),
            mission_id=mission_id,
            refresh_error=refresh_error,
            extra={"mission_id": mission_id, "title": title},
        )
    return json.dumps(
        {"mission_id": mission_id, "title": title, "status": status},
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def mission_update_description(mission_id: int, description: str) -> str:
    """Update a mission's prose description without touching its quests (D3).

    The bridge preserves every quest line byte-identical and in its original
    order. The write starts from a fresh card read; when that read is
    suspicious (no checkbox lines while the replica knows quests) the write is
    refused instead of silently deleting the checklist. An unknown
    ``mission_id`` fails with a not-found error and performs NO Deck call
    (Req 1).

    Args:
        mission_id: Local mission id.
        description: New prose description (quest lines are ignored).

    Returns:
        JSON {mission_id, status}. When the Deck write succeeds but the replica
        refresh fails, returns an explicit error (``code:
        replica_refresh_failed``, ``deck_written: true``) naming what Deck holds
        and how to reconcile — never a clean success with a stale replica.
    """
    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps(
            {"error": f"Mission {mission_id} not found"},
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps({"error": err}, ensure_ascii=False, default=str)

    stack_id, err = _resolve_stack_id(board_id, mission)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}"},
            ensure_ascii=False,
            default=str,
        )

    # The replica's quest rows are the only evidence that this mission has a
    # checklist. Use both the row count and the denormalized counter so a stale
    # read cannot be mistaken for a human deleting every quest.
    replica_quests = persistence.list_checklist_items(mission_id) or []
    expected_quests = max(
        len(replica_quests),
        int(mission.get("checklist_total") or 0),
    )

    result, err = deck_bridge.write_description(
        board_id,
        stack_id,
        mission["deck_task_id"],
        description,
        expected_quest_count=expected_quests,
    )
    if result is None:
        if err == deck_bridge.ERR_EMPTY_DESCRIPTION:
            detail = (
                f"Deck card {mission['deck_task_id']} read returned an empty "
                f"description while the replica has {expected_quests} quest(s); "
                "refusing to overwrite the card. Re-read the card and retry."
            )
        elif err == deck_bridge.ERR_QUESTS_MISSING:
            detail = (
                f"Deck card {mission['deck_task_id']} read returned no quest "
                f"lines while the replica has {expected_quests} quest(s); the "
                "read looks stale. Refusing to overwrite the card."
            )
        else:
            detail = f"Deck bridge unavailable: {err}"
        return json.dumps(
            {
                "error": detail,
                "mission_id": mission_id,
                "reason": err,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    # Refresh the replica from what Deck actually holds now: same prose, same
    # quests, same order, same state. Report a refresh failure instead of
    # hiding it; the Deck write already happened.
    _replica_id, _quest_ids, refresh_error = _refresh_mission_replica_from_card(
        mission, result, mission.get("status", "pendiente")
    )
    if refresh_error is not None:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} description updated"
            ),
            mission_id=mission_id,
            refresh_error=refresh_error,
            extra={"mission_id": mission_id},
        )

    return json.dumps(
        {"mission_id": mission_id, "status": "ok"},
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def mission_delete(
    mission_id: int,
    confirm: bool = False,
    reason: str = "",
    requested_by: str = "hermes",
) -> str:
    """Delete ONE mission from the replica, with an audit trail. NEVER touches Deck.

    This is a REPLICA-ONLY cleanup: the Deck card is not deleted, archived, or
    moved. Everything the replica holds for the mission — the mission row, its
    quests (``checklist_items``), ``intentos``, ``attempt_grants`` and
    ``turn_bitacora`` rows — is removed in a single transaction, or not at all.

    Deleting a mission is never a side effect of a typo: both ``confirm=True``
    and a non-empty ``reason`` are required. When either is missing the call
    fails validation and mutates nothing. An unknown ``mission_id`` fails with
    an explicit error naming the id.

    The deletion is recorded in the replica's ``mission_deletions`` audit ledger
    (who, when, why, and the deleted ids), which survives the mission.

    Args:
        mission_id: Local mission id.
        confirm: Must be True; guards against accidental deletion.
        reason: Non-empty justification, stored in the audit ledger.
        requested_by: Who requested the deletion (audit ``who``).

    Returns:
        JSON {status, mission_id, deck_task_id, project, title, deleted, audit_id}
        or a validation/not-found error object.
    """
    if not confirm:
        return json.dumps(
            {
                "error": "confirmation required: pass confirm=true to delete",
                "mission_id": mission_id,
            },
            ensure_ascii=False,
            default=str,
        )
    if not (reason or "").strip():
        return json.dumps(
            {
                "error": "reason required: mission_delete needs a non-empty reason",
                "mission_id": mission_id,
            },
            ensure_ascii=False,
            default=str,
        )

    try:
        result = persistence.delete_mission(
            mission_id, reason=reason, requested_by=requested_by
        )
    except ValueError as exc:
        return json.dumps(
            {"error": str(exc), "mission_id": mission_id},
            ensure_ascii=False,
            default=str,
        )

    if result is None:
        return json.dumps(
            {"error": f"Mission {mission_id} not found", "mission_id": mission_id},
            ensure_ascii=False,
            default=str,
        )

    return json.dumps(
        {
            "status": "deleted",
            "mission_id": result["mission_id"],
            "deck_task_id": result["deck_task_id"],
            "project": result["project"],
            "title": result["title"],
            "deleted": {
                "quests": result["quests_deleted"],
                "intentos": result["intentos_deleted"],
                "attempt_grants": result["grants_deleted"],
                "turn_bitacora": result["bitacora_deleted"],
            },
            "audit_id": result["audit_id"],
            "replica_only": True,
            "deck_untouched": True,
            "note": "Replica only: the Deck card was NOT deleted, archived, or moved.",
        },
        ensure_ascii=False,
        default=str,
    )


def _quest_add_batch(
    *,
    mission: dict,
    mission_id: int,
    board_id: int,
    stack_id: int,
    clean_titles: list[str],
) -> str:
    """Append a validated quest batch: one Deck write, one replica refresh.

    The ids are allocated read-only in one call and composed into every marker
    before the Deck write, so a failed write leaves no phantom replica row.
    A single ``refresh_error`` covers the whole batch: when Deck was written
    but the replica could not follow, the caller gets ``deck_written: true``.
    """
    try:
        first_id = persistence.next_checklist_item_id()
    except Exception as exc:
        return json.dumps(
            {"error": f"Cannot allocate quest ids: {exc}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    new_ids = [first_id + index for index in range(len(clean_titles))]
    entries = list(zip(clean_titles, new_ids))

    record, err = deck_bridge.append_quests_record(
        board_id,
        stack_id,
        mission["deck_task_id"],
        entries,
    )
    if record is None:
        return json.dumps(
            {"error": f"Deck bridge unavailable: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    positions = record["positions"]
    adopt_ids = dict(zip(positions, new_ids))
    _replica_id, quest_ids, refresh_error = _refresh_mission_replica_from_card(
        mission, record, adopt_ids=adopt_ids
    )
    if refresh_error is None and any(
        quest_ids.get(position) != quest_id
        for position, quest_id in adopt_ids.items()
    ):
        refresh_error = "appended quest rows do not use the composed marker ids"
    if refresh_error is not None:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quest batch appended at "
                f"positions {positions[0]}-{positions[-1]}"
            ),
            mission_id=mission_id,
            refresh_error=refresh_error,
            extra={
                "mission_id": mission_id,
                "positions": positions,
                "quest_ids": new_ids,
            },
        )

    return json.dumps(
        {
            "mission_id": mission_id,
            "quest_ids": new_ids,
            "count": len(new_ids),
            "identity": "marker",
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def quest_add(
    mission_id: int,
    title: str | None = None,
    quests: list[str] | None = None,
) -> str:
    """Append a quest, or a whole batch of quests, Deck-first, then the replica.

    The quest (or every quest in the batch) is always written with
    ``done=false`` (design D2/D10). There is no tool that marks a quest
    complete; only ``end_turn`` does that.

    ``title`` and ``quests`` are mutually exclusive. A batch is written with
    ONE Deck description write and ONE replica refresh, so N quests never cost
    N round-trips (card #218, quest 10). Every server-composed id is returned
    in request order.

    Args:
        mission_id: Local mission id.
        title: Quest text for the single-quest form (original signature).
        quests: Batch of quest texts. Mutually exclusive with ``title``.

    Returns:
        Single form: JSON {quest_id, mission_id, title, done, identity}.
        Batch form: JSON {mission_id, quest_ids, count, identity}, with
        ``quest_ids`` in the same order the quests were requested. When Deck
        accepted the write but the replica refresh failed, returns an explicit
        error (``code: replica_refresh_failed``, ``deck_written: true``)
        instead of a clean success.
    """
    if title is not None and quests is not None:
        return json.dumps(
            {
                "error": "Pass either 'title' or 'quests', not both",
                "code": "quest_add_ambiguous_input",
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )
    if title is None and quests is None:
        return json.dumps(
            {
                "error": "Pass either 'title' or 'quests'",
                "code": "quest_add_missing_input",
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    clean_titles: list[str] = []
    if quests is not None:
        if not isinstance(quests, list) or not quests:
            return json.dumps(
                {
                    "error": "Quest batch must be a non-empty list",
                    "code": "quests_empty",
                    "deck_written": False,
                },
                ensure_ascii=False,
                default=str,
            )
        for raw in quests:
            if not isinstance(raw, str):
                return json.dumps(
                    {
                        "error": "Every quest must be a string",
                        "code": "quest_text_invalid",
                        "deck_written": False,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            clean = deck_bridge.sanitize_quest_text(raw)
            if clean is None:
                code = (
                    "quest_text_multiline"
                    if ("\n" in raw or "\r" in raw)
                    else "quest_text_empty"
                )
                return json.dumps(
                    {
                        "error": "Quest text must be a single non-empty line",
                        "code": code,
                        "deck_written": False,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            clean_titles.append(clean)

    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps(
            {"error": f"Mission {mission_id} not found"},
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps({"error": err}, ensure_ascii=False, default=str)

    stack_id, err = _resolve_stack_id(board_id, mission)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}"},
            ensure_ascii=False,
            default=str,
        )

    if quests is not None:
        return _quest_add_batch(
            mission=mission,
            mission_id=mission_id,
            board_id=board_id,
            stack_id=stack_id,
            clean_titles=clean_titles,
        )

    # The marker id is composed by the server (never by the model) and must be
    # the same id the replica row will use. The id is allocated read-only, so
    # a failed Deck write leaves the replica untouched.
    clean_title = deck_bridge.sanitize_quest_text(title)
    if clean_title is None:
        raw_title = title or ""
        code = (
            "quest_text_multiline"
            if ("\n" in raw_title or "\r" in raw_title)
            else "quest_text_empty"
        )
        return json.dumps(
            {
                "error": "Quest text must be a single non-empty line",
                "code": code,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    try:
        new_quest_id = persistence.next_checklist_item_id()
    except Exception as exc:
        return json.dumps(
            {"error": f"Cannot allocate quest id: {exc}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    record, err = deck_bridge.append_quest_record(
        board_id,
        stack_id,
        mission["deck_task_id"],
        clean_title,
        quest_id=new_quest_id,
    )
    if record is None:
        return json.dumps(
            {"error": f"Deck bridge unavailable: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    position = record["position"]
    _replica_id, quest_ids, refresh_error = _refresh_mission_replica_from_card(
        mission, record, adopt_ids={position: new_quest_id}
    )
    if refresh_error is None and quest_ids.get(position) != new_quest_id:
        refresh_error = "appended quest row does not use the composed marker id"
    if refresh_error is not None:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quest appended at "
                f"position {position}"
            ),
            mission_id=mission_id,
            refresh_error=refresh_error,
            extra={"mission_id": mission_id, "title": clean_title, "position": position},
        )

    quest_id = new_quest_id
    return json.dumps(
        {
            "quest_id": quest_id,
            "mission_id": mission_id,
            "title": clean_title,
            "done": False,
            "identity": "marker",
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def quest_update(
    quest_id: int,
    title: str | None = None,
    position: int | None = None,
) -> str:
    """Surgically rewrite one quest line (Deck-first), always resetting done.

    ``position`` optionally overrides which Deck checkbox line is edited
    (defaults to the replica quest's ``item_index``). ``title`` optionally
    replaces the quest text. The replica is refreshed with ``done=false``
    (design D2/D10). No mark-complete path exists here.

    Args:
        quest_id: Local checklist-item (quest) id.
        title: Optional new quest text.
        position: Optional Deck checkbox position override.

    Returns:
        JSON {quest_id, title, done}. When Deck accepted the rewrite but the
        replica refresh failed, returns an explicit error (``code:
        replica_refresh_failed``, ``deck_written: true``).
    """
    quest = persistence.get_checklist_item_by_id(quest_id)
    if not quest:
        return json.dumps(
            {"error": f"Quest {quest_id} not found"},
            ensure_ascii=False,
            default=str,
        )

    mission = persistence.get_mission(quest["mission_id"])
    if not mission:
        return json.dumps(
            {"error": f"Mission {quest['mission_id']} not found"},
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps({"error": err}, ensure_ascii=False, default=str)

    stack_id, err = _resolve_stack_id(board_id, mission)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}"},
            ensure_ascii=False,
            default=str,
        )

    deck_position = position if position is not None else quest["item_index"]
    new_text = title if title is not None else quest["text"]

    record, err = deck_bridge.update_quest_record(
        board_id, stack_id, mission["deck_task_id"], deck_position, new_text
    )
    if record is None:
        return json.dumps(
            {"error": f"Deck bridge unavailable: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    _replica_id, _quest_ids, refresh_error = _refresh_mission_replica_from_card(
        mission, record
    )
    if refresh_error is not None:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quest at position "
                f"{deck_position} rewritten"
            ),
            mission_id=mission["id"],
            refresh_error=refresh_error,
            extra={
                "quest_id": quest_id,
                "title": new_text,
                "position": deck_position,
            },
        )

    return json.dumps(
        {"quest_id": quest_id, "title": new_text, "done": False},
        ensure_ascii=False,
        default=str,
    )


def _quest_pair(quest: dict) -> tuple[str, int]:
    """The identity-sensitive pair used to prove quests are not renamed."""
    return (quest["text"], 1 if quest.get("done") else 0)


@app.tool()
def quest_delete(
    quest_id: int,
    confirm: bool = False,
    reason: str = "",
    force: bool = False,
    requested_by: str = "hermes",
) -> str:
    """Delete ONE quest from the Deck card and the replica, preserving ids.

    The targeted quest line is removed from Deck and its replica row is
    deleted; every surviving quest keeps its id, text and state and only its
    ``item_index`` is recomputed. This never goes through the positional
    upsert, which would rename the quests after the deleted one.

    Both ``confirm=True`` and a non-empty ``reason`` are required and are
    validated before any Deck read or write. A quest with traceability rows
    (intentos, attempt grants, turn bitacora) is refused unless ``force=True``;
    with ``force`` those rows are deleted in the same transaction and the audit
    event in ``quest_deletions`` records the deleted ids.

    Args:
        quest_id: Local checklist-item (quest) id.
        confirm: Must be True; guards against accidental deletion.
        reason: Non-empty justification, stored in the audit ledger.
        force: Delete even when the quest has traceability rows.
        requested_by: Who requested the deletion (audit ``who``).

    Returns:
        JSON {status, quest_id, mission_id, text, deleted, deleted_ids,
        audit_id} or an explicit error. When Deck was written but the replica
        could not be refreshed, returns ``replica_refresh_failed`` with
        ``deck_written: true``.
    """
    if not confirm:
        return json.dumps(
            {
                "error": "confirmation required: pass confirm=true to delete",
                "code": "confirmation_required",
                "quest_id": quest_id,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )
    if not (reason or "").strip():
        return json.dumps(
            {
                "error": "reason required: quest_delete needs a non-empty reason",
                "code": "reason_required",
                "quest_id": quest_id,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    quest = persistence.get_checklist_item_by_id(quest_id)
    if not quest:
        return json.dumps(
            {"error": f"Quest {quest_id} not found", "quest_id": quest_id},
            ensure_ascii=False,
            default=str,
        )

    mission = persistence.get_mission(quest["mission_id"])
    if not mission:
        return json.dumps(
            {
                "error": f"Mission {quest['mission_id']} not found",
                "quest_id": quest_id,
            },
            ensure_ascii=False,
            default=str,
        )

    history = persistence.quest_history_counts(quest_id)
    if history and history.get("has_history") and not force:
        return json.dumps(
            {
                "error": (
                    "quest has traceability rows (intentos/grants/bitacora); "
                    "pass force=true to delete it and its history"
                ),
                "code": "quest_has_history",
                "quest_id": quest_id,
                "mission_id": mission["id"],
                "history": {
                    "intentos": history["intentos"],
                    "attempt_grants": history["grants"],
                    "turn_bitacora": history["bitacora"],
                },
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps({"error": err, "deck_written": False}, ensure_ascii=False)

    stack_id, err = _resolve_stack_id(board_id, mission)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    deck_position = quest["item_index"]
    record, err = deck_bridge.delete_quest_record_by_marker(
        board_id, stack_id, mission["deck_task_id"], quest_id
    )
    if record is None:
        if err == deck_bridge.ERR_LEGACY_IDENTITY:
            return json.dumps(
                {
                    "error": (
                        "Mission has no stable quest markers (legacy or mixed "
                        "checklist); quest_delete requires marker identity. "
                        "Run quest_migrate_identity(mission_id) first."
                    ),
                    "code": "legacy_identity",
                    "quest_id": quest_id,
                    "mission_id": mission["id"],
                    "deck_written": False,
                },
                ensure_ascii=False,
                default=str,
            )
        return json.dumps(
            {"error": f"Deck bridge unavailable: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    # Prove the identity invariant against the acknowledged card BEFORE touching
    # the replica: the survivors, in order, must be exactly the quests Deck kept.
    replica_before = persistence.list_checklist_items(mission["id"])
    expected_pairs = [
        _quest_pair(q) for q in replica_before if q["id"] != quest_id
    ]
    deck_pairs = [_quest_pair(q) for q in record.get("quests") or []]
    if expected_pairs != deck_pairs:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quest at position "
                f"{deck_position} deleted"
            ),
            mission_id=mission["id"],
            refresh_error=(
                "replica and Deck disagree about the surviving quests; "
                "the replica was not modified"
            ),
            extra={"quest_id": quest_id},
        )

    try:
        result = persistence.delete_checklist_item(
            quest_id,
            force=force,
            reason=reason,
            requested_by=requested_by,
            description=record.get("description"),
        )
    except Exception as exc:  # reported, never hidden
        logger.warning("quest_delete replica update failed: %s", exc)
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quest at position "
                f"{deck_position} deleted"
            ),
            mission_id=mission["id"],
            refresh_error=str(exc),
            extra={"quest_id": quest_id},
        )

    if result is None or result.get("refused"):
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quest at position "
                f"{deck_position} deleted"
            ),
            mission_id=mission["id"],
            refresh_error="replica quest row not found after the Deck write",
            extra={"quest_id": quest_id},
        )

    return json.dumps(
        {
            "status": "deleted",
            "quest_id": result["quest_id"],
            "mission_id": result["mission_id"],
            "text": result["text"],
            "deleted": {
                "intentos": result["intentos_deleted"],
                "attempt_grants": result["grants_deleted"],
                "turn_bitacora": result["bitacora_deleted"],
            },
            "deleted_ids": result["deleted_ids"],
            "audit_id": result["audit_id"],
            "forced": result["forced"],
            "identity": "marker",
            "deck_written": True,
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def quest_reorder(mission_id: int, ordered_ids: list[int]) -> str:
    """Reorder a mission's whole checklist to exactly ``ordered_ids``.

    ``ordered_ids`` must be exactly the mission's quest set: no duplicates,
    nothing missing, nothing from another mission. Any difference fails before
    any Deck or replica mutation. Ids move with their text and state — the pair
    ``(id, text)`` is invariant; only the order changes.

    One Deck read and one description write, then one replica transaction.

    Args:
        mission_id: Local mission id.
        ordered_ids: Quest ids in the exact desired order.

    Returns:
        JSON {status, mission_id, ordered_ids, quests} or an explicit error.
        When Deck was written but the replica could not be refreshed, returns
        ``replica_refresh_failed`` with ``deck_written: true``.
    """
    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps(
            {"error": f"Mission {mission_id} not found", "mission_id": mission_id},
            ensure_ascii=False,
            default=str,
        )

    quests = persistence.list_checklist_items(mission_id)
    current_ids = [q["id"] for q in quests]
    requested = list(ordered_ids or [])

    duplicates = sorted({i for i in requested if requested.count(i) > 1})
    missing = sorted(set(current_ids) - set(requested))
    extra = sorted(set(requested) - set(current_ids))
    if duplicates or missing or extra or len(requested) != len(current_ids):
        return json.dumps(
            {
                "error": (
                    "ordered_ids must be exactly the mission's quest set: "
                    f"missing={missing}, extra={extra}, duplicates={duplicates}"
                ),
                "code": "quest_reorder_mismatch",
                "mission_id": mission_id,
                "missing": missing,
                "extra": extra,
                "duplicates": duplicates,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps({"error": err, "deck_written": False}, ensure_ascii=False)

    stack_id, err = _resolve_stack_id(board_id, mission)
    if err:
        return json.dumps(
            {"error": f"Cannot resolve Deck stack: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    by_id = {q["id"]: q for q in quests}

    record, err = deck_bridge.reorder_quests_record_by_marker(
        board_id, stack_id, mission["deck_task_id"], requested
    )
    if record is None:
        if err == deck_bridge.ERR_LEGACY_IDENTITY:
            return json.dumps(
                {
                    "error": (
                        "Mission has no stable quest markers (legacy or mixed "
                        "checklist); quest_reorder requires marker identity. "
                        "Run quest_migrate_identity(mission_id) first."
                    ),
                    "code": "legacy_identity",
                    "mission_id": mission_id,
                    "deck_written": False,
                },
                ensure_ascii=False,
                default=str,
            )
        return json.dumps(
            {"error": f"Deck bridge unavailable: {err}", "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    # Same invariant as delete: the requested order must be the order Deck kept,
    # otherwise the replica is stale and must not be rewritten over it.
    expected_pairs = [_quest_pair(by_id[quest_id]) for quest_id in requested]
    deck_pairs = [_quest_pair(q) for q in record.get("quests") or []]
    if expected_pairs != deck_pairs:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quests reordered"
            ),
            mission_id=mission_id,
            refresh_error=(
                "replica and Deck disagree about the reordered quests; "
                "the replica was not modified"
            ),
            extra={"ordered_ids": requested},
        )

    try:
        result = persistence.reorder_checklist_items(
            mission_id, requested, description=record.get("description")
        )
    except Exception as exc:  # reported, never hidden
        logger.warning("quest_reorder replica update failed: %s", exc)
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quests reordered"
            ),
            mission_id=mission_id,
            refresh_error=str(exc),
            extra={"ordered_ids": requested},
        )

    if result is None:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quests reordered"
            ),
            mission_id=mission_id,
            refresh_error="mission row not found after the Deck write",
            extra={"ordered_ids": requested},
        )

    return json.dumps(
        {
            "status": "ok",
            "mission_id": mission_id,
            "ordered_ids": result["ordered_ids"],
            "quests": result["quests"],
            "identity": "marker",
            "deck_written": True,
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def quest_migrate_identity(
    mission_id: int,
    confirm: bool = False,
    reason: str = "",
    requested_by: str = "hermes",
) -> str:
    """Migrate ONE mission's existing quests to stable marker identity.

    Explicit and versioned: it rewrites only the requested mission's Deck
    description, adding a ``[](#q:{id})`` marker to each quest line while
    preserving the id, text, order, bullet and done state of every quest. It
    never generates new ids (that would rename exactly what it protects) and is
    idempotent: a second run adds no marker and changes no id.

    Both ``confirm=True`` and a non-empty ``reason`` are required and are
    validated before any Deck read or write. The audit row is written to the
    ``quest_identity_migrations`` ledger in the same transaction as the replica
    description refresh.

    Args:
        mission_id: Local mission id (one mission, never a project sweep).
        confirm: Must be True; guards against accidental rewrites.
        reason: Non-empty justification, stored in the audit ledger.
        requested_by: Who requested the migration (audit ``who``).

    Returns:
        JSON {status, mission_id, deck_written, migrated_ids, quest_ids,
        audit_id, quests} or an explicit error. When Deck was written but the
        replica could not be refreshed, returns ``replica_refresh_failed`` with
        ``deck_written: true``.
    """
    if not confirm:
        return json.dumps(
            {
                "error": "confirmation required: pass confirm=true to migrate",
                "code": "confirmation_required",
                "mission_id": mission_id,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )
    if not (reason or "").strip():
        return json.dumps(
            {
                "error": (
                    "reason required: quest_migrate_identity needs a "
                    "non-empty reason"
                ),
                "code": "reason_required",
                "mission_id": mission_id,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    mission = persistence.get_mission(mission_id)
    if not mission:
        return json.dumps(
            {"error": f"Mission {mission_id} not found", "mission_id": mission_id},
            ensure_ascii=False,
            default=str,
        )

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        return json.dumps(
            {"error": err, "deck_written": False},
            ensure_ascii=False,
            default=str,
        )

    stack_id, err = _resolve_stack_id(board_id, mission)
    if err:
        return json.dumps(
            {
                "error": f"Cannot resolve Deck stack: {err}",
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    replica_quests = persistence.list_checklist_items(mission_id)
    ids_by_position = [int(quest["id"]) for quest in replica_quests]

    record, err = deck_bridge.migrate_description_to_markers(
        board_id,
        stack_id,
        mission["deck_task_id"],
        ids_by_position,
    )
    if record is None:
        return json.dumps(
            {
                "error": f"Cannot migrate quest identity: {err}",
                "code": err if isinstance(err, str) else "migration_failed",
                "mission_id": mission_id,
                "deck_written": False,
            },
            ensure_ascii=False,
            default=str,
        )

    if record["status"] == "already_migrated":
        return json.dumps(
            {
                "status": "already_migrated",
                "mission_id": mission_id,
                "deck_written": False,
                "migrated_ids": [],
                "quest_ids": record["quest_ids"],
                "quests": [
                    {
                        "quest_id": quest["quest_id"],
                        "text": quest["text"],
                        "done": quest["done"],
                    }
                    for quest in record["quests"]
                ],
            },
            ensure_ascii=False,
            default=str,
        )

    try:
        result = persistence.migrate_quest_markers(
            mission_id,
            description=record["description"],
            reason=reason,
            requested_by=requested_by,
            quest_ids=record["quest_ids"],
            migrated_ids=record["migrated_ids"],
        )
    except Exception as exc:  # reported, never hidden
        logger.warning("quest_migrate_identity replica update failed: %s", exc)
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quests migrated to markers"
            ),
            mission_id=mission_id,
            refresh_error=str(exc),
            extra={"migrated_ids": record["migrated_ids"]},
        )

    if result is None:
        return _deck_write_refresh_failure(
            deck_written_what=(
                f"Deck card {mission['deck_task_id']} quests migrated to markers"
            ),
            mission_id=mission_id,
            refresh_error="mission row not found after the Deck write",
            extra={"migrated_ids": record["migrated_ids"]},
        )

    return json.dumps(
        {
            "status": "migrated",
            "mission_id": mission_id,
            "deck_written": True,
            "migrated_ids": result["migrated_ids"],
            "quest_ids": result["quest_ids"],
            "audit_id": result["audit_id"],
            "quests": [
                {
                    "quest_id": quest["quest_id"],
                    "text": quest["text"],
                    "done": quest["done"],
                }
                for quest in record["quests"]
            ],
        },
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def begin_turn(
    session_id: str,
    project: str,
    mission_id: int = 0,
    quest_id: int = 0,
    message: str = "",
    sender: str = "user",
    checklist_item_id: int = 0,
    full: bool = False,
) -> str:
    """Begin a new turn: execute gates fresh and create an intento.

    This is the first call of the consolidated 2-call turn workflow:
      begin_turn → trabajo → end_turn

    begin_turn EJECUTA INTERNAMENTE los 4 gates (1a/1b/1c/1e) de forma fresca,
    persistiendo los resultados en gate_state y capturándolos en el intento.
    Esto elimina la necesidad de llamar assert_gates manualmente antes del turno.

    The default response is a TURN DELTA (card #218, quest 11): the ids the
    caller must carry, the compact gate evidence (``{name, state, mandatory}``,
    never ``result_data``), the gate summary, and the pending-quest count. It
    never carries the mission payload, its description, or the full checklist —
    those do not change per turn and would be paid on every call.

    Pass ``full=True`` for the full state: today's payload plus the mission
    row and its complete checklist. Nothing is unreachable, only not paid for by
    default.

    Before ANY side effect (orphan cleanup AND gate execution), begin_turn
    resolves and validates the target quest (design D5). A quest that is already
    ``done`` or unknown fails hard with a ``code`` and mutates nothing.

    If an orphaned turn exists (active in memory but not matching this request),
    it is auto-completed as "fail" so the new turn can proceed — this prevents
    IRRECOVERABLE state where a crashed/blocked previous turn blocks all future turns.

    Args:
        session_id:         Active Hermes session identifier.
        project:            Project slug (e.g. "voy-rojo").
        mission_id:         Numeric mission ID (same as record_intento).
        quest_id:           Numeric quest (checklist item) ID. Canonical 4th
                            positional parameter, positionally compatible with
                            the legacy ``checklist_item_id``.
        message:            The user's raw message / query (used for context extraction).
        sender:             Optional sender name (default: "user").
        checklist_item_id:  Backward-compatible trailing alias for ``quest_id``.
        full:               If True, also return the full mission row and its
                            complete checklist. Defaults to False (turn delta).

    Returns:
        JSON string with intento_id, mission_id, quest_id, status, the compact
        gate list, the real fresh gate counts, and ``pending_quests``. With
        ``full=True`` it additionally carries ``mission`` and ``checklist``.
        On a done/unknown quest:
        ``{"error", "code": "quest_done"|"missing_quest", "quest_id"}``.
    """
    # 0. Guard (D5): resolve/validate the target quest BEFORE any mutation.
    #    This MUST precede the orphan cleanup and the gate execution so a done
    #    or missing quest leaves the system with zero side effects. The guard
    #    is REQUIRED: omitting the ids never silently bypasses it (W-a).
    resolved_quest_id = quest_id or checklist_item_id
    if not resolved_quest_id:
        return json.dumps(
            {
                "error": "A nonzero quest_id (or legacy checklist_item_id) is required",
                "code": "missing_quest",
                "quest_id": 0,
            },
            ensure_ascii=False,
            default=str,
        )
    if not mission_id:
        return json.dumps(
            {
                "error": "A nonzero mission_id is required",
                "code": "missing_mission",
                "mission_id": 0,
            },
            ensure_ascii=False,
            default=str,
        )

    target_quest = persistence.get_checklist_item_by_id(resolved_quest_id)
    if target_quest is None:
        return json.dumps(
            {
                "error": f"Quest {resolved_quest_id} not found",
                "code": "missing_quest",
                "quest_id": resolved_quest_id,
            },
            ensure_ascii=False,
            default=str,
        )
    if isinstance(target_quest, dict) and target_quest.get("done"):
        return json.dumps(
            {
                "error": f"Quest {resolved_quest_id} is already done",
                "code": "quest_done",
                "quest_id": resolved_quest_id,
            },
            ensure_ascii=False,
            default=str,
        )
    if isinstance(target_quest, dict) and target_quest.get("mission_id") != mission_id:
        # The quest must belong to the requested mission (D5). Otherwise a
        # crossed id would let end_turn close the wrong card position.
        return json.dumps(
            {
                "error": (
                    f"Quest {resolved_quest_id} does not belong to "
                    f"mission {mission_id}"
                ),
                "code": "quest_mission_mismatch",
                "quest_id": resolved_quest_id,
                "mission_id": mission_id,
            },
            ensure_ascii=False,
            default=str,
        )

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

    # 3. Agregar info de mandatory/best_effort a cada resultado (D8)
    for r in gate_results:
        cfg = GATE_CONFIG_MAP.get(r.name)
        if cfg:
            r.mandatory = cfg.mandatory
            r.best_effort = cfg.best_effort

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

    # 5. Crear intento con los gates frescos.
    #    Persist the RESOLVED quest id (quest_id or its legacy alias) — never
    #    the raw trailing alias, which is 0 when the caller uses quest_id.
    #    Otherwise end_turn's _complete_quest_for_intento short-circuits and
    #    the false→true quest transition never happens.
    intento_id = persistence.create_intento(
        session_id=session_id,
        project=resolved_project,
        mission_id=mission_id,
        checklist_item_id=resolved_quest_id,
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
    # Turn delta (card #218, quest 11): ids + compact gate evidence + pending
    # count. ``gates_captured`` / ``gates_passed_so_far`` / ``overall`` /
    # ``context`` are kept verbatim so existing callers and tests keep working;
    # nothing verbose was ever in this payload, so the delta IS the mission-free
    # shape. Mission/checklist detail is opt-in through ``full``.
    payload = {
        "status": "started",
        "intento_id": intento_id,
        "mission_id": mission_id,
        "quest_id": resolved_quest_id or None,
        "gates_captured": len(gate_results),
        "gates_passed_so_far": gates_passed,
        "overall": overall,
        "gates": compact.compact_gates(gate_dicts),
        "pending_quests": _pending_quest_count(mission_id),
        "context": {
            "sender": context["sender"],
            "topic": context["topic"],
            "project": resolved_project,
        },
    }
    if full:
        payload.update(
            _turn_full_state(
                {
                    "session_id": session_id,
                    "project": resolved_project,
                    "mission_id": mission_id,
                }
            )
        )
    return json.dumps(payload, ensure_ascii=False, default=str)


def _complete_quest_for_intento(intento: dict) -> dict:
    """Flip the intento's quest to done in Deck, then refresh the replica (D6).

    Closes the intento's quest in Deck (``done=true``) and refreshes the local
    replica in the SAME operation. ``end_turn`` calls this ONLY when the turn's
    ``final_status`` is ``success``; an aborted, failed or partial turn leaves
    the quest open. Deck stays the source of truth, so the local replica is
    refreshed only after ``deck_bridge.complete_quest`` acknowledges the write
    (D1).

    The replica refresh is mission-scoped and never per-quest: the quest flag
    is set and the mission's checklist counters are recomputed from the replica
    rows.

    Returns a dict with the resolution honestly separated:

    * ``quest_id`` / ``done``: the quest and whether it is now closed.
    * ``deck_written``: True only after Deck acknowledged the write.
    * ``reason``: ``refreshed`` (both sides done), ``deck_write_failed`` /
      ``stack_unresolved`` / ``board_unresolved`` / ``not_found`` /
      ``lookup_failed`` / ``mission_mismatch`` / ``not_resolved`` (nothing was
      written to Deck), or ``replica_refresh_failed`` (Deck WAS written and the
      replica is now stale — a real failure of the operation).
    * ``refresh_error``: the replica failure detail, else ``None``.
    """
    result = {
        "quest_id": intento.get("checklist_item_id") or None,
        "done": False,
        "deck_written": False,
        "reason": "not_resolved",
        "refresh_error": None,
        "identity": None,
    }
    mission_id = intento.get("mission_id") or 0
    quest_id = intento.get("checklist_item_id") or 0
    if not (mission_id and quest_id):
        return result

    try:
        mission = persistence.get_mission(mission_id)
        quest = persistence.get_checklist_item_by_id(quest_id)
    except Exception as exc:
        logger.warning(
            "Quest closure lookup failed (intento=%s): %s", intento.get("id"), exc
        )
        result["reason"] = "lookup_failed"
        return result

    if not isinstance(mission, dict) or not isinstance(quest, dict):
        logger.warning(
            "Quest closure skipped: mission #%s or quest #%s not found",
            mission_id,
            quest_id,
        )
        result["reason"] = "not_found"
        return result

    # Membership parity (W2): revalidate here too. begin_turn rejects a crossed
    # quest, but the deprecated record_intento tool can still create an intento
    # whose checklist_item_id belongs to another mission. end_turn must NEVER
    # write the foreign card, so fail closed with zero effects.
    if quest.get("mission_id") != mission_id:
        logger.warning(
            "Quest closure skipped: quest #%s does not belong to mission #%s",
            quest_id,
            mission_id,
        )
        result["reason"] = "mission_mismatch"
        return result

    board_id, err = _resolve_board_id(mission.get("project", ""))
    if err:
        logger.warning("Quest closure skipped (board): %s", err)
        result["reason"] = "board_unresolved"
        return result

    # W-g parity: resolve the stack that ACTUALLY holds the card (fail closed),
    # never guess the pending/first stack. When the card cannot be located the
    # turn closes with quest_done=False and NO Deck write against a guessed stack.
    stack_id, _stack_title, err = _resolve_stack_for_card(board_id, mission)
    if err:
        logger.warning("Quest closure skipped (stack): %s", err)
        result["reason"] = "stack_unresolved"
        return result

    closure, err = deck_bridge.complete_quest_identity(
        board_id,
        stack_id,
        mission["deck_task_id"],
        quest_id=quest_id,
        item_index=quest["item_index"],
    )
    if closure is None:
        if err == deck_bridge.ERR_MARKER_NOT_FOUND:
            result["reason"] = "marker_not_found"
        elif err == deck_bridge.ERR_MARKER_DUPLICATE:
            result["reason"] = "identity_mismatch"
        else:
            result["reason"] = "deck_write_failed"
        logger.warning(
            "Quest closure: Deck write failed for quest #%s: %s", quest_id, err
        )
        return result

    # Deck acknowledged the write: from here on any local failure means the
    # replica is behind Deck and the operation failed even though Deck changed.
    result["deck_written"] = True
    result["identity"] = closure["identity"]
    try:
        if persistence.set_quest_done(quest_id, True) is False:
            raise RuntimeError("quest row not found in the replica")
        if persistence.refresh_mission_checklist_counts(mission_id) is False:
            raise RuntimeError("mission row not found in the replica")
    except Exception as exc:
        logger.warning(
            "Quest closure: replica refresh failed for quest #%s: %s", quest_id, exc
        )
        result["reason"] = "replica_refresh_failed"
        result["refresh_error"] = str(exc)
        return result

    result["done"] = True
    result["reason"] = "refreshed"
    return result


@app.tool()
def end_turn(
    intento_id: int,
    status: str = "success",
    quest_done: bool | None = None,
    full: bool = False,
) -> str:
    """End the current turn: validate gates, complete the intento, close the quest.

    This is the second (and final) call of the consolidated 2-call turn workflow:
      begin_turn → trabajo → end_turn

    The classical signature accepts only the intento_id — all definitional
    data (session_id, project) is resolved internally from the DB so the
    orchestrating agent never has to pass it.

    end_turn is the ONLY false→true quest transition path (design D6). It flips
    the intento's quest to ``done`` in Deck (``- [ ]`` → ``- [x]``) and refreshes
    the replica. The transition happens ONLY when ``final_status`` is
    ``success``: an aborted, failed or partial turn leaves the quest open so the
    dashboard can tell a completed quest from an abandoned turn.

    ``final_status`` derives from MANDATORY gates only (design D8): a
    non-mandatory gate that is not PASS/SKIP never forces a fail. When a
    mandatory gate does not pass, ``final_status`` is ``fail`` regardless of the
    requested ``status``; when all mandatory gates pass, ``final_status`` is the
    requested ``status``.

    end_turn NEVER blocks permanently. When gates do not pass, it completes
    the intento with final_status="fail" and real gate detail, then clears
    the active turn state — always leaving the system in a recoverable state.

    The response is COMPACT (design D4): gates carry only
    ``{name, state, mandatory}`` and no raw ``result_data``. It is also a TURN
    DELTA (card #218, quest 11): it never carries the mission payload, its
    description, or the full checklist, because those do not change with the
    turn and would be paid on every call.

    Args:
        intento_id: Numeric intento ID returned by begin_turn().
        status:     Terminal status for the turn. Accepts ``success``,
                    ``aborted``, ``failed`` or ``partial`` (case-insensitive).
                    An unrecognized value is rejected with zero mutation.
        quest_done: Explicit quest-closure intent. ``None`` (default) keeps the
                    original behaviour: the quest is consumed only when
                    ``final_status`` is ``success``. ``False`` never consumes the
                    quest, even on a successful turn — this closes an empty turn
                    without lying. ``True`` with a ``final_status`` other than
                    ``success`` is rejected with zero mutation: there is no path
                    to force a dishonest closure.
        full:       If True, also return the full mission row and its complete
                    checklist. Defaults to False (turn delta).

    Returns:
        JSON string with completion status, gates_passed count, compact gate
        detail, and the quest_id/quest_done that reflect what actually happened.
        ``quest_done_reason`` explains why the quest was (not) consumed:
        ``refreshed``, ``vetoed``, ``not_success``, ``deck_write_failed``, etc.
        When Deck accepted the closure but the replica refresh failed, the
        response is an explicit error (``code: replica_refresh_failed``,
        ``deck_written: true``) — never a clean closure over a stale replica.
    """
    global _active_intento

    # 0a. Validate quest_done's type BEFORE any mutation.
    if quest_done is not None and not isinstance(quest_done, bool):
        return json.dumps(
            {
                "status": "error",
                "code": "invalid_quest_done",
                "error": (
                    f"Invalid quest_done {quest_done!r}. Expected true, false or None."
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    # 0b. Validate the requested terminal status BEFORE any mutation. An unknown
    #    value must leave the intento, the quest and the active-turn state
    #    untouched (no completion, no Deck write).
    normalized_status = status.strip().lower() if isinstance(status, str) else ""
    if normalized_status not in ("success", "aborted", "failed", "partial"):
        return json.dumps(
            {
                "status": "error",
                "error": (
                    f"Invalid status {status!r}. Expected one of: "
                    "success, aborted, failed, partial."
                ),
            },
            ensure_ascii=False,
            default=str,
        )

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

    # 3. Final gate evidence comes from the intento's FRESH snapshot, captured in
    #    begin_turn. The session-scoped list_gate_states is latest-per-gate and
    #    can be STALE when begin_turn degraded, so it must not decide the verdict
    #    (W-f/W-g). No snapshot → fail closed.
    final_gates = _gates_from_intento_snapshot(intento)

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

    # 5. Contar gates passed + final_status por gates MANDATORY (D8)
    #    A non-mandatory gate that is not in {PASS, SKIP} MUST NOT force a fail.
    #    W-f: fail closed — with no persisted mandatory-gate evidence (empty or
    #    incomplete final_gates) the turn MUST NOT be reported as success.
    gates_passed = sum(1 for g in final_gates if g.get("state") in ("PASS", "SKIP"))
    mandatory_failed = [
        g
        for g in final_gates
        if g.get("mandatory") and g.get("state") not in ("PASS", "SKIP")
    ]
    has_mandatory_evidence = any(bool(g.get("mandatory")) for g in final_gates)
    if final_gates and has_mandatory_evidence and not mandatory_failed:
        # Gates pass: the caller's requested terminal status wins.
        final_status = normalized_status
    else:
        # A mandatory gate did not pass: the gates own the verdict.
        final_status = "fail"

    # 5c. quest_done=True with a non-success verdict is a validation error with
    #     zero mutation: an explicit closure must never override the gates, and
    #     nothing above this point has written anything.
    if quest_done is True and final_status != "success":
        return json.dumps(
            {
                "status": "error",
                "code": "invalid_quest_done",
                "error": (
                    f"Cannot mark the quest done with final_status "
                    f"{final_status!r}: only a successful turn closes the quest."
                ),
                "intento_id": intento_id,
                "final_status": final_status,
            },
            ensure_ascii=False,
            default=str,
        )

    # 5b. Quest closure (D6): only a genuinely successful turn consumes the
    #     quest, and an explicit quest_done=False vetoes the closure even on
    #     success. Aborted/failed/partial (and gate-fail) leave it open so the
    #     dashboard can distinguish "quest done" from "turn abandoned".
    if final_status == "success" and quest_done is not False:
        closure = _complete_quest_for_intento(intento)
    else:
        closure = {
            "quest_id": intento.get("checklist_item_id") or None,
            "done": False,
            "deck_written": False,
            "reason": (
                "vetoed"
                if final_status == "success" and quest_done is False
                else "not_success"
            ),
            "refresh_error": None,
            "identity": None,
        }

    quest_id_closed = closure["quest_id"]
    quest_is_done = closure["done"]

    # 6. Completar intento con detalle completo (NEVER blocks — always completes)
    #    v7 widens intentos.status to the honest terminal vocabulary, so the
    #    persisted state matches the verdict instead of collapsing aborted and
    #    partial into 'fail'. Only the legacy 'failed' spelling is normalised.
    persisted_status = "fail" if final_status == "failed" else final_status
    try:
        persistence.complete_intento_with_gates(
            intento_id=intento_id,
            status=persisted_status,
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

    response = {
        "status": "ok",
        "intento_id": intento_id,
        "final_status": final_status,
        "gates_passed": gates_passed,
        "gates_total": len(final_gates) if final_gates else 4,
        "gates": compact.compact_gates(final_gates),
        "quest_id": quest_id_closed,
        "quest_done": quest_is_done,
        "quest_done_reason": closure["reason"],
        "identity": closure.get("identity"),
        "deck_written": closure["deck_written"],
    }

    if full:
        response.update(_turn_full_state(intento))

    # Fail-closed (card #218, forum #1): when Deck WAS written but the replica
    # refresh failed, the turn cannot be reported as a clean closure. The
    # intento is still finalized above (never left running) and the response
    # says exactly what Deck holds and that the replica is behind.
    if closure["refresh_error"] is not None:
        response.update(
            {
                "status": "error",
                "code": "replica_refresh_failed",
                "quest_done": False,
                "replica_refresh_error": closure["refresh_error"],
                "replica_stale": True,
                "reconcile_with": f"sync_task({intento.get('mission_id')})",
                "error": (
                    "The quest was marked done in Deck, but the local replica "
                    f"could not be refreshed ({closure['refresh_error']}). The "
                    "turn is recorded, the replica is stale; run "
                    f"sync_task({intento.get('mission_id')}) to reconcile."
                ),
            }
        )
        return json.dumps(response, ensure_ascii=False, default=str)

    return json.dumps(
        response,
        ensure_ascii=False,
        default=str,
    )


@app.tool()
def abort_turn(intento_id: int, reason: str) -> str:
    """Abort an in-flight turn without touching the quest.

    Finalises a ``running`` intento with the honest ``aborted`` status, stores
    ``reason`` in the intento's existing ``summary`` column, and leaves the
    quest, the gates and the attempt budget untouched. This is the companion of
    ``end_turn(quest_done=False)`` for the interrupted case: an abandoned turn
    is recorded as abandoned instead of being reported as a failure.

    Only a ``running`` intento can be aborted. Any other state returns an
    explicit error naming the current status and mutates nothing.

    Args:
        intento_id: Numeric intento ID returned by begin_turn().
        reason:     Non-empty explanation of why the turn was aborted.

    Returns:
        JSON string with ``final_status``/``persisted_status`` = ``aborted``,
        the untouched ``quest_id`` with ``quest_done`` false, and the stored
        reason. Errors: ``invalid_reason``, ``intento_not_found`` or
        ``intento_not_running``.
    """
    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if not normalized_reason:
        return json.dumps(
            {
                "status": "error",
                "code": "invalid_reason",
                "error": "A non-empty reason is required to abort a turn.",
                "intento_id": intento_id,
            },
            ensure_ascii=False,
            default=str,
        )

    intento = persistence.get_intento(intento_id)
    if intento is None:
        return json.dumps(
            {
                "status": "error",
                "code": "intento_not_found",
                "error": f"Intento #{intento_id} not found in database.",
                "intento_id": intento_id,
            },
            ensure_ascii=False,
            default=str,
        )

    current_status = intento.get("status")
    if current_status != "running":
        return json.dumps(
            {
                "status": "error",
                "code": "intento_not_running",
                "error": (
                    f"Intento #{intento_id} is not running "
                    f"(current status: {current_status})."
                ),
                "intento_id": intento_id,
                "current_status": current_status,
            },
            ensure_ascii=False,
            default=str,
        )

    gates_passed = intento.get("gates_passed") or 0
    try:
        persistence.complete_intento_with_summary(
            intento_id=intento_id,
            status="aborted",
            gates_passed=gates_passed,
            summary=normalized_reason,
        )
    except Exception as exc:
        logger.error("Failed to abort intento #%d: %s", intento_id, exc)
        return json.dumps(
            {
                "status": "error",
                "code": "abort_failed",
                "error": f"Failed to persist the abort: {exc}",
                "intento_id": intento_id,
            },
            ensure_ascii=False,
            default=str,
        )

    # Only the server-side turn bookkeeping is cleared; the quest and gates are
    # deliberately untouched.
    active = _get_active_intento()
    if active is not None and active["intento_id"] == intento_id:
        _clear_active_intento()

    return json.dumps(
        {
            "status": "ok",
            "intento_id": intento_id,
            "final_status": "aborted",
            "persisted_status": "aborted",
            "gates_passed": gates_passed,
            "quest_id": intento.get("checklist_item_id") or None,
            "quest_done": False,
            "reason": normalized_reason,
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
    card_id: int | None = None,
    description: str = "",
    board_id: int | None = None,
    stack_id: int | None = None,
    mission_id: int | None = None,
) -> str:
    """Update only the description of a Deck card — NEVER changes the title.

    With an explicit ``card_id``/``board_id``/``stack_id`` this behaves exactly
    as before. When ``mission_id`` is supplied, the missing pieces are resolved
    from the replica: the board from the project map and the stack from the
    mission's replicated ``deck_stack_id``. A backfilled ``deck_stack_id``
    avoids the ``deck_get_stacks`` lookup entirely; when it is ``NULL`` the
    existing lookup fallback is used.

    Args:
        card_id: Numeric card ID (defaults to the mission's ``deck_task_id``).
        description: New description content (markdown).
        board_id: Numeric board ID (defaults to the mission's board).
        stack_id: Numeric stack ID (defaults to ``deck_stack_id``/lookup).
        mission_id: Optional local mission id used to resolve the Deck target.

    Returns:
        JSON string confirming update. When ``mission_id`` is supplied the
        mission's replica is refreshed from the acknowledged write, so a stale
        checklist can never survive the update; if that refresh fails the reply
        is an explicit error (``code: replica_refresh_failed``,
        ``deck_written: true``).
    """
    from .mcp_client import call_mcp_tool, TOOL_NAMES

    mission = None
    if mission_id is not None:
        mission = persistence.get_mission(mission_id)
        if not mission:
            return json.dumps(
                {"error": f"Mission {mission_id} not found"},
                ensure_ascii=False,
                default=str,
            )
        if board_id is None:
            board_id, err = _resolve_board_id(mission.get("project", ""))
            if err:
                return json.dumps({"error": err}, ensure_ascii=False, default=str)
        if stack_id is None:
            stack_id, err = _resolve_stack_id(board_id, mission)
            if err:
                return json.dumps(
                    {"error": f"Cannot resolve Deck stack: {err}"},
                    ensure_ascii=False,
                    default=str,
                )
        if card_id is None:
            card_id = mission.get("deck_task_id")

    if card_id is None or board_id is None or stack_id is None:
        return json.dumps(
            {
                "error": (
                    "card_id, board_id and stack_id are required unless a "
                    "mission_id resolves them"
                )
            },
            ensure_ascii=False,
            default=str,
        )

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

    # Update only description — title explicitly preserved. The incoming prose
    # is sanitized first: a raw "- [x]" line would otherwise be persisted by a
    # later sync as done WITHOUT going through end_turn (D6 invariant).
    cleaned_description = deck_bridge.clean_prose(description)
    result, update_err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_update_card"],
        {
            "board_id": board_id,
            "card_id": card_id,
            "stack_id": stack_id,
            "title": current_title,
            "description": cleaned_description,
        },
        timeout=8.0,
    )
    if result is None:
        return json.dumps(
            {"error": f"Failed to update card: {update_err}", "deck_written": False}
        )

    response = {
        "status": "ok",
        "card_id": card_id,
        "title_preserved": current_title,
    }

    # The Deck write already happened: refresh THIS mission's replica from the
    # acknowledged description so it can never keep a checklist Deck no longer
    # has (or a stale prose). Only an explicitly resolved mission is refreshed;
    # a raw card id carries no mission to refresh.
    if mission is not None:
        response["mission_id"] = mission_id
        payload = {
            "title": current_title,
            "description": cleaned_description,
            "quests": deck_bridge.extract_quests(cleaned_description),
        }
        _replica_id, _quest_ids, refresh_error = _refresh_mission_replica_from_card(
            mission, payload, mission.get("status", "pendiente")
        )
        if refresh_error is not None:
            return _deck_write_refresh_failure(
                deck_written_what=(
                    f"Deck card {card_id} description updated"
                ),
                mission_id=mission_id,
                refresh_error=refresh_error,
                extra={"mission_id": mission_id},
            )

    return json.dumps(
        response,
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

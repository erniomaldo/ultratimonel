"""
server.py - FastMCP server with tools for gates, dashboard, and project maps.

Tools:
  - assert_gates(message, session_id)  -> run all gates, return status
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
# ── Tool handlers ───────────────────────────────────────────────────────


@app.tool()
def assert_gates(
    message: str,
    session_id: str,
    sender: str = "user",
) -> str:
    """Run all pre-flight gates and return structured results.

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
    gates_passed = sum(
        1 for r in gate_results if r.state in (PASS, SKIP)
    )
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
        return json.dumps({
            "error": f"Gate '{name}' not found",
            "valid_gates": list(GATE_CONFIG_MAP.keys()),
        })

    try:
        # We need the project — try from latest session
        session = persistence.get_session(session_id)
        project = session["project"] if session else "unknown"

        state = persistence.get_gate_state(session_id, project, name)
        if state is None:
            return json.dumps({
                "name": name,
                "state": "PENDING",
                "mandatory": GATE_CONFIG_MAP[name].mandatory,
                "message": "Gate has not been run yet in this session",
                "updated_at": "",
            })

        return json.dumps({
            "name": state["gate_name"],
            "state": state["state"],
            "mandatory": bool(state["mandatory"]),
            "message": state.get("message", ""),
            "updated_at": state.get("updated_at", ""),
        })
    except Exception as exc:
        logger.exception("check_gate failed")
        return json.dumps({
            "error": f"Failed to check gate: {exc}",
        })


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
        return json.dumps({
            "error": f"Gate '{name}' not found",
            "valid_gates": list(GATE_CONFIG_MAP.keys()),
        })

    try:
        session = persistence.get_session(session_id)
        project = session["project"] if session else "unknown"

        current = persistence.get_gate_state(session_id, project, name)
        current_state = current["state"] if current else BLOCK
        now = datetime.now(timezone.utc).isoformat()

        if current_state not in (BLOCK, WARN):
            return json.dumps({
                "name": name,
                "state": current_state,
                "message": f"Gate '{name}' is already {current_state} — no change needed",
                "updated_at": now,
            })

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

        return json.dumps({
            "name": name,
            "state": PASS,
            "message": f"Gate '{name}' transitioned {current_state} → PASS",
            "updated_at": now,
        })

    except Exception as exc:
        logger.exception("complete_gate failed")
        return json.dumps({
            "error": f"Failed to complete gate: {exc}",
        })


# ── Dashboard server tool ──────────────────────────────────────────────────


@app.tool()
def server(action: str) -> str:
    """Control the Ultratimonel Dashboard web server.

    Manages a subprocess running the FastAPI/stdio dashboard GUI.
    The dashboard reads from the same SQLite DB as the gates.

    Args:
        action: One of "status", "start", "stop", "restart".

    Returns:
        JSON string with port, pid, url, and running status.
    """
    global _dashboard_proc, _dashboard_port

    action = action.strip().lower()
    script = _dashboard_script()

    def _status_dict(running: bool, pid: int | None = None) -> dict:
        return {
            "action": action,
            "running": running,
            "port": _dashboard_port,
            "pid": pid or (_dashboard_proc.pid if _dashboard_proc and _dashboard_proc.poll() is None else None),
            "url": f"http://localhost:{_dashboard_port}",
            "script": script,
        }

    # ── status ───────────────────────────────────────────────────────
    if action == "status":
        if _dashboard_proc is None:
            return json.dumps(_status_dict(False))
        ret = _dashboard_proc.poll()
        if ret is not None:
            _dashboard_proc = None
            return json.dumps({**_status_dict(False), "exit_code": ret})
        return json.dumps(_status_dict(True))

    # ── stop ─────────────────────────────────────────────────────────
    if action == "stop":
        if _dashboard_proc is None:
            return json.dumps({**_status_dict(False), "message": "Dashboard not running"})
        ret = _dashboard_proc.poll()
        if ret is not None:
            _dashboard_proc = None
            return json.dumps({**_status_dict(False), "message": "Dashboard was already stopped", "exit_code": ret})
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
            return json.dumps({**_status_dict(True), "message": "Dashboard already running"})

        if script is None:
            return json.dumps({
                "error": "dashboard_server.py not found",
                "hint": "Expected at ultratimonel/dashboard_server.py",
            })

        # Find a free port
        _dashboard_port = _find_free_port(DASHBOARD_PORT)

        # Determine which python to use
        python = sys.executable

        try:
            _dashboard_proc = subprocess.Popen(
                [python, script, str(_dashboard_port)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "ULTRATIMONEL_DB_PATH": db_path},
            )
        except FileNotFoundError:
            return json.dumps({"error": f"Python not found: {python}"})
        except Exception as exc:
            return json.dumps({"error": f"Failed to start dashboard: {exc}"})

        # Brief wait to catch immediate crashes
        import time
        time.sleep(0.5)
        ret = _dashboard_proc.poll()
        if ret is not None:
            stderr = _dashboard_proc.stderr.read().decode(errors="replace") if _dashboard_proc.stderr else ""
            _dashboard_proc = None
            return json.dumps({
                "error": f"Dashboard exited immediately (code {ret})",
                "stderr": stderr[:500],
            })

        return json.dumps({
            **_status_dict(True),
            "message": f"Dashboard started on http://localhost:{_dashboard_port}",
        })

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

        # Then start
        _dashboard_port = _find_free_port(DASHBOARD_PORT)
        python = sys.executable

        try:
            _dashboard_proc = subprocess.Popen(
                [python, script, str(_dashboard_port)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "ULTRATIMONEL_DB_PATH": db_path},
            )
        except Exception as exc:
            return json.dumps({"error": f"Restart failed: {exc}"})

        import time
        time.sleep(0.5)
        ret = _dashboard_proc.poll()
        if ret is not None:
            _dashboard_proc = None
            return json.dumps({"error": f"Restart failed (exit code {ret})"})

        return json.dumps({
            **_status_dict(True),
            "message": f"Dashboard restarted on http://localhost:{_dashboard_port}",
        })

    # ── unknown action ───────────────────────────────────────────────
    return json.dumps({
        "error": f"Unknown action: '{action}'",
        "valid_actions": ["status", "start", "stop", "restart"],
    })


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

    return json.dumps({
        "status": "ok",
        "project": project,
        "path": maps_path,
        "total_projects": len(maps),
    }, ensure_ascii=False)


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
        return json.dumps({
            "error": f"Project '{project}' not found",
            "known_projects": list(maps.keys()),
        })

    del maps[project]
    save_project_maps(maps, maps_path)
    reload_project_maps(maps_path)

    return json.dumps({
        "status": "ok",
        "removed": project,
        "path": maps_path,
        "total_projects": len(maps),
    }, ensure_ascii=False)


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
        board_list = boards_data if isinstance(boards_data, list) else boards_data.get("boards", boards_data.get("result", []))
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
        coll_list = coll_data if isinstance(coll_data, list) else coll_data.get("collectives", coll_data.get("result", []))
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
        return json.dumps({"status": "ok", "message": "No projects mapped", "stale": []})

    boards_data, boards_err = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["deck_get_boards"],
        {},
        timeout=8.0,
    )

    if boards_data is None:
        return json.dumps({"error": f"Cannot reach Nextcloud Deck: {boards_err}"})

    board_list = boards_data if isinstance(boards_data, list) else boards_data.get("boards", boards_data.get("result", []))
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

    return json.dumps({
        "status": "ok",
        "total_projects": len(maps),
        "healthy": healthy,
        "stale": stale,
        "total_stale": len(stale),
    }, ensure_ascii=False, default=str)


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

    stacks = stacks_data if isinstance(stacks_data, list) else stacks_data.get("stacks", stacks_data.get("result", []))

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
                    {"board_id": board_id, "stack_id": stack.get("id"), "card_id": card_id},
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
                        checklist_done = sum(1 for it in items_data if it.get("status") == "done" or it.get("checked"))
                        for idx, item in enumerate(items_data):
                            checklist_items_data.append({
                                "index": idx,
                                "text": item.get("description", item.get("text", f"Item {idx+1}")),
                                "done": 1 if item.get("status") == "done" or item.get("checked") else 0,
                            })

                # No checklist items from Deck API? Parse description for markdown checkboxes
                if checklist_total == 0 and description:
                    lines = description.strip().split("\n")
                    for line in lines:
                        line = line.strip()
                        # Match - [ ] or - [x] style checkboxes
                        if line.startswith("- [") or line.startswith("* ["):
                            done = 1 if ("[x]" in line or "[X]" in line) else 0
                            text = line.split("]", 1)[1].strip() if "]" in line else line
                            checklist_items_data.append({
                                "index": checklist_total,
                                "text": text,
                                "done": done,
                            })
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

    return json.dumps({
        "project": project,
        "board_id": board_id,
        "synced": created,
        "errors": errors,
        "total_errors": len(errors),
    }, ensure_ascii=False, default=str)


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

    return json.dumps({
        "status": "ok",
        "projects_synced": len(results),
        "total_synced": total_synced,
        "total_errors": total_errors,
        "details": results,
    }, ensure_ascii=False, default=str)


@app.tool()
def mission_list(project: str) -> str:
    """List missions (Deck tasks) for a project.

    Args:
        project: Project slug.

    Returns:
        JSON with missions list, each including checklist items and
        latest intento status per item.
    """
    missions = persistence.list_missions(project)
    return json.dumps({
        "project": project,
        "missions": missions,
        "total": len(missions),
    }, ensure_ascii=False, default=str)

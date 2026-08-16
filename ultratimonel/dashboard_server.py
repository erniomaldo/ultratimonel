"""dashboard_server.py — Ultratimonel Dashboard (stdlib-only, zero deps).

Serves the NES-style mission viewer GUI using Python's built-in http.server.
Reads directly from the same SQLite DB as the MCP server.

Static root resolution (see ``resolve_static_root``):
  - Main port 3005 serves the Astro build output ``dashboard-astro/dist/``
    (final cut, ADR-5). The legacy ``dashboard/`` files leave the served tree.
  - ``ULTRATIMONEL_DASHBOARD_STATIC_ROOT`` overrides the root (staging, e.g.
    build validation on 3007, or a cut test on any other port).
  - Any other port without the env var serves the legacy ``dashboard/``.

Hierarchical routes (Ejecución 8, card #154 — approved 2026-08-15): the URL
path IS the hierarchy. New route structure (replaces the flat
``/proyectos/{project}/``, ``/misiones/{id}/``, ``/intentos/{id}/`` schema):

  /{proyectoName}/                          → missions of a project
  /{proyectoName}/{misionId}/               → mission detail + checklist items
  /{proyectoName}/{misionId}/{checklistItemId}/ → intentos of a checklist item
  /{proyectoName}/{misionId}/{checklistItemId}/{intentoId}/ → intento detail
    + gate logs (Ejecución 9: el nivel faltante de la propuesta original —
    el detalle del intento es una PÁGINA con URL propia, ya no un dialog).

Legacy routes get permanent redirects (301) to their equivalent new route:
  /proyectos/{project}   → /{project}/
  /misiones/{id}         → /{project}/{id}/          (project resolved from DB)
  /intentos/{id}         → /{project}/{mission}/{checklist_item}/{id}/  (DB)
If the entity cannot be resolved, the legacy route answers 404.

Post-build detail fallback (card #154, adapted to hierarchical routes): the
Astro build is static (``output: 'static'``, ADR-2) and ``getStaticPaths`` only
enumerates ids that exist at build time. Entities created after the build have
no shell in ``dist/``. For each hierarchical level whose shell is missing, this
server serves the generic fallback shell for that level
(``fallback/proyecto/index.html`` / ``fallback/mision/index.html`` /
``fallback/item/index.html`` / ``fallback/intento/index.html``) ONLY when the
entity exists (the same check the API performs, including project/mission/
item consistency). Unknown entities keep a real 404 (S8). The fallback shells
hydrate an island that resolves the path segments from
``window.location.pathname`` at runtime, so one file serves any entity of
that level.

Hierarchy flow:
  /api/projects                        → project list
  /api/projects/{project}/missions      → Deck-synced missions
  /api/missions/{id}                    → mission detail + checklist items
  /api/checklist/{item_id}/intentos     → intentos for a checklist item
  /api/intentos/{id}                   → intento detail + per-gate states
  /api/intentos/{id}/gate/{name}/logs   → gate transition log timeline

Endpoints:
  GET  /                  → index.html (SPA, from the configured static root)
  GET  /api/projects      → list of active projects (from project_maps.json + mission counts)
  GET  /api/projects/{project}/missions → missions (Deck tasks) for a project
  GET  /api/missions/{id} → mission detail with checklist items
  GET  /api/checklist/{item_id}/intentos → intentos for a checklist item
  GET  /api/intentos/{id} → intento detail with gates
  GET  /api/intentos/{id}/gate/{name}/logs → gate transition timeline
  GET  /static/*          → static files (JS, CSS images)
"""

import json
import logging
import os
import socket
import sqlite3
import socketserver
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

# ── Logging a archivo persistente + stderr (deferred init) ──
_LOG_DIR: Path | None = None
_LOG_FILE: str | None = None


def _resolve_log_dir() -> Path:
    """Return the log directory, creating it if needed."""
    global _LOG_DIR
    if _LOG_DIR is None:
        _LOG_DIR = Path(os.environ.get(
            "ULTRATIMONEL_LOG_DIR",
            str(Path.home() / ".hermes" / "logs"),
        ))
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def init_logging() -> None:
    """Initialize persistent logging (call once at startup).

    Writes to both a file (~/.hermes/logs/dashboard.log) and stderr.
    Defers LOG_DIR creation until first call so import-time side-effects
    are avoided.
    """
    global _LOG_FILE
    log_dir = _resolve_log_dir()
    _LOG_FILE = str(log_dir / "dashboard.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] dashboard: %(message)s",
        handlers=[
            logging.FileHandler(_LOG_FILE),
            logging.StreamHandler(sys.stderr),
        ],
    )
    logger = logging.getLogger("dashboard")
    logger.info("Dashboard log file: %s", _LOG_FILE)


logger = logging.getLogger("dashboard")

HERE = Path(__file__).parent.resolve()
DASHBOARD_DIR = HERE / "dashboard"
ASTRO_DIST_DIR = HERE / "dashboard-astro" / "dist"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3005

# Static root resolved per port in create_server(); set to the legacy dir
# until a server is created (safety default for imports/tests).
STATIC_ROOT: Path = DASHBOARD_DIR


def resolve_static_root(port: int) -> Path:
    """Resolve the static root for a server bound to ``port``.

    Resolution order (first match wins):
    1. ``ULTRATIMONEL_DASHBOARD_STATIC_ROOT`` env var — explicit override
       (used for staging/validation, e.g. 3007 build validation).
    2. Main port (``DEFAULT_PORT``, 3005) → Astro build output
       ``dashboard-astro/dist/`` — the final cut (ADR-5): the production
       port serves the build. The legacy files leave the served tree.
    3. Any other port → legacy ``dashboard/`` — keeps staging/test servers
       on the legacy tree unless the env override says otherwise.
    """
    env_root = os.environ.get("ULTRATIMONEL_DASHBOARD_STATIC_ROOT")
    if env_root:
        return Path(env_root)
    if port == DEFAULT_PORT:
        return ASTRO_DIST_DIR
    return DASHBOARD_DIR

# DB path — same env var as the MCP server uses
DB_PATH = os.environ.get(
    "ULTRATIMONEL_DB_PATH",
    os.path.expanduser("~/.hermes/ultratimonel.db"),
)

# Path to project_maps.json — same resolution as config_loader.py
PROJECT_MAPS_PATH = os.environ.get(
    "ULTRATIMONEL_PROJECT_MAPS",
    os.path.expanduser("~/.hermes/ultratimonel/project_maps.json"),
)

# Dashboard host — default to localhost only for security
DASHBOARD_HOST = os.environ.get(
    "ULTRATIMONEL_DASHBOARD_HOST",
    DEFAULT_HOST,
)

class DashboardHandler(SimpleHTTPRequestHandler):
    """Custom request handler with API + static file serving."""

    # ── helpers ───────────────────────────────────────────────────────

    def _db(self) -> sqlite3.Connection:
        """Open a SQLite connection with a 5-second lock timeout.

        The timeout prevents indefinite blocking when another process holds
        a write lock on the dashboard database. If the timeout expires,
        sqlite3.OperationalError is raised and the server continues running.
        """
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, content, status=200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self, msg="Not found"):
        self._json({"error": msg}, 404)

    def _db_available(self):
        return os.path.isfile(DB_PATH)

    def _load_project_maps(self):
        """Load project_maps.json and return dict."""
        if not os.path.isfile(PROJECT_MAPS_PATH):
            return {}
        try:
            with open(PROJECT_MAPS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    # ── routing ───────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        try:
            if path.startswith("/api/"):
                self._handle_api(path)
            elif path == "" or path == "/":
                self._serve_index()
            else:
                # Legacy routes → permanent redirect (301) to the new
                # hierarchical structure (Ejecución 8). Unresolvable entities
                # answer 404 instead.
                redirect = self._match_legacy_redirect(path)
                if redirect == "LEGACY_UNRESOLVED":
                    return self._html("<h1>Not found</h1>", 404)
                if redirect:
                    return self._redirect(redirect, path)

                # Post-build fallback: hierarchical routes whose static shell
                # was not enumerated at build time get the generic fallback
                # shell for that level when the entity exists.
                route = self._match_hierarchical_route(path)
                if route and not self._hierarchical_shell_exists(*route):
                    return self._serve_hierarchical_fallback(*route)
                super().do_GET()
        except Exception as exc:
            logger.exception("Request failed: %s", path)
            self._json({"error": str(exc)}, 500)

    def _handle_api(self, path: str):
        parts = [p for p in path.split("/") if p]  # ['api', 'projects', ...]

        # /api/projects
        if len(parts) == 2 and parts[1] == "projects":
            return self._api_projects()

        # /api/projects/{project}/missions
        elif len(parts) == 4 and parts[1] == "projects" and parts[3] == "missions":
            return self._api_project_missions(parts[2])

        # /api/missions/{id}
        elif len(parts) == 3 and parts[1] == "missions":
            return self._api_mission_detail(parts[2])

        # /api/checklist/{item_id}/intentos
        elif len(parts) == 4 and parts[1] == "checklist" and parts[3] == "intentos":
            return self._api_checklist_intentos(parts[2])

        # /api/intentos/{id}
        elif len(parts) == 3 and parts[1] == "intentos":
            return self._api_intento_detail(parts[2])

        # /api/intentos/{id}/gate/{name}/logs
        elif len(parts) == 6 and parts[1] == "intentos" and parts[3] == "gate" and parts[5] == "logs":
            return self._api_intento_gate_logs(parts[2], parts[4])

        else:
            self._not_found(f"Unknown API path: {path}")

    # ── hierarchical routes: legacy redirects + post-build fallback (Ejecución 8) ──

    def _redirect(self, location: str, original_path: str) -> None:
        """Answer 301 with a Location header pointing at the new route."""
        body = (
            f"<html><head><title>301 Moved Permanently</title></head>"
            f"<body><h1>301 Moved Permanently</h1>"
            f"<p><a href=\"{location}\">{location}</a></p></body></html>"
        ).encode("utf-8")
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        logger.info("301 %s → %s", original_path, location)

    def _match_legacy_redirect(self, path: str):
        """Return the new-route Location for legacy URLs, or None when the
        path is not a legacy route.

        - ``/proyectos/{project}`` → ``/{project}/`` (direct mapping).
        - ``/misiones/{id}`` → ``/{project}/{id}/`` — project resolved from DB.
        - ``/intentos/{id}`` → ``/{project}/{mission}/{checklist_item}/{id}/`` — DB.

        When the entity cannot be resolved (unknown id / no project), this
        returns a marker ``(None)`` via ``_legacy_unresolved`` semantics:
        the caller distinguishes "not a legacy route" (no redirect, fall
        through) from "legacy route but unknown entity" (404).
        """
        parts = [p for p in path.split("/") if p]

        # /proyectos/{project} → /{project}/
        if len(parts) == 2 and parts[0] == "proyectos":
            return f"/{unquote(parts[1])}/"

        # /misiones/{id} → /{project}/{id}/
        if len(parts) == 2 and parts[0] == "misiones" and parts[1].isdigit():
            project = self._mission_project(parts[1])
            if project is None:
                return "LEGACY_UNRESOLVED"
            return f"/{project}/{parts[1]}/"

        # /intentos/{id} → /{project}/{mission}/{checklist_item}/{id}/
        if len(parts) == 2 and parts[0] == "intentos" and parts[1].isdigit():
            location = self._intento_location(parts[1])
            if location is None:
                return "LEGACY_UNRESOLVED"
            return location

        return None

    def _mission_project(self, mission_id: str):
        """Resolve the project slug for a mission, or None."""
        if not self._db_available():
            return None
        conn = self._db()
        try:
            row = conn.execute(
                "SELECT project FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        conn.close()
        return row["project"] if row and row["project"] else None

    def _intento_location(self, intento_id: str):
        """Resolve the new hierarchical route for an intento, or None."""
        if not self._db_available():
            return None
        conn = self._db()
        try:
            row = conn.execute(
                """SELECT i.project AS intento_project, i.mission_id,
                          i.checklist_item_id, m.project AS mission_project
                   FROM intentos i
                   LEFT JOIN missions m ON m.id = i.mission_id
                   WHERE i.id = ?""",
                (intento_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        conn.close()
        if not row:
            return None
        project = row["intento_project"] or row["mission_project"]
        mission_id = row["mission_id"]
        item_id = row["checklist_item_id"]
        if not project or mission_id is None or item_id is None:
            return None
        return f"/{project}/{mission_id}/{item_id}/{intento_id}/"

    def _match_hierarchical_route(self, path: str):
        """Return ``(level, *segments)`` for hierarchical routes, else None.

        Levels (with or without a trailing slash; the caller strips it):
          ``/{proyectoName}``                        → ("proyecto", slug)
          ``/{proyectoName}/{misionId}``             → ("mision", slug, id)
          ``/{proyectoName}/{misionId}/{checklistItemId}`` → ("item", slug, id, id)
          ``/{proyectoName}/{misionId}/{checklistItemId}/{intentoId}``
                                                      → ("intento", slug, id, id, id)

        Only numeric ids count for the mission/item/intento levels — anything
        else falls through to regular static serving (S8: nonsense ids end in
        a real 404).
        """
        parts = [p for p in path.split("/") if p]
        if len(parts) == 1 and "." not in parts[0] and parts[0] not in ("static",):
            return ("proyecto", unquote(parts[0]))
        if len(parts) == 2 and parts[1].isdigit():
            return ("mision", unquote(parts[0]), parts[1])
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            return ("item", unquote(parts[0]), parts[1], parts[2])
        if (
            len(parts) == 4
            and parts[1].isdigit()
            and parts[2].isdigit()
            and parts[3].isdigit()
        ):
            return ("intento", unquote(parts[0]), parts[1], parts[2], parts[3])
        return None

    def _hierarchical_shell_exists(self, level: str, *segments: str) -> bool:
        """True when the build enumerated a static shell for this route."""
        target = STATIC_ROOT.joinpath(*segments) / "index.html"
        return target.exists() and target.is_file()

    def _entity_exists_hierarchical(self, level: str, *segments: str) -> bool:
        """True when the entity exists and matches the URL hierarchy (same
        checks the API performs). Guards the fallback: it only applies when the
        API would resolve the route. Unknown entities keep a real 404 (S8).

        - proyecto: the project slug exists (project_maps.json or missions.project).
        - mision: the mission exists AND its project matches the URL segment.
        - item: the checklist item exists AND its mission + project match.
        - intento: the intento exists AND its mission + checklist item +
          project match the URL segments (Ejecución 9).
        """
        if level == "proyecto":
            slug = segments[0]
            if slug in self._load_project_maps():
                return True
            if not self._db_available():
                return False
            conn = self._db()
            try:
                row = conn.execute(
                    "SELECT 1 FROM missions WHERE project = ? LIMIT 1", (slug,)
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
            conn.close()
            return row is not None

        if level == "mision":
            if len(segments) != 2 or not self._db_available():
                return False
            conn = self._db()
            try:
                row = conn.execute(
                    "SELECT 1 FROM missions WHERE id = ? AND project = ?",
                    (segments[1], segments[0]),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
            conn.close()
            return row is not None

        if level == "item":
            if len(segments) != 3 or not self._db_available():
                return False
            conn = self._db()
            try:
                row = conn.execute(
                    """SELECT 1 FROM checklist_items ci
                       JOIN missions m ON m.id = ci.mission_id
                       WHERE ci.id = ? AND ci.mission_id = ? AND m.project = ?""",
                    (segments[2], segments[1], segments[0]),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
            conn.close()
            return row is not None

        if level == "intento":
            if len(segments) != 4 or not self._db_available():
                return False
            conn = self._db()
            try:
                row = conn.execute(
                    """SELECT 1 FROM intentos i
                       JOIN missions m ON m.id = i.mission_id
                       WHERE i.id = ?
                         AND i.mission_id = ?
                         AND i.checklist_item_id = ?
                         AND m.project = ?""",
                    (segments[3], segments[1], segments[2], segments[0]),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
            conn.close()
            return row is not None

        return False

    def _serve_hierarchical_fallback(self, level: str, *segments: str) -> None:
        """Serve the generic fallback shell for a level when the entity exists,
        else 404."""
        if self._entity_exists_hierarchical(level, *segments):
            fallback = STATIC_ROOT / "fallback" / level / "index.html"
            if fallback.exists() and fallback.is_file():
                content = fallback.read_text(encoding="utf-8")
                return self._html(content)
        self._html("<h1>Not found</h1>", 404)

    # ── API handlers ───────────────────────────────────────────────────

    def _api_projects(self):
        """List projects from project_maps.json with mission counts from DB."""
        maps = self._load_project_maps()
        projects = []

        if not self._db_available():
            # No DB yet — return projects with 0 counts
            for slug, cfg in maps.items():
                projects.append({
                    "project": slug,
                    "mission_count": 0,
                    "completed_count": 0,
                    "has_board": bool(cfg.get("deck_board_id")),
                })
            return self._json({"projects": projects, "total": len(projects)})

        conn = self._db()

        # Get mission counts per project from the NEW missions table
        try:
            rows = conn.execute("""
                SELECT project,
                       COUNT(*) as mission_count,
                       SUM(CASE WHEN status = 'completada' THEN 1 ELSE 0 END) as completed_count,
                       MAX(created_at) as last_activity
                FROM missions
                GROUP BY project
                ORDER BY last_activity DESC
            """).fetchall()
            db_counts = {r["project"]: dict(r) for r in rows}
        except sqlite3.OperationalError:
            db_counts = {}
        conn.close()

        for slug, cfg in maps.items():
            counts = db_counts.get(slug, {})
            projects.append({
                "project": slug,
                "mission_count": counts.get("mission_count") or 0,
                "completed_count": counts.get("completed_count") or 0,
                "has_board": bool(cfg.get("deck_board_id")),
                "last_activity": counts.get("last_activity") or None,
            })

        # Sort: projects with missions first, then by name
        projects.sort(key=lambda p: (-p["mission_count"], p["project"]))

        return self._json({"projects": projects, "total": len(projects)})

    def _api_project_missions(self, project: str):
        """List Deck-synced missions for a project."""
        project = unquote(project)

        if not self._db_available():
            return self._json({"missions": [], "total": 0})

        conn = self._db()
        try:
            rows = conn.execute("""
                SELECT id, deck_task_id, project, title, description,
                       status, checklist_total, checklist_done, last_sync, created_at
                FROM missions
                WHERE project = ?
                ORDER BY created_at DESC
            """, (project,)).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return self._json({"missions": [], "total": 0})

        missions = []
        for r in rows:
            d = dict(r)

            # Get checklist items for this mission
            items = conn.execute("""
                SELECT id, mission_id, item_index, text, done
                FROM checklist_items
                WHERE mission_id = ?
                ORDER BY item_index
            """, (d["id"],)).fetchall()
            d["checklist_items"] = [dict(it) for it in items]

            # Get latest intento status for each checklist item
            for item in d["checklist_items"]:
                intento = conn.execute("""
                    SELECT id, status, gates_passed, gates_total, started_at, completed_at
                    FROM intentos
                    WHERE checklist_item_id = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                """, (item["id"],)).fetchone()
                item["latest_intento"] = dict(intento) if intento else None

            missions.append(d)

        conn.close()
        return self._json({"project": project, "missions": missions, "total": len(missions)})

    def _api_mission_detail(self, mission_id: str):
        """Get mission detail with checklist items and intentos per item."""
        if not self._db_available():
            return self._json({"error": "No database yet"})

        conn = self._db()
        try:
            mission = conn.execute(
                "SELECT * FROM missions WHERE id = ?",
                (mission_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            conn.close()
            return self._not_found(f"Mission {mission_id} not found")

        if not mission:
            conn.close()
            return self._not_found(f"Mission {mission_id} not found")

        result = dict(mission)

        # Checklist items
        items = conn.execute("""
            SELECT id, mission_id, item_index, text, done
            FROM checklist_items
            WHERE mission_id = ?
            ORDER BY item_index
        """, (result["id"],)).fetchall()

        checklist = []
        for item in items:
            item_dict = dict(item)
            # Intentos for this item
            intentos = conn.execute("""
                SELECT id, session_id, status, gates_passed, gates_total,
                       started_at, completed_at
                FROM intentos
                WHERE checklist_item_id = ?
                ORDER BY started_at DESC
                LIMIT 20
            """, (item_dict["id"],)).fetchall()
            item_dict["intentos"] = [dict(it) for it in intentos]
            checklist.append(item_dict)

        result["checklist"] = checklist

        conn.close()
        return self._json({"mission": result})

    def _api_checklist_intentos(self, item_id: str):
        """List intentos for a specific checklist item."""
        if not self._db_available():
            return self._json({"intentos": []})

        conn = self._db()
        try:
            intentos = conn.execute("""
                SELECT id, session_id, project, mission_id, checklist_item_id,
                       status, gates_passed, gates_total, started_at, completed_at
                FROM intentos
                WHERE checklist_item_id = ?
                ORDER BY started_at DESC
                LIMIT 50
            """, (item_id,)).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return self._json({"intentos": []})

        conn.close()
        return self._json({
            "checklist_item_id": int(item_id),
            "intentos": [dict(r) for r in intentos],
            "total": len(intentos),
        })

    def _api_intento_detail(self, intento_id: str):
        """Get intento detail with gate states (actions per gate)."""
        if not self._db_available():
            return self._json({"error": "No database yet"})

        conn = self._db()
        try:
            intento = conn.execute(
                "SELECT * FROM intentos WHERE id = ?",
                (intento_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            conn.close()
            return self._not_found(f"Intento {intento_id} not found")

        if not intento:
            conn.close()
            return self._not_found(f"Intento {intento_id} not found")

        result = dict(intento)

        # Gates (actions) for this intento's session
        gates = conn.execute("""
            SELECT gate_name, state, mandatory, duration_ms, message,
                   result_data, updated_at
            FROM gate_state
            WHERE session_id = ? AND project = ?
            ORDER BY gate_name
        """, (result["session_id"], result["project"])).fetchall()
        result["gates"] = [dict(g) for g in gates]

        # Mission info
        mission = conn.execute(
            "SELECT id, title, project FROM missions WHERE id = ?",
            (result["mission_id"],),
        ).fetchone()
        result["mission"] = dict(mission) if mission else None

        # Checklist item info
        item = conn.execute(
            "SELECT id, item_index, text FROM checklist_items WHERE id = ?",
            (result["checklist_item_id"],),
        ).fetchone()
        result["checklist_item"] = dict(item) if item else None

        conn.close()
        return self._json({"intento": result})

    def _api_intento_gate_logs(self, intento_id: str, gate_name: str):
        """Get the transition log timeline for a specific gate in an intento."""
        if not self._db_available():
            return self._json({"logs": []})

        conn = self._db()
        try:
            intento = conn.execute(
                "SELECT session_id, project FROM intentos WHERE id = ?",
                (intento_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            conn.close()
            return self._json({"logs": []})

        if not intento:
            conn.close()
            return self._json({"logs": []})

        rows = conn.execute("""
            SELECT id, gate_name, from_state, to_state, reason, created_at
            FROM gate_logs
            WHERE session_id = ? AND gate_name = ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (intento["session_id"], gate_name)).fetchall()
        conn.close()

        return self._json({
            "intento_id": int(intento_id),
            "gate_name": gate_name,
            "logs": [dict(r) for r in rows],
        })

    # ── SPA entry ─────────────────────────────────────────────────────

    def _serve_index(self):
        index_path = STATIC_ROOT / "index.html"
        if not index_path.exists():
            return self._html("<h1>Dashboard UI not found</h1>", 404)
        content = index_path.read_text(encoding="utf-8")
        self._html(content)

    # ── static file override ───────────────────────────────────────────

    def _strip_query(self, path: str) -> str:
        return path.split("?")[0]

    def translate_path(self, path):
        path = self._strip_query(path)
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            return str(STATIC_ROOT / rel)
        rel = path.lstrip("/")
        target = STATIC_ROOT / rel
        if target.exists() and target.is_file():
            return str(target)
        return str(STATIC_ROOT / rel)

    def end_headers(self):
        # No-cache for JS/HTML files so browser always picks up changes
        clean = self.path.split("?")[0]
        if clean.endswith('.js') or clean.endswith('.html'):
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()


def create_server(host: str = DASHBOARD_HOST, port: int = DEFAULT_PORT) -> HTTPServer:
    """Create an HTTPServer with SO_REUSEADDR for immediate port reclamation.

    Sets socket.SO_REUSEADDR=1 so that the port is reclaimable immediately
    after an ungraceful exit (crash, OOM, signal). Without this option the
    kernel keeps the socket in TIME_WAIT for ~60-120s and any new bind fails
    with OSError errno 98.

    Resolves the static root for the port (see ``resolve_static_root``) and
    makes it available to every handler instance.

    Args:
        host: Bind address (default: DASHBOARD_HOST, "127.0.0.1").
        port: Bind port (default: DEFAULT_PORT, 3005).

    Returns:
        Configured HTTPServer instance.
    """
    global STATIC_ROOT
    STATIC_ROOT = resolve_static_root(port)
    if not STATIC_ROOT.is_dir():
        logger.warning(
            "Static root %s does not exist — dashboard will 404 until a build exists",
            STATIC_ROOT,
        )
    server = HTTPServer((host, port), DashboardHandler)
    # SO_REUSEADDR — permite reocupar puerto inmediatamente tras caída
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.timeout = 1.0
    return server


def run_server(host: str = DASHBOARD_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the dashboard HTTP server with crash-safe shutdown handling.

    Wraps serve_forever() in a try/except/finally block so that unexpected
    exceptions are logged with full traceback (logger.exception) and the
    server shuts down cleanly. KeyboardInterrupt logs a graceful SIGINT
    message before shutdown. The finally block always logs exit.

    Args:
        host: Bind address (default: DASHBOARD_HOST, "127.0.0.1").
        port: Bind port (default: DEFAULT_PORT, 3005).
    """
    init_logging()
    server = create_server(host, port)
    url = f"http://localhost:{port}"
    logger.info("Dashboard listening on %s", url)
    print(f"🌐 ULTRATIMONEL DASHBOARD — {url}")
    print(f"📁 DB: {DB_PATH}")
    print(f"📂 Static: {STATIC_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down dashboard server (SIGINT)")
        server.shutdown()
    except Exception as exc:
        # logger.exception includes full traceback — critical for post-mortem.
        logger.exception("Dashboard server crashed: %s", exc)
        server.shutdown()
    finally:
        logger.info("Dashboard server exited")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run_server(host=DASHBOARD_HOST, port=port)

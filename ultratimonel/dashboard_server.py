"""dashboard_server.py — Ultratimonel Dashboard (stdlib-only, zero deps).

Serves the NES-style mission viewer GUI using Python's built-in http.server.
Reads directly from the same SQLite DB as the MCP server.

Hierarchy flow:
  /api/projects                        → project list
  /api/projects/{project}/missions      → Deck-synced missions
  /api/missions/{id}                    → mission detail + checklist items
  /api/checklist/{item_id}/intentos     → intentos for a checklist item
  /api/intentos/{id}                   → intento detail + per-gate states
  /api/intentos/{id}/gate/{name}/logs   → gate transition log timeline

Endpoints:
  GET  /                  → index.html (SPA)
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
import sqlite3
import socketserver
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] dashboard: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("dashboard")

HERE = Path(__file__).parent.resolve()
DASHBOARD_DIR = HERE / "dashboard"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3005

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

    def _db(self):
        conn = sqlite3.connect(DB_PATH)
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
        index_path = DASHBOARD_DIR / "index.html"
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
            return str(DASHBOARD_DIR / rel)
        rel = path.lstrip("/")
        target = DASHBOARD_DIR / rel
        if target.exists() and target.is_file():
            return str(target)
        return str(DASHBOARD_DIR / rel)

    def end_headers(self):
        # No-cache for JS/HTML files so browser always picks up changes
        clean = self.path.split("?")[0]
        if clean.endswith('.js') or clean.endswith('.html'):
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()


def create_server(host: str = DASHBOARD_HOST, port: int = DEFAULT_PORT) -> HTTPServer:
    server = HTTPServer((host, port), DashboardHandler)
    server.timeout = 1.0
    return server


def run_server(host: str = DASHBOARD_HOST, port: int = DEFAULT_PORT):
    server = create_server(host, port)
    url = f"http://localhost:{port}"
    logger.info("Dashboard listening on %s", url)
    print(f"🌐 ULTRATIMONEL DASHBOARD — {url}")
    print(f"📁 DB: {DB_PATH}")
    print(f"📂 Static: {DASHBOARD_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down dashboard server")
        server.shutdown()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run_server(host=DASHBOARD_HOST, port=port)

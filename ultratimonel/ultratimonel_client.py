"""
Cliente MCP para comunicación con el server ultratimonel via stdio JSON-RPC.

Implementa el handshake completo de inicialización de MCP antes de
enviar tools/call.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import uuid

logger = logging.getLogger(__name__)

# ── Rutas parametrizables (12-factor — ver config_loader.py) ──────────────
# NUNCA hardcodear rutas de máquina en el repo: se resuelven por env var con
# fallback portable (sys.executable / shutil.which). Ejemplo de config:
#   ULTRATIMONEL_MCP_CMD=/home/<user>/Proyectos/ultratimonel/.venv/bin/python3
#   ULTRATIMONEL_MCP_ARGS=/home/<user>/Proyectos/ultratimonel/main.py
# Si no hay env vars, se intenta leer la config MCP activa de Hermes
# (~/.hermes/config.yaml → mcp.servers.ultratimonel) — misma fuente que el
# runtime. Solo como último recurso cae a sys.executable.

def _hermes_mcp_config() -> dict:
    """Lee la config MCP de Hermes para el server ultratimonel (fuente de verdad).

    Soporta ambas estructuras: ``mcp.servers.ultratimonel`` (nuevo) y
    ``mcp_servers.ultratimonel`` (estructura actual de la config activa).
    """
    try:
        import yaml
        from pathlib import Path

        cfg_path = Path.home() / ".hermes" / "config.yaml"
        if not cfg_path.is_file():
            return {}
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        servers = (
            (data.get("mcp") or {}).get("servers")
            or data.get("mcp_servers")
            or {}
        )
        return servers.get("ultratimonel") or {}
    except Exception:
        return {}


def _resolve_mcp_cmd() -> str:
    """Resuelve el comando del MCP server: env var → config Hermes → portable."""
    env = os.environ.get("ULTRATIMONEL_MCP_CMD", "").strip()
    if env:
        return env
    cfg = _hermes_mcp_config()
    cmd = cfg.get("command", "")
    if cmd:
        return cmd
    return sys.executable or shutil.which("python3") or "python3"


def _resolve_mcp_args() -> list[str]:
    """Resuelve los args del MCP server: env var → config Hermes → vacío."""
    env = os.environ.get("ULTRATIMONEL_MCP_ARGS", "").strip()
    if env:
        return [env]
    cfg = _hermes_mcp_config()
    args = cfg.get("args") or []
    if args:
        return list(args)
    return []


def _resolve_nextcloud_args() -> str:
    env = os.environ.get("ULTRATIMONEL_NEXTCLOUD_ARGS", "").strip()
    if env:
        return env
    cfg = _hermes_mcp_config()
    return (
        cfg.get("env", {}).get("ULTRATIMONEL_NEXTCLOUD_ARGS")
        or "http_to_stdio_mcp.py"
    )


def _resolve_nextcloud_url() -> str:
    env = os.environ.get("ULTRATIMONEL_NEXTCLOUD_URL", "").strip()
    if env:
        return env
    cfg = _hermes_mcp_config()
    return (
        cfg.get("env", {}).get("ULTRATIMONEL_NEXTCLOUD_URL")
        or "http://localhost:2993/mcp"
    )


ULTRATIMONEL_CMD = _resolve_mcp_cmd()
ULTRATIMONEL_ARGS = _resolve_mcp_args()
ULTRATIMONEL_ENV = {
    "ULTRATIMONEL_CHECKPOINT_COMMAND": os.environ.get(
        "ULTRATIMONEL_CHECKPOINT_COMMAND", "agentcheckpoint"
    ),
    "ULTRATIMONEL_CHECKPOINT_ARGS": os.environ.get("ULTRATIMONEL_CHECKPOINT_ARGS", ""),
    "ULTRATIMONEL_NEXTCLOUD_COMMAND": os.environ.get(
        "ULTRATIMONEL_NEXTCLOUD_COMMAND", _resolve_mcp_cmd()
    ),
    "ULTRATIMONEL_NEXTCLOUD_ARGS": _resolve_nextcloud_args(),
    "ULTRATIMONEL_NEXTCLOUD_URL": _resolve_nextcloud_url(),
    "ULTRATIMONEL_NEXTCLOUD_TIMEOUT": os.environ.get(
        "ULTRATIMONEL_NEXTCLOUD_TIMEOUT", "600"
    ),
}


def _call_mcp_tool(tool_name: str, arguments: dict) -> dict | None:
    """
    Llama a una tool del MCP server ultratimonel via stdio JSON-RPC.
    Maneja el handshake completo: initialize → initialized → tools/call.
    """
    try:
        proc = subprocess.Popen(
            [ULTRATIMONEL_CMD] + ULTRATIMONEL_ARGS,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # FIX (2026-08-20, card #164): merge os.environ with the
            # ULTRATIMONEL_* overrides instead of replacing the process env.
            # Previously the server was spawned with ONLY the ULTRATIMONEL_*
            # vars (no PATH/HOME) → its gates 1a/1b could not spawn
            # `npx -y @agentmemory/mcp` / `agentcheckpoint` → WARN "unavailable"
            # every pre_llm_call → plugin bouncer blocked begin_turn post-gracia.
            env={**os.environ, **ULTRATIMONEL_ENV},
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        logger.error("ultratimonel-preflight: MCP server binary not found")
        return None
    except Exception as e:
        logger.error("ultratimonel-preflight: Failed to start MCP server: %s", e)
        return None

    def _send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def _recv() -> dict | None:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            return None

    try:
        # 1. Initialize handshake
        _send({
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ultratimonel-preflight", "version": "1.0.0"},
            },
        })
        init_resp = _recv()
        if not init_resp or "result" not in init_resp:
            logger.error("ultratimonel-preflight: Initialize failed: %s", init_resp)
            proc.kill()
            return None

        # 2. Send initialized notification
        _send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # 3. Call the tool
        req_id = str(uuid.uuid4())[:8]
        _send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        })

        # Leer respuestas hasta encontrar la que tenga nuestro id
        for _ in range(100):
            resp = _recv()
            if resp is None:
                break
            if isinstance(resp, dict) and resp.get("id") == req_id:
                if "result" in resp:
                    return resp["result"]
                elif "error" in resp:
                    logger.error(
                        "ultratimonel-preflight: MCP error: %s", resp["error"]
                    )
                    return None

    except subprocess.TimeoutExpired:
        logger.error("ultratimonel-preflight: MCP call timed out")
    except Exception as e:
        logger.error("ultratimonel-preflight: MCP error: %s", e)
    finally:
        try:
            proc.kill()
        except Exception:
            pass

    return None


def assert_gates(session_id: str, message: str, sender: str = "user") -> dict | None:
    """Ejecuta assert_gates en ultratimonel y devuelve el resultado."""
    return _call_mcp_tool("assert_gates", {
        "session_id": session_id,
        "message": message,
        "sender": sender,
    })


def gates_summary(gates_result: dict | None) -> str:
    """Convierte el resultado de assert_gates en texto legible para contexto."""
    if not gates_result:
        return "[ultratimonel] assert_gates: no response (server may be offline)"

    try:
        # FastMCP envuelve el resultado en content[{type:text, text:...}]
        raw = gates_result
        content = raw.get("content", [])
        if content and isinstance(content, list) and "text" in content[0]:
            raw = json.loads(content[0]["text"])

        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw

        gates = data.get("gates", [])
        status = data.get("status", "UNKNOWN")

        lines = [f"[ultratimonel] gates status: {status}"]
        for g in gates:
            name = g.get("name", "?")
            state = g.get("state", "?")
            mandatory = g.get("mandatory", False)
            marker = "🔴" if state == "BLOCK" else "🟡" if state == "WARN" else "✅" if state == "PASS" else "⏭️"
            lines.append(f"  {marker} Gate {name}: {state}{' (mandatory)' if mandatory else ''}")

        cp = data.get("context_envelope", {}).get("checkpoint_state", {})
        if cp and cp.get("status") != "not_found":
            val = str(cp.get("value", ""))
            lines.append(f"  📌 Checkpoint: {val[:200]}")

        deck = data.get("context_envelope", {}).get("deck_cards", [])
        if deck:
            for card in deck[:3]:
                lines.append(f"  🃏 Deck: {card.get('title', '?')}")

        return "\n".join(lines)

    except Exception as e:
        return f"[ultratimonel] Error parsing gates result: {e}"


# ── Turn Count Persistence Wrappers (v4) ─────────────────────────────────────

from .persistence import Persistence

# Create instance with default DB path (same as server.py uses)
_db_path = os.environ.get(
    "ULTRATIMONEL_DB_PATH",
    os.path.expanduser("~/.hermes/ultratimonel.db"),
)
persistence = Persistence(_db_path)


def get_turn_count(session_id: str) -> int:
    """Get persisted turn count for a session. Returns 0 if not found."""
    return persistence.get_turn_count(session_id)


def set_turn_count(session_id: str, count: int) -> bool:
    """Persist turn count for a session. Returns success status."""
    return persistence.set_turn_count(session_id, count)

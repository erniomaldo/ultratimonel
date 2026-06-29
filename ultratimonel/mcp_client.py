"""mcp_client.py — Sync MCP stdio client for calling other MCP servers.

Replaces the old HTTP JSON-RPC approach with direct stdio connections,
matching how Hermes itself connects to its MCP servers.

Each call spawns a fresh subprocess (stdio transport), calls the tool,
shuts down cleanly, and returns.  This is simple and avoids async issues
— the overhead is fine for per-turn gate checks.
"""

import json
import logging
import os
import subprocess
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── MCP protocol version ─────────────────────────────────────────────
PROTOCOL_VERSION = "2024-11-05"

# ── Known MCP servers: command/args mirror Hermes config.yaml ────────

MCP_SERVER_CONFIGS: dict[str, dict] = {
    "agentmemory": {
        "command": "npx",
        "args": ["-y", "@agentmemory/mcp"],
    },
    "nextcloud": {
        "command": (
            os.environ.get(
                "ULTRATIMONEL_NEXTCLOUD_COMMAND",
                "/home/ernesto-personal/Proyectos/ultratimonel/.venv/bin/python3",
            )
        ),
        "args": [
            os.environ.get(
                "ULTRATIMONEL_NEXTCLOUD_ARGS",
                "/home/ernesto-personal/Proyectos/http-to-stdio/http_to_stdio_mcp.py",
            )
        ],
        "env": {
            "UPSTREAM_MCP_URL": os.environ.get(
                "ULTRATIMONEL_NEXTCLOUD_URL",
                "https://mcpnextcloud.agendasencilla.com/mcp",
            ),
            "UPSTREAM_MCP_HEADERS": os.environ.get(
                "ULTRATIMONEL_NEXTCLOUD_HEADERS",
                '{"Authorization": "Bearer oieojknfaoibnfasoinfasoinasdopinasdoiasnd"}',
            ),
        },
    },
}


def _get_checkpoint_config() -> dict:
    """Return checkpoint server config, reading env override if set."""
    command = os.environ.get(
        "ULTRATIMONEL_CHECKPOINT_COMMAND",
        "/home/ernesto-personal/.hermes/mcp-servers/checkpoint-server/.venv/bin/python3",
    )
    args_env = os.environ.get(
        "ULTRATIMONEL_CHECKPOINT_ARGS",
        "/home/ernesto-personal/.hermes/mcp-servers/checkpoint-server/main.py",
    )
    return {
        "command": command,
        "args": args_env.split(",") if "," in args_env else [args_env],
    }


# ── Tool name mapping ─────────────────────────────────────────────────
# Hermes prefixes MCP tool names with "mcp_<server_name>_" internally.
# When calling the MCP server directly, we use the UNPREFIXED names.

TOOL_NAMES: dict[str, dict[str, str]] = {
    "agentmemory": {
        "smart_search": "memory_smart_search",
    },
    "checkpoint": {
        "get_state": "get_state",
        "set_state": "set_state",
    },
    "nextcloud": {
        "deck_get_boards": "deck_get_boards",
        "deck_get_stacks": "deck_get_stacks",
        "collectives_get_pages": "collectives_get_pages",
        "collectives_get_page": "collectives_get_page",
    },
}


def _read_line(stream, timeout: float = 5.0) -> Optional[str]:
    """Read a single line from a stream with timeout."""
    import select

    if timeout <= 0:
        return None

    # Poll for data with timeout
    readable, _, _ = select.select([stream], [], [], timeout)
    if not readable:
        return None  # timeout

    line = stream.readline()
    if not line:
        return None
    return line.strip()


def _json_rpc_request(request_id: int, method: str, params: Optional[dict] = None) -> str:
    """Build a JSON-RPC 2.0 request string."""
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return json.dumps(payload, ensure_ascii=False)


def _parse_response(line: str) -> tuple[Optional[Any], Optional[str]]:
    """Parse a JSON-RPC response line.

    Recursively unwraps nested ``content`` blocks from MCP stdio
    (common when http-to-stdio proxy double-wraps the response).

    Returns:
        (result, None) on success
        (None, error_message) on error
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON response: {e}"

    if "error" in data and data["error"] is not None:
        err = data["error"]
        msg = err.get("message", str(err))
        return None, msg

    result = data.get("result")

    # Recursively unwrap MCP content blocks
    def _unwrap(value: Any) -> Any:
        if isinstance(value, dict) and "content" in value:
            content = value["content"]
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        try:
                            parsed = json.loads(text)
                            # Only recurse if parsed is a content-wrapped dict
                            if isinstance(parsed, dict) and "content" in parsed:
                                return _unwrap(parsed)
                            return parsed
                        except (json.JSONDecodeError, TypeError):
                            return text
        return value

    return _unwrap(result), None


def call_mcp_tool(
    server_name: str,
    tool_name: str,
    params: Optional[dict] = None,
    timeout: float = 8.0,
) -> tuple[Optional[Any], Optional[str]]:
    """Call an MCP tool on a stdio-connected server and return (result, error).

    This is a SYNCHRONOUS implementation using subprocess + select for MCP
    stdio transport.  Spawns the server process, performs the JSON-RPC
    initialize handshake, calls the tool, then shuts down.

    Args:
        server_name: "agentmemory" or "checkpoint"
        tool_name: Unprefixed MCP tool name (e.g. "memory_smart_search")
        params: Tool parameters dict
        timeout: Max seconds for the entire operation

    Returns:
        Tuple of (result_data, error_type):
          - (result, None) on success
          - (None, "timeout") on timeout
          - (None, "unavailable") on connection or protocol error
    """
    # Resolve server config
    if server_name == "checkpoint":
        config = _get_checkpoint_config()
    else:
        config = MCP_SERVER_CONFIGS.get(server_name)

    if not config:
        return None, f"unknown server: {server_name}"

    command = config["command"]
    args = config.get("args", [])

    logger.info(
        "Spawning MCP server %s: %s %s",
        server_name, command, " ".join(args),
    )

    # Build process env: inherit current + merge server-specific vars
    proc_env = os.environ.copy()
    server_env = config.get("env", {})
    if server_env:
        proc_env.update(server_env)

    try:
        proc = subprocess.Popen(
            [command] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
        )
    except FileNotFoundError:
        logger.warning("Command not found for %s: %s", server_name, command)
        return None, "unavailable"
    except Exception as exc:
        logger.warning("Failed to spawn %s: %s", server_name, exc)
        return None, "unavailable"

    try:
        # ── Phase 1: Initialize ──────────────────────────────────────
        init_req = _json_rpc_request(
            1, "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ultratimonel", "version": "1.0.0"},
            },
        )
        proc.stdin.write((init_req + "\n").encode())
        proc.stdin.flush()

        init_resp = _read_line(proc.stdout, timeout=timeout * 0.2)
        if init_resp is None:
            logger.warning("No initialize response from %s (timeout)", server_name)
            return None, "timeout"

        result, err = _parse_response(init_resp)
        if err:
            logger.warning("Initialize failed for %s: %s", server_name, err)
            return None, "unavailable"

        # ── Phase 2: Initialized notification ────────────────────────
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        proc.stdin.write((notif + "\n").encode())
        proc.stdin.flush()

        # ── Phase 3: Call tool ───────────────────────────────────────
        call_req = _json_rpc_request(
            2, "tools/call",
            {"name": tool_name, "arguments": params or {}},
        )
        proc.stdin.write((call_req + "\n").encode())
        proc.stdin.flush()

        call_resp = _read_line(proc.stdout, timeout=timeout * 0.6)
        if call_resp is None:
            logger.warning("No tool response from %s/%s (timeout)", server_name, tool_name)
            return None, "timeout"

        result, err = _parse_response(call_resp)
        if err:
            logger.warning("Tool call %s/%s failed: %s", server_name, tool_name, err)
            return None, "unavailable"

        # ── Phase 4: Shutdown ────────────────────────────────────────
        shutdown_req = _json_rpc_request(3, "shutdown")
        proc.stdin.write((shutdown_req + "\n").encode())
        proc.stdin.flush()

        # Read shutdown response (best-effort)
        _read_line(proc.stdout, timeout=1.0)

        # Send exit notification
        exit_notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "exit",
        })
        proc.stdin.write((exit_notif + "\n").encode())
        proc.stdin.flush()

        return result, None

    except Exception as exc:
        logger.warning("MCP call to %s/%s failed: %s", server_name, tool_name, exc)
        return None, "unavailable"
    finally:
        # Ensure process is cleaned up
        try:
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

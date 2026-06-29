"""mcp_client.py — Sync MCP stdio client with persistent subprocess caching.

Replaces the old spawn-per-call approach.  Each server gets ONE subprocess
that lives for the duration of the process — the MCP stdio protocol supports
multiple tools/call requests over a single initialized connection.

Design:
  - _MCPConnection — wraps a subprocess + initialize handshake
  - call_mcp_tool() — stateless entry point (unchanged signature)
  - _connection_cache — dict[str, _MCPConnection] kept alive until interpreter exit
  - atexit cleanup shuts down all cached connections gracefully
  - Auto-reconnect on broken connection: one retry with fresh subprocess
"""

import atexit
import json
import logging
import os
import select
import subprocess
import sys
import time
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


# ── Low-level helpers ─────────────────────────────────────────────────


def _read_line(stream, timeout: float = 5.0) -> Optional[str]:
    """Read a single line from a stream with timeout."""
    if timeout <= 0:
        return None

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

    def _unwrap(value: Any) -> Any:
        if isinstance(value, dict) and "content" in value:
            content = value["content"]
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        try:
                            parsed = json.loads(text)
                            if isinstance(parsed, dict) and "content" in parsed:
                                return _unwrap(parsed)
                            return parsed
                        except (json.JSONDecodeError, TypeError):
                            return text
        return value

    return _unwrap(result), None


# ── Persistent MCP Connection ─────────────────────────────────────────


class _MCPConnection:
    """A persistent stdio MCP connection to a single server.

    Spawns the subprocess once, performs the initialize handshake,
    then keeps the connection alive for multiple tool calls.

    Call ``.close()`` to shut down gracefully.
    """

    __slots__ = ("server_name", "proc", "_next_id", "_closed")

    def __init__(self, server_name: str, config: dict):
        self.server_name = server_name
        self.proc: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._closed = False
        self._connect(config)

    # ── internal helpers ───────────────────────────────────────────

    def _build_env(self, config: dict) -> dict:
        proc_env = os.environ.copy()
        server_env = config.get("env", {})
        if server_env:
            proc_env.update(server_env)
        return proc_env

    def _connect(self, config: dict) -> None:
        """Spawn subprocess and perform initialize handshake."""
        command = config["command"]
        args = config.get("args", [])
        proc_env = self._build_env(config)

        logger.info(
            "Spawning MCP server %s: %s %s",
            self.server_name, command, " ".join(args),
        )

        try:
            self.proc = subprocess.Popen(
                [command] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
            )
        except FileNotFoundError:
            logger.warning("Command not found for %s: %s", self.server_name, command)
            self._closed = True
            raise
        except Exception as exc:
            logger.warning("Failed to spawn %s: %s", self.server_name, exc)
            self._closed = True
            raise

        # Initialize handshake
        init_req = _json_rpc_request(
            self._next_id, "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ultratimonel", "version": "1.0.0"},
            },
        )
        self._next_id += 1
        self.proc.stdin.write((init_req + "\n").encode())
        self.proc.stdin.flush()

        init_resp = _read_line(self.proc.stdout, timeout=5.0)
        if init_resp is None:
            logger.warning("No initialize response from %s (timeout)", self.server_name)
            self._die()
            raise ConnectionError(f"Initialize timeout for {self.server_name}")

        result, err = _parse_response(init_resp)
        if err:
            logger.warning("Initialize failed for %s: %s", self.server_name, err)
            self._die()
            raise ConnectionError(f"Initialize failed for {self.server_name}: {err}")

        # Send initialized notification
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        self.proc.stdin.write((notif + "\n").encode())
        self.proc.stdin.flush()

    def _die(self) -> None:
        """Force-kill the subprocess (no graceful shutdown)."""
        self._closed = True
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.proc.stderr.close()
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception:
            pass
        self.proc = None

    # ── public API ─────────────────────────────────────────────────

    def call_tool(
        self,
        tool_name: str,
        params: Optional[dict] = None,
        timeout: float = 8.0,
    ) -> tuple[Optional[Any], Optional[str]]:
        """Call an MCP tool on this persistent connection.

        Returns:
            (result, None) on success
            (None, "timeout") on timeout
            (None, "unavailable") on connection or protocol error
        """
        if self._closed or self.proc is None:
            return None, "unavailable"

        call_id = self._next_id
        self._next_id += 1

        call_req = _json_rpc_request(
            call_id, "tools/call",
            {"name": tool_name, "arguments": params or {}},
        )

        try:
            self.proc.stdin.write((call_req + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            logger.warning(
                "Write error on %s/%s: %s", self.server_name, tool_name, exc,
            )
            self._die()
            return None, "unavailable"

        call_resp = _read_line(self.proc.stdout, timeout=timeout)
        if call_resp is None:
            logger.warning(
                "Tool call %s/%s timed out (%.1fs)",
                self.server_name, tool_name, timeout,
            )
            # Don't close on timeout — the connection may still be healthy
            return None, "timeout"

        return _parse_response(call_resp)

    def close(self) -> None:
        """Graceful shutdown: send shutdown + exit, then wait."""
        if self._closed or self.proc is None:
            return
        self._closed = True

        shutdown_id = self._next_id
        self._next_id += 1

        try:
            shutdown_req = _json_rpc_request(shutdown_id, "shutdown")
            self.proc.stdin.write((shutdown_req + "\n").encode())
            self.proc.stdin.flush()
            _read_line(self.proc.stdout, timeout=1.0)

            exit_notif = json.dumps({
                "jsonrpc": "2.0",
                "method": "exit",
            })
            self.proc.stdin.write((exit_notif + "\n").encode())
            self.proc.stdin.flush()
        except Exception:
            pass
        finally:
            try:
                self.proc.stdin.close()
                self.proc.stdout.close()
                self.proc.stderr.close()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=2)
                except Exception:
                    pass
            self.proc = None


# ── Connection cache ──────────────────────────────────────────────────

_connection_cache: dict[str, _MCPConnection] = {}


@atexit.register
def _cleanup_all() -> None:
    """Shut down all cached connections at interpreter exit."""
    for name, conn in list(_connection_cache.items()):
        try:
            conn.close()
        except Exception:
            pass
    _connection_cache.clear()


def _resolve_config(server_name: str) -> dict:
    """Resolve the config dict for a server name."""
    if server_name == "checkpoint":
        return _get_checkpoint_config()

    config = MCP_SERVER_CONFIGS.get(server_name)
    if config is None:
        raise ValueError(f"Unknown MCP server: {server_name}")
    return config


def call_mcp_tool(
    server_name: str,
    tool_name: str,
    params: Optional[dict] = None,
    timeout: float = 8.0,
) -> tuple[Optional[Any], Optional[str]]:
    """Call an MCP tool on a stdio-connected server and return (result, error).

    This is the main entry point, kept signature-compatible with the original.
    Uses a persistent subprocess cache under the hood — spawns once per server
    and reuses the connection for subsequent calls.

    On unavailable (broken pipe, failed init, etc.), retries ONCE with a fresh
    connection before giving up.  On timeout, no retry (the server is alive but
    slow — the caller's gate logic handles this as WARN).

    Args:
        server_name: "agentmemory", "checkpoint", or "nextcloud"
        tool_name: Unprefixed MCP tool name (e.g. "memory_smart_search")
        params: Tool parameters dict
        timeout: Max seconds for the tool call phase (not total)

    Returns:
        Tuple of (result_data, error_type):
          - (result, None) on success
          - (None, "timeout") on timeout
          - (None, "unavailable") on connection or protocol error
    """
    config = _resolve_config(server_name)

    # First attempt: use or create cached connection
    conn = _connection_cache.get(server_name)
    if conn is None:
        try:
            conn = _MCPConnection(server_name, config)
            _connection_cache[server_name] = conn
        except (FileNotFoundError, ConnectionError, OSError) as exc:
            logger.warning("Failed to create connection to %s: %s", server_name, exc)
            return None, "unavailable"

    result, error = conn.call_tool(tool_name, params, timeout=timeout)

    # On unavailable (broken connection), retry once with fresh connection
    if result is None and error == "unavailable":
        logger.info("Retrying %s/%s with fresh connection", server_name, tool_name)
        try:
            conn.close()
        except Exception:
            pass
        if server_name in _connection_cache:
            del _connection_cache[server_name]

        try:
            conn = _MCPConnection(server_name, config)
            _connection_cache[server_name] = conn
        except (FileNotFoundError, ConnectionError, OSError) as exc:
            logger.warning("Retry failed for %s: %s", server_name, exc)
            return None, "unavailable"

        result, error = conn.call_tool(tool_name, params, timeout=timeout)

    return result, error

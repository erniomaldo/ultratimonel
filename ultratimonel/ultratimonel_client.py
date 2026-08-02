"""
Cliente MCP para comunicación con el server ultratimonel via stdio JSON-RPC.

Implementa el handshake completo de inicialización de MCP antes de
enviar tools/call.
"""

import json
import logging
import subprocess
import uuid

logger = logging.getLogger(__name__)

ULTRATIMONEL_CMD = "/home/ernesto-personal/Proyectos/ultratimonel/.venv/bin/python3"
ULTRATIMONEL_ARGS = ["/home/ernesto-personal/Proyectos/ultratimonel/main.py"]
ULTRATIMONEL_ENV = {
    "ULTRATIMONEL_CHECKPOINT_COMMAND": "agentcheckpoint",
    "ULTRATIMONEL_CHECKPOINT_ARGS": "",
    "ULTRATIMONEL_NEXTCLOUD_COMMAND": "/home/ernesto-personal/Proyectos/ultratimonel/.venv/bin/python3",
    "ULTRATIMONEL_NEXTCLOUD_ARGS": "/home/ernesto-personal/Proyectos/http-to-stdio/http_to_stdio_mcp.py",
    "ULTRATIMONEL_NEXTCLOUD_URL": "https://mcpnextcloud.agendasencilla.com/mcp",
    "ULTRATIMONEL_NEXTCLOUD_TIMEOUT": "600",
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
            env={**ULTRATIMONEL_ENV},
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

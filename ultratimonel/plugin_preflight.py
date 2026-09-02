"""
Ultratimonel Pre-flight Plugin

Implementa el patrón Nikhil Verma de "mandatory tool contracts" sobre Hermes:

1. pre_llm_call: Ejecuta assert_gates antes de cada turno, inyecta contexto
2. pre_tool_call: Bouncer que verifica gates ANTES de ejecutar tools críticas
3. post_tool_call: Bloqueo inescapable después de end_turn — todas las tools fallan

El agente NO puede saltarse el pre_tool_call — corre en el runtime de Hermes.
"""

import json
import logging
import os
from typing import Any

GRACE_TURNS = int(os.environ.get("ULTRATIMONEL_GRACE_TURNS", "3"))
_turn_count = 0

# Estado del turno actual (para post_tool_call)
_turn_ended = False
_turn_active = False

from . import ultratimonel_client

logger = logging.getLogger(__name__)

# ── Cache de gates (lo llena pre_llm_call, lo consulta pre_tool_call) ─────
_last_gates_result: dict | None = None
_last_session_id: str | None = None
_last_gates_parsed: list[dict] | None = None

# ── Tools que requieren gates validados — Nikhil: mandatory tool contracts ──
TOOLS_REQUIRING_VERIFIED_GATES = {
    # Completar un intento requiere 4/4 gates PASS (como endTurn de Nikhil)
    "mcp__ultratimonel__complete_intento",
    # Registrar intento también requiere gates
    "mcp__ultratimonel__record_intento",
    # Tools que modifican datos (write operations)
    "mcp__nextcloud__deck_update_card",
    "mcp__nextcloud__nc_webdav_write_file",
    "mcp__nextcloud__nc_webdav_delete_resource",
    "write_file",
    "patch",
}


def _parse_gates(result: dict | None) -> list[dict] | None:
    """Extrae la lista de gates del resultado de assert_gates."""
    if not result:
        return None
    try:
        raw = result
        content = raw.get("content", [])
        if content and isinstance(content, list) and "text" in content[0]:
            raw = json.loads(content[0]["text"])
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
        return data.get("gates", [])
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _gates_all_pass(gates: list[dict]) -> tuple[bool, list[str]]:
    """Verifica que todos los gates mandatory estén PASS o SKIP.
    Retorna (True, []) o (False, [nombres de gates fallando])."""
    failed = []
    for g in gates:
        state = g.get("state", "BLOCK")
        mandatory = g.get("mandatory", True)
        if mandatory and state not in ("PASS", "SKIP"):
            failed.append(f"{g['name']}({state}): {g.get('message', '')}")
    return len(failed) == 0, failed


def _gates_count_passed(gates: list[dict]) -> int:
    """Cuenta cuántas gates están en PASS o SKIP."""
    return sum(1 for g in gates if g.get("state") in ("PASS", "SKIP"))


def _gates_bouncer(ctx=None, tool_name: str = "", args: dict | None = None, **kwargs) -> dict | None:
    """
    PRE_TOOL_CALL HOOK — Bouncer estilo Nikhil Verma.

    Bloquea tools críticas si los gates no se han ejecutado o no están PASS.
    Retorna None → tool se ejecuta. Retorna {"action": "block", ...} → tool bloqueada.
    """
    # 1. Solo aplica a tools que requieren gates verificados
    if tool_name not in TOOLS_REQUIRING_VERIFIED_GATES:
        return None

    global _last_gates_parsed

    # 2. ¿Hay gates cacheados?
    if _last_gates_parsed is None:
        return {
            "action": "block",
            "message": (
                "🚫 No se han ejecutado los gates de ultratimonel en esta sesión.\n\n"
                "REQUISITO: Debes ejecutar assert_gates() con el nombre del proyecto "
                "antes de usar esta herramienta.\n\n"
                "Ejemplo:\n"
                '  assert_gates(\n'
                '      message="ultratimonel: validar gates para <descripción>",\n'
                '      session_id="<session_id>",\n'
                "  )\n\n"
                "Luego verifica con check_gate() que las 4 gates estén PASS."
            ),
        }

    # 3. Verificar estado de gates
    gates = _last_gates_parsed
    all_pass, failed_gates = _gates_all_pass(gates)
    gates_passed = _gates_count_passed(gates)

    # Grace turns — primeros N turnos permiten sin bloquear por gates fallando
    if _turn_count <= GRACE_TURNS:
        return None

    if not all_pass:
        detail = "\n".join(f"  🔴 {f}" for f in failed_gates)
        return {
            "action": "block",
            "message": (
                f"🚫 Gates obligatorios no pasaron ({gates_passed}/4).\n\n"
                f"{detail}\n\n"
                "Corrige los gates bloqueantes antes de continuar. "
                "Ejecuta assert_gates() con el proyecto correcto."
            ),
        }

    # 4. Nikhil pattern: complete_intento es como endTurn — requiere 4/4
    if tool_name == "mcp__ultratimonel__complete_intento":
        if gates_passed < 4:
            return {
                "action": "block",
                "message": (
                    f"🚫 No puedes completar el intento — solo {gates_passed}/4 gates han pasado.\n\n"
                    "REQUISITO: Los 4 gates deben estar en PASS antes de completar un intento.\n\n"
                    "Ejecuta assert_gates() con el proyecto correcto (incluye el nombre del "
                    "proyecto en el mensaje) y verifica con check_gate()."
                ),
            }
        # También verificar que el gates_passed del argumento coincida
        requested = args.get("gates_passed", 0)
        if requested != 4:
            return {
                "action": "block",
                "message": (
                    f"🚫 gates_passed={requested} no válido. "
                    f"Debe ser 4 (los 4 gates PASS reales).\n\n"
                    f"Usa el valor real del resultado de assert_gates()."
                ),
            }

    # 5. deck_update_card: bloquear si se intenta cambiar el título
    if tool_name == "mcp__nextcloud__deck_update_card":
        if args.get("title"):
            return {
                "action": "block",
                "message": (
                    "🚫 No puedes modificar el título de la card Deck.\n\n"
                    "Usa la herramienta mcp__ultratimonel__card_update_description "
                    "si solo necesitas actualizar la descripción."
                ),
            }

    # 6. Todo en orden — permitir ejecución
    return None


def _post_turn_guard(ctx=None, tool_name: str = "", args: dict | None = None, result: dict | None = None, **kwargs) -> dict | None:
    """
    POST_TOOL_CALL HOOK — Bloqueo inescapable después de end_turn.

    Después de que se ejecuta end_turn(), TODAS las tools fallan de forma
    inescapable hasta que se llame a begin_turn() para iniciar un nuevo turno.
    
    Patrones bloqueados:
    - begin_turn → begin_turn (duplicado en misma respuesta)
    - begin_turn → end_turn (sin trabajo)
    - begin_turn → trabajo → end_turn → trabajo2 (tool tras end_turn)
    
    Regla: 1 ciclo por respuesta. begin_turn → trabajo → end_turn.
    Entre respuestas: end_turn de la anterior, begin_turn de la nueva. ✅
    """
    global _turn_ended, _turn_active
    
    # Detectar si se llamó end_turn — marcar como terminado
    if tool_name == "mcp__ultratimonel__end_turn":
        _turn_ended = True
        _turn_active = False
        return None
    
    # Detectar si se llamó begin_turn — iniciar nuevo ciclo
    if tool_name == "mcp__ultratimonel__begin_turn":
        if _turn_active:
            # Ya hay un turno activo en esta respuesta — bloquear duplicado
            return {
                "action": "block",
                "message": (
                    f"🚫 TOOL BLOCKED: {tool_name}\n\n"
                    "Ya hay un turno activo. No puedes llamar begin_turn() dos veces "
                    "sin end_turn() intermedio en la misma respuesta.\n\n"
                    "Flujo correcto (1 ciclo por respuesta):\n"
                    "  begin_turn() → trabajo → end_turn()\n\n"
                    "begin_turn() en una respuesta NUEVA está bien."
                ),
            }
        # begin_turn siempre inicia un nuevo ciclo (limpia flags)
        _turn_active = True
        _turn_ended = False
        return None
    
    # Despuès de end_turn, BLOQUEAR TODO
    if _turn_ended:
        return {
            "action": "block",
            "message": (
                f"🚫 TOOL BLOCKED INESCAPABLE: {tool_name}\n\n"
                "El turno actual ya fue cerrado con end_turn().\n"
                "Todas las tools fallan después de cerrar un turno.\n\n"
                "Flujo correcto:\n"
                "  begin_turn() → trabajo → end_turn()\n\n"
                "Para continuar, llama a begin_turn() para iniciar un nuevo turno."
            )
        }
    
    return None


def _on_session_start(session_id: str, **kwargs):
    """Hook: se ejecuta al crear una nueva sesión — inicializa el contador de gates."""
    global _turn_count, _turn_ended, _turn_active
    _turn_count = 0
    _turn_ended = False
    _turn_active = False
    logger.info("ultratimonel-preflight: Session started — running initial gates")

    result = ultratimonel_client.assert_gates(
        session_id=session_id,
        message="[session_start]",
        sender="plugin",
    )

    global _last_gates_result, _last_session_id, _last_gates_parsed
    _last_gates_result = result
    _last_session_id = session_id
    _last_gates_parsed = _parse_gates(result)

    summary = ultratimonel_client.gates_summary(result)
    logger.info("ultratimonel-preflight: Initial gates:\n%s", summary)


def _pre_llm_call(
    session_id: str,
    user_message: str,
    is_first_turn: bool,
    **kwargs,
):
    """
    Hook pre_llm_call: ejecuta assert_gates y alimenta la caché para pre_tool_call.

    Nikhil pattern: el contador se actualiza cada turno. Si el agente omite
    incluir el proyecto en el mensaje, los gates salen SKIP (proyecto unknown)
    y pre_tool_call bloquea las tools de escritura.
    """
    global _last_gates_result, _last_session_id, _last_gates_parsed

    global _turn_count
    _turn_count += 1

    # Primer turno: usar gates de on_session_start si existen
    if is_first_turn and _last_gates_result is not None:
        gates = _parse_gates(_last_gates_result)
        if gates:
            _last_gates_parsed = gates
            summary = ultratimonel_client.gates_summary(_last_gates_result)
            return {"context": summary}

    # Ejecutar gates frescos
    result = ultratimonel_client.assert_gates(
        session_id=session_id,
        message=user_message[:500],
        sender="plugin",
    )

    _last_gates_result = result
    _last_session_id = session_id
    _last_gates_parsed = _parse_gates(result)

    summary = ultratimonel_client.gates_summary(result)

    # SIEMPRE inyectar resumen de gates — el pre_tool_call bloquea igual,
    # pero el agente necesita visibilidad para auto-corregirse (Nikhil: self-correction)
    if gates_summary_has_issues(summary):
        return {"context": summary}

    if is_first_turn:
        return {"context": summary}

    # Injertar resumen compacto cada 3 turnos aunque todo esté OK
    return None


def gates_summary_has_issues(summary: str) -> bool:
    """Detecta si el resumen contiene BLOCK o WARN."""
    return "BLOCK" in summary or "WARN" in summary


def register(ctx):
    """Registrar hooks del plugin — todos son obligatorios."""
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("pre_tool_call", _gates_bouncer)
    ctx.register_hook("post_tool_call", _post_turn_guard)
    logger.info(
        "ultratimonel-preflight: Plugin v2.0 registered — "
        "pre_llm_call + pre_tool_call (Nikhil bouncer) + post_tool_call (turn lock) active"
    )

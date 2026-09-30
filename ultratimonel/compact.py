"""compact.py — Pure serializers that strip verbose fields from tool output.

Design D4: ``end_turn``, ``mission_list`` and read/list tools emit compact
output by default. The ~91 KB culprit is each gate's ``result_data`` (gate 1e
carries full Deck card descriptions), so compact gate output never includes it.

This module is intentionally pure: no I/O, no imports from the rest of the
package, no side effects. Every function accepts a mapping (or an object with
attributes, such as a ``GateResult`` dataclass) and returns a new plain
``dict``/``list``.
"""

from typing import Any, Iterable, Mapping

__all__ = ["compact_gate", "compact_gates", "compact_mission", "compact_quest"]


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping or from an attribute-bearing object."""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _gate_name(gate: Any) -> str:
    """Read a gate's name, accepting the persistence column ``gate_name``.

    ``GateResult`` exposes ``name``; ``list_gate_states`` rows expose
    ``gate_name``. Both must compact to the same ``name`` key.
    """
    name = _field(gate, "name", None)
    if name:
        return name
    return _field(gate, "gate_name", "")


def compact_gate(gate: Any) -> dict[str, Any]:
    """Serialize one gate to its compact shape ``{name, state, mandatory}``.

    Drops ``message``, ``duration_ms`` and ``result_data`` (D4). ``mandatory``
    defaults to ``True`` to match ``GateConfig``'s default. Accepts either a
    ``GateResult`` (``name``) or a ``list_gate_states`` row (``gate_name``).
    """
    return {
        "name": _gate_name(gate),
        "state": _field(gate, "state", ""),
        "mandatory": bool(_field(gate, "mandatory", True)),
    }


def compact_gates(gates: Iterable[Any]) -> list[dict[str, Any]]:
    """Serialize a sequence of gates, dropping verbosity from each."""
    return [compact_gate(g) for g in gates]


def compact_mission(mission: Any) -> dict[str, Any]:
    """Serialize a mission to ``{id, title, status}``.

    Drops ``description``, ``checklist_items`` and every other verbose field;
    callers that need the full payload must opt in explicitly.
    """
    return {
        "id": _field(mission, "id"),
        "title": _field(mission, "title", ""),
        "status": _field(mission, "status", ""),
    }


def compact_quest(quest: Any) -> dict[str, Any]:
    """Serialize a quest (checklist item) to ``{id, text, done}``.

    ``done`` is normalized to a ``bool`` so callers always see the public
    ``done: bool`` vocabulary (D10), regardless of the SQLite ``0``/``1``.
    """
    return {
        "id": _field(quest, "id"),
        "text": _field(quest, "text", ""),
        "done": bool(_field(quest, "done", 0)),
    }

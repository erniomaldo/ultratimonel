"""deck_bridge.py — Internal Deck write bridge over the proven ``mcp_client`` path.

Nextcloud Deck is the ONE source of truth. This module owns the high-level Deck
semantics (mission card writes and quest — markdown checkbox — composition) and
routes every operation through ``mcp_client.call_mcp_tool("nextcloud", ...)``,
the stdio path already proven by ``card_update_description`` (design D1).

Contract (design D1/D2/D3):

* Every operation returns a ``(value, err)`` tuple. On success ``err`` is
  ``None``; on bridge failure (MCP unavailable/timeout) ``value`` is ``None``
  and ``err`` is a non-empty string.
* The bridge NEVER writes SQLite and NEVER falls back to a local write. Only
  ``server.py`` refreshes the replica, and only after the Deck write is
  acknowledged.
* A quest is a markdown checkbox line (``- [ ] …`` / ``- [x] …``, ``*`` bullets
  accepted) inside the card ``description``. There is no Deck checklist tool.
* ``update_description`` never touches quests: quest lines are preserved
  byte-identical and in their original relative order (D3). Checkbox lines in
  the incoming prose are omitted so prose cannot introduce a quest.
"""

import json
import logging
import re
from typing import Any, Optional

from . import mcp_client

logger = logging.getLogger(__name__)

__all__ = [
    "create_card",
    "update_title",
    "update_description",
    "clean_prose",
    "append_quest",
    "update_quest",
    "complete_quest",
    "extract_quests",
    "read_card",
]

_NEXTCLOUD = "nextcloud"
_DEFAULT_TIMEOUT = 8.0

# Authoritative quest matcher: a markdown checkbox line after stripping
# surrounding whitespace. ``- [ ] text`` / ``- [x] text`` / ``* [ ] text`` /
# ``* [X] text``. The bullet must be followed by at least one space before the
# bracket. ``extract_quests`` is the ONE definition of a quest line; every
# consumer (``server.sync_tasks``, ``clean_prose``) sources its notion of a
# quest from it.
_CHECKBOX_RE = re.compile(r"^[-*]\s+\[([ xX])\]\s*(.*)$")

# Tolerant sanitization matcher used ONLY by ``clean_prose``: it must drop every
# line any tolerant consumer could count as a quest — the authoritative form
# plus dangerous checkbox-like variants (``- [TODO] x``, ``- [] x``,
# ``- [  ] x``, ``+ [x] x``) and indented markers. A strict superset of
# ``_CHECKBOX_RE``.
_QUEST_LIKE_RE = re.compile(r"^\s*[-*+]\s*\[[^\]]*\]", re.IGNORECASE)


# ── Low-level MCP plumbing ─────────────────────────────────────────────


def _deck_tool(tool_key: str) -> str:
    """Resolve an unprefixed Deck tool name via the shared mapping."""
    return mcp_client.TOOL_NAMES[_NEXTCLOUD].get(tool_key, tool_key)


def _deck_call(
    tool_key: str,
    params: dict[str, Any],
) -> tuple[Optional[Any], Optional[str]]:
    """Call one Deck tool on the nextcloud MCP server."""
    return mcp_client.call_mcp_tool(
        _NEXTCLOUD,
        _deck_tool(tool_key),
        params,
        timeout=_DEFAULT_TIMEOUT,
    )


def _as_text(value: Any) -> Optional[str]:
    """Return ``value`` as text, decoding MCP ``content`` blocks defensively."""
    if isinstance(value, dict) and isinstance(value.get("content"), list):
        for item in value["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text", "")
    return None


def _normalize_card(card: Any) -> Optional[dict[str, Any]]:
    """Normalize a ``deck_get_card`` payload to a single card dict, or None."""
    candidate = card
    if isinstance(candidate, list) and candidate:
        candidate = candidate[0]

    if isinstance(candidate, dict):
        # Defensive double-unwrap for http-to-stdio content blocks.
        text = _as_text(candidate)
        if text is not None:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return candidate
            candidate = parsed[0] if isinstance(parsed, list) and parsed else parsed

    return candidate if isinstance(candidate, dict) else None


def _read_card(
    board_id: int,
    stack_id: int,
    card_id: int,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Fetch a card and normalize it. Returns ``(card, err)``."""
    card, err = _deck_call(
        "deck_get_card",
        {"board_id": board_id, "card_id": card_id, "stack_id": stack_id},
    )
    if card is None:
        return None, err or "unavailable"
    normalized = _normalize_card(card)
    if normalized is None:
        return None, "unexpected Deck response shape"
    return normalized, None


def _write_card(
    board_id: int,
    stack_id: int,
    card_id: int,
    title: str,
    description: str,
) -> tuple[Optional[bool], Optional[str]]:
    """Write a card's title + description. Returns ``(True, None)`` on success."""
    result, err = _deck_call(
        "deck_update_card",
        {
            "board_id": board_id,
            "card_id": card_id,
            "stack_id": stack_id,
            "title": title,
            "description": description,
        },
    )
    if result is None:
        return None, err or "unavailable"
    return True, None


def _extract_card_id(result: Any) -> Optional[int]:
    """Pull a numeric card id out of a ``deck_create_card`` response."""
    if isinstance(result, list) and result:
        result = result[0]
    if isinstance(result, dict):
        for key in ("id", "card_id", "cardId"):
            value = result.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None
    if isinstance(result, int) and not isinstance(result, bool):
        return result
    return None


# ── Quest parsing / composition ────────────────────────────────────────


def _is_checkbox_line(line: str) -> bool:
    """True for a quest or any checkbox-like variant (sanitization only).

    Uses the tolerant ``_QUEST_LIKE_RE`` so no line any consumer could parse as
    a quest survives ``clean_prose``.
    """
    return _QUEST_LIKE_RE.match(line) is not None


def _single_line_quest_text(text: str) -> Optional[str]:
    """Return stripped ``text`` when it is single-line, else ``None`` (W-d).

    Quest text is composed into a ``- [ ] <text>`` line. A ``\\n``/``\\r`` in
    the title would let it inject extra lines — including an already-checked
    ``- [x]`` — so a multi-line title is rejected before any Deck write.
    """
    if text is None:
        return None
    if "\n" in text or "\r" in text:
        return None
    return text.strip()


def extract_quests(description: str) -> list[dict[str, Any]]:
    """Parse markdown checkbox lines from a card description.

    Returns ``[{"line_no", "done", "text"}, ...]`` in document order.
    ``line_no`` is the 0-based index into ``description.split("\\n")`` so
    callers can preserve the raw line byte-identically. ``done`` is a bool.
    """
    quests: list[dict[str, Any]] = []
    for line_no, raw in enumerate(description.split("\n")):
        match = _CHECKBOX_RE.match(raw.strip())
        if match is None:
            continue
        quests.append(
            {
                "line_no": line_no,
                "done": match.group(1).lower() == "x",
                "text": match.group(2).strip(),
            }
        )
    return quests


def clean_prose(prose: str) -> str:
    """Return prose with every markdown checkbox line omitted (D3).

    This is the exact cleaning ``update_description`` applies before composing
    the Deck description: checkbox lines (including ``- [x]``) are dropped so
    prose can never introduce a quest. Mission creation reuses it to honor the
    "no quest is created" contract (D2/D9, Req 1).
    """
    return "\n".join(
        line for line in (prose or "").split("\n") if not _is_checkbox_line(line)
    ).strip()


# ── Public operations ──────────────────────────────────────────────────


def read_card(
    board_id: int,
    stack_id: int,
    card_id: int,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Read and normalize a Deck card for replica recovery.

    Returns the normalized card dict (``title``, ``description``, …) or
    ``(None, err)`` when the bridge is unavailable. Used by ``sync_task`` to
    re-read the authoritative card before refreshing the local replica (D7).
    """
    return _read_card(board_id, stack_id, card_id)



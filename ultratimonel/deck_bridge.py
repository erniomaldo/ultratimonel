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
    """Normalize a ``deck_get_card`` payload to a single card dict, or None.

    A dict is only accepted when it actually has the shape of a card: a
    non-empty ``title`` and a ``description`` field. Any other payload — a
    textual error (``{"type": "text", "text": "Deck unavailable"}``), an HTML
    gateway page wrapped in a content block, or a missing/empty title — yields
    ``None`` so callers fail with ``unexpected Deck response shape`` instead of
    overwriting the card with ``title=''`` and losing the title and its quests.
    """
    candidate = card
    if isinstance(candidate, list) and candidate:
        candidate = candidate[0]

    if not isinstance(candidate, dict):
        return None

    # Defensive double-unwrap for http-to-stdio content blocks.
    text = _as_text(candidate)
    if text is not None:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list) and parsed:
            candidate = parsed[0]
        elif parsed is not None:
            candidate = parsed

    if not isinstance(candidate, dict):
        return None
    if not candidate.get("title"):
        return None
    if "description" not in candidate:
        return None
    return candidate


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


def create_card(
    board_id: int,
    stack_id: int,
    title: str,
    description: str = "",
) -> tuple[Optional[int], Optional[str]]:
    """Create a Deck card in ``stack_id``. Returns ``(card_id, err)``."""
    result, err = _deck_call(
        "deck_create_card",
        {
            "board_id": board_id,
            "stack_id": stack_id,
            "title": title,
            "description": description,
        },
    )
    if result is None:
        return None, err or "unavailable"
    card_id = _extract_card_id(result)
    if card_id is None:
        return None, "unexpected Deck response shape"
    return card_id, None


def update_title(
    board_id: int,
    stack_id: int,
    card_id: int,
    title: str,
) -> tuple[Optional[bool], Optional[str]]:
    """Update a card's title while preserving its description byte-identically."""
    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, err
    description = card.get("description", "") or ""
    return _write_card(board_id, stack_id, card_id, title, description)


def update_description(
    board_id: int,
    stack_id: int,
    card_id: int,
    prose: str,
) -> tuple[Optional[bool], Optional[str]]:
    """Update a card's prose without touching its quests (D3).

    Every checkbox line in the current description is preserved
    byte-identically and in its original relative order. Checkbox lines in the
    incoming ``prose`` are omitted so prose cannot introduce a quest.
    """
    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, err

    title = card.get("title", "") or ""
    if not title:
        # Baseline guard: never write a card whose title could not be resolved.
        return None, "unexpected Deck response shape"
    current = card.get("description", "") or ""
    original_lines = current.split("\n")
    preserved = [
        original_lines[q["line_no"]] for q in extract_quests(current)
    ]

    cleaned = clean_prose(prose)

    if preserved:
        quest_block = "\n".join(preserved)
        new_description = f"{cleaned}\n\n{quest_block}" if cleaned else quest_block
    else:
        new_description = cleaned

    return _write_card(board_id, stack_id, card_id, title, new_description)


def append_quest(
    board_id: int,
    stack_id: int,
    card_id: int,
    text: str,
) -> tuple[Optional[int], Optional[str]]:
    """Append ``- [ ] text`` to the card. Returns ``(position, err)``.

    ``position`` is the 0-based index of the new quest among the card's
    quests. The quest is written with ``done=false``. Multi-line ``text`` is
    rejected (``quest_text_multiline``) so it cannot compose extra checkboxes.
    """
    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, err

    clean = _single_line_quest_text(text)
    if clean is None:
        return None, "quest_text_multiline"

    title = card.get("title", "") or ""
    current = card.get("description", "") or ""
    position = len(extract_quests(current))
    new_line = f"- [ ] {clean}"

    if current.strip():
        new_description = current.rstrip("\n") + "\n" + new_line
    else:
        new_description = new_line

    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return position, None


def update_quest(
    board_id: int,
    stack_id: int,
    card_id: int,
    position: int,
    text: str,
) -> tuple[Optional[bool], Optional[str]]:
    """Surgically rewrite one quest line, keeping ``done=false``.

    Only the targeted quest line changes; every other line stays
    byte-identical. Multi-line ``text`` is rejected
    (``quest_text_multiline``) so it cannot compose extra checkboxes.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    clean = _single_line_quest_text(text)
    if clean is None:
        return None, "quest_text_multiline"

    if position < 0 or position >= len(quests):
        return None, "quest_position_out_of_range"

    target = quests[position]
    raw = lines[target["line_no"]]
    bullet = "*" if raw.strip().startswith("*") else "-"
    lines[target["line_no"]] = f"{bullet} [ ] {clean}"
    return _write_card(board_id, stack_id, card_id, title, "\n".join(lines))


def complete_quest(
    board_id: int,
    stack_id: int,
    card_id: int,
    position: int,
) -> tuple[Optional[bool], Optional[str]]:
    """Flip ``- [ ]`` to ``- [x]`` at exactly one quest position.

    Only the targeted quest line changes; every other line stays
    byte-identical.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    if position < 0 or position >= len(quests):
        return None, "quest_position_out_of_range"

    line_no = quests[position]["line_no"]
    lines[line_no] = re.sub(r"\[ \]", "[x]", lines[line_no], count=1)
    return _write_card(board_id, stack_id, card_id, title, "\n".join(lines))


def _read_lines_and_quests(
    board_id: int,
    stack_id: int,
    card_id: int,
) -> tuple[Optional[str], Optional[list[str]], list[dict[str, Any]], Optional[str]]:
    """Read a card and return ``(title, raw_lines, parsed_quests, err)``."""
    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, None, [], err
    current = card.get("description", "") or ""
    return card.get("title", "") or "", current.split("\n"), extract_quests(current), None

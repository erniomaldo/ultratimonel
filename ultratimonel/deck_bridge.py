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
* Description writes fail closed when the replica is the only evidence that a
  checklist exists: a fresh read that yields no quest lines while the replica
  knows N > 0 quests is treated as a suspicious read, not as a human decision
  to delete the checklist (card #218, forum #1). No write happens in that case.
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
    "update_title_record",
    "update_description",
    "write_description",
    "clean_prose",
    "append_quest",
    "append_quest_record",
    "append_quests_record",
    "update_quest",
    "update_quest_record",
    "delete_quest_record",
    "delete_quest_record_by_marker",
    "reorder_quests_record",
    "reorder_quests_record_by_marker",
    "complete_quest",
    "complete_quest_identity",
    "migrate_description_to_markers",
    "compose_quest_line",
    "sanitize_quest_text",
    "classify_identity",
    "extract_quests",
    "read_card",
    "ERR_EMPTY_DESCRIPTION",
    "ERR_QUESTS_MISSING",
    "ERR_QUEST_PRESERVATION_MISMATCH",
    "ERR_LEGACY_IDENTITY",
    "ERR_MARKER_NOT_FOUND",
    "ERR_MARKER_DUPLICATE",
    "IDENTITY_MARKER",
    "IDENTITY_LEGACY",
    "IDENTITY_MIXED",
    "IDENTITY_EMPTY",
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

# Quest identity marker (card #218, quest 4). Deck renders markdown with
# ``html: false``, so an HTML comment would be escaped and shown as text. An
# empty link with a fragment is invisible in the rendered UI, survives the
# ``href`` and does not navigate:
#
#     - [ ] text [](#q:11403)
#
# The marker is composed by the server, never by the model/agent, and it is
# not part of the quest text returned to the user.
_MARKER_RE = re.compile(r"\s*\[\]\(#q:(\d+)\)\s*$")
_MARKER_TOKEN_RE = re.compile(r"\s*\[\]\(#q:\d+\)\s*")

IDENTITY_MARKER = "marker"
IDENTITY_LEGACY = "legacy"
IDENTITY_MIXED = "mixed"
IDENTITY_EMPTY = "empty"

ERR_LEGACY_IDENTITY = "legacy_identity"
ERR_MARKER_NOT_FOUND = "marker_not_found"
ERR_MARKER_DUPLICATE = "marker_duplicate"

# Fail-closed error codes for a suspicious description read (card #218,
# forum #1). ``update_description`` refuses to write when the fresh read shows
# no quest lines while the replica knows quests for the mission: the most
# likely cause is a stale/empty read, and writing would silently delete the
# card's checklist.
ERR_EMPTY_DESCRIPTION = "deck_description_empty_but_replica_has_quests"
ERR_QUESTS_MISSING = "deck_description_missing_quests_but_replica_has_them"
ERR_QUEST_PRESERVATION_MISMATCH = "quest_preservation_mismatch"


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


def _split_marker(body: str) -> tuple[str, Optional[int]]:
    """Split a trailing ``[](#q:{id})`` marker off a quest body.

    ``body`` is the checkbox payload after the ``[ ]``/``[x]`` state. The
    marker is only recognized at the very end of the line, so ordinary text
    that happens to contain a marker-like fragment is left untouched.
    """
    match = _MARKER_RE.search(body)
    if match is None:
        return body, None
    return body[: match.start()].rstrip(), int(match.group(1))


def sanitize_quest_text(text: str) -> Optional[str]:
    """Return server-safe single-line quest text, or ``None`` when invalid.

    Rejects ``\\n``/``\\r`` (they could compose extra checkbox lines) and
    strips any marker the caller tried to inject: the id is server-owned and
    must never be forged by the model.
    """
    clean = _single_line_quest_text(text)
    if clean is None:
        return None
    clean = _MARKER_TOKEN_RE.sub(" ", clean).strip()
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    return clean or None


def compose_quest_line(
    text: str,
    quest_id: int,
    *,
    done: bool = False,
    bullet: str = "-",
) -> str:
    """Compose the canonical marked quest line.

    Format: ``- [ ] text [](#q:{id})`` — the marker always trails the line,
    separated by one space. Any marker already present in ``text`` is removed
    so the server-owned id can never be forged or duplicated.
    """
    clean = sanitize_quest_text(text)
    if clean is None:
        raise ValueError("quest_text_invalid")
    if bullet not in ("-", "*"):
        bullet = "-"
    state = "x" if done else " "
    return f"{bullet} [{state}] {clean} [](#q:{int(quest_id)})"


def extract_quests(description: str) -> list[dict[str, Any]]:
    """Parse markdown checkbox lines from a card description.

    Returns ``[{"line_no", "done", "text", "quest_id"}, ...]`` in document
    order. ``line_no`` is the 0-based index into ``description.split("\\n")`` so
    callers can preserve the raw line byte-identically. ``done`` is a bool.
    ``quest_id`` is the id carried by a trailing ``[](#q:{id})`` marker, or
    ``None`` for a legacy line (which is never assigned an invented id).
    ``text`` never includes the marker.
    """
    quests: list[dict[str, Any]] = []
    for line_no, raw in enumerate(description.split("\n")):
        match = _CHECKBOX_RE.match(raw.strip())
        if match is None:
            continue
        text, quest_id = _split_marker(match.group(2).strip())
        quests.append(
            {
                "line_no": line_no,
                "done": match.group(1).lower() == "x",
                "text": text,
                "quest_id": quest_id,
            }
        )
    return quests


def classify_identity(description: str) -> str:
    """Classify a description's quest identity.

    * ``marker``: at least one quest and every quest carries a marker.
    * ``legacy``: quests exist and none carry a marker.
    * ``mixed``: some quests carry a marker and some do not.
    * ``empty``: the description has no quests.
    """
    quests = extract_quests(description)
    if not quests:
        return IDENTITY_EMPTY
    marked = sum(1 for quest in quests if quest.get("quest_id") is not None)
    if marked == len(quests):
        return IDENTITY_MARKER
    if marked == 0:
        return IDENTITY_LEGACY
    return IDENTITY_MIXED


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


def update_title_record(
    board_id: int,
    stack_id: int,
    card_id: int,
    title: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Update a card's title and return the authoritative post-write card.

    Returns ``({"title", "description", "quests"}, None)`` where ``title`` and
    ``description`` are exactly what was written and ``quests`` is the parsed
    checklist of that written description, so the caller can refresh its
    replica from the acknowledged outcome in the same operation (no extra
    read, no per-quest Deck call).
    """
    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, err
    description = card.get("description", "") or ""
    ok, werr = _write_card(board_id, stack_id, card_id, title, description)
    if ok is None:
        return None, werr
    return {
        "title": title,
        "description": description,
        "quests": extract_quests(description),
    }, None


def update_title(
    board_id: int,
    stack_id: int,
    card_id: int,
    title: str,
) -> tuple[Optional[bool], Optional[str]]:
    """Update a card's title while preserving its description byte-identically."""
    record, err = update_title_record(board_id, stack_id, card_id, title)
    if record is None:
        return None, err
    return True, None


def _compose_description(
    card: dict[str, Any],
    prose: str,
    expected_quest_count: Optional[int],
) -> tuple[Optional[str], Optional[str]]:
    """Compose the next description from one freshly read card.

    Returns ``(new_description, err)``. Checkbox lines from the current
    description are copied byte-identically, in their original relative order;
    checkbox lines in ``prose`` are dropped. The composed result is validated
    against the full preserved list (not a count) before returning.

    Fail-closed: when the fresh read shows zero quest lines but the replica
    knows ``expected_quest_count`` > 0 quests, the read is suspicious and the
    caller must NOT write. An empty description is reported distinctly from a
    non-empty description whose checklist vanished, so the error says which.
    """
    title = card.get("title", "") or ""
    if not title:
        # Never write a card whose title could not be resolved.
        return None, "unexpected Deck response shape"

    current = card.get("description", "") or ""
    original_lines = current.split("\n")
    preserved = [
        original_lines[q["line_no"]] for q in extract_quests(current)
    ]

    if expected_quest_count and expected_quest_count > 0 and not preserved:
        if not current.strip():
            return None, ERR_EMPTY_DESCRIPTION
        return None, ERR_QUESTS_MISSING

    cleaned = clean_prose(prose)
    if preserved:
        quest_block = "\n".join(preserved)
        new_description = f"{cleaned}\n\n{quest_block}" if cleaned else quest_block
    else:
        new_description = cleaned

    composed_lines = new_description.split("\n")
    after = [
        composed_lines[q["line_no"]]
        for q in extract_quests(new_description)
    ]
    if after != preserved:
        # Byte-identity is a full-list invariant, never a count comparison.
        return None, ERR_QUEST_PRESERVATION_MISMATCH

    return new_description, None


def write_description(
    board_id: int,
    stack_id: int,
    card_id: int,
    prose: str,
    *,
    expected_quest_count: Optional[int] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Fresh read + compose + Deck write of a card description.

    Returns ``({"title", "description", "quests"}, None)`` on success, where
    ``description`` is exactly what was written to Deck and ``quests`` is the
    parsed checklist of that written description (same order and state), so the
    caller can refresh its replica from the authoritative outcome.

    Returns ``(None, err)`` without writing anything when the fresh read fails,
    the response is not a card, or the read is suspicious (see
    ``_compose_description``).
    """
    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, err

    new_description, cerr = _compose_description(
        card, prose, expected_quest_count
    )
    if new_description is None:
        return None, cerr

    title = card.get("title", "") or ""
    ok, werr = _write_card(
        board_id, stack_id, card_id, title, new_description
    )
    if ok is None:
        return None, werr

    return {
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


def update_description(
    board_id: int,
    stack_id: int,
    card_id: int,
    prose: str,
    *,
    expected_quest_count: Optional[int] = None,
) -> tuple[Optional[bool], Optional[str]]:
    """Update a card's prose without touching its quests (D3).

    Every checkbox line in the current description is preserved
    byte-identically and in its original relative order. Checkbox lines in the
    incoming ``prose`` are omitted so prose cannot introduce a quest.

    Every write starts from a fresh read of the card. When
    ``expected_quest_count`` (the replica's quest count for this mission) is
    N > 0 and the fresh read yields no checkbox lines, the write is refused and
    ``(None, err)`` is returned: a stale/empty read must never silently delete
    a checklist. Use ``write_description`` when the caller needs the exact
    description that was written.
    """
    result, err = write_description(
        board_id,
        stack_id,
        card_id,
        prose,
        expected_quest_count=expected_quest_count,
    )
    if result is None:
        return None, err
    return True, None


def append_quest_record(
    board_id: int,
    stack_id: int,
    card_id: int,
    text: str,
    *,
    quest_id: Optional[int] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Append ``- [ ] text [](#q:{quest_id})`` and return the written card.

    When ``quest_id`` is supplied (the normal server path) the new line carries
    its stable identity marker. ``None`` keeps the unmarked form for internal
    callers that explicitly want a legacy line.

    Returns ``({"position", "title", "description", "quests"}, None)``. The
    description is exactly what was written to Deck, so the caller refreshes
    its replica from the acknowledged outcome without a second read.
    """
    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, err

    clean = sanitize_quest_text(text)
    if clean is None:
        raw = text or ""
        code = "quest_text_multiline" if ("\n" in raw or "\r" in raw) else "quest_text_empty"
        return None, code

    title = card.get("title", "") or ""
    current = card.get("description", "") or ""
    position = len(extract_quests(current))
    if quest_id is None:
        new_line = f"- [ ] {clean}"
    else:
        new_line = compose_quest_line(clean, quest_id)

    if current.strip():
        new_description = current.rstrip("\n") + "\n" + new_line
    else:
        new_description = new_line

    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "position": position,
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


def append_quests_record(
    board_id: int,
    stack_id: int,
    card_id: int,
    entries: list[tuple[str, int]],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Append several marked quest lines in ONE Deck read + ONE Deck write.

    ``entries`` is a sequence of ``(text, quest_id)`` pairs. Every entry is
    validated and sanitized before the card is read, so an invalid entry never
    touches Deck. The server owns every ``quest_id``; they are composed into
    the lines as ``[](#q:{id})`` markers.

    Returns ``({"position", "positions", "title", "description", "quests"},
    None)`` where ``positions`` are the 0-based quest indexes of the new lines,
    in request order, and ``description`` is exactly what was written to Deck.
    """
    if not entries:
        return None, "quest_text_empty"

    composed: list[str] = []
    for text, quest_id in entries:
        clean = sanitize_quest_text(text)
        if clean is None:
            raw = text or ""
            code = (
                "quest_text_multiline"
                if ("\n" in raw or "\r" in raw)
                else "quest_text_empty"
            )
            return None, code
        composed.append(compose_quest_line(clean, quest_id))

    card, err = _read_card(board_id, stack_id, card_id)
    if card is None:
        return None, err

    title = card.get("title", "") or ""
    current = card.get("description", "") or ""
    position = len(extract_quests(current))
    block = "\n".join(composed)

    if current.strip():
        new_description = current.rstrip("\n") + "\n" + block
    else:
        new_description = block

    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "position": position,
        "positions": list(range(position, position + len(composed))),
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


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
    record, err = append_quest_record(board_id, stack_id, card_id, text)
    if record is None:
        return None, err
    return record["position"], None


def update_quest_record(
    board_id: int,
    stack_id: int,
    card_id: int,
    position: int,
    text: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Rewrite one quest line and return the authoritative post-write card.

    Returns ``({"position", "title", "description", "quests"}, None)``. The
    description is exactly what was written to Deck, so the caller refreshes
    its replica from the acknowledged outcome without a second read.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    clean = sanitize_quest_text(text)
    if clean is None:
        raw = text or ""
        code = "quest_text_multiline" if ("\n" in raw or "\r" in raw) else "quest_text_empty"
        return None, code

    if position < 0 or position >= len(quests):
        return None, "quest_position_out_of_range"

    target = quests[position]
    raw = lines[target["line_no"]]
    bullet = "*" if raw.strip().startswith("*") else "-"
    if target.get("quest_id") is not None:
        # Keep the existing identity marker: a text edit must never rename the
        # quest or turn a marked mission into a mixed one.
        lines[target["line_no"]] = compose_quest_line(
            clean, target["quest_id"], bullet=bullet
        )
    else:
        lines[target["line_no"]] = f"{bullet} [ ] {clean}"
    new_description = "\n".join(lines)
    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "position": position,
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


def delete_quest_record(
    board_id: int,
    stack_id: int,
    card_id: int,
    position: int,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Remove exactly one quest line and return the authoritative card.

    Only the targeted quest's line is removed; every other line (prose and the
    remaining quests, with their state) stays byte-identical and in order.

    Returns ``({"position", "title", "description", "quests"}, None)``. The
    description is exactly what was written to Deck, so the caller refreshes
    its replica from the acknowledged outcome without a second read.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    if position < 0 or position >= len(quests):
        return None, "quest_position_out_of_range"

    del lines[quests[position]["line_no"]]
    new_description = "\n".join(lines)
    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "position": position,
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


def delete_quest_record_by_marker(
    board_id: int,
    stack_id: int,
    card_id: int,
    quest_id: int,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Remove the one quest line whose marker is ``quest_id``.

    Refuses (``legacy_identity``) unless EVERY quest on the card carries a
    marker: a legacy or mixed mission has no stable identity to delete by, and
    falling back to a position would silently rename the survivors. The read
    happens before any write, so a refusal mutates nothing.

    Returns ``({"position", "quest_id", "identity", "title", "description",
    "quests"}, None)`` on success.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    if classify_identity("\n".join(lines)) != IDENTITY_MARKER:
        return None, ERR_LEGACY_IDENTITY

    matches = [q for q in quests if q.get("quest_id") == int(quest_id)]
    if not matches:
        return None, ERR_MARKER_NOT_FOUND
    if len(matches) > 1:
        return None, ERR_MARKER_DUPLICATE

    position = quests.index(matches[0])
    del lines[matches[0]["line_no"]]
    new_description = "\n".join(lines)
    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "position": position,
        "quest_id": int(quest_id),
        "identity": IDENTITY_MARKER,
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


def reorder_quests_record(
    board_id: int,
    stack_id: int,
    card_id: int,
    ordered_positions: list[int],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Reorder the card's quest lines into ``ordered_positions``.

    Each element is the CURRENT 0-based quest position whose raw line takes the
    next quest slot. The list must be a permutation of the card's quest
    positions; anything else is rejected without a write.

    The raw lines move verbatim, so text and ``[x]``/``[ ]`` state are
    preserved. Non-quest lines keep their slots. One Deck read and one Deck
    description write.

    Returns ``({"order", "title", "description", "quests"}, None)``.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    positions = list(ordered_positions or [])
    if sorted(positions) != list(range(len(quests))):
        return None, "quest_reorder_invalid_order"

    slot_line_nos = [q["line_no"] for q in quests]
    ordered_raw = [lines[quests[p]["line_no"]] for p in positions]
    for slot, raw in zip(slot_line_nos, ordered_raw):
        lines[slot] = raw

    new_description = "\n".join(lines)
    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "order": positions,
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


def reorder_quests_record_by_marker(
    board_id: int,
    stack_id: int,
    card_id: int,
    ordered_ids: list[int],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Reorder the card's quest lines by their markers.

    ``ordered_ids`` are the marker ids (which equal the replica quest ids) in
    the desired order. Refuses (``legacy_identity``) unless every quest carries
    a marker. Each raw line moves verbatim, so ids, text and ``[x]``/``[ ]``
    state are preserved with zero positional identity.

    Returns ``({"order", "identity", "title", "description", "quests"}, None)``.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    if classify_identity("\n".join(lines)) != IDENTITY_MARKER:
        return None, ERR_LEGACY_IDENTITY

    current_ids = [q["quest_id"] for q in quests]
    ordered = [int(quest_id) for quest_id in (ordered_ids or [])]
    if len(ordered) != len(set(ordered)) or sorted(ordered) != sorted(current_ids):
        return None, "quest_reorder_mismatch"

    by_marker = {q["quest_id"]: q for q in quests}
    slot_line_nos = [q["line_no"] for q in quests]
    ordered_raw = [lines[by_marker[quest_id]["line_no"]] for quest_id in ordered]
    for slot, raw in zip(slot_line_nos, ordered_raw):
        lines[slot] = raw

    new_description = "\n".join(lines)
    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "order": ordered,
        "identity": IDENTITY_MARKER,
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


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
    record, err = update_quest_record(board_id, stack_id, card_id, position, text)
    if record is None:
        return None, err
    return True, None


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


def complete_quest_identity(
    board_id: int,
    stack_id: int,
    card_id: int,
    *,
    quest_id: int,
    item_index: int,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Close one quest, locating it by marker first and by position only if safe.

    * Fully marked mission: the line MUST carry ``#q:{quest_id}``; a missing
      marker fails closed (``marker_not_found``) instead of guessing a position.
    * Legacy mission (no markers): the existing positional behaviour is kept.
    * Mixed mission: the marker wins when the target line has one; otherwise the
      positional fallback is used because that line has no identity yet.

    Returns ``({"identity": "marker"|"positional", "line_no", "quest_id"},
    None)``. Only the target line changes; every other line stays
    byte-identical.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    identity = classify_identity("\n".join(lines))
    if identity == IDENTITY_EMPTY:
        return None, "quest_not_found"

    matches = [q for q in quests if q.get("quest_id") == int(quest_id)]
    if len(matches) > 1:
        return None, ERR_MARKER_DUPLICATE
    if matches:
        target = matches[0]
        used = IDENTITY_MARKER
    else:
        if identity == IDENTITY_MARKER:
            return None, ERR_MARKER_NOT_FOUND
        if item_index < 0 or item_index >= len(quests):
            return None, "quest_position_out_of_range"
        target = quests[item_index]
        used = "positional"

    line_no = target["line_no"]
    lines[line_no] = re.sub(r"\[ \]", "[x]", lines[line_no], count=1)
    ok, werr = _write_card(board_id, stack_id, card_id, title, "\n".join(lines))
    if ok is None:
        return None, werr
    return {
        "identity": used,
        "line_no": line_no,
        "quest_id": int(quest_id),
    }, None


def migrate_description_to_markers(
    board_id: int,
    stack_id: int,
    card_id: int,
    ids_by_position: list[int],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Add a ``[](#q:{id})`` marker to every quest line of one card.

    ``ids_by_position`` is the replica's quest id for each quest line in
    document order. Existing markers are preserved verbatim; only unmarked
    lines gain one, so the operation is idempotent and never renames a quest.

    A fully marked card returns ``status="already_migrated"`` with no write.
    A mixed or legacy card is rewritten in one description write, preserving
    line order, bullet char, text and ``[x]``/``[ ]`` state.

    Returns ``({"status", "migrated_ids", "quest_ids", "title", "description",
    "quests"}, None)``. Every failure happens before the write.
    """
    title, lines, quests, err = _read_lines_and_quests(board_id, stack_id, card_id)
    if lines is None:
        return None, err

    if not quests:
        return None, "quest_migration_empty"

    identity = classify_identity("\n".join(lines))
    if identity == IDENTITY_MARKER:
        return {
            "status": "already_migrated",
            "migrated_ids": [],
            "quest_ids": [q["quest_id"] for q in quests],
            "title": title,
            "description": "\n".join(lines),
            "quests": quests,
        }, None

    if len(ids_by_position) != len(quests):
        return None, "quest_migration_replica_mismatch"

    new_lines = list(lines)
    migrated_ids: list[int] = []
    quest_ids: list[int] = []
    for idx, quest in enumerate(quests):
        existing = quest.get("quest_id")
        if existing is not None:
            quest_ids.append(int(existing))
            continue
        candidate = ids_by_position[idx]
        if candidate is None:
            return None, "quest_migration_missing_id"
        marker_id = int(candidate)
        raw = new_lines[quest["line_no"]]
        stripped = raw.strip()
        bullet = "*" if stripped.startswith("*") else "-"
        state = "x" if quest["done"] else " "
        new_lines[quest["line_no"]] = (
            f"{bullet} [{state}] {quest['text']} [](#q:{marker_id})"
        )
        migrated_ids.append(marker_id)
        quest_ids.append(marker_id)

    if len(set(quest_ids)) != len(quest_ids):
        return None, "quest_migration_identity_collision"

    # The markers that will exist after the rewrite must be exactly the
    # replica's ids, otherwise delete/reorder would address ids the card does
    # not carry. Fail closed instead of half-migrating.
    if sorted(quest_ids) != sorted(int(i) for i in ids_by_position):
        return None, "quest_migration_replica_mismatch"

    new_description = "\n".join(new_lines)
    ok, werr = _write_card(board_id, stack_id, card_id, title, new_description)
    if ok is None:
        return None, werr
    return {
        "status": "migrated",
        "migrated_ids": migrated_ids,
        "quest_ids": quest_ids,
        "title": title,
        "description": new_description,
        "quests": extract_quests(new_description),
    }, None


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

"""
context_extractor.py — Parse sender, topic, project from a message string.

Extraction rules per SDD design §6:
  - sender:   passed through from session / tool arg (default: "user")
  - topic:    first sentence or leading noun phrase of the message
  - project:  matched via known-project regex dict; falls back to topic
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# Known project patterns (case-insensitive)
# These are generic regex patterns — NOT machine-specific data.
KNOWN_PROJECTS: dict[str, str] = {
    r"\bultratimonel\b": "ultratimonel",
    r"\bnocturno\b": "nocturno",
    r"\bmessagens\b": "messagens",
    r"\bhermes\b": "hermes",
    r"\bopenspec\b": "openspec",
    # Collectives
    r"\blecutra\s+r[áa]pida\b|\blecutra\b": "lectura-rapida",
    r"\bvoy\s+rojo\b": "voy-rojo",
    r"\bkgd\b|\bsolar\b": "kgd-solar",
    r"\bquickintegratia\b|\bqia\b": "quickintegratia",
    r"\bquiero\s+c[óo]digo\b": "quiero-codigo",
    r"\bquickflorence\b": "quickflorence",
    r"\bagenda\s+sencilla\b": "agenda-sencilla",
    r"\bmi\s+mundo\b": "mi-mundo",
    r"\bagentcheckpoint\b": "agentcheckpoint",
    r"\bpictomcp\b": "pictomcp",
    r"\bpuppetablechar\w*mcp\b|\bpuppetmcp\b": "puppetablecharmcp",
    r"\bchatwoot\b": "chatwoot-mcp",
}

# ── Project Map Loading ────────────────────────────────────────────────
# PROJECT_DECK_MAP and PROJECT_COLLECTIVE_MAP contain Nextcloud IDs that
# are specific to the user's instance.  They live in a gitignored JSON
# file (project_maps.json at the repo root) so the repo stays portable.
#
# Inline defaults are provided for backward compatibility — existing
# installs continue to work.  New projects should be added ONLY to the
# JSON file, never to the inline dicts.

_PROJECT_MAPS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "project_maps.json"
)


def _load_project_maps() -> dict:
    """Load user-specific project maps from gitignored JSON file.

    Returns dict with keys "collectives" and "decks", each being a
    ``{slug: id}`` dict.  Returns empty dicts if the file doesn't exist.
    """
    maps: dict = {"collectives": {}, "decks": {}}
    if not os.path.exists(_PROJECT_MAPS_PATH):
        return maps
    try:
        with open(_PROJECT_MAPS_PATH) as f:
            user_maps = json.load(f)
        if isinstance(user_maps, dict):
            maps.update(user_maps)
        else:
            logger.warning("project_maps.json: expected dict, got %s", type(user_maps))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load project_maps.json: %s", exc)
    return maps


_USER_MAPS = _load_project_maps()

# ── Collectives ─────────────────────────────────────────────────────────

# Inline defaults for existing installs.  Overridden by project_maps.json.
PROJECT_COLLECTIVE_MAP: dict[str, int] = {
    "lectura-rapida": 1,
    "voy-rojo": 6,
    "kgd-solar": 7,
    "quickintegratia": 8,
    "quiero-codigo": 9,
    "quickflorence": 10,
    "agenda-sencilla": 11,
    "mi-mundo": 12,
    "agentcheckpoint": 13,
    "pictomcp": 14,
    "puppetablecharmcp": 15,
    "chatwoot-mcp": 16,
}
PROJECT_COLLECTIVE_MAP.update(_USER_MAPS.get("collectives") or {})

# ── Deck Boards ─────────────────────────────────────────────────────────

# Inline defaults for existing installs.  Overridden by project_maps.json.
PROJECT_DECK_MAP: dict[str, int] = {
    "voy-rojo": 7,
    "kgd-solar": 8,
    "quickintegratia": 9,
    "lectura-rapida": 10,
    "quiero-codigo": 11,
    "quickflorence": 13,
    "agenda-sencilla": 14,
    "agentcheckpoint": 15,
    "pictomcp": 16,
    "puppetablecharmcp": 17,
    "chatwoot-mcp": 18,
    "mi-mundo": 20,
    # NOTE: "ultratimonel": 21 was removed from inline defaults in
    #       PR #3 feedback — it belongs in project_maps.json.
}
PROJECT_DECK_MAP.update(_USER_MAPS.get("decks") or {})

# Remove any keys with falsy (non-positive) values  # guard against bad data
PROJECT_COLLECTIVE_MAP = {k: v for k, v in PROJECT_COLLECTIVE_MAP.items() if v}
PROJECT_DECK_MAP = {k: v for k, v in PROJECT_DECK_MAP.items() if v}

# Priority-ordered regex: first match wins
_PROJECT_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), name)
    for pattern, name in KNOWN_PROJECTS.items()
]


def extract_context(
    message: str,
    session_id: str,
    sender: str = "user",
) -> dict:
    """Parse sender, topic, and project from the given message.

    Args:
        message:    The user's raw message string.
        session_id: Active Hermes session identifier.
        sender:     Optional sender override (e.g. from session metadata).

    Returns:
        dict with keys: sender, topic, project, session_id.
    """
    message = message or ""

    # Topic: first sentence (split on .!? or first ~60 chars)
    topic = message.strip()
    if topic:
        # Grab the first sentence
        sent_match = re.split(r"[.!?]+", topic, maxsplit=1)
        topic = sent_match[0].strip()
        # Cap at 100 chars
        if len(topic) > 100:
            topic = topic[:100].rsplit(" ", 1)[0] + "…"
    if not topic:
        topic = "general"

    # Project: match known patterns in the full message
    project = topic  # fallback
    lowest_pos = len(message)
    for pattern, proj in _PROJECT_PATTERNS:
        match = pattern.search(message)
        if match and match.start() < lowest_pos:
            lowest_pos = match.start()
            project = proj

    return {
        "sender": sender,
        "topic": topic,
        "project": project,
        "session_id": session_id,
    }

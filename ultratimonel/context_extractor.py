"""
context_extractor.py — Parse sender, topic, project from a message string.

Extraction rules per SDD design §6:
  - sender:   passed through from session / tool arg (default: "user")
  - topic:    first sentence or leading noun phrase of the message
  - project:  matched via known-project regex dict; falls back to topic
"""

import logging
import re

logger = logging.getLogger(__name__)

# Known project patterns (case-insensitive)
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
    r"\bquiero\s+c[oó]digo\b": "quiero-codigo",
    r"\bquickflorence\b": "quickflorence",
    r"\bagenda\s+sencilla\b": "agenda-sencilla",
    r"\bmi\s+mundo\b": "mi-mundo",
    r"\bagentcheckpoint\b": "agentcheckpoint",
    r"\bpictomcp\b": "pictomcp",
    r"\bpuppetablechar\w*mcp\b|\bpuppetmcp\b": "puppetablecharmcp",
    r"\bchatwoot\b": "chatwoot-mcp",
}

# Project → Nextcloud Collective ID mapping (for gate 1c)
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

# Project → Nextcloud Deck board ID mapping (for gate 1e)
# Replaces the old substring-search-over-all-boards approach.
# Only boards with deletedAt === 0 are mapped here.
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
    "ultratimonel": 21,
}

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

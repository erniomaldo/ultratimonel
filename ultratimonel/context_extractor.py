"""
context_extractor.py — Parse sender, topic, project from a message string.

Extraction rules per SDD design §6:
  - sender:   passed through from session / tool arg (default: "user")
  - topic:    first sentence or leading noun phrase of the message
  - project:  matched via project_maps.json patterns; falls back to topic

⛔ ANTIPATRÓN: No agregues proyectos aquí.
Los proyectos se configuran en project_maps.json (o via env var ULTRATIMONEL_PROJECT_MAPS).
Usa las tools MCP: map_add() / map_setup()
Editar este archivo para agregar proyectos es un error de diseño.
"""

import logging
import re
from typing import Any

from .config_loader import load_project_maps

logger = logging.getLogger(__name__)

# ── Load project maps from external JSON ──────────────────────────────────
# These are loaded once at import time. They can be reloaded via
# reload_project_maps() if the JSON changes at runtime.

_project_maps: dict[str, dict[str, Any]] = {}
_project_patterns: list[tuple[re.Pattern, str]] = []


def reload_project_maps(path: str | None = None) -> None:
    """Reload project maps from the JSON file.

    Call this after modifying project_maps.json to pick up changes
    without restarting the server.
    """
    global _project_maps, _project_patterns
    _project_maps = load_project_maps(path)

    # Build regex patterns from each project's patterns list
    _project_patterns = []
    for project_name, config in _project_maps.items():
        raw_patterns = config.get("patterns", [])
        for pat in raw_patterns:
            # Escape to word-boundary regex (case-insensitive)
            regex = r"\b" + re.escape(pat.lower()) + r"\b"
            try:
                compiled = re.compile(regex, re.IGNORECASE)
                _project_patterns.append((compiled, project_name))
            except re.error as exc:
                logger.warning("Invalid pattern '%s' for project '%s': %s", pat, project_name, exc)

    logger.info("Loaded %d project(s) with %d pattern(s)", len(_project_maps), len(_project_patterns))


# Load on import
reload_project_maps()


# ── Public helpers for map access ─────────────────────────────────────────

def get_project_maps() -> dict[str, dict[str, Any]]:
    """Return the current project maps."""
    return _project_maps


def is_known_project(project: str) -> bool:
    """Check if a project name is in the known project maps."""
    return project in _project_maps


# ── Context extraction ────────────────────────────────────────────────────


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
    # ⛔ Si no hay match, project se queda como "unknown" (no topic)
    project = "unknown"
    lowest_pos = len(message)
    for pattern, proj in _project_patterns:
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

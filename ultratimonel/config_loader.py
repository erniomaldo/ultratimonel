"""config_loader.py — Load project configuration from external JSON.

Externalizes KNOWN_PROJECTS, PROJECT_DECK_MAP, and PROJECT_COLLECTIVE_MAP
to a JSON file so users never need to edit Python code.

⛔ ANTIPATRÓN: No hardcodees proyectos aquí.
Los proyectos se configuran en project_maps.json.
Usa las tools MCP: map_add() / map_setup()
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default path for project maps
_DEFAULT_MAPS_PATH = os.path.expanduser("~/.hermes/ultratimonel/project_maps.json")


def resolve_maps_path() -> str:
    """Resolve the project maps file path.

    Resolution order (12-factor app, factor III):
    1. ULTRATIMONEL_PROJECT_MAPS env var
    2. ~/.hermes/ultratimonel/project_maps.json

    Returns:
        Absolute path to the JSON file.
    """
    return os.environ.get(
        "ULTRATIMONEL_PROJECT_MAPS",
        _DEFAULT_MAPS_PATH,
    )



def load_project_maps(path: str | None = None) -> dict[str, dict[str, Any]]:
    """Load project maps from external JSON file.

    Graceful degradation: returns empty dict if file doesn't exist,
    so the server starts even without configuration.

    Returns:
        Dict mapping project slug -> {patterns, deck_board_id, collective_id}
    """
    maps_path = path or resolve_maps_path()

    if not os.path.isfile(maps_path):
        logger.info("No project maps file at %s — running in degraded mode", maps_path)
        return {}

    try:
        with open(maps_path, encoding="utf-8") as f:
            data: dict[str, dict[str, Any]] = json.load(f)
        logger.info("Loaded %d project(s) from %s", len(data), maps_path)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load project maps from %s: %s", maps_path, exc)
        return {}


def save_project_maps(
    maps: dict[str, dict[str, Any]],
    path: str | None = None,
) -> None:
    """Save project maps to external JSON file.

    Creates parent directories if they don't exist.

    Args:
        maps: Project maps dict.
        path: Override path (uses resolve_maps_path() if None).
    """
    maps_path = path or resolve_maps_path()
    parent = os.path.dirname(maps_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    with open(maps_path, "w", encoding="utf-8") as f:
        json.dump(maps, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d project(s) to %s", len(maps), maps_path)

"""Shared registry for season metadata and existing season-specific profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = Path("config/seasons.json")


def _registry(root: Path = ROOT) -> dict[str, Any]:
    path = root / REGISTRY_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Unable to load season registry: {path}") from error
    seasons = value.get("seasons") if isinstance(value, dict) else None
    if not isinstance(seasons, dict):
        raise ValueError(f"Invalid season registry: {path}")
    return seasons


def season_codes(root: Path = ROOT) -> list[str]:
    """Return registered season codes in registry order."""
    return list(_registry(root))


def load_season(season: str, root: Path = ROOT) -> dict[str, Any]:
    """Return one season's metadata, resolving no paths or rule semantics."""
    seasons = _registry(root)
    try:
        value = seasons[season]
    except KeyError as error:
        raise ValueError(f"Unknown season {season!r}; registered seasons: {', '.join(seasons)}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Invalid registry entry for season {season!r}")
    return {"season": season, **value}

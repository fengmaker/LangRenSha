"""Shared rules, with season schedules and import settings from the registry."""
from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from .season_config import load_season
else:
    from season_config import load_season

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = Path("config/game_rules.json")


def load_rules(root: Path = ROOT) -> dict:
    return json.loads((root / RULES_PATH).read_text(encoding="utf-8"))


def load_scope(season: str, root: Path = ROOT) -> dict:
    return {"season": season, **load_season(season, root)["scope"]}


def load_formal_rules(season: str, root: Path = ROOT) -> dict:
    """Adapt shared rules to the existing season importers' input shape."""
    shared = load_rules(root)
    settings = load_season(season, root)["formal_import"]
    result = {"season": season, **shared, **settings}
    if "board_counts" in settings:
        result["boards"] = {
            code: {**shared["boards"][code], "scored_count": count}
            for code, count in settings["board_counts"].items()
        }
    result["confirmed_rule_handling"] = {
        **shared.get("confirmed_rule_handling", {}),
        **settings.get("confirmed_rule_handling", {}),
    }
    return result

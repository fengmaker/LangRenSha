"""Store the common ranking boards once per static player season range."""

from typing import Any


SNAPSHOT_SCHEMA_VERSION = 2


def split_player_rankings(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    stats = profile.get("stats")
    boards = {"ranking_boards": stats["ranking_boards"]} if isinstance(stats, dict) and "ranking_boards" in stats else {}
    shared = {key: profile[key] for key in ("release_id", "analytics_version", "scope")}
    shared.update(boards)
    if not boards:
        return profile, shared
    compact = {**profile, "stats": {key: value for key, value in stats.items() if key != "ranking_boards"}}
    return compact, shared


def restore_player_rankings(profile: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    for key in ("release_id", "analytics_version", "scope"):
        if profile.get(key) != shared.get(key):
            raise ValueError(f"Shared player rankings {key} binding differs from the profile")
    if "ranking_boards" not in shared:
        return profile
    if not isinstance(profile.get("stats"), dict) or "ranking_boards" in profile["stats"]:
        raise ValueError("Shared player rankings require a compact player stats object")
    return {**profile, "stats": {**profile["stats"], "ranking_boards": shared["ranking_boards"]}}

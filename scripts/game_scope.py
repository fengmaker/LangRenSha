"""User-selected scope for structured game records; raw media stays independent."""
from __future__ import annotations

from pathlib import Path
import re

from rule_config import load_scope
from season_config import season_codes

ROOT = Path(__file__).resolve().parents[1]
POLICY_REL = "config/seasons.json"


def load_policy(root: Path = ROOT, season: str = "S22") -> dict:
    if not (Path(root) / POLICY_REL).is_file():
        return {}
    if season not in season_codes(Path(root)):
        return {}
    return load_scope(season, Path(root))


def exclusion_reason(entry: dict, *, root: Path = ROOT) -> str | None:
    season = entry.get("season", "S22")
    if season not in {"S21", "S22"}:
        return None
    policy = load_policy(root, season)
    if entry.get("phase") in policy.get("excluded_phases", []):
        return "用户要求移除表演赛" if season == "S22" else "S21表演赛与特辑不进入正式对局"
    if entry.get("date") in policy.get("excluded_dates", []):
        return "用户确认2026-07-03为娱乐局，移除且不计入正式比赛"
    if season == "S22":
        from board_catalog import BOARD_CODES, canonical_board_name
        board = entry.get("board") or entry.get("board_name")
        code = BOARD_CODES.get(canonical_board_name(board))
        if code in policy.get("excluded_board_codes", []):
            return "用户确认该版型为娱乐版型，不计分且不进入正式统计"
    bvid = entry.get("bvid")
    if not bvid and isinstance(entry.get("slug"), str):
        match = re.search(r"BV[0-9A-Za-z]+", entry["slug"])
        bvid = match[0] if match else None
    if bvid in policy.get("excluded_bvids", []):
        return f"该局已按用户要求移出{season}对局范围"
    return None

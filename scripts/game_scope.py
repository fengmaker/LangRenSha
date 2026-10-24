"""User-selected scope for structured game records; raw media stays independent."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
POLICY_REL = "config/S22_game_scope.json"


def load_policy(root: Path = ROOT) -> dict:
    path = Path(root) / POLICY_REL
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("season") != "S22":
        raise ValueError("对局范围配置的赛季无效")
    return value


def exclusion_reason(entry: dict, *, root: Path = ROOT) -> str | None:
    if entry.get("season", "S22") != "S22":
        return None
    policy = load_policy(root)
    if entry.get("phase") in policy.get("excluded_phases", []):
        return "用户要求移除表演赛"
    if entry.get("date") in policy.get("excluded_dates", []):
        return "用户确认2026-07-03为娱乐局，移除且不计入正式比赛"
    bvid = entry.get("bvid")
    if not bvid and isinstance(entry.get("slug"), str):
        match = re.search(r"BV[0-9A-Za-z]+", entry["slug"])
        bvid = match[0] if match else None
    if bvid in policy.get("excluded_bvids", []):
        return "该局已按用户要求移出S22对局范围"
    return None

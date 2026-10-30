"""Validate exported review feedback; --apply stores it separately from source facts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from website.api.bluffs import load_review, physical_wolf, review_items, source_fingerprint

TARGET = ROOT / "data/extractions/S22/bluff_review/user_confirmed.json"
DECISIONS = {"yes", "no", "uncertain", "comment", "later", ""}


def source_games(season: str = "S22") -> list[dict]:
    from website.api import publisher

    entries, _, _ = publisher.load_publication(ROOT, season)
    all_names = {seat.get("name") for entry in entries for seat in entry["dossier"].get("seats", [])}
    if season == "S23":
        ids = {
            name: str(uuid.uuid5(publisher.PERSON_NAMESPACE, name.strip().casefold()))
            for name in all_names if isinstance(name, str)
        }
    else:
        ids = {name: name for name in all_names if isinstance(name, str)}
    games = []
    for entry in entries:
        game = publisher._public_game(
            entry["dossier"], entry["voting"], entry["endgame"], entry["audit"],
            entry["board"], ids, source_voting=entry.get("source_voting"),
            derivations=entry.get("derivations"),
        )
        game["bvid"] = entry["bvid"]
        games.append(game)
    return games


def validate_feedback(value: dict, games: list[dict], season: str = "S22") -> dict[str, dict]:
    if (not isinstance(value, dict) or value.get("kind") != "s22_bluff_feedback"
            or value.get("schema_version") != 1 or value.get("season") != season
            or not isinstance(value.get("records"), list)):
        raise ValueError(f"不是 {season} 悍跳复核反馈文件")
    indexed = {game["id"]: game for game in games}
    current_items = {
        row["review_id"]: row
        for row in review_items(games, load_review(season))
    }
    records = {}
    for row in value["records"]:
        if not isinstance(row, dict):
            raise ValueError("反馈记录格式错误")
        game = indexed.get(row.get("game_id"))
        if game is None:
            raise ValueError(f"未知对局：{row.get('game_id')}")
        if not isinstance(row.get("source_fingerprint"), str) or not re.fullmatch(
                r"[a-f0-9]{64}", row["source_fingerprint"]):
            raise ValueError("反馈缺少有效的整局来源指纹")
        seat = next((seat for seat in game["seats"] if type(row.get("seat")) is int
                     and seat["seat"] == row["seat"]), None)
        review_id = f"{game['bvid']}:{row.get('seat')}"
        current = current_items.get(review_id)
        if row.get("bvid") != game["bvid"] or row.get("review_id") != review_id or review_id in records:
            raise ValueError(f"反馈编号错误或重复：{review_id}")
        already_included = bool(current and current.get("manual_included") is True)
        if (seat is None or (not physical_wolf(game, seat) and not already_included) or row.get("name") != seat["name"]
                or row.get("physical_role") != seat.get("role")):
            raise ValueError(f"选手或狼人底牌不匹配：{review_id}")
        claim_signature = row.get("claim_fingerprint")
        current = current_items.get(review_id)
        if claim_signature is not None:
            if (not isinstance(claim_signature, str) or current is None
                    or claim_signature != current.get("claim_fingerprint")):
                raise ValueError(f"悍跳结论或证据依据已变化，请重新复核：{review_id}")
        elif row.get("source_fingerprint") != source_fingerprint(game):
            raise ValueError(f"原始事实已变化，请重新复核：{review_id}")
        if "manual_success" in row:
            success_value = row["manual_success"]
            success_signature = row.get("success_fingerprint")
            if ((success_value is not None and type(success_value) is not bool)
                    or not isinstance(success_signature, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", success_signature)
                    or current is None
                    or current.get("decision") != "yes"
                    or current.get("claim_needs_review")
                    or success_signature != current.get("success_fingerprint")
                    or claim_signature != current.get("claim_fingerprint")):
                raise ValueError(f"悍跳成功依据或当前悍跳结论已变化：{review_id}")
        decision, notes, day, role = (row.get(key) for key in ("decision", "notes", "claim_day", "claimed_role"))
        if (not isinstance(decision, str) or decision not in DECISIONS or not isinstance(notes, str)
                or len(notes) > 4000 or day not in (None, 1, 2, "later") or type(day) is bool
                or role not in (None, "预言家", "通灵师")):
            raise ValueError(f"结论、天数或意见格式错误：{review_id}")
        normalization = row.get("normalization_notes")
        if normalization is not None and (not isinstance(normalization, list) or len(normalization) > 20
                or any(not isinstance(note, str) or len(note) > 1000 for note in normalization)):
            raise ValueError(f"整理说明格式错误：{review_id}")
        if not decision and not notes.strip() and "manual_success" not in row:
            continue
        records[review_id] = {key: row.get(key) for key in (
            "review_id", "game_id", "bvid", "seat", "name", "physical_role", "source_fingerprint",
            "claim_fingerprint", "success_fingerprint", "inference_version", "claimed_role", "claim_day",
            "notes", "updated_at",
            "input_values", "normalization_notes", "feedback_origin")}
        if 'manual_success' in row:
            records[review_id]['manual_success'] = row['manual_success']
        records[review_id]["decision"] = decision or "comment"
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--apply", action="store_true", help="保存已验证的反馈；默认只预检")
    args = parser.parse_args()
    value=json.loads(args.feedback.read_text(encoding="utf-8-sig"))
    season=value.get('season') if isinstance(value,dict) else None
    if season not in {'S22','S23'}:raise ValueError('不支持的悍跳反馈赛季')
    records = validate_feedback(value, source_games(season),season)
    target=TARGET if season=='S22' else ROOT/'data/extractions/S23/bluff_review/user_confirmed.json'
    if args.apply:
        target.parent.mkdir(parents=True,exist_ok=True)
        previous = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"schema_version": 1, "season": season, "records": {}}
        previous["records"].update(records)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
    print(json.dumps({"valid_records": len(records), "applied": args.apply}, ensure_ascii=False))


if __name__ == "__main__":
    main()

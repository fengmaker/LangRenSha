"""Validate exported review feedback; --apply stores it separately from source facts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from website.api.bluffs import physical_wolf, source_fingerprint

TARGET = ROOT / "data/extractions/S22/bluff_review/user_confirmed.json"
DECISIONS = {"yes", "no", "uncertain", "comment", "later", ""}


def source_games() -> list[dict]:
    games = []
    for path in sorted((ROOT / "data/games/S22").glob("*/dossier.json")):
        game = json.loads(path.read_text(encoding="utf-8"))
        game["id"] = game["slug"]
        game["bvid"] = re.search(r"BV[0-9A-Za-z]{10}", path.parent.name)[0]
        game["voting"] = json.loads((path.parent / "voting.json").read_text(encoding="utf-8"))
        games.append(game)
    return games


def validate_feedback(value: dict, games: list[dict]) -> dict[str, dict]:
    if (not isinstance(value, dict) or value.get("kind") != "s22_bluff_feedback"
            or value.get("schema_version") != 1 or value.get("season") != "S22"
            or not isinstance(value.get("records"), list)):
        raise ValueError("不是 S22 悍跳复核反馈文件")
    indexed = {game["id"]: game for game in games}
    records = {}
    for row in value["records"]:
        if not isinstance(row, dict):
            raise ValueError("反馈记录格式错误")
        game = indexed.get(row.get("game_id"))
        if game is None:
            raise ValueError(f"未知对局：{row.get('game_id')}")
        seat = next((seat for seat in game["seats"] if type(row.get("seat")) is int
                     and seat["seat"] == row["seat"]), None)
        review_id = f"{game['bvid']}:{row.get('seat')}"
        if row.get("bvid") != game["bvid"] or row.get("review_id") != review_id or review_id in records:
            raise ValueError(f"反馈编号错误或重复：{review_id}")
        if (seat is None or not physical_wolf(game, seat) or row.get("name") != seat["name"]
                or row.get("physical_role") != seat.get("role")):
            raise ValueError(f"选手或狼人底牌不匹配：{review_id}")
        if row.get("source_fingerprint") != source_fingerprint(game):
            raise ValueError(f"原始事实已变化，请重新复核：{review_id}")
        decision, notes, day, role = (row.get(key) for key in ("decision", "notes", "claim_day", "claimed_role"))
        if (not isinstance(decision, str) or decision not in DECISIONS or not isinstance(notes, str)
                or len(notes) > 4000 or day not in (None, 1, 2, "later") or type(day) is bool
                or role not in (None, "预言家", "通灵师")):
            raise ValueError(f"结论、天数或意见格式错误：{review_id}")
        normalization = row.get("normalization_notes")
        if normalization is not None and (not isinstance(normalization, list) or len(normalization) > 20
                or any(not isinstance(note, str) or len(note) > 1000 for note in normalization)):
            raise ValueError(f"整理说明格式错误：{review_id}")
        if not decision and not notes.strip():
            continue
        records[review_id] = {key: row.get(key) for key in (
            "review_id", "game_id", "bvid", "seat", "name", "physical_role", "source_fingerprint",
            "inference_version", "claimed_role", "claim_day", "notes", "updated_at",
            "input_values", "normalization_notes", "feedback_origin")}
        records[review_id]["decision"] = decision or "comment"
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--apply", action="store_true", help="保存已验证的反馈；默认只预检")
    args = parser.parse_args()
    records = validate_feedback(json.loads(args.feedback.read_text(encoding="utf-8-sig")), source_games())
    if args.apply:
        previous = json.loads(TARGET.read_text(encoding="utf-8")) if TARGET.exists() else {"schema_version": 1, "season": "S22", "records": {}}
        previous["records"].update(records)
        temporary = TARGET.with_suffix(".tmp")
        temporary.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(TARGET)
    print(json.dumps({"valid_records": len(records), "applied": args.apply}, ensure_ascii=False))


if __name__ == "__main__":
    main()

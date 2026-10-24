"""Create, check, import and audit scored S22 entries using the formal rulebook."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

import batch_s22 as batch
from database import ReviewError
from formal_rule_checks import final_gaps, issues, registry
from game_records import empty_event, import_game, template, validate, validate_batch
from game_scope import exclusion_reason

REPORT = batch.ROOT / "data/reports/S22_正式规则校验.json"


def make_entry(board_code, event_date, game_number, rounds=1):
    if board_code not in registry()["boards"]:
        raise ReviewError("该版型不属于S22计分正式版型")
    date.fromisoformat(event_date)
    if type(game_number) is not int or game_number < 1 or rounds < 1:
        raise ReviewError("局次和轮数必须是正整数")
    board = template(board_code)
    return {
        "slug": f"S22-{event_date}-g{game_number:02d}-{board_code}",
        "season": "S22", "date": event_date, "phase": "regular", "episode": None,
        "day_in_episode": None, "game_number": game_number, "board": board_code,
        "winner": None, "roster": [], "commentators": [], "referee": None,
        "files": [],
        "seats": [{"seat": n, "name": None, "role": None, "faction": None,
                   "learning_target": None, "learned_role": None}
                  for n in range(1, board["seat_count"] + 1)],
        "rounds": [{"number": n,
                    "night": [empty_event(s["code"]) for s in board["night_slots"]],
                    "day": [empty_event(s["code"]) for s in board["day_slots"]]}
                   for n in range(1, rounds + 1)],
    }


def check(value, *, final=False, check_files=True):
    validate_batch(value, check_files=check_files, check_rules=False)
    problems = []

    def add(code, message, severity="error"):
        problems.append({"code": code, "severity": severity, "round": None,
                         "slot": None, "message": message})

    reason = exclusion_reason(value)
    if reason:
        add("excluded_game", "娱乐局或表演赛不能进入正式计分范围：" + reason)
    formal = registry()
    if value.get("season") != "S22" or value["board"] not in formal["boards"]:
        add("not_formal_board", "该局不属于本赛季正式版型")
    else:
        problems.extend(issues(value))
        if value.get("phase") not in {"regular", "finals_week"}:
            add("formal_phase", "正式对局阶段必须为regular或finals_week")
        number = value.get("game_number")
        if number is None:
            add("unknown_game_number", "局次待核，不能据此生成已确认赛程", "pending")
        elif str(number) in formal["rotation"]["daily_game_slots"] and value["board"] not in formal["rotation"]["daily_game_slots"][str(number)]:
            add({1: "first_board", 2: "second_board", 3: "third_board"}[number], "版型与正式比赛该局次的固定/轮换安排不符")
        elif number > 3 and value["board"] != "mechanical_wolf_seer":
            # This scored exception was explicitly confirmed by the user.
            confirmed = any(e["date"] == value["date"] and e["game_number"] == number
                            and e["board_code"] == value["board"] and e["counted"]
                            for e in formal["rotation"]["scored_exception_games"])
            if not confirmed:
                add("extra_board_confirmation", "非机械狼加赛需确认是否计分，并登记赛程例外", "pending")
        if value.get("winner") not in {None, "good", "werewolf"}:
            add("formal_winner", "本季正式局胜方为好人或狼人；个人胜利另行判断")
        board = template(value["board"])
        if board.get("dynamic_roles"):
            pool = board["role_pool"]
            for role, amount in Counter(p["role"] for p in value["seats"] if p["role"]).items():
                if role not in pool or amount > pool[role]:
                    add("role_pool", "实际发牌超过候选牌池：" + role)
        if final:
            for field in final_gaps(value):
                add("unresolved_field", "最终录入仍有未知字段：" + field, "pending")
            if not value.get("commentators"):
                add("unknown_commentators", "最终录入缺少解说", "pending")
            if len(value["roster"]) != board["seat_count"] or set(value["roster"]) != {p["name"] for p in value["seats"]}:
                add("roster", "最终录入的排班与座位姓名必须齐全且一致", "pending")
            if not any(f.get("role") == "audio" for f in value["files"]):
                add("audio_source", "最终录入需要主音频源文件关联", "pending")
            if not problems:
                try:
                    validate(value, check_files=check_files)
                except ReviewError as exc:
                    add("complete_validation", str(exc))
    errors = [p for p in problems if p["severity"] == "error"]
    pending = [p for p in problems if p["severity"] == "pending"]
    return {"slug": value["slug"], "mode": "final" if final else "draft",
            "valid": not errors and (not final or not pending),
            "errors": errors, "pending": pending}


def audit():
    state = batch.load_state()
    items = []
    for bvid, entry in state["items"].items():
        path = batch.ROOT / entry["output_dir"] / "dossier.json"
        try:
            result = check(batch.read_json(path), final=False)
        except (ReviewError, ValueError, KeyError, TypeError) as exc:
            result = {"valid": False, "errors": [{"code": "structure", "message": str(exc)}], "pending": []}
        result.update(bvid=bvid, file=batch.relative(path), sha256=batch.digest(path))
        value = batch.read_json(path)
        result["unknown_events"] = sum(e["action"] == "unknown" for r in value["rounds"] for phase in ("night", "day") for e in r[phase])
        items.append(result)
    report = {"generated_at": batch.now(), "rule_file": "config/S22_formal_rules.json",
              "rule_sha256": batch.digest(batch.ROOT / "config/S22_formal_rules.json"),
              "rulebook": "docs/12_S22正式版型规则与录入流程.md",
              "mode": "known_facts_only", "games": len(items),
              "games_with_contradictions": sum(bool(i["errors"]) for i in items),
              "error_count": sum(len(i["errors"]) for i in items),
              "pending_count": sum(len(i["pending"]) for i in items),
              "unknown_event_count": sum(i["unknown_events"] for i in items),
              "unconfirmed_rule_groups": len(registry()["pending_rules"]),
              "note": "现存档案是允许未知的资料档案。本报告不自动改写事实，也不将通过草稿检查等同于最终确认。",
              "items": items}
    calendar = {}
    for entry in state["items"].values():
        calendar.setdefault(entry["date"], set()).add(entry.get("game_number"))
    report["catalogue_missing_daily_slots"] = [
        {"date": event_date, "game_number": number, "status": "catalogue_gap"}
        for event_date, present in sorted(calendar.items()) for number in (1, 2, 3) if number not in present]
    batch.atomic_json(REPORT, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--board", required=True)
    init.add_argument("--date", required=True)
    init.add_argument("--game-number", type=int, required=True)
    init.add_argument("--rounds", type=int, default=1)
    init.add_argument("--output", type=Path, required=True)
    for name in ("check", "import"):
        sub = commands.add_parser(name)
        sub.add_argument("file", type=Path)
        sub.add_argument("--final", action="store_true")
    commands.add_parser("audit")
    args = parser.parse_args()
    if args.command == "init":
        value = make_entry(args.board, args.date, args.game_number, args.rounds)
        if args.output.exists():
            raise ReviewError("输出文件已存在，拒绝覆盖")
        batch.atomic_json(args.output, value)
        result = {"created": str(args.output), "status": "draft"}
    elif args.command == "audit":
        report = audit()
        result = {k: v for k, v in report.items() if k != "items"}
        result["report"] = batch.relative(REPORT)
    else:
        value = batch.read_json(args.file)
        result = check(value, final=args.final)
        if args.command == "import" and result["valid"]:
            if not any(f.get("role") == "audio" for f in value["files"]):
                raise ReviewError("入库前必须补齐已登记的主音频来源关联")
            result["receipt"] = import_game(value, allow_incomplete=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command in {"check", "import"} and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

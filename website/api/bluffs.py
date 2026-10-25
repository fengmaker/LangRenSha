"""Evidence-backed, provisional bluff statistics over the published season."""
from __future__ import annotations

from functools import lru_cache
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from website.api.analytics import effective_faction

ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "bluffs"
WOLF_ROLES = {"狼人", "狼王", "机械狼", "盗宝大师", "假面", "诡术师", "典狱长", "黑狼王", "白狼王"}
METHODOLOGY = [
    "悍跳必须同时满足狼人底牌和公开自称预言家或通灵师；同一选手同一局只计一次，好人诈身份、狼混及仅说自己取得某技能不直接计入。",
    "主要核查第一天的警上、PK及警下发言，直到实际入夜或自爆结束白天；竞选延期到次日单独标注。晚期复盘可佐证首日，但不能把后日发言直接当作首日自称。",
    "悍跳成功按狼队战术结果判断：该悍跳者竞选拿到警徽，或第一天最终被放逐的是好人，满足任一条件即成功；不要求其本人归票或过半好人跟票。",
    "以最终放逐结果为准，不把平票首轮、夜间死亡、技能出局、首日自爆中断后的次日放逐算作首日成功。",
    "悍跳身份由转写、复盘及警徽票交叉推断；仅上警、成为候选人或拿徽不能单独证明悍跳。用户明确填写的复核结论及备注优先，已确认记录和助手推断分别标注。",
    "悍跳归属不确定时不计为已识别次数；成功结果不确定时排除在成功率分母之外，并列入待复核。三项技能正确率仍留空。",
]


def physical_wolf(game: dict, seat: dict) -> bool:
    return bool(seat.get("role") in WOLF_ROLES
                and effective_faction(game, seat) == "werewolf")


def source_fingerprint(game: dict) -> str:
    """Bind inference to identity, vote and result facts, ignoring presentation."""
    voting = game.get("voting") or {}
    core = {
        "id": game.get("id", game.get("slug")), "date": str(game.get("date", "")),
        "seats": [{key: seat.get(key) for key in ("seat", "name", "role")}
                  for seat in sorted(game.get("seats", []), key=lambda row: row["seat"])],
        "results": [{"day": round_.get("number"), **{key: event.get(key) for key in
                    ("slot", "action", "actor", "targets")}}
                    for round_ in game.get("rounds", []) for event in round_.get("day", [])
                    if event.get("slot") in {"sheriff_result", "exile_result", "badge", "self_destruct"}],
        "days": [{key: day.get(key) for key in ("day", "sheriff", "exile")}
                 for day in voting.get("days", [])],
        "ballots": [{**{key: ballot.get(key) for key in
                     ("id", "day", "kind", "stage", "number", "status", "winner")},
                     "votes": [{key: vote.get(key) for key in ("voter", "target", "state")}
                               for vote in ballot.get("votes", [])]}
                    for ballot in voting.get("ballots", [])],
    }
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()


@lru_cache(maxsize=8)
def load_review(season: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", season):
        return {"games": []}
    path = ASSET_ROOT / f"{season}.json"
    if not path.is_file():
        return {"games": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _final_exile(game: dict, day: int) -> tuple[int | None, bool, list[str]]:
    """Prefer the final result event; never treat an early PK winner as final."""
    events = [event for round_ in game.get("rounds", []) if round_.get("number") == day
              for event in round_.get("day", []) if event.get("slot") == "exile_result"]
    targets = {target for event in events if event.get("action") == "exile"
               for target in event.get("targets", [])}
    statuses = {row.get("exile") for row in (game.get("voting") or {}).get("days", [])
                if row.get("day") == day}
    if len(targets) == 1:
        if "interrupted_self_destruct" in statuses:
            return None, False, ["首日放逐结果与自爆中断记录冲突"]
        return next(iter(targets)), True, []
    if len(targets) > 1:
        return None, False, ["首日存在多个最终放逐目标"]
    if statuses.intersection({"interrupted_self_destruct", "not_held", "not_applicable"}):
        return None, True, []
    ballots = [ballot for ballot in (game.get("voting") or {}).get("ballots", [])
               if ballot.get("day") == day and ballot.get("kind") == "exile"]
    if ballots:
        final = ballots[-1]
        if type(final.get("winner")) is int:
            return final["winner"], True, []
    if any(event.get("action") in {"none", "not_held"} for event in events):
        return None, True, []
    return None, False, ["首日最终放逐结果缺失"]


def _badge_result(game: dict, seat: int, claim_day: int = 1) -> tuple[bool | None, list[str]]:
    elected = {target for round_ in game.get("rounds", []) for event in round_.get("day", [])
               if event.get("slot") == "sheriff_result" and event.get("action") == "elected"
               for target in event.get("targets", [])}
    if elected:
        eligible = {target for round_ in game.get("rounds", []) if round_.get("number", 0) >= claim_day
                    for event in round_.get("day", [])
                    if event.get("slot") == "sheriff_result" and event.get("action") == "elected"
                    for target in event.get("targets", [])}
        return seat in eligible, []
    ballots = [ballot for ballot in (game.get("voting") or {}).get("ballots", [])
               if ballot.get("kind") == "sheriff"]
    if ballots and type(ballots[-1].get("winner")) is int:
        return ballots[-1]["winner"] == seat and ballots[-1].get("day", 0) >= claim_day, []
    no_badge = any(
        event.get("action") == "none" and (
            event.get("slot") == "sheriff_result"
            or (round_.get("number") == 1 and event.get("slot") == "badge"))
        for round_ in game.get("rounds", []) for event in round_.get("day", [])
    )
    if no_badge:
        return False, []
    if ballots:
        final = ballots[-1]
        eligible = final.get("eligible_voters")
        votes = final.get("votes", [])
        recorded = {vote.get("voter") for vote in votes if vote.get("state") in {"cast", "abstained"}}
        tallies = Counter(vote.get("target") for vote in votes
                          if vote.get("state") == "cast" and vote.get("target") is not None)
        if (final.get("stage") == "pk" and final.get("status") == "complete"
                and isinstance(eligible, list) and set(eligible).issubset(recorded)
                and tallies and sum(value == max(tallies.values()) for value in tallies.values()) > 1):
            return False, []
    days = (game.get("voting") or {}).get("days", [])
    statuses = {row.get("sheriff") for row in days}
    first_statuses = {row.get("sheriff") for row in days if row.get("day") == 1}
    if "badge_lost" in statuses or first_statuses.intersection({"not_held", "not_applicable"}):
        return False, []
    seats = {row["seat"] for row in game.get("seats", [])}
    if seats and any(row.get("day") == 1 and row.get("off_police") == []
                     and set(row.get("on_police") or []) == seats
                     for row in (game.get("voting") or {}).get("registrations", [])):
        # A complete registration with everyone on police leaves no sheriff voters.
        return False, []
    return None, ["最终警长竞选结果缺失"]


def evaluate_success(game: dict, seat_number: int, claim_day: int | str | None = 1) -> dict:
    if claim_day not in {1, 2}:
        return {"value": None, "reasons": [], "questions": ["悍跳发生天数待确认，暂不判断成功"]}
    badge, badge_questions = _badge_result(game, seat_number, claim_day)
    target, final_known, questions = _final_exile(game, 1)
    target_seat = next((seat for seat in game.get("seats", []) if seat["seat"] == target), None)
    faction = effective_faction(game, target_seat) if target_seat else None
    reasons = []
    if badge:
        reasons.append({"kind": "elected_badge", "text": "该悍跳者竞选获得警徽"})
    if claim_day == 1 and final_known and target is not None and faction == "good":
        reasons.append({"kind": "first_day_good_exiled", "target": target,
                        "text": f"首日最终放逐{target}号好人，按狼队战术结果计成功"})
    if reasons:
        return {"value": True, "reasons": reasons, "questions": []}
    if final_known and target is not None and faction not in {"good", "werewolf"}:
        questions.append("首日最终被放逐者的个人胜利阵营不明确")
    if badge is False and final_known and not questions:
        return {"value": False, "reasons": [{"kind": "neither_condition",
                "text": "未在起跳后竞选拿徽，也不满足首日悍跳放逐好人的条件"}], "questions": []}
    return {"value": None, "reasons": [], "questions": list(dict.fromkeys(questions + badge_questions))}


def review_items(games: list[dict], payload: dict) -> list[dict]:
    indexed = {row["game_id"]: row for row in payload.get("games", [])}
    output = []
    for game in games:
        game_id = game.get("id", game.get("slug"))
        source = indexed.get(game_id)
        valid = source is not None and source.get("source_fingerprint") == source_fingerprint(game)
        assessments = {row["seat"]: row for row in source.get("assessments", [])} if valid else {}
        for seat in game.get("seats", []):
            if not physical_wolf(game, seat):
                continue
            record = assessments.get(seat["seat"])
            questions = list(record.get("review_questions", [])) if record else []
            decision = record.get("decision", "uncertain") if record else "uncertain"
            if not valid:
                questions.append("尚无对应推断记录" if source is None else "原始身份或结果已变化，需要重核推断")
            elif record is None:
                questions.append("该狼人座位尚无悍跳判断")
            elif record.get("name") != seat["name"] or record.get("physical_role") != seat.get("role"):
                decision = "uncertain"
                questions.append("推断中的选手或底牌与当前发布记录不一致")
            if decision == "yes" and not record.get("evidence") and record.get("verification_status") != "user_confirmed":
                decision = "uncertain"
                questions.append("悍跳判断缺少定位证据")
            success = evaluate_success(game, seat["seat"], record.get("claim_day", 1)) if decision == "yes" else {
                "value": None, "reasons": [], "questions": []}
            questions.extend(success["questions"])
            if decision == "uncertain" and not questions:
                questions.append("发言归属或是否正式跳信息神待复核")
            bvid = (game.get("source") or {}).get("bvid", source.get("bvid") if source else None)
            evidence = []
            for entry in record.get("evidence", []) if record else []:
                public = {key: entry[key] for key in ("kind", "text", "start_ms", "end_ms", "interpretation")
                          if key in entry}
                if isinstance(bvid, str) and re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
                    start = entry.get("start_ms")
                    seconds = max(0, int(start / 1000)) if isinstance(start, (int, float)) else 0
                    public["url"] = f"https://www.bilibili.com/video/{bvid}/?t={seconds}"
                evidence.append(public)
            output.append({
                "review_id": f"{bvid}:{seat['seat']}",
                "source_fingerprint": source_fingerprint(game),
                "game_id": game_id, "date": str(game.get("date", "")),
                "game_number": game.get("game_number"),
                "bvid": bvid,
                "player_id": seat.get("person_id"), "seat": seat["seat"], "name": seat["name"],
                "physical_role": seat.get("role"), "claimed_role": record.get("claimed_role") if record else None,
                "decision": decision, "confidence": record.get("confidence", "low") if record else "low",
                "claim_day": record.get("claim_day") if record else None,
                "first_day_claim": record.get("first_day_claim") if record else None,
                "decision_note": record.get("decision_note", "") if record else "",
                "verification_status": record.get("verification_status", "assistant_inferred") if record else "assistant_inferred",
                "evidence": evidence,
                "success": success["value"], "success_reasons": success["reasons"],
                "review_questions": list(dict.fromkeys(questions)),
                "needs_review": decision == "uncertain" or bool(questions),
            })
    return output


def aggregate_bluffs(games: list[dict], payload: dict) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict] = {}
    for game in games:
        for seat in game.get("seats", []):
            if seat.get("person_id") is not None:
                stats.setdefault(str(seat["person_id"]), {
                    "bluff_count": 0, "bluff_count_complete": True, "bluff_pending_games": 0,
                    "bluff_review_count": 0, "bluff_success_rate": {
                        "numerator": 0, "denominator": 0, "rate": None, "excluded": 0, "game_ids": []},
                })
    for item in review_items(games, payload):
        player_id = str(item["player_id"])
        if player_id not in stats:
            continue
        row = stats[player_id]
        metric = row["bluff_success_rate"]
        row["bluff_review_count"] += int(item["needs_review"])
        if item["decision"] == "uncertain":
            row["bluff_count_complete"] = False
            row["bluff_pending_games"] += 1
            metric["excluded"] += 1
        elif item["decision"] == "yes":
            row["bluff_count"] += 1
            if item["success"] is None:
                metric["excluded"] += 1
            else:
                metric["denominator"] += 1
                metric["numerator"] += int(item["success"])
                metric["game_ids"].append(item["game_id"])
    for row in stats.values():
        metric = row["bluff_success_rate"]
        metric["rate"] = metric["numerator"] / metric["denominator"] if metric["denominator"] else None
    return stats

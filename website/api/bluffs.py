"""Final bluff outcomes and their statistics; no historical evidence dependencies."""
from __future__ import annotations
from collections import Counter
from typing import Any
from website.api.analytics import _add_denominator, _add_excluded, _metric_result, _new_metric, effective_faction

WOLF_ROLES = {"狼人", "狼王", "机械狼", "盗宝大师", "假面", "诡术师", "典狱长", "黑狼王", "白狼王", "九尾狐", "狼术师", "狼女孩", "捣蛋鬼"}
def physical_wolf(game: dict, seat: dict) -> bool:
    return bool(seat.get("role") in WOLF_ROLES
                and effective_faction(game, seat) == "werewolf")


def included_in_review(game: dict, seat: dict, assessment: dict | None) -> bool:
    return physical_wolf(game, seat) or bool(
        assessment and assessment.get('manual_included') is True
        and assessment.get('verification_status') == 'user_confirmed'
        and assessment.get('decision') == 'yes')


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


def _badge_result(game: dict, seat: int, claim_day: int = 1,
                  result_review: dict | None = None) -> tuple[bool | None, list[str]]:
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
    if result_review and result_review.get('badge')=='lost' and result_review.get('evidence'):
        return False, []
    return None, ["最终警长竞选结果缺失"]


def evaluate_success(game: dict, seat_number: int, claim_day: int | str | None = 1,
                     *, result_review: dict | None = None) -> dict:
    if type(claim_day) is not int or claim_day < 1:
        return {"value": None, "reasons": [], "questions": ["悍跳发生天数待确认，暂不判断成功"]}
    badge, badge_questions = _badge_result(game, seat_number, claim_day, result_review)
    reasons = []
    if badge:
        reasons.append({"kind": "elected_badge", "text": "该悍跳者竞选获得警徽"})
    if claim_day > 1 and badge is False:
        return {"value": False, "reasons": [{"kind": "later_claim_without_badge",
                "text": "悍跳发生在首日放逐之后，且未在起跳后竞选拿徽；首日放逐不计入这次尝试成功"}], "questions": []}
    if claim_day > 1:
        return {"value": True if badge is True else None, "reasons": reasons,
                "questions": [] if badge is True else badge_questions}
    target, final_known, questions = _final_exile(game, 1)
    target_seat = next((seat for seat in game.get("seats", []) if seat["seat"] == target), None)
    faction = effective_faction(game, target_seat) if target_seat else None
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


def review_items(games: list[dict], payload: dict | None = None) -> list[dict]:
    return [{**row, "date": game["date"], "game_number": game.get("game_number")}
            for game in games for row in game.get("bluffs", [])]


def fully_reviewed_game_count(items: list[dict]) -> int:
    """Count games whose current included records all have final human decisions."""
    by_game: dict[str, list[dict]] = {}
    for item in items:
        by_game.setdefault(item["game_id"], []).append(item)
    return sum(
        bool(rows) and all(
            item["verification_status"] == "user_confirmed"
            for item in rows
        )
        for rows in by_game.values()
    )


def aggregate_bluffs(games: list[dict], payload: dict | None = None) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict] = {}
    items = review_items(games, payload)
    games_by_id = {game.get("id", game.get("slug")): game for game in games}
    by_seat = {(item["game_id"], item["seat"]): item for item in items}
    for game in games:
        for seat in game.get("seats", []):
            if seat.get("person_id") is not None:
                row = stats.setdefault(str(seat["person_id"]), {
                    "bluff_count": 0, "bluff_count_complete": any(g.get("bluff_review_available", False) for g in games), "bluff_pending_games": 0,
                    "bluff_rate": _new_metric(),
                    "bluff_review_count": 0, "bluff_success_rate": _new_metric(),
                    "bluff_badge_count": _new_metric(), "bluff_first_day_exiled": _new_metric(),
                })
                game_id = game.get("id", game.get("slug"))
                item = by_seat.get((game_id, seat["seat"]))
                faction = effective_faction(game, seat)
                if faction == "werewolf" or item and item["manual_included"]:
                    if item and item["decision"] == "uncertain":
                        _add_excluded(row["bluff_rate"])
                    else:
                        _add_denominator(row["bluff_rate"], game_id,
                                         success=bool(item and item["decision"] == "yes"))
                elif faction is None:
                    _add_excluded(row["bluff_rate"])
    for item in items:
        player_id = str(item["player_id"])
        if player_id not in stats:
            continue
        row = stats[player_id]
        metric = row["bluff_success_rate"]
        row["bluff_review_count"] += int(item["needs_review"])
        if item["decision"] == "uncertain":
            row["bluff_count_complete"] = False
            row["bluff_pending_games"] += 1
            _add_excluded(metric)
            _add_excluded(row["bluff_badge_count"])
            _add_excluded(row["bluff_first_day_exiled"])
        elif item["decision"] == "yes":
            row["bluff_count"] += 1
            game = games_by_id[item["game_id"]]
            badge, _ = _badge_result(game, item["seat"])
            target, exile_known, _ = _final_exile(game, 1)
            for key, outcome in (
                    ("bluff_badge_count", badge),
                    ("bluff_first_day_exiled", target == item["seat"] if exile_known else None)):
                if outcome is None:
                    _add_excluded(row[key])
                else:
                    _add_denominator(row[key], item["game_id"], success=outcome)
            if item["success"] is None:
                _add_excluded(metric)
            else:
                _add_denominator(metric, item["game_id"], success=item["success"])
    for row in stats.values():
        for key in ("bluff_rate", "bluff_success_rate", "bluff_badge_count", "bluff_first_day_exiled"):
            row[key] = _metric_result(row[key])
    return stats

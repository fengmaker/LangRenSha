"""Evidence-backed, provisional bluff statistics over the published season."""
from __future__ import annotations

from functools import lru_cache
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from website.api.analytics import _add_denominator, _add_excluded, _metric_result, _new_metric, effective_faction
from website.api.bluff_frames import public_image_url

ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "bluffs"
WOLF_ROLES = {"狼人", "狼王", "机械狼", "盗宝大师", "假面", "诡术师", "典狱长", "黑狼王", "白狼王", "九尾狐", "狼术师"}
METHODOLOGY = [
    "悍跳必须同时满足狼人底牌和公开自称预言家或通灵师；同一选手同一局只计一次，好人诈身份、狼混及仅说自己取得某技能不直接计入。",
    "主要核查第一天的警上、PK及警下发言，直到实际入夜或自爆结束白天；竞选延期到次日单独标注。晚期复盘可佐证首日，但不能把后日发言直接当作首日自称。",
    "悍跳成功按狼队战术结果判断：该悍跳者竞选拿到警徽，或第一天最终被放逐的是好人，满足任一条件即成功；不要求其本人归票或过半好人跟票。",
    "以最终放逐结果为准，不把平票首轮、夜间死亡、技能出局、首日自爆中断后的次日放逐算作首日成功。",
    "悍跳身份由转写、复盘及警徽票交叉推断；仅上警、成为候选人或拿徽不能单独证明悍跳。用户明确填写的复核结论及备注优先，已确认记录和助手推断分别标注。",
    "悍跳归属不确定时不计为已识别次数；成功结果不确定时排除在成功率分母之外，并列入待复核。",
    "悍跳率为悍跳次数除以可判定的狼人阵营出场次数；悍跳归属或阵营未知时排除，用户明确额外纳入的记录按对应复核结果计入。",
]
S23_VIDEO_METHODOLOGY = [
    "优先核对首日警上最后一位发言临近结束时的原视频截图；自爆提前中断时核对中断前画面，必要时补看PK、警下或延期竞选。",
    "导播座位摘要中的验人、身份与警徽流须结合本人发言确认；引用他人、讨论站边和仅缺少摘要均不能单独决定是否悍跳。",
    "正式对局未记录、但法官和终局复盘均明确宣布的警徽流失，可由带定位证据的专项复核补充；与正式当选结果冲突时拒绝采用。",
]


def physical_wolf(game: dict, seat: dict) -> bool:
    return bool(seat.get("role") in WOLF_ROLES
                and effective_faction(game, seat) == "werewolf")


def included_in_review(game: dict, seat: dict, assessment: dict | None) -> bool:
    return physical_wolf(game, seat) or bool(
        assessment and assessment.get('manual_included') is True
        and assessment.get('verification_status') == 'user_confirmed'
        and assessment.get('decision') == 'yes')


def _direct_source_fingerprint(game: dict) -> str:
    """Hash the broad source projection used only to conservatively read legacy rows."""
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


def source_fingerprint(game: dict) -> str:
    """Prefer a validated source binding while its derived view stays unchanged."""
    current = _direct_source_fingerprint(game)
    binding = game.get("bluff_source_binding")
    if isinstance(binding, dict) and set(binding) == {"derived_fingerprint", "source_fingerprint"}:
        derived = binding.get("derived_fingerprint")
        source = binding.get("source_fingerprint")
        if (isinstance(derived, str) and re.fullmatch(r"[a-f0-9]{64}", derived)
                and isinstance(source, str) and re.fullmatch(r"[a-f0-9]{64}", source)
                and derived == current):
            return source
    return current


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def evidence_source_ref(source_path: str) -> str:
    """Return a non-path key for matching a frozen evidence source hash."""
    normalized = source_path.replace("\\", "/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def evidence_source_fingerprint(evidence: list[dict]) -> str:
    """Bind a claim to its text, locator and source content hashes."""
    fields = ("kind", "text", "start_ms", "end_ms", "interpretation", "source_sha256",
              "source_ref", "image_url")
    rows = [{key: entry[key] for key in fields if key in entry}
            for entry in evidence if isinstance(entry, dict)]
    return _fingerprint({"version": 1, "evidence": rows})


def claim_fingerprint(game: dict, assessment: dict) -> str:
    """Hash the identity, claimed turn and evidence needed to decide bluff attribution."""
    seat_number = assessment.get("seat")
    seat = next((row for row in game.get("seats", []) if row.get("seat") == seat_number), None)
    identity = None if seat is None else {
        "seat": seat.get("seat"), "name": seat.get("name"), "role": seat.get("role"),
        # A personal faction change matters only if it changes eligibility for
        # review; manual-included mixed-blood assessments remain eligible.
        "included_in_review": included_in_review(game, seat, assessment),
    }
    evidence = assessment.get("evidence")
    evidence = evidence if isinstance(evidence, list) else []
    frozen_sources = game.get("bluff_evidence_sources")
    evidence_rows = []
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        row = {key: entry[key] for key in (
            "kind", "text", "start_ms", "end_ms", "interpretation", "source_ref", "source_sha256", "image_url"
        ) if key in entry}
        source_ref = entry.get("source_ref")
        if isinstance(source_ref, str):
            # A removed binding or missing source intentionally fingerprints stale.
            row["source_sha256"] = (frozen_sources.get(source_ref)
                                    if isinstance(frozen_sources, dict) else None)
        evidence_rows.append(row)
    evidence_binding = assessment.get("evidence_source_fingerprint")
    if assessment.get("evidence_source_binding") == "whole_game":
        evidence_binding = source_fingerprint(game)
    return _fingerprint({
        "claim_rules_version": 1, "game_id": game.get("id", game.get("slug")),
        "date": str(game.get("date", "")), "identity": identity,
        "claim_basis": {key: assessment.get(key) for key in (
            "claimed_role", "claim_day", "actual_claim_day", "first_day_claim",
            "manual_source_sha256", "manual_review_id")},
        "evidence": evidence_source_fingerprint(evidence_rows),
        "source_binding": evidence_binding,
    })


def success_fingerprint(game: dict, seat_number: int, claim_day: int | str | None = 1,
                        *, result_review: dict | None = None) -> str:
    """Hash computed outcomes and inputs that actually affect bluff success."""
    if type(claim_day) is not int or claim_day < 1:
        voting = game.get("voting") or {}
        days = [row.get("number") for row in game.get("rounds", []) if type(row.get("number")) is int]
        days.extend(row.get("day") for row in voting.get("days", []) if type(row.get("day")) is int)
        days.extend(ballot.get("day") for ballot in voting.get("ballots", [])
                    if ballot.get("kind") == "sheriff" and type(ballot.get("day")) is int)
        last_day = max(days, default=1)
        first_possible_claim_day = 3 if claim_day == "later" else 1
        badge_outcomes = {
            day: _badge_result(game, seat_number, day, result_review)
            for day in range(first_possible_claim_day, last_day + 2)
        }
        exile = None
        if first_possible_claim_day == 1:
            target, known, questions = _final_exile(game, 1)
            target_seat = next((seat for seat in game.get("seats", []) if seat.get("seat") == target), None)
            exile = {"target": target, "known": known, "questions": questions,
                     "faction": effective_faction(game, target_seat) if target_seat else None}
        official_badge, _ = _badge_result(game, seat_number, first_possible_claim_day)
        supplemental_result = ({"badge": result_review.get("badge"),
                                "evidence": result_review.get("evidence")}
                               if official_badge is None and isinstance(result_review, dict) else None)
        return _fingerprint({"success_rules_version": 1, "claim_day": claim_day,
                             "seat": seat_number, "possible_badge_outcomes": badge_outcomes,
                             "possible_first_day_exile": exile,
                             "supplemental_badge_result": supplemental_result})
    official_badge, _ = _badge_result(game, seat_number, claim_day if type(claim_day) is int else 1)
    badge, badge_questions = _badge_result(
        game, seat_number, claim_day if type(claim_day) is int else 1, result_review)
    target, exile_known, exile_questions = (
        _final_exile(game, 1) if claim_day == 1 and badge is not True else (None, False, [])
    )
    target_seat = next((seat for seat in game.get("seats", []) if seat.get("seat") == target), None)
    supplemental_result = ({"badge": result_review.get("badge"),
                            "evidence": result_review.get("evidence")}
                           if official_badge is None and isinstance(result_review, dict) else None)
    return _fingerprint({
        "success_rules_version": 1, "claim_day": claim_day, "seat": seat_number,
        "badge_outcome": badge, "badge_questions": badge_questions,
        "first_day_exile_target": target,
        "first_day_exile_known": exile_known, "first_day_exile_questions": exile_questions,
        "first_day_exile_faction": effective_faction(game, target_seat) if claim_day == 1 and target_seat else None,
        "supplemental_badge_result": supplemental_result,
    })


def assessment_success_day(assessment: dict | None) -> int | str | None:
    if not assessment:
        return None
    day = assessment.get("claim_day", 1)
    actual_day = assessment.get("actual_claim_day")
    if day == "later" and type(actual_day) is int and actual_day > 2:
        return actual_day
    return day


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


def review_items(games: list[dict], payload: dict) -> list[dict]:
    indexed = {row["game_id"]: row for row in payload.get("games", [])}
    output = []
    for game in games:
        game_id = game.get("id", game.get("slug"))
        source = indexed.get(game_id)
        fingerprint = source_fingerprint(game)
        source_valid = source is not None and source.get("source_fingerprint") == fingerprint
        assessments = {row["seat"]: row for row in source.get("assessments", [])} if source else {}
        for seat in game.get("seats", []):
            record = assessments.get(seat["seat"])
            if not included_in_review(game, seat, record):
                continue
            questions = list(record.get("review_questions", [])) if record else []
            decision = record.get("decision", "uncertain") if record else "uncertain"
            identity_matches = bool(record and record.get("name") == seat.get("name")
                                    and record.get("physical_role") == seat.get("role"))
            # User-confirmed fields are authoritative. Dependency signatures
            # may flag changed inputs for an assistant inference, but cannot
            # revoke a human decision or remove it from the statistics.
            user_confirmed = bool(record and record.get('verification_status') == 'user_confirmed'
                                  and identity_matches and decision in {'yes', 'no'})
            input_change_notes = []
            claim_signature = record.get("claim_fingerprint") if record else None
            claim_legacy_compatible = bool(source_valid and identity_matches)
            claim_matches = bool(
                isinstance(claim_signature, str)
                and re.fullmatch(r"[a-f0-9]{64}", claim_signature)
                and claim_signature == claim_fingerprint(game, record)
            ) if record else False
            if record and not claim_signature:
                # Old immutable assets have no item-level signature. Keep their
                # conclusions only while the previous whole-game binding matches.
                claim_matches = claim_legacy_compatible
            claim_needs_review = bool(record and not user_confirmed
                                      and decision in {"yes", "no"} and not claim_matches)
            if user_confirmed and claim_signature and not claim_matches:
                input_change_notes.append('关联的发言旁证或阶段输入已变化；人工悍跳结论保持锁定，未据此修改。')
            success_needs_review = False
            legacy_success_needs_review = False
            source_decision = decision
            if source is None:
                questions.append("尚无对应推断记录")
            elif record is None:
                questions.append("该狼人座位尚无悍跳判断")
            elif not identity_matches:
                decision = "uncertain"
                questions.append("推断中的选手或底牌与当前发布记录不一致")
            elif claim_needs_review:
                decision = "uncertain"
                questions.append("悍跳身份、自称阶段或发言证据依据已变化：上次悍跳结论保留为待复核")
            if record and source_decision == "yes":
                stored_success_signature = record.get("success_fingerprint")
                current_success_signature = success_fingerprint(
                    game, seat["seat"], assessment_success_day(record),
                    result_review=source.get("result_review"),
                )
                success_matches = bool(
                    isinstance(stored_success_signature, str)
                    and re.fullmatch(r"[a-f0-9]{64}", stored_success_signature)
                    and stored_success_signature == current_success_signature
                )
                if not stored_success_signature:
                    # Missing technical metadata never revokes a human result.
                    # Unsaved rule-derived results are recalculated below.
                    success_matches = True
                if user_confirmed and 'manual_success' in record:
                    if stored_success_signature and not success_matches:
                        input_change_notes.append('关联的警徽、放逐或阵营输入已变化；人工成功结果保持锁定，未据此修改。')
                    success_matches = True
                    legacy_success_needs_review = False
                if not success_matches:
                    success_needs_review = True
                    questions.append("悍跳结论保留；程序成功判断所依赖的警徽、首日放逐或有效阵营已变化，需重新核对推断")
            if decision == "yes" and not record.get("evidence") and record.get("verification_status") != "user_confirmed":
                decision = "uncertain"
                questions.append("悍跳判断缺少定位证据")
            success_day=assessment_success_day(record)
            actual_day=record.get("actual_claim_day") if record else None
            manual_success = bool(record and record.get('verification_status') == 'user_confirmed'
                                  and 'manual_success' in record and decision == 'yes'
                                  and user_confirmed)
            if manual_success:
                value = record['manual_success']
                label = '成功' if value is True else '失败' if value is False else '待定'
                success = {'value': value, 'reasons': [{'kind': 'user_review', 'text': f'用户人工复核：{label}。'}],
                           'questions': ['用户将成功结果保留为待定'] if value is None else []}
            else:
                success = evaluate_success(game, seat["seat"], success_day,
                                           result_review=source.get('result_review')) if source_decision == "yes" else {
                    "value": None, "reasons": [], "questions": []}
            questions.extend(success["questions"])
            if decision == "uncertain" and not questions:
                questions.append("发言归属或是否正式跳信息神待复核")
            bvid = (game.get("source") or {}).get("bvid", source.get("bvid") if source else None)
            evidence = []
            for entry in record.get("evidence", []) if record else []:
                public = {key: entry[key] for key in ("kind", "text", "start_ms", "end_ms", "interpretation")
                          if key in entry}
                screenshot=public_image_url(entry.get("image_url"))
                if screenshot:
                    public["image_url"]=screenshot
                if isinstance(bvid, str) and re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
                    start = entry.get("start_ms")
                    seconds = max(0, int(start / 1000)) if isinstance(start, (int, float)) else 0
                    public["url"] = f"https://www.bilibili.com/video/{bvid}/?t={seconds}"
                evidence.append(public)
            needs_review=decision=='uncertain' or bool(questions)
            stage=record.get('review_stage') if record else None
            user_review=needs_review and bool(record.get('requires_user_review',stage!='assistant_pending') if record else True)
            assistant_pending=stage=='assistant_pending' or (needs_review and not user_review)
            output.append({
                "review_id": f"{bvid}:{seat['seat']}",
                "source_fingerprint": fingerprint,
                "claim_fingerprint": claim_fingerprint(game, record) if record else None,
                "success_fingerprint": (success_fingerprint(
                    game, seat["seat"], success_day, result_review=source.get("result_review"))
                    if record else None),
                "game_id": game_id, "date": str(game.get("date", "")),
                "game_number": game.get("game_number"),
                "bvid": bvid,
                "player_id": seat.get("person_id"), "seat": seat["seat"], "name": seat["name"],
                "physical_role": seat.get("role"), "claimed_role": record.get("claimed_role") if record else None,
                "decision": decision, "confidence": record.get("confidence", "low") if record else "low",
                "claim_day": record.get("claim_day") if record else None,
                "actual_claim_day":actual_day,
                "first_day_claim": record.get("first_day_claim") if record else None,
                "decision_note": record.get("decision_note", "") if record else "",
                "previous_decision": record.get("decision") if record else None,
                "verification_status": record.get("verification_status", "assistant_inferred") if record else "assistant_inferred",
                "evidence": evidence,
                "success": None if success_needs_review or claim_needs_review else success["value"],
                "current_success": success["value"],
                "previous_success": (record.get("manual_success")
                                     if record and record.get("verification_status") == "user_confirmed"
                                     and "manual_success" in record else None),
                "previous_success_saved": bool(record and record.get("verification_status") == "user_confirmed"
                                                and "manual_success" in record),
                "success_needs_review": success_needs_review,
                "legacy_success_needs_review": legacy_success_needs_review,
                "claim_needs_review": claim_needs_review,
                "input_change_notes": input_change_notes,
                "success_reasons": success["reasons"],
                "success_source": 'user' if manual_success else 'rules',
                "manual_included": not physical_wolf(game, seat),
                "review_questions": list(dict.fromkeys(questions)),
                "needs_review": needs_review,
                "requires_user_review":user_review,"assistant_pending":assistant_pending,"review_stage":stage,
            })
    return output


def aggregate_bluffs(games: list[dict], payload: dict) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict] = {}
    items = review_items(games, payload)
    by_seat = {(item["game_id"], item["seat"]): item for item in items}
    for game in games:
        for seat in game.get("seats", []):
            if seat.get("person_id") is not None:
                row = stats.setdefault(str(seat["person_id"]), {
                    "bluff_count": 0, "bluff_count_complete": bool(payload.get("games")), "bluff_pending_games": 0,
                    "bluff_rate": _new_metric(),
                    "bluff_review_count": 0, "bluff_success_rate": _new_metric(),
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
        elif item["decision"] == "yes":
            row["bluff_count"] += 1
            if item["success"] is None:
                _add_excluded(metric)
            else:
                _add_denominator(metric, item["game_id"], success=item["success"])
    for row in stats.values():
        row["bluff_rate"] = _metric_result(row["bluff_rate"])
        row["bluff_success_rate"] = _metric_result(row["bluff_success_rate"])
    return stats

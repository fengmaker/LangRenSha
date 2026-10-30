"""Apply user-confirmed S22 election and default-abstention rules after source corrections."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from game_flow import replay

ROOT = Path(__file__).resolve().parents[1]
RULE_PATH = "config/game_rules.json"
DEFERRED_EVIDENCE = ROOT / "data/extractions/S22/voting_review/deferred_elections.json"


def confirmed_rules():
    value = json.loads((ROOT / RULE_PATH).read_text(encoding="utf-8"))
    return value["shared_rules"]["voting"]


def event(round_, slot):
    return next((e for e in round_.get("day", []) if e["slot"] == slot), None)


def known_departures(round_):
    out = set()
    for e in round_.get("day", []):
        if e["action"] in {"die", "exile", "shoot", "die_after_speech", "suicide"}:
            out.update(e["targets"])
        if e["action"] == "self_destruct" and e.get("actor") is not None:
            out.add(e["actor"])
    return out


def ballot_living_seats(dossier, day, facts=None, supplements=()):
    flow = replay(dossier, facts, supplements)
    return next((r["living_before_vote"] for r in flow["rounds"] if r["day"] == day and day in flow["days"]), None)


def apply_rules(facts, audit, dossier):
    rules = confirmed_rules()
    applications, issues, flow = [], [], []
    game_flow = replay(dossier, facts, audit.get("night_death_supplements", []), audit.get("endgame_phases", []),
                       audit.get("causal_terminal"))
    audit["game_flow"] = game_flow
    issues.extend(game_flow["issues"])
    if game_flow["terminal"]:
        facts["days"] = [d for d in facts["days"] if d["day"] in game_flow["days"]]
    living_by_day = {r["day"]: r["living_before_vote"] for r in game_flow["rounds"] if r["day"] in game_flow["days"]}
    eligibility = []
    previous_defaults = {a["target"]: set(a["voters"]) for a in audit.get("rule_applications", [])}
    bvid = re.search(r"BV[0-9A-Za-z]{10}", facts["game_slug"])
    proof = None
    if bvid and DEFERRED_EVIDENCE.is_file():
        proof = next((x for x in json.loads(DEFERRED_EVIDENCE.read_text(encoding="utf-8"))["items"] if x["bvid"] == bvid.group()), None)
        if proof and hashlib.sha256((ROOT / proof["source_path"]).read_bytes()).hexdigest() != proof["source_sha256"]:
            raise ValueError("延期竞选依据的转写已变化：" + bvid.group())
    rounds = {r["number"]: r for r in dossier.get("rounds", [])}
    sheriff_ballots = [b for b in facts["ballots"] if b["kind"] == "sheriff"]
    first_day_ballots = [b for b in sheriff_ballots if b["day"] == 1]
    registration = next((r for r in facts["registrations"] if r["day"] == 1), None)

    def self_destruct(day):
        r = rounds.get(day, {})
        e = event(r, "self_destruct")
        if e and e["action"] == "self_destruct":
            return e.get("actor")
        return next((x["actor"] for x in facts["interruptions"] if x["day"] == day), None)

    day1_sheriff = event(rounds.get(1, {}), "sheriff_result")
    unfinished = (not first_day_ballots or bool(first_day_ballots[-1]["tied_candidates"]) or
                  bool(day1_sheriff and day1_sheriff["action"] == "deferred")) and not (
                      day1_sheriff and day1_sheriff["action"] in {"elected", "none"})
    may_be_deferred = unfinished and self_destruct(1) is not None
    deferred = may_be_deferred and (bool(day1_sheriff and day1_sheriff["action"] == "deferred") or bool(proof))
    day2_ballots = [b for b in sheriff_ballots if b["day"] == 2]
    badge_lost = deferred and not day2_ballots and self_destruct(2) is not None
    if deferred:
        flow.append({"day": 1, "status": "deferred", "actor": self_destruct(1),
                     "reason": "首日白天狼人自爆，中断未完成的警长竞选；仅延至第二天继续。",
                     "evidence": proof.get("evidence", []) if proof else []})
    elif may_be_deferred:
        issues.append({"code": "election_interruption_unconfirmed", "target": None, "day": 1,
                       "reason": "已知首日有自爆，但竞选是否在自爆前完成尚未明确；不能仅凭没有提取到警徽票判为延期。"})
    if badge_lost:
        flow.append({"day": 2, "status": "badge_lost", "actor": self_destruct(2),
                     "reason": "延期竞选当天再次狼人自爆，警徽流失，不再顺延。",
                     "evidence": proof.get("day2_evidence", []) if proof else []})
    elif deferred and day2_ballots:
        flow.append({"day": 2, "status": "recorded", "actor": None,
                     "reason": "首日自爆后的延期竞选，由原警下玩家给警上候选投票；PK仍单列。",
                     "evidence": proof.get("day2_evidence", []) if proof else []})

    for b in facts["ballots"]:
        living = None
        if b["kind"] == "sheriff":
            if b["day"] is not None and b["day"] > 2:
                issues.append({"code": "sheriff_after_day2", "target": b["id"], "day": b["day"],
                               "reason": "警长竞选不能延期至第三天及以后，需核对日序或投票类型。"})
            if b["day"] == 2 and not deferred:
                issues.append({"code": "deferred_prerequisite", "target": b["id"], "day": 2,
                               "reason": "第二天警徽票缺少首日自爆中断未完竞选的依据，需核对延期条件。"})
            if registration and b["stage"] != "pk" and b["day"] in {1, 2}:
                eligible = set(registration["off_police"])
                if b["day"] == 2:
                    # Previously revealed departures still remove voting rights;
                    # the registration itself remains the original police split.
                    eligible -= known_departures(rounds.get(1, {}))
                voters = {v["voter"] for v in b["votes"]}
                if voters <= eligible:
                    b["eligible_voters"] = sorted(eligible)
                else:
                    b["eligible_voters"] = None
                    issues.append({"code": "off_police_conflict", "target": b["id"], "day": b["day"],
                                   "reason": "警徽票出现原警下名单之外的投票者，不能以本规则修正座号或名单。"})
            elif b["stage"] == "pk" and b["candidates"]:
                if b["day"] == 1:
                    living = list(range(1, 13))
                elif b["day"] == 2 and deferred:
                    living = sorted(set(range(1, 13)) - known_departures(rounds.get(1, {})))
                if living is not None:
                    eligible = set(living) - set(b["candidates"])
                    if {v["voter"] for v in b["votes"]} <= eligible:
                        b["eligible_voters"] = sorted(eligible)
        elif b["kind"] == "exile":
            living = living_by_day.get(b["day"])
            if living is not None:
                eligible = set(living)
                if b["stage"] == "pk" and b["candidates"]:
                    eligible -= set(b["candidates"])
                if {v["voter"] for v in b["votes"]} <= eligible:
                    b["eligible_voters"] = sorted(eligible)
                    eligibility.append({"target": b["id"], "day": b["day"], "living": living,
                                        "living_count": len(living), "eligible_voters": sorted(eligible),
                                        "vote_count": len(eligible), "basis": "night_deaths_and_previous_day_departures"})
                else:
                    b["eligible_voters"] = None
                    issues.append({"code": "living_voter_conflict", "target": b["id"], "day": b["day"],
                                   "reason": "播报投票者与当时存活名单冲突：" + str(sorted({v["voter"] for v in b["votes"]} - eligible)) + "；需核对出局时点、日序或号码。"})

        if b["eligible_voters"] is not None:
            missing = sorted(set(b["eligible_voters"]) - {v["voter"] for v in b["votes"]})
            defaulted = sorted(set(missing) | {s for s in previous_defaults.get(b["id"], set())
                                               if any(v["voter"] == s and v["state"] == "abstained" for v in b["votes"])})
            if missing:
                b["votes"] += [{"voter": s, "target": None, "state": "abstained"} for s in missing]
                b["votes"].sort(key=lambda v: v["voter"])
            if defaulted:
                applications.append({"rule": "unannounced_choice_is_abstention", "target": b["id"], "day": b["day"],
                                     "voters": defaulted, "reason": "依用户确认口径：已举行投票中，有票权且没有明确投向的玩家默认弃票。"})
            b["unrecorded_voters"] = []
            b["status"] = "complete"
        else:
            b["unrecorded_voters"] = None
            b["status"] = "partial"

    for d in facts["days"]:
        day = d["day"]
        if any(b["day"] == day for b in sheriff_ballots):
            d["sheriff"] = "recorded"
        elif day == 1 and deferred:
            d["sheriff"] = "deferred"
        elif day >= 2 and badge_lost:
            d["sheriff"] = "badge_lost"
        elif day > 2 or (day == 2 and not may_be_deferred):
            d["sheriff"] = "not_applicable"
        else:
            d["sheriff"] = "unknown"
    audit["rule_applications"] = applications
    audit["eligibility_derivations"] = eligibility
    audit["election_flow"] = flow
    audit["rule_issues"] = issues
    audit["voting_rule_source"] = {"path": RULE_PATH, "sha256": hashlib.sha256((ROOT / RULE_PATH).read_bytes()).hexdigest(), **rules["source"]}
    audit["note"] = "已应用用户确认的延期竞选和默认弃票口径；规则推导与原文明确播报分别保留。票权名单仍未知时不补造投票人。"

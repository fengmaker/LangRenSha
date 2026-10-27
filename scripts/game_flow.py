"""Replay departures at their actual phase; keep deductions outside source facts."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEATH_ACTIONS = {"die", "exile", "shoot", "die_after_speech", "suicide"}


def event(round_, slot):
    return next((e for e in round_.get("day", []) + round_.get("night", []) if e["slot"] == slot), None)


def departures(round_):
    dead = set()
    for e in round_.get("day", []):
        if e["action"] in DEATH_ACTIONS:
            dead.update(e["targets"])
        if e["action"] == "self_destruct" and e.get("actor") is not None:
            dead.add(e["actor"])
    for e in round_.get("night", []):
        if e["action"] == "invalid_exchange" and e.get("result") == "disqualified_repeat_target":
            dead.add(e["actor"])
    return dead


def poisoned_seats(dossier, round_):
    result = set()
    mechanical = next((s for s in dossier.get("seats", []) if s.get("role") == "机械狼"), {})
    shield = event(round_, "mechanical_action")
    for e in round_.get("night", []):
        if e["action"] != "poison":
            continue
        effects = e.get("effects", [])
        if effects:
            result.update(x["dead_seat"] for x in effects if x.get("dead_seat") and x["kind"] in {"poison_death", "poison_reflected"})
        elif e["slot"] == "witch_poison" and mechanical.get("learned_role") == "机械守卫":
            if shield and shield["action"] == "guard" and set(e["targets"]) & set(shield["targets"]):
                result.add(e["actor"])
            elif shield and shield["action"] != "unknown":
                result.update(e["targets"])
        else:
            result.update(e["targets"])
    return result


def night_result(dossier, round_, departed, spent, supplements):
    recorded = event(round_, "night_deaths")
    if recorded and recorded["action"] in {"die", "peaceful"}:
        return set(recorded["targets"]), "recorded"
    extra = next((s for s in supplements if s["day"] == round_["number"]), None)
    if extra is not None:
        return set(extra["targets"]), "announcement"
    # This board has no guard, exchange, dream or mask that can redirect a hit.
    # An unknown potion is usable only while its living owner still has it.
    if dossier.get("board") != "mixed_blood":
        return None, "unknown"
    witch = next((s["seat"] for s in dossier.get("seats", []) if s.get("role") == "女巫"), None)
    attack, save, poison = (event(round_, s) for s in ("wolf_attack", "witch_save", "witch_poison"))
    if not attack or attack["action"] not in {"attack", "pass", "forbidden", "unavailable"}:
        return None, "unknown"
    saved, poisoned = set(), set()
    if save and poison and save["action"] == "save" and poison["action"] == "poison":
        return None, "unknown"
    for slot, potion, other, targets in (("witch_save", save, poison, saved), ("witch_poison", poison, save, poisoned)):
        if potion and potion["action"] in {"save", "poison"}:
            if slot in spent or witch in departed or len(potion["targets"]) != 1:
                return None, "unknown"
            targets.update(potion["targets"])
        elif (witch in departed or slot in spent or
              (potion and potion["action"] in {"pass", "unavailable", "none"}) or
              (other and other["action"] in {"save", "poison"})):
            continue
        else:
            return None, "unknown"
    return ((set(attack["targets"]) - saved) | poisoned) - departed, "night_settlement"


def replay(dossier, facts=None, supplements=(), endgame_phases=(), terminal_confirmation=None):
    """A current ballot precedes its exile and any shot triggered by that exile."""
    facts = facts or {"ballots": [], "interruptions": []}
    seats = dossier.get("seats", [])
    everyone = {s["seat"] for s in seats} or set(range(1, 13))
    roles = {s["seat"]: s.get("role") for s in seats}
    rules = json.loads((ROOT / "config/S22_formal_rules.json").read_text(encoding="utf-8"))
    board = rules["boards"].get(dossier.get("board"), {})
    pool = board.get("role_pool") or board.get("role_composition", [])
    if not isinstance(pool, list):
        pool = []
    sides = {p["physical_identity"]: p["elimination_side"] for p in pool}
    sides_by_seat = {s["seat"]: sides.get(s.get("role")) for s in seats}
    groups = {side: {n for n, value in sides_by_seat.items() if value == side}
              for side in ("civilian", "god", "werewolf")}
    roster_known = len(seats) == 12 and all(v in groups for v in sides_by_seat.values())
    departed, spent, rows, deductions, issues, gaps = set(), set(), [], [], [], []
    complete = True
    terminal = None

    def victory(number, phase):
        if not roster_known:
            return None
        # Referee recap BV1sYEo6QEyS: when both conditions are reached in the
        # same night, wolf-knife priority settles the result for the wolves.
        order = ("civilian", "god", "werewolf") if phase == "night" else ("werewolf", "civilian", "god")
        for side in order:
            if groups[side] and groups[side] <= departed:
                return {"round": number, "phase": phase, "after_day": number - 1 if phase == "night" else number,
                        "winner": "good" if side == "werewolf" else "werewolf", "eliminated_side": side}
        return None

    previous_number = 0
    for r in sorted(dossier.get("rounds", []), key=lambda r: r["number"]):
        n = r["number"]
        if n != previous_number + 1:
            complete = False
            gaps.append({"round": previous_number + 1, "slot": "round"})
        previous_number = n
        night_dead, basis = night_result(dossier, r, departed, spent, supplements)
        for e in r.get("night", []):
            if e["slot"] in {"witch_save", "witch_poison"} and e["action"] in {"save", "poison"}:
                spent.add(e["slot"])
            if e["action"] == "invalid_exchange" and e.get("result") == "disqualified_repeat_target":
                departed.add(e["actor"])
        if night_dead is None:
            complete = False
            gaps.append({"round": n, "slot": "night_deaths"})
        else:
            departed.update(night_dead)
            if basis != "recorded":
                deductions.append({"round": n, "slot": "night_deaths", "targets": sorted(night_dead), "basis": basis})
        exile = event(r, "exile_result")
        expelled = set(exile["targets"]) if exile and exile["action"] == "exile" else set()
        ballots = [b for b in facts.get("ballots", []) if b["day"] == n and b["kind"] == "exile"]
        if not expelled and ballots and ballots[-1].get("winner"):
            expelled.add(ballots[-1]["winner"])
        mechanical = next((s for s in seats if s.get("role") == "机械狼"), {})
        shots = [e for e in r.get("day", []) if e["slot"] in {"hunter_shot", "wolf_king_shot", "mechanical_day_skill"}
                 and (e["slot"] != "mechanical_day_skill" or e["action"] == "shoot" or
                      mechanical.get("learned_role") in {None, "机械猎人"})]
        poisoned = poisoned_seats(dossier, r)
        for shot in shots:
            # A living hunter's unknown slot cannot remove a player. Its trigger
            # is needed before an unknown response makes the roster uncertain.
            triggered = shot.get("actor") in (night_dead or set())
            if shot["action"] == "shoot" and shot.get("actor") not in expelled:
                departed.update(shot["targets"])
            elif triggered and shot["action"] == "unknown" and shot.get("actor") not in poisoned:
                complete = False
                gaps.append({"round": n, "slot": shot["slot"]})
        night_end = victory(n, "night")
        if terminal is None and night_end:
            terminal = night_end
        for e in r.get("day", []):
            if e["slot"] == "masked_delayed_death" and e["action"] == "die_after_speech":
                departed.update(e["targets"])
        living = sorted(everyone - departed) if complete else None
        row = {"day": n, "night_deaths": sorted(night_dead) if night_dead is not None else None,
               "night_basis": basis, "living_before_vote": living, "roster_gaps": list(gaps)}
        daily = departures(r) | expelled
        departed.update(daily)
        if any(shot.get("actor") in expelled and shot["action"] == "unknown" for shot in shots):
            complete = False
            gaps.extend({"round": n, "slot": shot["slot"]} for shot in shots
                        if shot.get("actor") in expelled and shot["action"] == "unknown")
        ended_day = (bool(expelled) or (exile and exile["action"] == "none") or
                     any(e["action"] == "self_destruct" for e in r.get("day", [])) or
                     any(x["day"] == n and x["ends_day"] for x in facts.get("interruptions", [])))
        if not ended_day:
            complete = False
            gaps.append({"round": n, "slot": "exile_result"})
        row["living_after_day"] = sorted(everyone - departed) if complete else None
        rows.append(row)
        if terminal is None:
            terminal = victory(n, "day")

    # A later factual ballot/action is contradictory evidence, never a reason
    # to silently delete votes. Such a game keeps its days and gets a question.
    if terminal:
        last_day = terminal["after_day"]
        later_ballots = any(b.get("day") and b["day"] > last_day for b in facts.get("ballots", []))
        later_actions = any(r["number"] > last_day and any(
            e["slot"] != "night_deaths" and e["action"] in {"exile", "self_destruct", "shoot", "die_after_speech"}
            and not (r["number"] == terminal["round"] and terminal["phase"] == "night" and
                     e["action"] == "shoot" and e.get("actor") in
                     (next(x["night_deaths"] for x in rows if x["day"] == r["number"]) or []))
            for e in r.get("day", [])) for r in dossier.get("rounds", []))
        later_nights = any(r["number"] > terminal["round"] and any(
            e["action"] in {"attack", "poison", "save", "guard", "check", "learn", "dream", "exchange"}
            for e in r.get("night", [])) for r in dossier.get("rounds", []))
        if later_ballots or later_actions or later_nights or (dossier.get("winner") and dossier["winner"] != terminal["winner"]):
            issues.append({"code": "terminal_conflict", "day": terminal["round"], "target": None,
                           "reason": "出局记录推导的屠边时间或胜方与后续实际事件/公布胜方冲突，需核对出局记录。"})
            terminal = None
    if terminal is None and not issues:
        completed = [p for p in endgame_phases if p.get("day") is not None and
                     p.get("result") in {"werewolf_win", "good_win"}]
        if completed:
            p = min(completed, key=lambda p: p["day"])
            if not any(b.get("day") and b["day"] > p["day"] for b in facts.get("ballots", [])):
                terminal = {"round": p["day"], "phase": "endgame", "after_day": p["day"],
                            "winner": "werewolf" if p["result"] == "werewolf_win" else "good",
                            "eliminated_side": None}
    if terminal_confirmation:
        confirmed = dict(terminal_confirmation)
        if (confirmed.get("phase") not in {"night", "day", "endgame"} or
                confirmed.get("winner") not in {"good", "werewolf"} or
                type(confirmed.get("after_day")) is not int):
            raise ValueError("因果终局确认格式不合法")
        if any(b.get("day") and b["day"] > confirmed["after_day"] for b in facts.get("ballots", [])):
            raise ValueError("因果终局确认不能覆盖之后实际存在的投票")
        if terminal is None or confirmed["after_day"] < terminal["after_day"]:
            terminal = confirmed
    days = [r["day"] for r in rows if not terminal or r["day"] <= terminal["after_day"]]
    phases = []
    for r in dossier.get("rounds", []):
        n = r["number"]
        if not terminal or n <= terminal["round"]:
            phases.append({"round": n, "phase": "night", "label": "开局夜晚" if n == 1 else f"第{n-1}天夜晚"})
        if n in days:
            phases.append({"round": n, "phase": "day", "label": f"第{n}天白天"})
        elif terminal and n == terminal["round"] and terminal["phase"] == "night":
            shots = [e["slot"] for e in r.get("day", []) if e["action"] == "shoot"]
            if shots:
                phases.append({"round": n, "phase": "day", "label": f"第{n-1}天夜晚 · 死亡技能结算",
                               "event_slots": ["night_deaths", *shots]})
    return {"days": days, "rounds": rows, "terminal": terminal, "deductions": deductions,
            "issues": issues, "display_phases": phases}


def collect_death_announcements(segments, dossier, facts, audit):
    """Use complete judge death reports inside a uniquely dated daylight span."""
    from voting_records import GROUP, seats, normalized, evidence

    recap = audit.get("day_crosscheck_source", {}).get("recap_segments", [])
    cutoff = min((s["start_ms"] for s in recap), default=float("inf"))
    dusk = [s["start_ms"] for s in segments if s["start_ms"] < cutoff and
            re.match(r"^(?:好[的]?|各位玩家|所有玩家|请所有玩家|[54321五四三二一，,。])*天黑请闭眼", normalized(s["text"]))]
    anchors = [(ev["start_ms"], x["day"]) for x in facts["ballots"] + facts["interruptions"]
               if x.get("day") for ev in audit["evidence"].get(x["id"], [])[:1]]
    reports = {}
    for i, s in enumerate(segments):
        if s["start_ms"] >= cutoff or not re.search(r"昨[夜晚]", s["text"]):
            continue
        rows = [x for x in segments[i:i+6] if x["start_ms"] - s["start_ms"] < 18000]
        text = normalized("".join(x["text"] for x in rows))
        if re.search(r"如果|假如|可能|我觉得|昨天.*昨夜|明天", text[:text.find("昨")]):
            continue
        peaceful = re.search(r"昨[夜晚](?:信息)?[，,：:。]*(?:是)?平安夜", text)
        deaths = re.search(rf"昨[夜晚](?:双死[，,。]*死亡[顺数]序不分先后[，,。]*)?(?:死亡的?(?:是|为)?[：:，,]*)?(?P<seats>{GROUP})(?:[，,。]*)(?:双死|死亡|倒牌)", text)
        if not peaceful and not (deaths and re.search(r"没有遗言|发动技能|请灭灯|不分先后", text)):
            continue
        moment = s["start_ms"]
        left = max((t for t in dusk if t < moment), default=0)
        right = min((t for t in dusk if t > moment), default=cutoff)
        days = {day for t, day in anchors if left <= t < right}
        if len(days) != 1:
            continue
        day = days.pop()
        targets = sorted(set(seats(deaths["seats"]))) if deaths else []
        report = {"day": day, "targets": targets, "evidence": [evidence(rows, audit.get("source_path", ""))]}
        reports.setdefault(day, []).append(report)
    result = []
    for day, reports_for_day in sorted(reports.items()):
        choices = {tuple(r["targets"]) for r in reports_for_day}
        recorded = next((event(r, "night_deaths") for r in dossier.get("rounds", []) if r["number"] == day), None)
        if len(choices) == 1 and (not recorded or recorded["action"] == "unknown"):
            result.append({**reports_for_day[0], "evidence": [e for r in reports_for_day for e in r["evidence"]]})
    return result

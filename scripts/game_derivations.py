"""Prepare shared game rules before validation, database import and publication.

Source observations stay in their existing evidence files.  Changes to typed
records, their prerequisites, remaining review work and conflicts are returned
together, so downstream consumers do not need to reason about blank slots.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

try:
    from . import game_inference as inference
    from .role_constraints import event_constraint, family, puppet_target
    from .board_outcomes import derive_board_outcomes
    from .board_config import load_template
    from .season_config import load_season
except ImportError:
    import game_inference as inference
    from role_constraints import event_constraint, family, puppet_target
    from board_outcomes import derive_board_outcomes
    from board_config import load_template
    from season_config import load_season

ROOT = Path(__file__).resolve().parents[1]
VERSION = 1
EVENT_FIELDS = {"slot", "action", "actor", "targets", "result", "start_seat", "direction",
                "votes", "random_point", "speech_scope", "availability", "effects"}
INACTIVE = {None, "unknown", "unavailable", "forbidden", "not_applicable", "not_held", "none"}
TRIGGERED = {"hunter_shot", "wolf_king_shot", "mechanical_day_skill"}
ACTIVE_ACTIONS = {"attack", "guard", "save", "poison", "check", "learn", "dream", "dance",
                  "give_mask", "verify", "exchange", "select_pair", "choose", "speak", "duel", "shoot", "self_destruct"}
WOLF_ROLES = {"狼人", "机械狼", "狼王", "黑狼王", "白狼王", "诡术师", "假面", "典狱长", "狼术师", "九尾狐", "盗宝大师"}
GOOD_ROLES = {"预言家", "通灵师", "女巫", "毒师", "猎人", "守卫", "骑士", "摄梦人", "平民", "魔术师",
              "定序王子", "舞者", "白痴", "白神", "蒙面人", "白泽"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


@lru_cache(maxsize=None)
def board_template(code, season=None):
    if season == "S23":
        mapping = load_season(season, ROOT)["formal_import"]["board_code_map"]
        code = mapping.get(code, code)
    try:
        return load_template(code, ROOT)
    except FileNotFoundError:
        return {}


def rule_sources():
    paths = [ROOT / "config/game_rules.json", ROOT / "config/seasons.json"]
    paths += sorted((ROOT / "config/board_templates").glob("*.json"))
    paths += [ROOT / "scripts" / name for name in
              ("game_derivations.py", "role_constraints.py", "board_outcomes.py", "game_inference.py",
               "sheriff_speech_evidence.py", "voting_records.py", "board_config.py",
               "rule_config.py", "season_config.py")]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _event(round_, slot, phase=None):
    return next((e for ph in ([phase] if phase else ["night", "day"])
                 for e in round_.get(ph, []) if e.get("slot") == slot), None)


def _self_destruct_ends_unvoted_day(round_, ballots):
    event = _event(round_, "self_destruct", "day")
    return bool(event and event.get("action") == "self_destruct"
                and not any(b.get("kind") == "exile" for b in ballots))


def _observed_terminal(game, supplemental):
    explicit = (game.get("_publication_context") or {}).get("terminal_observation")
    if explicit:
        return deepcopy(explicit)
    explicit = inference.terminal_from_events(game)
    if explicit:
        return explicit
    for row in (supplemental or {}).get("events", []):
        event = row.get("event", {})
        if (event.get("action") == "surrender" and type(row.get("round")) is int
                and row.get("phase") in {"night", "day"}):
            return {"round": row["round"], "phase": row["phase"], "basis": "observed_surrender"}
    reviewed = (supplemental or {}).get("phase_reviewed", supplemental or {})
    events = reviewed.get("events", [])
    ended = any(e.get("action") == "game_end" and e.get("state") == "performed" for e in events)
    if not ended:
        return None
    preceding = [e for e in events if type(e.get("round")) is int and e.get("state") == "performed"
                 and e.get("action") != "game_end" and e.get("phase") in {"night", "day", "endgame"}]
    if not preceding:
        return None
    # Review files may append an earlier withdrawal after the terminal recap.
    # Game phase/round, rather than JSON list order or recap seconds, orders it.
    last = max(preceding, key=lambda e: (e["round"], {"night": 0, "day": 1, "endgame": 2}[e["phase"]]))
    return {"round": last["round"], "phase": "day" if last["phase"] == "endgame" else last["phase"],
            "basis": "reviewed_game_end_and_preceding_phase"}


def _supplemental_disqualifications(supplemental):
    result = {}
    for row in (supplemental or {}).get("events", []):
        event = row.get("event", {})
        if (event.get("action") != "disqualify" or type(row.get("round")) is not int
                or row.get("phase") not in {"night", "day"}):
            continue
        seats = set(event.get("targets", []))
        if not seats and type(event.get("actor")) is int:
            seats.add(event["actor"])
        result.setdefault((row["round"], row["phase"]), set()).update(seats)
    return result


def _role_owner(event, roles, template_slot):
    actor = inference._actor_for_tracking(event, roles)
    if actor is not None:
        return actor
    role = template_slot.get("actor_role")
    matches = roles.get(role, [])
    return matches[0] if len(matches) == 1 else None


def _night_deaths(round_):
    records = [e for ph in ("night", "day") for e in round_.get(ph, [])
               if e.get("slot") == "night_deaths" and e.get("action") in {"die", "peaceful"}]
    dead = {s for e in records for s in e.get("targets", [])}
    return dead, bool(records)


def _ordinary_settlement(game, round_, dead, uses, roles):
    """Resolve only boards without unobserved redirection or extra kills."""
    if family(game.get("board")) not in {"mixed_blood", "seer_witch_hunter_white", "wolf_king_guard",
                                          "wolf_king_knight", "black_wolf_king_knight"}:
        return None
    attack = _event(round_, "wolf_attack", "night")
    if not attack or attack.get("action") not in {"attack", "pass", "forbidden", "unavailable"}:
        return None
    hit = set(attack.get("targets", [])) if attack["action"] == "attack" else set()
    guard = _event(round_, "guard", "night")
    shield = set()
    if guard:
        owner = inference._actor_for_tracking(guard, roles)
        if guard.get("action") == "guard":
            shield.update(guard.get("targets", []))
        elif guard.get("action") not in {"pass", "unavailable", "forbidden"} and owner not in dead:
            return None
    saved, poisoned = set(), set()
    save, poison = _event(round_, "witch_save", "night"), _event(round_, "witch_poison", "night")
    for e, other, action, targets in [(save, poison, "save", saved), (poison, save, "poison", poisoned)]:
        if e is None:
            continue
        owner = inference._actor_for_tracking(e, roles)
        if e.get("action") == action:
            if e.get("result") != "failed":
                targets.update(e.get("targets", []))
        elif (owner in dead or uses[(owner, e["slot"])] or
              e.get("action") in {"pass", "unavailable", "forbidden"} or
              (other and other.get("action") in {"save", "poison"})):
            continue
        else:
            return None
    return (hit - saved - shield) | (hit & saved & shield) | poisoned


def _unique_resource_uses(game, roles):
    uses, departed = {}, set()
    for r in game.get("rounds", []):
        for e in r.get("night", []):
            if (e.get("slot"), e.get("action")) not in {("witch_save", "save"), ("witch_poison", "poison"), ("mechanical_action", "learn")}:
                continue
            actor = inference._actor_for_tracking(e, roles)
            if actor is not None and actor not in departed:
                uses.setdefault((actor, e["slot"]), []).append(r["number"])
        departed.update(inference._actual_deaths(r.get("night", []) + r.get("day", [])))
    return {key: rounds[0] for key, rounds in uses.items() if len(rounds) == 1}


def derive_game(dossier, voting=None, *, supplemental=None, endgame=None, terminal_observation=None,
                speech_evidence=None):
    """Return typed records plus reproducible, private derivation evidence.

    Observed actions are never silently removed to make rules consistent.
    A contradiction becomes an issue; only unknown fields are completed.
    """
    game, votes = deepcopy(dossier), deepcopy(voting)
    changes, issues, states, timeline, work, consequences, gaps = [], [], [], [], [], [], []
    inputs = {"dossier": fingerprint(dossier), "voting": fingerprint(voting),
              "supplemental": fingerprint(supplemental), "endgame": fingerprint(endgame)}
    if terminal_observation is not None:
        inputs["terminal_observation"] = fingerprint(terminal_observation)
    if speech_evidence is not None:
        inputs["speech_evidence"] = fingerprint(speech_evidence)
    template = board_template(game.get("board"), game.get("season"))
    templates = {p: {s["code"]: s for s in template.get(p + "_slots", [])} for p in ("night", "day")}
    roles = inference._role_seats(game)
    roster = {p["seat"] for p in game.get("seats", []) if type(p.get("seat")) is int}
    by_seat = {p["seat"]: p for p in game.get("seats", [])}
    terminal = deepcopy(terminal_observation) if terminal_observation is not None else _observed_terminal(game, supplemental)
    disqualifications = _supplemental_disqualifications(supplemental)

    def change(obj, key, new, path, rule, dependencies):
        old = obj.get(key)
        if old == new:
            return
        changes.append({"path": path + [key], "before": deepcopy(old), "after": deepcopy(new),
                        "rule": rule, "dependencies": deepcopy(dependencies)})
        obj[key] = deepcopy(new)

    def issue(code, number, phase, slot, **extra):
        issues.append({"code": code, "round": number, "phase": phase, "slot": slot, **extra})

    # Known physical identities already establish the ordinary victory side.
    # Mixed-blood and third-party coupling remain separate state, not wolf roles.
    if family(game.get("board")) != "ghost_bride":
        for si, seat in enumerate(game.get("seats", [])):
            role = seat.get("role")
            faction = "werewolf" if role in WOLF_ROLES else "good" if role in GOOD_ROLES else None
            if faction and seat.get("faction") is None:
                change(seat, "faction", faction, ["dossier", "seats", si], "physical_role_victory_faction", [role])
    puppet = puppet_target(game)
    if puppet is not None:
        si = next(i for i, seat in enumerate(game['seats']) if seat['seat'] == puppet)
        change(game['seats'][si], 'faction', 'werewolf', ['dossier', 'seats', si],
               'neighbor_puppet_follows_wolves', [1, 'night', 'puppet_select', puppet])
    forms = board_template("mechanical_wolf_seer").get("mechanical_forms", {})
    for ri, r in enumerate(game.get("rounds", [])):
        for ei, e in enumerate(r.get("night", [])):
            actor = _role_owner(e, roles, templates["night"].get(e["slot"], {}))
            targets = e.get("targets", [])
            if e.get("slot") == "mixed_blood_model" and e.get("action") == "choose" and len(targets) == 1:
                model = by_seat.get(targets[0], {})
                if actor in by_seat and by_seat[actor].get("faction") is None and model.get("faction") in {"good", "werewolf"}:
                    si = game["seats"].index(by_seat[actor])
                    change(by_seat[actor], "faction", model["faction"], ["dossier", "seats", si],
                           "mixed_blood_follows_observed_model", [r["number"], actor, targets[0]])
            if e.get("slot") != "mechanical_action" or e.get("action") != "learn" or len(targets) != 1 or actor not in by_seat:
                continue
            target_role = by_seat.get(targets[0], {}).get("role")
            candidates = [name for name, spec in forms.items() if spec.get("learned_from") == target_role]
            if len(candidates) != 1:
                continue
            form, seat = candidates[0], by_seat[actor]
            si = game["seats"].index(seat)
            path = ["dossier", "rounds", ri, "night", ei]
            if seat.get("learning_target") is None:
                change(seat, "learning_target", targets[0], ["dossier", "seats", si], "observed_mechanical_learning", [r["number"], targets[0]])
            if seat.get("learned_role") is None:
                change(seat, "learned_role", form, ["dossier", "seats", si], "mechanical_form_from_target_identity", [targets[0], target_role])
            if e.get("result") in {None, "", "unknown"}:
                change(e, "result", form, path, "mechanical_form_from_target_identity", [targets[0], target_role])

    # Reuse the existing checked poison, hunter, feedback and voting inference.
    # This now runs at preparation time and its typed changes are persisted.
    normalized = deepcopy(game)
    normalized["board"] = family(game.get("board"))
    normalized["voting"] = votes or {"days": [], "ballots": []}
    if terminal:
        normalized["terminal_observation"] = terminal
    projected = inference.build_game_presentation(normalized)
    indexed = {(r["number"], p, e["slot"]): e for r in projected["rounds"]
               for p in ("night", "day") for e in r[p]}
    for ri, r in enumerate(game.get("rounds", [])):
        for phase in ("night", "day"):
            for ei, e in enumerate(r.get(phase, [])):
                derived = indexed.get((r["number"], phase, e["slot"]))
                if not derived or not derived.get("inferred"):
                    continue
                for key in sorted(EVENT_FIELDS - {"slot"}):
                    if key not in derived:
                        continue
                    if key == "action" and derived[key] not in templates[phase].get(e["slot"], {}).get("actions", []):
                        continue
                    change(e, key, derived[key], ["dossier", "rounds", ri, phase, ei],
                           "existing_checked_inference", [derived.get("inference_note", "")])

    unique_resource_uses = _unique_resource_uses(game, roles)
    dead, exact = set(), True
    badge_holder, badge_known, badge_lost = None, False, False
    uses, previous, used_targets, learning = Counter(), {}, {}, {}
    for ri, r in enumerate(game.get("rounds", [])):
        n = r["number"]
        before = set(dead)
        round_events = [*r.get("night", []), *r.get("day", [])]
        wolf_killed_last_god = inference.terminal_wolf_attack_kills_last_god(
            game, n, before, round_events, terminal,
        )
        night_dead, night_known = _night_deaths(r)
        if not night_known:
            settled = _ordinary_settlement(game, r, before, uses, roles)
            if settled is not None:
                e = _event(r, "night_deaths", "day") or _event(r, "night_deaths", "night")
                if e and inference._is_empty_unknown(e):
                    phase = "day" if e in r.get("day", []) else "night"
                    ei = r[phase].index(e)
                    path = ["dossier", "rounds", ri, phase, ei]
                    change(e, "action", "die" if settled else "peaceful", path, "ordinary_night_settlement", [n])
                    change(e, "targets", sorted(settled), path, "ordinary_night_settlement", [n])
                    night_dead, night_known = settled, True
        night_dead.update(inference._actual_deaths(r.get("night", [])))
        current_dq = disqualifications.get((n, "night"), set()) | disqualifications.get((n, "day"), set())
        before_vote = before | night_dead | current_dq
        day_non_results = [e for e in r.get("day", []) if e.get("slot") != "night_deaths"]
        current_ballots = [b for b in (votes or {}).get("ballots", []) if b.get("day") == n]
        exile_ballots = [b for b in current_ballots if b.get("kind") == "exile"]
        current_exiles = {s for e in day_non_results if e.get("action") == "exile"
                          for s in e.get("targets", [])}
        current_exiles.update(b.get("winner") for b in exile_ballots if type(b.get("winner")) is int)
        # Before-vote deaths are distinct from the ensuing exile and shot.
        before_vote.update(s for e in day_non_results if e.get("action") == "die_after_speech"
                           for s in e.get("targets", []))
        # Night deaths trigger their recorded shots before the exile vote.
        # Exile-triggered shots remain after that vote, including chained shots.
        morning_shots = {e.get("actor"): e.get("targets", []) for e in day_non_results
                         if e.get("action") == "shoot"}
        pending = set(night_dead)
        while pending:
            victims = set(morning_shots.get(pending.pop(), [])) - before_vote
            before_vote.update(victims)
            pending.update(victims)
        current_departures = before_vote | current_exiles | inference._actual_deaths(day_non_results)
        ordinary_kings = roles.get("狼王", [])
        ordinary_king = ordinary_kings[0] if len(ordinary_kings) == 1 else None
        terminal_last_wolf_king = bool(
            ordinary_king is not None
            and inference.terminal_last_wolf_king_exile(
                game, n, before, current_departures, current_exiles, terminal,
            )
        )
        day_record = next((d for d in (votes or {}).get("days", []) if d.get("day") == n), None)
        exile_result = _event(r, "exile_result", "day")
        if (day_record and _self_destruct_ends_unvoted_day(r, current_ballots)
                and exile_result and inference._is_empty_unknown(exile_result)):
            path = ["dossier", "rounds", ri, "day", r["day"].index(exile_result)]
            change(exile_result, "action", "none", path, "self_destruct_ends_unvoted_day", [n])
            change(exile_result, "result", "interrupted_self_destruct", path, "self_destruct_ends_unvoted_day", [n])
        vote_exact = exact and night_known
        living = sorted(roster - before_vote) if vote_exact else None
        # A source-proven complete initial exile electorate is a later anchor.
        anchors = [b.get("eligible_voters") for b in exile_ballots if b.get("stage") == "initial"
                   and b.get("status") == "complete" and b.get("eligible_voters") is not None]
        if not vote_exact and anchors and all(set(x) == set(anchors[0]) for x in anchors):
            if not set(anchors[0]) & before_vote:
                living, vote_exact = sorted(anchors[0]), True
                before_vote = roster - set(living)
            else:
                issue("survival_anchor_conflict", n, "day", "exile_vote")

        special = derive_board_outcomes(game, n,
            living_before_night=sorted(roster - before) if exact else None,
            living_before_vote=living)
        board_constraints = {(c["phase"], c["slot"]): c for c in special["constraints"]}
        for item in special["issues"]:
            target = gaps if any(word in item["code"] for word in ("unknown", "missing", "not_unique")) else issues
            target.append({"round": n, **item})
        consequences.extend({"round": n, **item} for item in special["consequences"])
        for effect in special["consequences"]:
            kind = effect.get("type")
            slot = {"expected_seer_feedback": "seer_check", "dance_result": "dance_resolution",
                    "trade_result": "trade_resolution", "fox_hunt_result": "nine_tail_hunt",
                    "wolf_attack_blocked": "wolf_attack", "poison_immunity": "witch_poison",
                    "puppet_effect": "puppet_skill_effect"}.get(kind)
            if not slot:
                continue
            phase = "day" if kind == "fox_hunt_result" else "night"
            e = _event(r, slot, phase)
            if e is None:
                continue
            path = ["dossier", "rounds", ri, phase, r[phase].index(e)]
            if kind in {"dance_result", "trade_result", "puppet_effect"} and inference._is_empty_unknown(e):
                action = effect["result"]
                if action in templates[phase].get(slot, {}).get("actions", []):
                    change(e, "action", action, path, "known_board_settlement", [effect])
                    targets = effect.get("expected_deaths", []) if kind == "dance_result" else effect.get("targets", [])
                    change(e, "targets", targets, path, "known_board_settlement", [effect])
            elif kind == "poison_immunity":
                if effect.get("seat") in e.get("targets", []) and e.get("action") == "poison" and e.get("result") is None:
                    change(e, "result", "immune", path, "role_poison_immunity", [effect])
            elif kind == "wolf_attack_blocked":
                if e.get("action") == "attack" and e.get("result") is None:
                    change(e, "result", "protected_by_dance", path, "dancer_in_dance_protection", [effect])
            elif e.get("action") not in INACTIVE and e.get("result") in {None, "", "unknown"}:
                change(e, "result", effect["result"], path, "known_board_feedback_or_outcome", [effect])

        for phase in ("night", "day"):
            for ei, e in enumerate(r.get(phase, [])):
                slot = e["slot"]
                path = ["dossier", "rounds", ri, phase, ei]
                actor = _role_owner(e, roles, templates[phase].get(slot, {}))
                later_use = unique_resource_uses.get((actor, slot))
                if (phase == "night" and later_use is not None and later_use > n
                        and actor not in before and inference._is_empty_unknown(e)
                        and "pass" in templates[phase].get(slot, {}).get("actions", [])):
                    rule = "unique_later_learning_proves_earlier_nonuse" if slot == "mechanical_action" else "unique_later_bottle_use_proves_earlier_nonuse"
                    change(e, "action", "pass", path, rule,
                           [{"actor": actor, "slot": slot, "used_on_night": later_use}])
                    change(e, "actor", actor, path, "unique_role_owner", [actor])
                # Election self-destruct may precede this night's announcement,
                # just like an observed initial sheriff vote. Earlier days'
                # departures still rule out any new ordinary action.
                dead_at_opportunity = before if phase == "night" or slot == "self_destruct" else before_vote
                past_end = bool(terminal and (n > terminal["round"] or
                                (n == terminal["round"] and terminal["phase"] == "night" and phase == "day")))
                constraint = event_constraint(game, n, phase, e, actor=actor,
                    dead_before=dead_at_opportunity, uses=uses, used_targets=used_targets,
                    previous=previous, learning=learning)
                board_constraint = board_constraints.get((phase, slot))
                if board_constraint and board_constraint["status"] != "unknown":
                    constraint = {**constraint, **board_constraint}
                status, reason = constraint.get("status", "unknown"), constraint.get("reason", "evidence_needed")
                ordinary_king_trigger = (
                    inference.ordinary_wolf_king_shot_triggered(
                        game, n, actor, round_events, exiles=current_exiles,
                    )
                    if actor == ordinary_king and slot in {"wolf_king_state", "wolf_king_shot"}
                    else None
                )
                terminal_check_skipped = (
                    phase == "night" and wolf_killed_last_god
                    and inference.night_slot_after_wolf_attack(game, slot)
                )
                terminal_hunter_shot_skipped = (
                    phase == "day" and slot == "hunter_shot"
                    and inference.terminal_god_departure(
                        game, n, phase, before, round_events, terminal,
                    )
                )
                ordinary_king_state_before_departure = (
                    slot == "wolf_king_state" and actor in roles.get("狼王", [])
                    and actor not in current_departures and actor not in before
                )
                ordinary_king_state_ended = (
                    slot == "wolf_king_state" and terminal_last_wolf_king and actor == ordinary_king
                )
                ordinary_king_state_without_trigger = (
                    phase == "night" and slot == "wolf_king_state"
                    and actor == ordinary_king and actor in current_departures
                    and not terminal_last_wolf_king
                    and ordinary_king_trigger is False
                    and reason not in {"wolf_king_poisoned", "dream_death_blocks_shot"}
                )
                terminal_wolf_king_shot_skipped = (
                    phase == "day" and slot == "wolf_king_shot"
                    and terminal_last_wolf_king and actor == ordinary_king
                )
                ordinary_king_shot_without_trigger = (
                    phase == "day" and slot == "wolf_king_shot"
                    and actor == ordinary_king and not terminal_last_wolf_king
                    and ordinary_king_trigger is False
                )
                ordinary_king_shot_trigger_unknown = (
                    phase == "day" and slot == "wolf_king_shot"
                    and actor == ordinary_king and actor in current_departures
                    and not terminal_last_wolf_king and ordinary_king_trigger is None
                    and inference._is_empty_unknown(e)
                )
                if terminal_check_skipped or terminal_hunter_shot_skipped or terminal_wolf_king_shot_skipped:
                    status, reason = "unavailable", "game_ended_before_action"
                elif past_end:
                    status, reason = "unavailable", "game_ended"
                elif ordinary_king_state_ended:
                    status, reason = "unavailable", "game_ended_before_action"
                elif ordinary_king_state_before_departure:
                    status, reason = "unknown", "wolf_king_departure_not_confirmed"
                elif ordinary_king_state_without_trigger:
                    status, reason = "unavailable", "death_trigger_absent"
                elif ordinary_king_shot_without_trigger and e.get("action") in {None, "unknown", "unavailable"}:
                    status, reason = "unavailable", "death_trigger_absent"
                elif ordinary_king_shot_trigger_unknown and status != "unavailable":
                    status, reason = "unknown", "wolf_king_trigger_unknown"
                elif actor in current_dq and phase == "day":
                    status, reason = "unavailable", "disqualified"
                elif actor in before and slot in {"hunter_state", "wolf_king_state", "mechanical_knife_status"}:
                    status, reason = "unavailable", "actor_departed"
                elif (actor in dead_at_opportunity and slot not in {"badge", "sheriff_result", "hunter_state", "wolf_king_state"}
                      and not (phase == "day" and slot in TRIGGERED and actor not in before)):
                    status, reason = "unavailable", "actor_departed"
                if (slot in TRIGGERED and actor is not None and actor not in dead_at_opportunity
                        and phase == "day" and e.get("action") in {None, "unknown"}):
                    # An exile in this day may still trigger a subsequent shot.
                    exiled = {s for x in day_non_results if x.get("action") == "exile" for s in x.get("targets", [])}
                    exiled.update(b.get("winner") for b in exile_ballots if b.get("winner"))
                    if actor not in exiled:
                        status, reason = "unavailable", "death_trigger_absent"
                if status == "unavailable":
                    replacement = "unavailable"
                    if reason == "treasure_first_night_attack_forbidden":
                        replacement = "forbidden"
                    elif slot in {"hunter_state", "wolf_king_state"} and reason in {"hunter_poisoned", "wolf_king_poisoned", "dream_death_blocks_shot"}:
                        replacement = "cannot_shoot"
                    if (inference._is_empty_unknown(e) and replacement in templates[phase].get(slot, {}).get("actions", [])
                            and not ordinary_king_state_before_departure
                            and not ordinary_king_state_ended):
                        change(e, "action", replacement, path, reason, [n, phase, actor])
                    elif (slot in {"hunter_state", "wolf_king_state", "mechanical_knife_status"}
                          and actor in before and "unavailable" in templates[phase].get(slot, {}).get("actions", [])):
                        change(e, "action", "unavailable", path, "qualification_ends_on_departure", [n, actor])
                    elif (e.get("action") in ACTIVE_ACTIONS and reason not in {"marked_side_not_strictly_larger", "puppet_selected_skill_disabled"}
                          and not (past_end and slot == "night_deaths")):
                        issue("action_unavailable", n, phase, slot, actor=actor, reason=reason)
                legal = constraint.get("legal_targets")
                if legal is not None and slot in {"guard", "seer_check", "wolf_attack", "witch_save", "witch_poison",
                                                   "dreamer_action", "masquerade_verify", "masquerade_mask", "dancer_dance", "warden_trade_targets"}:
                    legal = sorted(set(legal) - dead_at_opportunity)
                if legal is not None and e.get("action") not in INACTIVE | {"pass"}:
                    illegal = sorted(set(e.get("targets", [])) - set(legal))
                    if illegal and status != "unavailable":
                        issue("illegal_targets", n, phase, slot, actor=actor, targets=illegal, reason=reason)
                review_required = status != "unavailable"
                if slot == "wolf_king_state" and actor in roles.get("狼王", []):
                    review_required = False
                if slot in {"hunter_state", "wolf_king_state"} and night_known and actor not in night_dead:
                    review_required = False
                if slot == "self_destruct" and exile_ballots:
                    review_required = False
                if slot in {"sheriff_candidates", "sheriff_vote", "sheriff_result"} and (badge_known or badge_lost):
                    review_required = False
                if slot == "badge" and (badge_known or badge_lost):
                    review_required = False
                state = {"round": n, "phase": phase, "slot": slot, "actor": actor,
                         "status": status, "reason": reason, "legal_targets": legal}
                state["review_required"] = review_required and inference._is_empty_unknown(e)
                if constraint.get("availability"):
                    state["availability"] = constraint["availability"]
                if constraint.get("consequences"):
                    state["consequences"] = constraint["consequences"]
                states.append(state)
                if state["review_required"]:
                    work.append({"round": n, "phase": phase, "slot": slot, "actor": actor,
                                 "reason": reason, "legal_targets": legal})
                if e.get("action") not in INACTIVE | {"pass"}:
                    uses[(actor, slot)] += 1
                    same_pair = (slot == "guile_exchange" and
                                 (magician := _event(r, "magician_exchange", "night")) is not None and
                                 magician.get("action") == "exchange" and
                                 set(magician.get("targets", [])) == set(e.get("targets", [])))
                    if same_pair:
                        # Cancellation is known; whether it consumes a future
                        # target use is not. Do not turn it into a false ban.
                        used_targets[(actor, slot)] = None
                    elif used_targets.get((actor, slot), set()) is not None:
                        used_targets.setdefault((actor, slot), set()).update(e.get("targets", []))
                previous[(actor, slot)] = {"round": n, "action": e.get("action"), "targets": e.get("targets", [])}
                if slot == "mechanical_action" and e.get("action") == "learn" and e.get("targets"):
                    form = e.get("result") or by_seat.get(actor, {}).get("learned_role")
                    learning[actor] = {"round": n, "target": e["targets"][0], "form": form}

        exiled = {s for e in day_non_results if e.get("action") == "exile" for s in e.get("targets", [])}
        if exile_ballots and exile_ballots[-1].get("winner"):
            exiled.add(exile_ballots[-1]["winner"])
        after = before_vote | inference._actual_deaths(day_non_results) | exiled
        ended = bool(exile_ballots or exiled or any(e.get("action") == "self_destruct" or
                     (e.get("slot") == "exile_result" and e.get("action") == "none") for e in day_non_results))
        unresolved_shot = any(inference._is_empty_unknown(e) and e.get("slot") in TRIGGERED
                              and _role_owner(e, roles, templates["day"].get(e["slot"], {})) in (night_dead | exiled)
                              for e in day_non_results)
        exact = vote_exact and ended and not unresolved_shot
        for e in day_non_results:
            if e.get("slot") == "sheriff_result" and e.get("action") == "elected" and e.get("targets"):
                badge_holder, badge_known, badge_lost = e["targets"][0], True, False
            elif e.get("slot") == "badge" and e.get("action") in {"transfer", "hold"}:
                badge_holder = (e.get("targets") or [e.get("actor")])[0]
                badge_known, badge_lost = badge_holder is not None, False
            elif e.get("slot") == "badge" and (e.get("action") == "destroy" or e.get("result") in {"badge_lost", "badge_destroyed"}):
                badge_holder, badge_known, badge_lost = None, True, True
        if any(d.get("day") == n and d.get("sheriff") == "badge_lost" for d in (votes or {}).get("days", [])):
            badge_holder, badge_known, badge_lost = None, True, True
        timeline.append({"day": n, "dead_before_night": sorted(before), "night_deaths": sorted(night_dead),
                         "night_deaths_complete": night_known, "living_before_vote": living,
                         "living_after_day": sorted(roster - after) if exact else None,
                         "known_departed_after_day": sorted(after), "disqualified": sorted(current_dq), "badge_holder": badge_holder,
                         "badge_known": badge_known, "badge_lost": badge_lost})
        dead = after

    if votes is not None and speech_evidence:
        _derive_sheriff_registration(votes, speech_evidence, roster, changes)
    vote_work = _derive_voting(game, votes, timeline, terminal, changes, issues) if votes is not None else []
    report = {"schema_version": 1, "version": VERSION, "game_slug": game.get("slug"),
              "input_hashes": inputs, "rule_sources": rule_sources(), "terminal": terminal,
              "rounds": timeline, "slot_states": states, "review_tasks": work,
              "vote_review_tasks": vote_work,
              "changes": changes, "consequences": consequences, "issues": issues, "gaps": gaps,
              "output_hashes": {"dossier": fingerprint(game), "voting": fingerprint(votes)}}
    if speech_evidence is not None:
        report["sheriff_speech_evidence"] = deepcopy(speech_evidence)
    # JSON object keys (for example a dance's seat-to-faction map) are strings.
    # Normalize once at the artifact boundary so prepare/read/compare is exact.
    report = json.loads(json.dumps(report, ensure_ascii=False))
    return {"dossier": game, "voting": votes, "derivations": report}


def _derive_sheriff_registration(votes, evidence, roster, changes):
    """Direct judge lists fill signup; speech chains remain supporting evidence."""
    existing = [r for r in votes.get("registrations", []) if r.get("day") == 1]
    if existing:
        return
    direct = evidence.get("registration")
    if not direct or direct.get("day") != 1:
        return
    on = set(direct["on_police"])
    if not on <= roster or set(direct["off_police"]) != roster - on:
        raise ValueError("法官报名名单缺少一致的上警/警下集合")
    old = deepcopy(votes["registrations"])
    new = old + [{"id": "derived-judge-initial-registration", "day": 1,
                  "on_police": sorted(on), "off_police": sorted(roster - on)}]
    changes.append({"path": ["voting", "registrations"], "before": old, "after": deepcopy(new),
                    "rule": "judge_initial_sheriff_signup_list", "dependencies": ["sheriff_speech_evidence.registration"]})
    votes["registrations"] = new


def _derive_voting(game, votes, timeline, terminal, changes, issues):
    rounds = {r["number"]: r for r in game.get("rounds", [])}
    flow = {r["day"]: r for r in timeline}
    registrations = {r["day"]: r for r in votes.get("registrations", [])}

    def set_value(obj, key, new, path, rule, dependencies):
        if obj.get(key) != new:
            changes.append({"path": path + [key], "before": deepcopy(obj.get(key)), "after": deepcopy(new),
                            "rule": rule, "dependencies": dependencies})
            obj[key] = deepcopy(new)

    for bi, b in enumerate(votes.get("ballots", [])):
        day = b.get("day")
        row = flow.get(day, {})
        eligible = None
        if terminal and (day > terminal["round"] or (day == terminal["round"] and terminal["phase"] == "night")):
            issues.append({"code": "ballot_after_terminal", "round": day, "ballot": b.get("id")})
            continue
        if b.get("kind") == "exile" and row.get("living_before_vote") is not None:
            eligible = set(row["living_before_vote"])
            if b.get("stage") == "pk":
                eligible -= set(b.get("candidates") or [])
        elif b.get("kind") == "sheriff" and day in {1, 2} and registrations:
            registration = registrations.get(1)
            if registration and b.get("stage") != "pk":
                # Initial/deferred elections can precede current night death
                # announcements. Preserve their observed electorate.
                eligible = set(registration["off_police"]) - set(row.get("dead_before_night", []))
        if eligible is None:
            continue
        actual = {x["voter"] for x in b.get("votes", [])}
        invalid = actual - eligible
        if invalid:
            issues.append({"code": "ineligible_recorded_voter", "round": day, "ballot": b.get("id"),
                           "seats": sorted(invalid)})
            continue
        path = ["voting", "ballots", bi]
        set_value(b, "eligible_voters", sorted(eligible), path, "survival_and_ballot_stage", [day, b.get("kind"), b.get("stage")])
        if len(eligible) == 1 and not actual and b.get("winner") and b.get("kind") == "sheriff":
            voter = next(iter(eligible))
            set_value(b, "votes", [{"voter": voter, "target": b["winner"], "state": "cast"}], path,
                      "unique_elector_and_elected_result", [day, sorted(eligible), b["winner"]])
            actual.add(voter)
        missing = sorted(eligible - actual)
        set_value(b, "unrecorded_voters", missing, path, "electorate_minus_recorded_votes", [day])
        set_value(b, "status", "partial" if missing else "complete", path, "electorate_coverage", [day])
    for di, d in enumerate(votes.get("days", [])):
        n = d["day"]
        round_ = rounds.get(n, {})
        found = [b for b in votes.get("ballots", []) if b.get("day") == n]
        self_destruct = _event(round_, "self_destruct", "day")
        if _self_destruct_ends_unvoted_day(round_, found) and d.get("exile") == "unknown":
            set_value(d, "exile", "interrupted_self_destruct", ["voting", "days", di],
                      "self_destruct_ends_unvoted_day", [n, self_destruct.get("actor")])
        if not any(b.get("kind") == "sheriff" for b in found) and d.get("sheriff") == "unknown":
            earlier = [row for row in timeline if row["day"] < n]
            if earlier and earlier[-1].get("badge_known"):
                set_value(d, "sheriff", "badge_lost" if earlier[-1].get("badge_lost") else "not_applicable",
                          ["voting", "days", di], "election_already_resolved", [earlier[-1]["day"]])
    tasks = []
    for b in votes.get("ballots", []):
        common = {"round": b.get("day"), "phase": "day", "ballot_id": b.get("id")}
        if b.get("eligible_voters") is None:
            tasks.append({**common, "slot": "vote_eligibility", "reason": "electorate_evidence_needed"})
        else:
            targets = b.get("candidates") or flow.get(b.get("day"), {}).get("living_before_vote")
            tasks.extend({**common, "slot": "vote_choice", "actor": voter, "legal_targets": targets,
                          "reason": "unresolved_recorded_vote_gap"} for voter in b.get("unrecorded_voters") or [])
    return tasks


def restore_source_records(dossier, voting, report):
    """Undo our unchanged previous outputs before recomputing dependencies."""
    values = {"dossier": deepcopy(dossier), "voting": deepcopy(voting)}
    for patch in reversed((report or {}).get("changes", [])):
        path = patch["path"]
        node = values
        try:
            for key in path[:-1]:
                node = node[key]
            if node[path[-1]] == patch["after"]:
                node[path[-1]] = deepcopy(patch["before"])
        except (KeyError, IndexError, TypeError):
            # A user/source change can remove the previous derived object.
            continue
    return values


def apply_precomputed(dossier, voting, report):
    """Validate and consume saved derivations without running any game rules."""
    if report.get("version") != VERSION or report.get("game_slug") != dossier.get("slug"):
        raise ValueError("规则推导版本或对局关联不一致，请重新生成")
    if report.get("rule_sources") != rule_sources():
        raise ValueError("通用规则已变化，请重新生成规则推导")
    values = {"dossier": deepcopy(dossier), "voting": deepcopy(voting)}
    actual = {k: fingerprint(v) for k, v in values.items()}
    if actual == report.get("output_hashes"):
        return values
    if any(actual[k] != report.get("input_hashes", {}).get(k) for k in actual):
        raise ValueError("基础事实已变化，规则推导已过期，请重新生成")
    for patch in report.get("changes", []):
        node = values
        for key in patch["path"][:-1]:
            node = node[key]
        key = patch["path"][-1]
        current = node.get(key) if isinstance(node, dict) else node[key]
        if current != patch["before"]:
            raise ValueError("规则推导依赖与当前字段不一致")
        node[key] = deepcopy(patch["after"])
    if {k: fingerprint(v) for k, v in values.items()} != report.get("output_hashes"):
        raise ValueError("规则推导输出指纹不一致")
    return values

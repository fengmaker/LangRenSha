"""Derive board-specific constraints and outcomes from explicit game facts.

This module never rewrites the game record.  Uncertain survival, faction,
mask, mark, or action-order facts stay unresolved in the returned report.
"""
from __future__ import annotations

from collections import Counter


_WOLF_ROLES = {
    "狼人", "机械狼", "狼王", "黑狼王", "诡术师", "假面", "典狱长",
    "白狼王", "九尾狐", "盗宝大师", "狼术师",
}
_GOOD_ROLES = {
    "预言家", "通灵师", "女巫", "猎人", "守卫", "白神", "白痴",
    "骑士", "摄梦人", "平民", "魔术师", "定序王子", "舞者", "毒师",
    "蒙面人", "白泽",
}
_INACTIVE = {"pass", "unavailable", "forbidden", "not_applicable", "not_held", "none", "no_effect"}
_TRADE_CHOICES = {
    "trade": ("trade", "trade"),
    "betray": ("betray", "betray"),
    "trade_betray": ("trade", "betray"),
    "betray_trade": ("betray", "trade"),
}
_RESULT_FACTIONS = {
    "good": "good", "good_faction": "good", "civilian": "good", "god": "good",
    "好人": "good", "好人阵营": "good", "平民": "good", "神职": "good",
    "werewolf": "werewolf", "wolf": "werewolf", "wolf_faction": "werewolf",
    "狼人": "werewolf", "狼人阵营": "werewolf", "狼队": "werewolf",
}
_SUCCESSFUL_RESULTS = {
    "success", "successful", "effect_applied", "guarded", "protected",
    "protected_by_guard", "protected_by_dance_pool", "saved", "poisoned",
    "shot_hit", "hit", "成功", "成功生效", "保护成功", "保护生效",
    "守护成功", "守住", "解药生效", "毒药生效", "毒杀成功", "猎枪命中",
    "开枪命中", "命中", "击中",
}


def _family(game: dict) -> str | None:
    code = game.get("board")
    if not isinstance(code, str):
        return None
    for prefix in ("s21_", "s23_"):
        if code.startswith(prefix):
            return code[len(prefix):]
    return code


def _seat_rows(game: dict) -> dict[int, dict]:
    return {row["seat"]: row for row in game.get("seats", [])
            if isinstance(row, dict) and type(row.get("seat")) is int}


def _seat_ids(game: dict) -> list[int]:
    return sorted(_seat_rows(game))


def _rounds(game: dict) -> dict[int, dict]:
    return {row["number"]: row for row in game.get("rounds", [])
            if isinstance(row, dict) and type(row.get("number")) is int}


def _event(round_: dict | None, phase: str, slot: str) -> dict | None:
    if not isinstance(round_, dict):
        return None
    return next((event for event in round_.get(phase, [])
                 if isinstance(event, dict) and event.get("slot") == slot), None)


def _all_events(game: dict, *, slot: str, phase: str | None = None) -> list[tuple[int, str, dict]]:
    result = []
    for round_ in game.get("rounds", []):
        if not isinstance(round_, dict) or type(round_.get("number")) is not int:
            continue
        phases = (phase,) if phase else ("night", "day")
        for phase_name in phases:
            for event in round_.get(phase_name, []) or []:
                if isinstance(event, dict) and event.get("slot") == slot:
                    result.append((round_["number"], phase_name, event))
    return sorted(result, key=lambda row: (row[0], 0 if row[1] == "night" else 1))


def _targets(event: dict | None) -> list[int] | None:
    if not isinstance(event, dict) or not isinstance(event.get("targets"), list):
        return None
    targets = event["targets"]
    if any(type(seat) is not int for seat in targets) or len(set(targets)) != len(targets):
        return None
    return list(targets)


def _role(seats: dict[int, dict], seat: int) -> str | None:
    value = seats.get(seat, {}).get("role")
    if not isinstance(value, str) or value.strip().lower() in {"", "unknown", "unavailable", "待核", "未知"}:
        return None
    return value


def _claims_success(result) -> bool:
    if not isinstance(result, str):
        return False
    value = result.strip().lower().replace(" ", "_")
    return value in _SUCCESSFUL_RESULTS


def _faction(seats: dict[int, dict], seat: int) -> str | None:
    row = seats.get(seat, {})
    faction = row.get("faction")
    if faction in {"good", "werewolf"}:
        return faction
    role = _role(seats, seat)
    if role in _WOLF_ROLES:
        return "werewolf"
    if role in _GOOD_ROLES:
        return "good"
    return None


def _add_constraint(rows: list[dict], phase: str, slot: str, status: str,
                    reason: str, legal_targets: list[int] | None = None) -> None:
    row = {"phase": phase, "slot": slot, "status": status, "reason": reason}
    if legal_targets is not None:
        row["legal_targets"] = legal_targets
    rows.append(row)


def _add_issue(rows: list[dict], code: str, phase: str, slot: str, **details) -> None:
    rows.append({"code": code, "phase": phase, "slot": slot, **details})


def _wolf_seats(seats: dict[int, dict]) -> tuple[set[int], bool]:
    wolves, complete = set(), True
    for seat, row in seats.items():
        role = _role(seats, seat)
        faction = row.get("faction")
        if faction == "werewolf" or role in _WOLF_ROLES:
            wolves.add(seat)
        elif faction in {"good", "third_party"} or role in _GOOD_ROLES:
            continue
        else:
            complete = False
    return wolves, complete


def _seat_list(value) -> list[int] | None:
    if value is None:
        return None
    try:
        seats = list(value)
    except TypeError:
        return None
    if any(type(seat) is not int for seat in seats) or len(set(seats)) != len(seats):
        return None
    return sorted(seats)


def _puppet_selection(game: dict, number: int) -> tuple[int | None, bool]:
    selections = _all_events(game, slot="puppet_select", phase="night")
    selected = None
    uncertain = False
    for round_no, _, event in selections:
        if round_no > number:
            continue
        if event.get("action") == "select":
            targets = _targets(event)
            if targets is None or len(targets) != 1 or selected is not None:
                uncertain = True
            else:
                selected = targets[0]
        elif event.get("action") not in _INACTIVE:
            uncertain = True
    return selected, uncertain


def _neighbor_puppet(game: dict, number: int, living_before_night,
                     constraints: list[dict], consequences: list[dict], issues: list[dict]) -> None:
    seats = _seat_rows(game)
    rows = _rounds(game)
    current = rows.get(number)
    event = _event(current, "night", "puppet_select")
    living = _seat_list(living_before_night)

    if number != 1:
        status, reason = "unavailable", "puppet_selection_is_first_night_only"
        legal = None
    elif living is None:
        status, reason, legal = "unknown", "living_before_night_unknown", None
    else:
        # 首夜相邻资格以原狼牌为准；已归狼阵营的傀儡不能扩展可选邻座。
        wolves = {seat for seat in seats if _role(seats, seat) in {'狼人', '狼王'}}
        roles_complete = all(_role(seats, seat) is not None for seat in seats)
        roster_complete = bool(seats) and set(seats) == set(range(1, max(seats) + 1))
        if not roles_complete or not roster_complete or not wolves:
            status, reason, legal = "unknown", "wolf_seats_unknown", None
        else:
            adjacent = set()
            max_seat = max(seats)
            for wolf in wolves:
                adjacent.update({((wolf - 2) % max_seat) + 1, (wolf % max_seat) + 1})
            legal = sorted(adjacent & set(living))
            status, reason = "available", "first_night_puppet_targets_adjacent_to_any_wolf"
    _add_constraint(constraints, "night", "puppet_select", status, reason, legal)

    if event and event.get("action") == "select":
        targets = _targets(event)
        if number != 1:
            _add_issue(issues, "puppet_not_first_night", "night", "puppet_select")
        if targets is None or len(targets) != 1:
            _add_issue(issues, "puppet_target_not_unique", "night", "puppet_select")
        elif legal is not None and targets[0] not in legal:
            _add_issue(issues, "puppet_target_not_adjacent_to_wolf", "night", "puppet_select",
                       target=targets[0], legal_targets=legal)

    puppet, uncertain = _puppet_selection(game, number)
    if puppet is None:
        if uncertain:
            _add_constraint(constraints, "night", "puppet_skill_effect", "unknown",
                            "puppet_selection_or_target_history_conflicts")
        return
    role = _role(seats, puppet)
    if role is None:
        _add_constraint(constraints, "night", "puppet_skill_effect", "unknown",
                        "puppet_physical_identity_unknown")
        return

    effect = None
    if role == "预言家":
        effect = {"type": "seer_feedback_reversal", "seat": puppet,
                  "rule": "S22:boards.neighbor_puppet.board_rules.effects.seer",
                  "effective_from_round": 2}
    elif role in {"女巫", "守卫", "猎人"}:
        effect = {"type": "skill_disabled", "seat": puppet, "role": role,
                  "rule": "S22:boards.neighbor_puppet.board_rules.effects",
                  "effective_from_round": 2}
    if effect:
        consequences.append(effect)

    if role != "猎人":
        _add_constraint(constraints, "day", "puppet_hunter_eligibility", "unavailable",
                        "selected_puppet_is_not_hunter")
    elif number > 1:
        _add_constraint(constraints, "day", "puppet_hunter_eligibility", "unavailable",
                        "puppet_selected_skill_disabled")
    if number > 1 or effect is None:
        action = "reverse_check" if role == "预言家" else "skill_disabled" if effect else "no_effect"
        consequences.append({"type": "puppet_effect", "result": action, "targets": [puppet],
                             "rule": "S22:boards.neighbor_puppet.board_rules.effects"})

    if number == 1:
        if effect:
            _add_constraint(constraints, "night", "puppet_skill_effect", "unknown",
                            "same_night_wake_order_not_proven")
        return
    if role == "预言家":
        for event in current.get("night", []) if isinstance(current, dict) else []:
            if event.get("slot") != "seer_check" or event.get("actor") != puppet or event.get("action") != "check":
                continue
            targets = _targets(event)
            if targets is None or len(targets) != 1:
                continue
            checked_faction = _faction(seats, targets[0])
            if checked_faction is None:
                continue
            expected = "good" if checked_faction == "werewolf" else "werewolf"
            consequences.append({"type": "expected_seer_feedback", "seat": puppet,
                                 "target": targets[0], "result": expected,
                                 "rule": "S22:boards.neighbor_puppet.board_rules.effects.seer"})
            if event.get("result") in {"good", "werewolf"} and event["result"] != expected:
                _add_issue(issues, "puppet_seer_feedback_conflict", "night", "seer_check",
                           seat=puppet, target=targets[0], observed=event["result"], expected=expected)
    else:
        disabled_slots = {"女巫": {"witch_save", "witch_poison"},
                          "守卫": {"guard"}, "猎人": {"hunter_state", "hunter_shot"}}.get(role, set())
        disabled_by_phase = {"night": {"witch_save", "witch_poison", "guard", "hunter_state"},
                             "day": {"hunter_shot"}}
        for phase, slots in disabled_by_phase.items():
            for slot in sorted(slots & disabled_slots):
                action = _event(current, phase, slot)
                if action and action.get("action") not in _INACTIVE | {"unknown"}:
                    result = action.get("result")
                    consequences.append({"type": "observed_ineffective_action", "slot": slot,
                                         "actor": action.get("actor"),
                                         "targets": _targets(action),
                                         "action": action.get("action"),
                                         "observed_result": result,
                                         "rule": "S22:boards.neighbor_puppet.board_rules.effects"})
                    if _claims_success(result):
                        _add_issue(issues, "puppet_disabled_skill_result_conflict", phase, slot,
                                   seat=puppet, observed_result=result)
                else:
                    _add_constraint(constraints, phase, slot, "unavailable",
                                    "puppet_selected_skill_disabled")


def _masquerade(game: dict, number: int, living_before_night,
                constraints: list[dict], consequences: list[dict], issues: list[dict]) -> None:
    rows, seats = _rounds(game), _seat_rows(game)
    current = rows.get(number)
    living = _seat_list(living_before_night)

    if number == 1:
        first_dance = _event(current, "night", "dancer_dance")
        if first_dance and first_dance.get("action") == "dance":
            _add_issue(issues, "dance_first_night_unavailable", "night", "dancer_dance")
        _add_constraint(constraints, "night", "dancer_dance", "unavailable",
                        "dance_starts_second_night")
    else:
        dance = _event(current, "night", "dancer_dance")
        used, unknown_history = set(), False
        all_rounds = _rounds(game)
        for prior_no in range(1, number):
            prior_round = all_rounds.get(prior_no)
            if prior_round is None or _event(prior_round, "night", "dancer_dance") is None:
                unknown_history = True
        for round_no, _, prior in _all_events(game, slot="dancer_dance", phase="night"):
            if round_no >= number:
                continue
            if prior.get("action") == "dance":
                targets = _targets(prior)
                if targets is None or len(targets) != 3:
                    unknown_history = True
                else:
                    used.update(targets)
            elif prior.get("action") not in _INACTIVE:
                unknown_history = True
        if unknown_history:
            _add_constraint(constraints, "night", "dancer_dance", "unknown",
                            "previous_dance_participants_unknown")
        elif living is None:
            _add_constraint(constraints, "night", "dancer_dance", "unknown",
                            "living_before_night_unknown")
        else:
            legal = sorted(set(living) - used)
            _add_constraint(constraints, "night", "dancer_dance", "available",
                            "dance_three_living_players_once_per_game", legal)
            if dance and dance.get("action") == "dance":
                targets = _targets(dance)
                if targets is None or len(targets) != 3:
                    _add_issue(issues, "dance_target_count_invalid", "night", "dancer_dance")
                elif used.intersection(targets):
                    _add_issue(issues, "dance_participant_reused", "night", "dancer_dance",
                               seats=sorted(used.intersection(targets)))
                elif not set(targets).issubset(living):
                    _add_issue(issues, "dance_target_not_living", "night", "dancer_dance",
                               seats=sorted(set(targets) - set(living)))

    poison = _event(current, "night", "witch_poison")
    poison_immune_roles = {seat for seat in seats if _role(seats, seat) in {"假面", "舞者"}}
    if poison and poison.get("action") == "poison":
        targets = _targets(poison)
        if targets is not None:
            for target in sorted(set(targets) & poison_immune_roles):
                consequences.append({"type": "poison_immunity", "seat": target,
                                     "source_slot": "witch_poison",
                                     "rule": "S22:boards.masquerade.board_rules.poison_immunity"})

    dance = _event(current, "night", "dancer_dance")
    targets = _targets(dance)
    actor = dance.get("actor") if isinstance(dance, dict) else None
    if number > 1 and dance and dance.get("action") == "dance" and targets is not None and len(targets) == 3:
        if type(actor) is int and actor in targets:
            for target in targets:
                consequences.append({"type": "wolf_attack_immunity", "seat": target,
                                     "reason": "dancer_is_in_three_person_dance_pool",
                                     "rule": "S22:boards.masquerade.board_rules.dancer_in_dance"})
        _dance_outcome(game, number, current, dance, targets, seats, living,
                       consequences, issues)


def _dance_outcome(game: dict, number: int, current: dict, dance: dict, targets: list[int],
                   seats: dict[int, dict], living: list[int] | None,
                   consequences: list[dict], issues: list[dict]) -> None:
    if living is None:
        return
    if not set(targets).issubset(living):
        return
    mask = _event(current, "night", "masquerade_mask")
    if mask is None or mask.get("action") == "unknown":
        _add_issue(issues, "dance_mask_state_unknown", "night", "dance_resolution",
                   reason="mask slot does not prove whether a participant's dance faction changed")
        return
    masked_seat = None
    masked_faction = None
    if mask.get("action") == "give_mask":
        mask_targets = _targets(mask)
        if mask_targets is None or len(mask_targets) != 1:
            _add_issue(issues, "dance_mask_target_unknown", "night", "dance_resolution")
            return
        masked_seat = mask_targets[0]
        masked_faction = _RESULT_FACTIONS.get(str(mask.get("result", "")).strip().lower())
        if masked_seat in targets and masked_faction is None:
            _add_issue(issues, "dance_mask_faction_unknown", "night", "dance_resolution", seat=masked_seat)
            return

    factions = {}
    for seat in targets:
        faction = masked_faction if seat == masked_seat else _faction(seats, seat)
        if faction is None:
            _add_issue(issues, "dance_faction_unknown", "night", "dance_resolution", seat=seat)
            return
        factions[seat] = faction
    counts = Counter(factions.values())
    if len(counts) == 1:
        expected_action, victims = "no_death", []
    elif len(counts) == 2 and max(counts.values()) == 2:
        minority = min(counts, key=lambda faction: counts[faction])
        expected_action = "minority_dies"
        victims = sorted(seat for seat, faction in factions.items() if faction == minority)
    else:
        _add_issue(issues, "dance_minority_not_unique", "night", "dance_resolution",
                   factions=factions)
        return

    consequences.append({"type": "dance_result", "number": number,
                         "result": expected_action, "expected_deaths": victims,
                         "factions": factions,
                         "rule": "S22:boards.masquerade.board_rules.dance"})
    observed = _event(current, "night", "dance_resolution")
    if observed and observed.get("action") in {"no_death", "minority_dies"}:
        if observed["action"] != expected_action:
            _add_issue(issues, "dance_resolution_conflict", "night", "dance_resolution",
                       observed=observed["action"], expected=expected_action,
                       expected_deaths=victims)
    night_deaths = _event(current, "day", "night_deaths")
    if victims and night_deaths and night_deaths.get("action") == "peaceful":
        _add_issue(issues, "dance_death_conflicts_with_peaceful_night", "day", "night_deaths",
                   expected_deaths=victims)

    attack = _event(current, "night", "wolf_attack")
    attack_targets = _targets(attack)
    if type(dance.get("actor")) is int and dance["actor"] in targets and attack_targets:
        protected = set(targets).intersection(attack_targets)
        if protected:
            consequences.append({"type": "wolf_attack_blocked", "seats": sorted(protected),
                                 "rule": "S22:boards.masquerade.board_rules.dancer_in_dance"})


def _warden_seat(seats: dict[int, dict]) -> int | None:
    matches = [seat for seat in seats if _role(seats, seat) == "典狱长"]
    return matches[0] if len(matches) == 1 else None


def _trade_history(game: dict, number: int) -> tuple[set[int], bool]:
    used, uncertain = set(), False
    rounds = _rounds(game)
    for round_no in range(1, number):
        round_ = rounds.get(round_no)
        selected = _event(round_, "night", "warden_trade_targets")
        decision = _event(round_, "night", "trade_decisions")
        if selected is None or decision is None:
            uncertain = True
            continue
        if selected.get("action") in _INACTIVE and decision.get("action") in _INACTIVE:
            continue
        pair = _targets(selected)
        if selected.get("action") != "select_pair" or pair is None or len(pair) != 2:
            if selected.get("action") not in _INACTIVE or decision.get("action") not in _INACTIVE:
                uncertain = True
            continue
        choices = _TRADE_CHOICES.get(decision.get("action"))
        decision_targets = _targets(decision)
        if choices is None or decision_targets != pair:
            uncertain = True
            continue
        used.update(pair)
    return used, uncertain


def _all_in(game: dict, number: int, living_before_night,
             constraints: list[dict], consequences: list[dict], issues: list[dict]) -> None:
    rows, seats = _rounds(game), _seat_rows(game)
    current = rows.get(number)
    selected = _event(current, "night", "warden_trade_targets")
    decision = _event(current, "night", "trade_decisions")
    warden = _warden_seat(seats)
    living = _seat_list(living_before_night)
    used, unknown_history = _trade_history(game, number)

    if number == 1:
        _add_constraint(constraints, "night", "warden_trade_targets", "unavailable",
                        "warden_trade_starts_second_night")
    elif warden is None:
        _add_constraint(constraints, "night", "warden_trade_targets", "unknown",
                        "warden_identity_not_unique")
    elif unknown_history:
        _add_constraint(constraints, "night", "warden_trade_targets", "unknown",
                        "prior_trade_participants_or_choices_unknown")
    elif living is None:
        _add_constraint(constraints, "night", "warden_trade_targets", "unknown",
                        "living_before_night_unknown")
    else:
        legal = sorted(set(living) - used)
        _add_constraint(constraints, "night", "warden_trade_targets", "available",
                        "warden_trade_from_second_night_each_participant_once", legal)

    if selected and selected.get("action") == "select_pair":
        pair = _targets(selected)
        if number == 1:
            _add_issue(issues, "warden_trade_first_night", "night", "warden_trade_targets")
        if pair is None or len(pair) != 2:
            _add_issue(issues, "warden_trade_pair_invalid", "night", "warden_trade_targets")
        elif len(pair) != 2 or pair[0] == pair[1]:
            _add_issue(issues, "warden_trade_pair_invalid", "night", "warden_trade_targets")
        else:
            if used.intersection(pair):
                _add_issue(issues, "warden_trade_participant_reused", "night", "warden_trade_targets",
                           seats=sorted(used.intersection(pair)))
            if living is not None and not set(pair).issubset(living):
                _add_issue(issues, "warden_trade_target_not_living", "night", "warden_trade_targets",
                           seats=sorted(set(pair) - set(living)))
    if number > 1 and not any(row.get("slot") == "trade_decisions" for row in constraints):
        pair = _targets(selected)
        choice = decision.get("action") if isinstance(decision, dict) else None
        status = "available" if pair is not None and len(pair) == 2 else "unknown"
        reason = "trade_pair_selected" if status == "available" else "trade_pair_not_confirmed"
        _add_constraint(constraints, "night", "trade_decisions", status, reason, pair)

    if not selected or selected.get("action") != "select_pair" or not decision:
        return
    pair = _targets(selected)
    choices = _TRADE_CHOICES.get(decision.get("action"))
    decision_targets = _targets(decision)
    if pair is None or len(pair) != 2 or choices is None:
        return
    if decision_targets != pair:
        _add_issue(issues, "trade_choice_does_not_match_pair_order", "night", "trade_decisions",
                   selected_pair=pair, decision_targets=decision_targets)
        return
    if number == 1:
        return

    if any(_role(seats, seat) is None for seat in pair):
        _add_issue(issues, "trade_pair_identity_unknown", "night", "trade_decisions", seats=pair)
        return
    pair_wardens = [seat for seat in pair if _role(seats, seat) == "典狱长"]

    if pair_wardens:
        paired_warden = pair_wardens[0]
        warden_choice = choices[pair.index(paired_warden)]
        other = pair[1] if pair[0] == paired_warden else pair[0]
        other_choice = choices[pair.index(other)]
        departing = paired_warden if warden_choice == other_choice else other
        expected_resolution = "warden_self_trade" if departing == paired_warden else "betrayal_death"
        resolution_rule = "S22:boards.all_in.board_rules.resolution.warden_in_pair"
        consequences.append({"type": "expected_death", "seat": departing,
                             "cause": "warden_trade_resolution",
                             "reason": "warden_same_choice" if departing == paired_warden else "warden_different_choice",
                             "rule": resolution_rule})
    elif choices == ("trade", "trade"):
        expected_resolution = "immune"
        resolution_rule = "S22:boards.all_in.board_rules.resolution.trade_trade"
        consequences.append({"type": "night_damage_immunity", "seats": pair,
                             "rule": resolution_rule})
    elif choices == ("betray", "betray"):
        expected_resolution = "mutual_targets"
        resolution_rule = "S22:boards.all_in.board_rules.resolution.betray_betray"
        consequences.append({"type": "skill_target_exchange", "seats": pair,
                             "original_targets_preserved": True,
                             "resolution_order": "unknown",
                             "rule": resolution_rule})
    else:
        trade_seat = pair[choices.index("trade")]
        expected_resolution = "betrayal_death"
        resolution_rule = "S22:boards.all_in.board_rules.resolution.trade_betray"
        consequences.append({"type": "expected_death", "seat": trade_seat,
                             "cause": "warden_trade_resolution", "reason": "mixed_trade_choice",
                             "rule": resolution_rule})

    consequences.append({"type": "trade_result", "result": expected_resolution,
                         "targets": pair, "rule": resolution_rule})

    observed = _event(current, "night", "trade_resolution")
    if observed and observed.get("action") not in _INACTIVE | {"unknown", expected_resolution}:
        _add_issue(issues, "trade_resolution_conflict", "night", "trade_resolution",
                   observed=observed.get("action"), expected=expected_resolution)
    night_deaths = _event(current, "day", "night_deaths")
    if night_deaths and night_deaths.get("action") == "peaceful" and any(
            row["type"] == "expected_death" for row in consequences):
        _add_issue(issues, "trade_death_conflicts_with_peaceful_night", "day", "night_deaths",
                   expected_deaths=[row["seat"] for row in consequences if row["type"] == "expected_death"])


def _fox_mark_history(game: dict, number: int) -> tuple[set[int], bool, list[dict]]:
    marks, complete, issues = set(), True, []
    rounds = _rounds(game)
    for round_no in range(1, number + 1):
        round_ = rounds.get(round_no)
        if round_ is None:
            complete = False
            issues.append({"code": "fox_mark_round_missing", "round": round_no})
            continue
        mark = _event(round_, "night", "nine_tail_mark")
        night_marks = []
        if mark is None:
            complete = False
        elif mark.get("action") == "mark":
            targets = _targets(mark)
            if targets is None or len(targets) != 1:
                complete = False
            else:
                night_marks.extend(targets)
        elif mark.get("action") not in _INACTIVE:
            complete = False

        # Mark clearing and marking can both occur at night.  When they
        # affect the same seat, the template does not prove their order.
        clears = []
        for slot in ("whiteze_clear_mark", "whiteze_clear"):
            clear = _event(round_, "night", slot)
            if clear is None:
                complete = False
            elif clear.get("action") in {"clear", "clear_mark"}:
                targets = _targets(clear)
                if targets is None or not targets:
                    complete = False
                else:
                    clears.append(set(targets))
            elif clear.get("action") not in _INACTIVE:
                complete = False

        if clears:
            cleared_this_night = set().union(*clears)
            if set(night_marks).intersection(cleared_this_night):
                complete = False
                issues.append({"code": "fox_mark_clear_order_unknown", "round": round_no})
            marks.difference_update(cleared_this_night)
        marks.update(night_marks)

        if round_no < number:
            vote_mark = _event(round_, "day", "nine_tail_vote_mark")
            if vote_mark is None:
                complete = False
            elif vote_mark.get("action") == "mark":
                targets = _targets(vote_mark)
                if targets is None or len(targets) != 1:
                    complete = False
                else:
                    marks.update(targets)
            elif vote_mark.get("action") not in _INACTIVE:
                complete = False
    return marks, complete, issues


def _fox(game: dict, number: int, living_before_vote,
         constraints: list[dict], consequences: list[dict], issues: list[dict]) -> None:
    rows, seats = _rounds(game), _seat_rows(game)
    current = rows.get(number)
    living = _seat_list(living_before_vote)
    foxes = [seat for seat in seats if _role(seats, seat) == "九尾狐"]
    fox = foxes[0] if len(foxes) == 1 else None
    marks, history_complete, history_issues = _fox_mark_history(game, number)
    for item in history_issues:
        _add_issue(issues, item["code"], "day", "nine_tail_hunt", **{k: v for k, v in item.items() if k != "code"})

    poison = _event(current, "night", "witch_poison")
    witch = poison.get("actor") if isinstance(poison, dict) else None
    if type(witch) is not int:
        witches = [seat for seat in seats if _role(seats, seat) == "女巫"]
        witch = witches[0] if len(witches) == 1 else None
    targets = _targets(poison)
    if (poison and poison.get("action") == "poison" and witch is not None
            and _role(seats, witch) == "女巫" and fox is not None and targets and fox in targets):
        consequences.append({"type": "poison_immunity", "seat": fox,
                             "source_slot": "witch_poison",
                             "rule": "S23:fox_poison_immunity"})

    if fox is None:
        _add_constraint(constraints, "day", "nine_tail_hunt", "unknown", "fox_identity_not_unique")
        return
    if living is None:
        _add_constraint(constraints, "day", "nine_tail_hunt", "unknown", "living_before_vote_unknown")
        return
    if fox not in living:
        _add_constraint(constraints, "day", "nine_tail_hunt", "unavailable", "fox_not_alive_before_vote")
        return
    if not history_complete:
        _add_constraint(constraints, "day", "nine_tail_hunt", "unknown", "fox_mark_history_incomplete")
        return

    marked_alive = (marks & set(living)) | {fox}
    unmarked_alive = set(living) - marked_alive
    success = len(marked_alive) > len(unmarked_alive)
    status = "available" if success else "unavailable"
    reason = "marked_side_strictly_larger" if success else "marked_side_not_strictly_larger"
    _add_constraint(constraints, "day", "nine_tail_hunt", status, reason)

    hunt = _event(current, "day", "nine_tail_hunt")
    skill = _event(current, "day", "nine_tail_skill")
    attempted = bool((hunt and hunt.get("action") == "hunt")
                     or (skill and skill.get("action") == "attempt"))
    if not attempted:
        return
    expected = "success" if success else "failure"
    victims = sorted(unmarked_alive) if success else []
    consequences.append({"type": "fox_hunt_result", "result": expected,
                         "fox": fox, "marked_alive": sorted(marked_alive),
                         "unmarked_alive": sorted(unmarked_alive),
                         "expected_deaths": victims,
                         "rule": "S23:fox_hunt_threshold"})
    if success:
        consequences.extend({"type": "expected_death", "seat": victim,
                             "cause": "nine_tail_hunt", "rule": "S23:fox_hunt_threshold"}
                            for victim in victims)
    observed = (hunt or skill or {}).get("result")
    normalized = str(observed or "").strip().lower()
    if normalized in {"success", "successful", "成功"}:
        normalized = "success"
    elif normalized in {"failure", "failed", "失败"}:
        normalized = "failure"
    else:
        normalized = None
    if normalized is not None and normalized != expected:
        _add_issue(issues, "fox_hunt_result_conflict", "day", "nine_tail_hunt",
                   observed=normalized, expected=expected)


def derive_board_outcomes(game: dict, number: int, *, living_before_night=None,
                          living_before_vote=None) -> dict:
    """Return board-specific constraints, consequences, and contradictions.

    ``living_before_night`` and ``living_before_vote`` must be exact seat sets
    supplied by the caller's checked survival replay.  When omitted, this
    module does not treat every seat without a recorded death as living.
    """
    if type(number) is not int or number < 1:
        raise ValueError("number must be a positive integer")
    if not isinstance(game, dict):
        raise TypeError("game must be a dossier dictionary")

    constraints: list[dict] = []
    consequences: list[dict] = []
    issues: list[dict] = []
    board = _family(game)
    if board == "neighbor_puppet":
        _neighbor_puppet(game, number, living_before_night, constraints, consequences, issues)
    elif board == "masquerade":
        _masquerade(game, number, living_before_night, constraints, consequences, issues)
    elif board == "all_in":
        _all_in(game, number, living_before_night, constraints, consequences, issues)
    elif board == "qingqiu_night":
        _fox(game, number, living_before_vote, constraints, consequences, issues)
    return {"constraints": constraints, "consequences": consequences, "issues": issues}

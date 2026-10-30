"""Pure, evidence-bounded role and board constraints for game opportunities.

This module consumes already replayed state.  It does not decide who is alive,
replay votes, or mutate the dossier.  Unknown board timing and incomplete
history stay unknown instead of being filled from common-play assumptions.
"""

from __future__ import annotations


_BOARD_ALIASES = {
    "s21_seer_witch_hunter_white_mixed": "mixed_blood",
    "s21_mechanical_wolf_seer": "mechanical_wolf_seer",
    "s21_guile_realm": "guile_realm",
    "s21_masquerade": "masquerade",
    "s21_treasure_master": "treasure_master",
    "s21_neighbor_puppet": "neighbor_puppet",
    "s21_all_in": "all_in",
    "s23_mixed_blood": "mixed_blood",
    "s23_mechanical_wolf_seer": "mechanical_wolf_seer",
    "s23_guile_realm": "guile_realm",
    "s23_masquerade": "masquerade",
    "s23_treasure_master": "treasure_master",
}

_MECHANICAL_FORMS = {
    "机械双刀狼": {"source": "狼人", "phase": "night", "action": "attack", "wolves": True},
    "机械通灵师": {"source": "通灵师", "phase": "night", "action": "check"},
    "机械女巫": {"source": "女巫", "phase": "night", "action": "poison"},
    "机械猎人": {"source": "猎人", "phase": "day", "action": "shoot"},
    "机械守卫": {"source": "守卫", "phase": "night", "action": "guard"},
    "机械平民": {"source": "平民", "phase": None, "action": None},
}
_MECHANICAL_FORM_BY_ROLE = {
    row["source"]: form for form, row in _MECHANICAL_FORMS.items()
}
_MECHANICAL_FORM_ALIASES = {
    "mechanical_double_attack_werewolf": "机械双刀狼",
    "机械双刀狼人": "机械双刀狼",
}
_MECHANICAL_LEARN_TARGET_ROLES = frozenset(_MECHANICAL_FORM_BY_ROLE)
_TREASURE_ROLE_COUNTS = {
    "通灵师": 1, "毒师": 1, "猎人": 1, "摄梦人": 1, "蒙面人": 1,
    "平民": 5, "狼王": 1, "狼人": 3, "盗宝大师": 1,
}
_TREASURE_CARD_ACTION = {
    "通灵师": "check", "毒师": "poison", "猎人": "shoot",
    "摄梦人": "dream", "蒙面人": "delay_death", "平民": "no_skill",
    "狼王": "shoot", "狼人": "attack",
}
_SEER_CHECK_ROLE_BY_FAMILY = {
    "all_in": "预言家",
    "black_wolf_king_knight": "预言家",
    "ghost_bride": "预言家",
    "guile_realm": "预言家",
    "magic_duel": "预言家",
    "masquerade": "预言家",
    "mechanical_wolf_seer": "通灵师",
    "mixed_blood": "预言家",
    "neighbor_puppet": "预言家",
    "qingqiu_night": "预言家",
    "seer_witch_hunter_white": "预言家",
    "treasure_master": "通灵师",
    "wolf_king_guard": "预言家",
    "wolf_king_knight": "预言家",
}
_WOLF_KNIFE_ACTORS = frozenset({"狼人", "狼王", "黑狼王", "白狼王"})
_WOLF_SIDE_SPECIAL_ROLES = frozenset({"诡术师", "假面", "狼术师", "九尾狐", "典狱长"})
_INACTIVE_ACTIONS = {
    None, "unknown", "pass", "unavailable", "not_held", "not_triggered",
    "forbidden",
}
_NO_VALUE = object()


def family(code: str | None) -> str | None:
    """Return the shared family key for season-prefixed board codes."""
    if not isinstance(code, str) or not code:
        return None
    if code in _BOARD_ALIASES:
        return _BOARD_ALIASES[code]
    for prefix in ("s21_", "s23_"):
        if code.startswith(prefix):
            return code[len(prefix):]
    return code


def _board_code(game: dict) -> str | None:
    board = game.get("board")
    if isinstance(board, dict):
        board = board.get("code")
    return board if isinstance(board, str) else None


def _season(game: dict, code: str | None) -> str | None:
    season = game.get("season")
    if isinstance(season, str) and season:
        return season.upper()
    if isinstance(code, str) and code.startswith("s21_"):
        return "S21"
    if isinstance(code, str) and code.startswith("s23_"):
        return "S23"
    return None


def _seat_rows(game: dict) -> list[dict] | None:
    seats = game.get("seats")
    if not isinstance(seats, list):
        seats = game.get("players")
    if not isinstance(seats, list):
        return None
    return [row for row in seats if isinstance(row, dict)]


def _seat_roles(game: dict) -> dict[int, str | None] | None:
    rows = _seat_rows(game)
    if rows is None:
        return None
    result = {}
    for row in rows:
        seat = row.get("seat", row.get("number"))
        if type(seat) is int:
            result[seat] = row.get("role")
    return result


def _actor_role(game: dict, actor: int | None) -> str | None:
    if type(actor) is not int:
        return None
    return (_seat_roles(game) or {}).get(actor)


def _role_known(game: dict, actor: int | None, expected: str, reason: str) -> dict | None:
    roles = _seat_roles(game)
    if type(actor) is not int or roles is None or actor not in roles or roles[actor] is None:
        return _result("unknown", reason)
    if roles[actor] != expected:
        return _result("unknown", reason)
    return None


def _all_seats(game: dict) -> list[int] | None:
    roles = _seat_roles(game)
    if roles is None or not roles:
        return None
    return sorted(roles)


def _result(
    status: str,
    reason: str,
    *,
    legal_targets=_NO_VALUE,
    availability=_NO_VALUE,
) -> dict:
    value = {"status": status, "reason": reason}
    if legal_targets is not _NO_VALUE:
        value["legal_targets"] = legal_targets
    if availability is not _NO_VALUE:
        value["availability"] = availability
    return value


def _use_count(uses, actor: int, slot: str) -> int | None:
    if uses is None:
        return None
    value = uses.get((actor, slot), 0)
    return value if type(value) is int else None


def _previous(previous, actor: int, slot: str) -> dict | None:
    if previous is None:
        return None
    value = previous.get((actor, slot))
    return value if isinstance(value, dict) else None


def _targets(event: dict) -> list:
    value = event.get("targets")
    return value if isinstance(value, list) else []


def _has_action(event: dict) -> bool:
    return event.get("action") not in _INACTIVE_ACTIONS


def _round_events(game: dict, number: int, phase: str) -> list[dict] | None:
    rounds = game.get("rounds")
    if not isinstance(rounds, list):
        return None
    for round_ in rounds:
        if isinstance(round_, dict) and round_.get("number") == number:
            events = round_.get(phase)
            return [row for row in events if isinstance(row, dict)] if isinstance(events, list) else []
    return None


def _living_targets(game: dict, dead_before) -> list[int] | None:
    seats = _all_seats(game)
    if seats is None or dead_before is None:
        return None
    departed = set(dead_before)
    return [seat for seat in seats if seat not in departed]


def _seer_check_constraint(game, phase, event, *, actor, dead_before):
    expected_role = _SEER_CHECK_ROLE_BY_FAMILY.get(family(_board_code(game)))
    if expected_role is None:
        return _result("unknown", "seer_check_role_unknown", legal_targets=None)
    roles = _seat_roles(game)
    if (family(_board_code(game)) == "treasure_master" and roles is not None
            and set(roles) == set(range(1, 13)) and all(roles.values())
            and not any(role in {"unknown", "未知", "身份未知"} for role in roles.values())
            and expected_role not in roles.values()):
        return _result("unavailable", "seer_check_role_absent", legal_targets=None)
    role = _actor_role(game, actor)
    if type(actor) is not int or role is None:
        return _result("unknown", "seer_check_actor_unknown", legal_targets=None)
    if role != expected_role:
        return _result("unavailable", "seer_check_actor_role_mismatch", legal_targets=None)
    if phase != "night":
        return _result("unavailable", "seer_check_wrong_phase", legal_targets=None)
    if dead_before is None:
        return _result("unknown", "seer_check_survival_unknown", legal_targets=None)
    legal = _living_targets(game, dead_before)
    if legal is None:
        return _result("unknown", "seer_check_targets_unknown", legal_targets=None)
    if actor in set(dead_before):
        return _result("unavailable", "seer_check_actor_departed", legal_targets=legal)

    action = event.get("action")
    if action == "check":
        targets = _targets(event)
        if not targets:
            return _result("unknown", "seer_check_target_unknown", legal_targets=legal)
        if len(targets) != 1:
            return _result("unavailable", "seer_check_target_count_invalid", legal_targets=legal)
        if targets[0] not in legal:
            return _result("unavailable", "seer_check_target_invalid", legal_targets=legal)
    elif _has_action(event):
        return _result("unavailable", "seer_check_action_invalid", legal_targets=legal)
    return _result("available", "seer_check_available", legal_targets=legal)


def _wolf_attack_constraint(game, number, event, *, actor, dead_before):
    role = _actor_role(game, actor)
    if dead_before is None:
        return _result("unknown", "wolf_attack_survival_unknown", legal_targets=None)
    legal = _living_targets(game, dead_before)
    if legal is None:
        return _result("unknown", "wolf_attack_targets_unknown", legal_targets=None)

    action = event.get("action")
    if action == "forbidden":
        return _result("unavailable", "wolf_attack_forbidden", legal_targets=legal)
    if action == "attack":
        targets = _targets(event)
        if not targets:
            return _result("unknown", "wolf_attack_target_unknown", legal_targets=legal)
        if len(targets) != 1:
            return _result("unavailable", "wolf_attack_target_count_invalid", legal_targets=legal)
        if targets[0] not in legal:
            return _result("unavailable", "wolf_attack_target_invalid", legal_targets=legal)
    elif action not in _INACTIVE_ACTIONS:
        return _result("unavailable", "wolf_attack_action_invalid", legal_targets=legal)

    if role == "混血儿":
        return _result("unavailable", "mixed_blood_has_no_wolf_knife", legal_targets=legal)
    if role == "机械狼":
        if actor in set(dead_before):
            return _result("unavailable", "wolf_attack_actor_departed", legal_targets=legal)
        wolves = _ordinary_wolves_state(game, number, dead_before)
        if wolves == "unknown":
            return _result("unknown", "ordinary_wolf_departure_unknown", legal_targets=legal)
        return _result("available" if wolves == "available" else "unavailable",
                       "ordinary_wolves_departed" if wolves == "available" else "ordinary_wolves_alive",
                       legal_targets=legal)
    if role in _WOLF_SIDE_SPECIAL_ROLES:
        return _result("unknown", "wolf_attack_special_role_rule_unknown", legal_targets=legal)
    if type(actor) is not int or role is None:
        return _result("unknown", "wolf_attack_actor_unknown", legal_targets=legal)
    if actor in set(dead_before):
        return _result("unavailable", "wolf_attack_actor_departed", legal_targets=legal)
    if role not in _WOLF_KNIFE_ACTORS:
        return _result("unavailable", "wolf_attack_actor_not_in_wolf_team", legal_targets=legal)
    return _result("available", "wolf_attack_available", legal_targets=legal)


def _same_night_medicine_used(game, number: int, actor: int, sibling: str, previous) -> bool | None:
    prior = _previous(previous, actor, sibling)
    if prior and prior.get("round") == number and prior.get("action") in {"save", "poison"}:
        return True
    if prior and prior.get("round") == number and prior.get("action") == "unknown":
        return None
    for row in _round_events(game, number, "night") or []:
        if row.get("slot") == sibling and row.get("actor") == actor:
            if row.get("action") in {"save", "poison"}:
                return True
            if row.get("action") == "unknown":
                return None
    return False


def _medicine_constraint(game, number, phase, event, *, actor, uses, previous):
    slot = event.get("slot")
    role = _actor_role(game, actor)
    allowed_roles = {"女巫"} if slot == "witch_save" else {"女巫", "毒师"}
    if role not in allowed_roles:
        return _result("unknown", "medicine_actor_unknown")
    if phase != "night":
        return _result("unavailable", "medicine_wrong_phase")
    count = _use_count(uses, actor, slot)
    if count is None:
        return _result("unknown", "medicine_use_history_unknown")
    if count >= 1:
        return _result("unavailable", f"{slot}_spent")
    if role == "女巫":
        sibling = "witch_poison" if slot == "witch_save" else "witch_save"
        sibling_use = _same_night_medicine_used(game, number, actor, sibling, previous)
        if sibling_use is None:
            return _result("unknown", "same_night_medicine_history_unknown")
        if sibling_use:
            return _result("unavailable", "one_witch_medicine_per_night")
    seats = _all_seats(game)
    if slot == "witch_save":
        if seats is None:
            return _result("unknown", "witch_save_targets_unknown", legal_targets=None)
        legal = [seat for seat in seats if seat != actor]
        if _has_action(event) and actor in _targets(event):
            return _result("unavailable", "witch_cannot_save_self", legal_targets=legal)
        return _result("available", "medicine_available", legal_targets=legal)
    return _result("available", "medicine_available", legal_targets=seats)


def _mixed_blood_constraint(number, phase, event, *, actor, uses):
    if event.get("slot") != "mixed_blood_model":
        return None
    if type(actor) is not int:
        return _result("unknown", "mixed_blood_actor_unknown")
    if phase != "night":
        return _result("unavailable", "mixed_blood_choice_wrong_phase")
    if number != 1:
        return _result("unavailable", "mixed_blood_choice_first_night_only")
    count = _use_count(uses, actor, "mixed_blood_model")
    if count is None:
        return _result("unknown", "mixed_blood_history_unknown")
    if count >= 1:
        return _result("unavailable", "mixed_blood_choice_spent")
    return _result("available", "mixed_blood_choice_available")


def _mechanical_form(game, actor: int, learning) -> tuple[dict | None, dict | None]:
    if learning is None:
        return None, None
    learned = learning.get(actor)
    if not isinstance(learned, dict):
        return None, {}
    form = learned.get("form")
    if isinstance(form, str):
        form = _MECHANICAL_FORM_ALIASES.get(form, form)
    if form not in _MECHANICAL_FORMS:
        form = _MECHANICAL_FORM_BY_ROLE.get(form)
    if form not in _MECHANICAL_FORMS:
        target = learned.get("target")
        target_role = (_seat_roles(game) or {}).get(target) if type(target) is int else None
        form = _MECHANICAL_FORM_BY_ROLE.get(target_role)
    if form not in _MECHANICAL_FORMS:
        return None, learned
    return _MECHANICAL_FORMS[form], learned


def _unknown_prior_learning(previous, actor: int) -> bool:
    row = _previous(previous, actor, "mechanical_action")
    return bool(row and row.get("action") == "unknown")


def _ordinary_wolves_state(game: dict, number: int, dead_before) -> str:
    if dead_before is None:
        return "unknown"
    roles = _seat_roles(game)
    if roles is None or not roles:
        return "unknown"
    ordinary_wolves = [seat for seat, role in roles.items() if role == "狼人"]
    if not ordinary_wolves or any(role is None for role in roles.values()):
        return "unknown"
    if set(ordinary_wolves) <= set(dead_before):
        return "available"
    # This board has no resurrection. A confirmed later departure proves that
    # an ordinary wolf was still alive at the start of this earlier night,
    # even when an unrelated earlier departure slot is blank.
    remaining = set(ordinary_wolves) - set(dead_before)
    for round_ in game.get("rounds") or []:
        if type(round_.get("number")) is not int or round_["number"] < number:
            continue
        for phase in ("night", "day"):
            for event in round_.get(phase) or []:
                if event.get("action") == "self_destruct" and event.get("actor") in remaining:
                    return "wolves_alive"
                if (event.get("action") in {"die", "exile", "shoot"}
                        and set(event.get("targets") or []) & remaining):
                    return "wolves_alive"
    if _departure_history_unknown(game, number):
        return "unknown"
    return "wolves_alive"


def mechanical_knife_constraint(game: dict, number: int, phase: str, *, actor: int | None, dead_before) -> dict:
    """Confirm knife takeover from departures before the current night."""
    unknown_actor = _role_known(game, actor, "机械狼", "mechanical_actor_unknown")
    if unknown_actor is not None:
        return unknown_actor
    if phase != "night":
        return _result("unavailable", "mechanical_knife_night_only")
    if number == 1:
        return _result("unavailable", "mechanical_knife_first_night")
    if dead_before is not None and actor in dead_before:
        return _result("unavailable", "actor_departed")
    wolves = _ordinary_wolves_state(game, number, dead_before)
    if wolves == "unknown":
        return _result("unknown", "ordinary_wolf_departure_unknown")
    if wolves == "wolves_alive":
        return _result("unavailable", "ordinary_wolves_alive")
    return _result("available", "ordinary_wolves_departed")


def _wolves_for_treasure_state(game: dict, number: int, dead_before) -> str:
    if dead_before is None:
        return "unknown"
    roles = _seat_roles(game)
    if roles is None or not roles or any(role is None for role in roles.values()):
        return "unknown"
    takeover = {"狼人", "狼王", "黑狼王"}
    wolves = [seat for seat, role in roles.items() if role in takeover]
    if not wolves:
        return "unknown"
    if set(wolves) <= set(dead_before):
        return "available"
    if _departure_history_unknown(game, number):
        return "unknown"
    return "wolves_alive"


def _departure_history_unknown(game: dict, before_number: int) -> bool:
    departure_slots = {
        "night_deaths", "hunter_shot", "wolf_king_shot", "mechanical_day_skill",
        "exile_result", "self_destruct",
    }
    for round_ in game.get("rounds") or []:
        if not isinstance(round_, dict):
            continue
        if type(round_.get("number")) is int and round_["number"] >= before_number:
            continue
        for event in round_.get("day") or []:
            if (isinstance(event, dict) and event.get("slot") in departure_slots
                    and event.get("action") in {None, "unknown"}):
                return True
    return False


def _mechanical_targets(game: dict, actor: int) -> list[int] | None:
    roles = _seat_roles(game)
    if roles is None or not roles:
        return None
    return sorted(
        seat for seat, role in roles.items()
        if seat != actor and role in _MECHANICAL_LEARN_TARGET_ROLES
    )


def _mechanical_constraint(
    game, number, phase, event, *, actor, dead_before, uses, previous, learning,
):
    slot = event.get("slot")
    if slot == "mechanical_knife_status":
        return mechanical_knife_constraint(game, number, phase, actor=actor, dead_before=dead_before)
    role = _actor_role(game, actor)
    if role != "机械狼":
        return _result("unknown", "mechanical_actor_unknown", availability="unknown")

    learned_form, learned = _mechanical_form(game, actor, learning)
    if slot == "mechanical_action" and event.get("action") == "learn":
        if phase != "night":
            return _result("unavailable", "mechanical_learning_wrong_phase", availability="wrong_phase")
        if learned is None and _unknown_prior_learning(previous, actor):
            return _result("unknown", "mechanical_learning_history_unknown", availability="unknown")
        if learned:
            return _result("unavailable", "mechanical_learning_spent", availability="locked")
        targets = _mechanical_targets(game, actor)
        if targets is None:
            return _result("unknown", "mechanical_learning_targets_unknown", legal_targets=None,
                           availability="learning")
        selected = _targets(event)
        if _has_action(event) and (len(selected) != 1 or selected[0] not in targets):
            return _result("unavailable", "mechanical_learning_target_invalid", legal_targets=targets,
                           availability="learning")
        return _result("available", "mechanical_learning_available", legal_targets=targets,
                       availability="learning")

    if learned is None:
        if learned_form is None and _unknown_prior_learning(previous, actor):
            return _result("unknown", "mechanical_learning_history_unknown", availability="unknown")
        if learned_form is None:
            return _result("unknown", "mechanical_form_unknown", availability="unknown")
        return _result("unknown", "mechanical_form_unknown", availability="unknown")
    if learned_form is None:
        return _result("unknown", "mechanical_form_unknown", availability="unknown")

    learned_round = learned.get("round")
    if type(number) is not int or type(learned_round) is not int:
        return _result("unknown", "mechanical_unlock_round_unknown", availability="unknown")
    if phase == "night" and number == learned_round:
        return _result("unavailable", "mechanical_learning_night_locked", availability="learning")
    offset = 1 if phase == "night" else 0
    if number < learned_round + offset:
        return _result("unavailable", "mechanical_skill_locked", availability="locked")
    if learned_form["phase"] is None:
        return _result("unavailable", "mechanical_form_has_no_skill", availability="no_skill")
    if learned_form["phase"] != phase:
        return _result("unavailable", "mechanical_skill_wrong_phase", availability="wrong_phase")

    action = event.get("action")
    if action not in _INACTIVE_ACTIONS and action != learned_form["action"]:
        return _result("unavailable", "mechanical_action_wrong_form", availability="available")
    if learned_form.get("wolves"):
        wolves = _ordinary_wolves_state(game, number, dead_before)
        if wolves == "unknown":
            return _result("unknown", "ordinary_wolf_departure_unknown", availability="unknown")
        if wolves == "wolves_alive":
            return _result("unavailable", "ordinary_wolves_alive", availability="wolves_alive")
    if learned_form["action"] == "poison":
        poison_uses = _count_history(game, actor, "mechanical_action", "poison", before=number)
        if poison_uses >= 1:
            return _result("unavailable", "mechanical_poison_spent")
    if learned_form["action"] == "shoot":
        poison_state = _hunter_poison_state(game, actor, number, learning)
        if poison_state == "poisoned":
            return _result("unavailable", "mechanical_hunter_poisoned", availability="poisoned")
        if poison_state == "unknown":
            return _result("unknown", "mechanical_hunter_poison_unknown", availability="unknown")

    if learned_form["action"] in {"guard", "dream"}:
        target_slot = "mechanical_action"
        rule = "mechanical_guard" if learned_form["action"] == "guard" else "mechanical_dream"
        prior = _previous(previous, actor, target_slot)
        legal = _all_seats(game)
        if legal is None:
            return _result("unknown", "mechanical_targets_unknown", legal_targets=None,
                           availability="available")
        blocked = set()
        if prior and prior.get("round") == number - 1:
            if prior.get("action") == "unknown":
                return _result("unknown", f"{rule}_history_unknown", legal_targets=None,
                               availability="unknown")
            if prior.get("action") == learned_form["action"]:
                blocked.update(prior.get("targets") or [])
        legal = [seat for seat in legal if seat not in blocked]
        if _has_action(event) and set(_targets(event)).intersection(blocked):
            return _result("unavailable", f"{rule}_target_repeat", legal_targets=legal,
                           availability="available")
        return _result("available", "mechanical_skill_available", legal_targets=legal,
                       availability="available")
    return _result("available", "mechanical_skill_available", availability="available")


def _count_history(game, actor: int, slot: str, action: str, *, before: int | None = None) -> int:
    total = 0
    for round_ in game.get("rounds") or []:
        if not isinstance(round_, dict):
            continue
        number = round_.get("number")
        if before is not None and type(number) is int and number >= before:
            continue
        for phase in ("night", "day"):
            for row in round_.get(phase) or []:
                if (isinstance(row, dict) and row.get("actor") == actor
                        and row.get("slot") == slot and row.get("action") == action):
                    total += 1
    return total


def _hunter_poison_state(game, actor: int, number: int, learning) -> str:
    """Resolve poison qualification from known poison sources and effects."""
    unresolved = False
    for round_ in game.get("rounds") or []:
        if not isinstance(round_, dict) or type(round_.get("number")) is not int:
            continue
        if round_["number"] > number:
            continue
        for event in round_.get("night") or []:
            if not isinstance(event, dict):
                continue
            slot = event.get("slot")
            if slot == "witch_poison":
                if event.get("action") == "unknown":
                    unresolved = True
                    continue
                if event.get("action") != "poison":
                    continue
            elif slot == "mechanical_action":
                mech_actor = event.get("actor")
                mech = next((row for row in _seat_rows(game) or []
                             if row.get("seat", row.get("number")) == mech_actor
                             and row.get("role") == "机械狼"), None)
                if mech is None:
                    continue
                form, learned = _mechanical_form(game, mech_actor, learning)
                if form is None or learned is None:
                    if event.get("action") in {"poison", "unknown"}:
                        unresolved = True
                    continue
                if form.get("action") != "poison":
                    continue
                if type(learned.get("round")) is not int or round_["number"] < learned["round"] + 1:
                    continue
                if event.get("action") == "unknown":
                    unresolved = True
                    continue
                if event.get("action") != "poison":
                    continue
            else:
                continue
            if event.get("result") == "failed":
                continue
            effects = event.get("effects")
            if isinstance(effects, list) and effects:
                for effect in effects:
                    if (isinstance(effect, dict) and "poison" in str(effect.get("kind", ""))
                            and effect.get("dead_seat") == actor):
                        return "poisoned"
                    if (isinstance(effect, dict) and effect.get("kind") == "poison_unresolved"
                            and effect.get("intended_target") == actor):
                        unresolved = True
                if any(isinstance(effect, dict) and effect.get("kind") == "poison_unresolved"
                       for effect in effects):
                    unresolved = True
                continue
            targets = event.get("resolved_targets") or event.get("targets") or []
            if actor not in targets:
                if event.get("action") == "unknown":
                    unresolved = True
                continue
            # Mechanical guard can reflect the ordinary witch's poison.
            code = _board_code(game)
            current_night = round_.get("number")
            mech = next((row for row in _seat_rows(game) or [] if row.get("role") == "机械狼"), None)
            if slot == "witch_poison" and family(code) == "mechanical_wolf_seer" and mech:
                mech_actor = mech.get("seat", mech.get("number"))
                form, form_row = _mechanical_form(game, mech_actor, learning)
                if form and form_row and form.get("action") == "guard":
                    unlocked = type(form_row.get("round")) is int and current_night >= form_row["round"] + 1
                    guard = next((row for row in round_.get("night") or []
                                  if isinstance(row, dict) and row.get("slot") == "mechanical_action"), None)
                    if unlocked and guard and guard.get("action") == "guard" and actor in (guard.get("targets") or []):
                        continue
                    if unlocked and guard and guard.get("action") == "unknown":
                        unresolved = True
                        continue
            return "poisoned"
    return "unknown" if unresolved else "clear"


def _same_target_rule(
    game, number, event, *, actor, slot, previous, used_targets,
    repeat_mode, rule, target_count=None, exclude_actor=False,
):
    if type(actor) is not int:
        return _result("unknown", f"{rule}_actor_unknown", legal_targets=None)
    seats = _all_seats(game)
    if seats is None or used_targets is None or previous is None:
        return _result("unknown", f"{rule}_history_unknown", legal_targets=None)
    used = used_targets.get((actor, slot), set())
    if not isinstance(used, (set, frozenset, list, tuple)):
        return _result("unknown", f"{rule}_history_unknown", legal_targets=None)
    blocked = set(used) if repeat_mode == "never" else set()
    prior = _previous(previous, actor, slot)
    if repeat_mode == "consecutive" and prior and prior.get("round") == number - 1:
        if prior.get("action") == "unknown":
            return _result("unknown", f"{rule}_history_unknown", legal_targets=None)
        if prior.get("action") not in _INACTIVE_ACTIONS:
            blocked.update(prior.get("targets") or [])
    if exclude_actor:
        blocked.add(actor)
    legal = [seat for seat in seats if seat not in blocked]
    chosen = _targets(event)
    if _has_action(event):
        if target_count is not None and len(chosen) != target_count:
            return _result("unavailable", f"{rule}_target_count_invalid", legal_targets=legal)
        if len(set(chosen)) != len(chosen) or any(target not in legal for target in chosen):
            reason = f"{rule}_target_repeat" if set(chosen).intersection(blocked) else f"{rule}_target_invalid"
            return _result("unavailable", reason, legal_targets=legal)
    return _result("available", f"{rule}_targets_available", legal_targets=legal)


def _confirmed_night_deaths(game, number: int) -> set[int]:
    round_ = next((row for row in game.get("rounds") or []
                   if isinstance(row, dict) and row.get("number") == number), None)
    if round_ is None:
        return set()
    return {
        seat
        for phase in ("night", "day")
        for event in round_.get(phase) or []
        if isinstance(event, dict) and event.get("slot") == "night_deaths"
        and event.get("action") == "die"
        for seat in _targets(event)
        if type(seat) is int
    }


def _dreamer_actor(game, event) -> int | None:
    actor = event.get("actor")
    if type(actor) is int:
        return actor
    roles = _seat_roles(game)
    if roles is None:
        return None
    dreamers = [seat for seat, role in roles.items() if role == "摄梦人"]
    return dreamers[0] if len(dreamers) == 1 else None


def _dream_consequences(game, number, event, *, actor, slot, previous):
    if event.get("action") != "dream":
        return []
    targets = _targets(event)
    if len(targets) != 1 or type(targets[0]) is not int:
        return []
    target = targets[0]
    consequences = [{
        "type": "wolf_attack_immunity",
        "seat": target,
        "rule": "dreamer_target_immune_to_wolf_attack_that_night",
    }]
    prior = _previous(previous, actor, slot)
    if (prior and prior.get("round") == number - 1 and prior.get("action") == "dream"
            and targets[0] in (prior.get("targets") or [])):
        consequences.append({
            "type": "repeat_dream_death",
            "seat": target,
            "rule": "dreamer_same_target_on_two_consecutive_nights_dies",
        })
    if _actor_role(game, actor) == "摄梦人" and actor in _confirmed_night_deaths(game, number):
        consequences.append({
            "type": "dreamer_night_death_link",
            "seat": target,
            "rule": "dreamer_night_death_links_current_night_dream_target",
        })
    return consequences


def _dream_death_blocks_shot(game, number, actor) -> bool:
    night_dead = _confirmed_night_deaths(game, number)
    if actor not in night_dead:
        return False
    rounds = game.get("rounds") or []
    current = next((row for row in rounds if isinstance(row, dict)
                    and row.get("number") == number), None)
    prior_round = next((row for row in rounds if isinstance(row, dict)
                        and row.get("number") == number - 1), None)
    if current is None:
        return False
    for current_phase in ("night", "day"):
        for event in current.get(current_phase) or []:
            if (not isinstance(event, dict)
                    or event.get("slot") not in {"dreamer_action", "treasure_card_skill"}
                    or event.get("action") != "dream"):
                continue
            slot = event["slot"]
            dreamer = _dreamer_actor(game, event) if slot == "dreamer_action" else event.get("actor")
            targets = _targets(event)
            if dreamer is None or len(targets) != 1 or targets[0] != actor:
                continue
            repeated = False
            if prior_round is not None:
                repeated = any(
                    isinstance(previous, dict) and previous.get("action") == "dream"
                    and targets[0] in (previous.get("targets") or [])
                    for prior_phase in ("night", "day")
                    for previous in prior_round.get(prior_phase) or []
                    if isinstance(previous, dict) and previous.get("slot") == slot
                    and (previous.get("actor") == dreamer or previous.get("actor") is None)
                )
            linked = (slot == "dreamer_action" and _actor_role(game, dreamer) == "摄梦人"
                      and dreamer in night_dead)
            if repeated or linked:
                return True
    return False


def _dreamer_constraint(game, number, event, *, actor, previous):
    if type(actor) is not int:
        return _result("unknown", "dreamer_actor_unknown", legal_targets=None)
    seats = _all_seats(game)
    if seats is None:
        return _result("unknown", "dreamer_targets_unknown", legal_targets=None)
    targets = _targets(event)
    if _has_action(event) and (len(set(targets)) != len(targets) or any(t not in seats for t in targets)):
        return _result("unavailable", "dreamer_target_invalid", legal_targets=seats)
    result = _result("available", "dreamer_targets_available", legal_targets=seats)
    consequences = _dream_consequences(
        game, number, event, actor=actor, slot="dreamer_action", previous=previous,
    )
    if consequences:
        result["consequences"] = consequences
    return result


def _guile_constraint(game, number, phase, event, *, actor, used_targets, previous):
    slot = event.get("slot")
    if slot == "guile_exchange":
        if phase != "night":
            return _result("unavailable", "guile_exchange_wrong_phase")
        return _same_target_rule(
            game, number, event, actor=actor, slot=slot, previous=previous,
            used_targets=used_targets, repeat_mode="never", rule="guile_exchange",
            target_count=2,
        )
    return None


def _masquerade_constraint(game, number, phase, event, *, actor, previous, used_targets):
    slot = event.get("slot")
    if slot == "dancer_dance":
        if phase != "night":
            return _result("unavailable", "dance_wrong_phase")
        unknown_actor = _role_known(game, actor, "舞者", "dance_actor_unknown")
        if unknown_actor is not None:
            return unknown_actor
        if number == 1:
            return _result("unavailable", "dance_starts_second_night")
        return _same_target_rule(
            game, number, event, actor=actor, slot=slot, previous=previous,
            used_targets=used_targets, repeat_mode="never", rule="dancer_dance",
            target_count=3,
        )
    if slot not in {"masquerade_verify", "masquerade_mask"}:
        return None
    if phase != "night":
        return _result("unavailable", "masquerade_wrong_phase")
    unknown_actor = _role_known(game, actor, "假面", "masquerade_actor_unknown")
    if unknown_actor is not None:
        return unknown_actor
    if number == 1:
        return _result("unavailable", "masquerade_skills_start_second_night")
    return _same_target_rule(
        game, number, event, actor=actor, slot=slot, previous=previous,
        used_targets=used_targets, repeat_mode="consecutive", rule=slot,
        target_count=1,
    )


def _treasure_dynamic(game, code: str | None) -> bool:
    return (family(code) == "treasure_master"
            and _season(game, code) != "S21"
            and not (isinstance(code, str) and code.startswith("s21_")))


def _treasure_pool(game) -> set[str] | None:
    rows = _seat_rows(game)
    if rows is None or not rows or any(not isinstance(row.get("role"), str) or not row.get("role") for row in rows):
        return None
    counts = dict(_TREASURE_ROLE_COUNTS)
    for row in rows:
        role = row.get("role")
        if role not in counts:
            return None
        counts[role] -= 1
        if counts[role] < 0:
            return None
    return {role for role, amount in counts.items() if amount > 0}


def _treasure_choice_in_round(game, number: int, actor: int) -> dict | None:
    for row in _round_events(game, number, "night") or []:
        if row.get("slot") == "treasure_choice" and row.get("actor") == actor:
            return row
    return None


def _treasure_choice_constraint(game, number, phase, event, *, actor, previous):
    slot = event.get("slot")
    if slot not in {"treasure_remainder", "treasure_choice", "treasure_card_skill"}:
        return None
    code = _board_code(game)
    if not _treasure_dynamic(game, code):
        return _result("unknown", "legacy_treasure_rules_not_shared")
    if _actor_role(game, actor) != "盗宝大师":
        return _result("unknown", "treasure_actor_unknown")
    if phase != "night":
        return _result("unavailable", "treasure_action_wrong_phase")
    if slot == "treasure_remainder":
        if number != 1:
            return _result("unavailable", "treasure_remainder_first_night_only")
        return _result("available", "treasure_remainder_view_available")
    if slot == "treasure_choice":
        pool = _treasure_pool(game)
        if pool is None:
            return _result("unknown", "treasure_remainder_pool_unknown")
        if event.get("action") == "choose":
            choice = event.get("result")
            if not isinstance(choice, str) or not choice:
                return _result("unknown", "treasure_choice_unknown")
            if choice not in pool:
                return _result("unavailable", "treasure_choice_not_in_remainder")
        else:
            choice = None
        prior = _previous(previous, actor, slot)
        if prior and prior.get("round") == number - 1 and prior.get("action") == "choose":
            previous_choice = _treasure_choice_in_round(game, number - 1, actor)
            if previous_choice is None or not isinstance(previous_choice.get("result"), str):
                return _result("unknown", "treasure_choice_history_unknown")
            if choice is not None and choice == previous_choice["result"]:
                return _result("unavailable", "treasure_choice_cannot_repeat_consecutively")
        elif prior and prior.get("round") == number - 1 and prior.get("action") == "unknown":
            return _result("unknown", "treasure_choice_history_unknown")
        return _result("available", "treasure_choice_available")

    choice = _treasure_choice_in_round(game, number, actor)
    if choice is None:
        return _result("unknown", "treasure_choice_for_skill_unknown")
    if choice.get("action") in {"pass", "unavailable"}:
        return _result("unavailable", "treasure_skill_without_choice")
    if choice.get("action") != "choose":
        return _result("unknown", "treasure_choice_for_skill_unknown")
    role = choice.get("result")
    pool = _treasure_pool(game)
    if pool is None:
        return _result("unknown", "treasure_remainder_pool_unknown")
    if role not in pool:
        return _result("unavailable", "treasure_choice_not_in_remainder")
    required_action = _TREASURE_CARD_ACTION.get(role)
    if required_action is None:
        return _result("unknown", "treasure_skill_form_unknown")
    action = event.get("action")
    if action not in _INACTIVE_ACTIONS and action != required_action:
        return _result("unavailable", "treasure_skill_does_not_match_choice")
    if required_action == "poison":
        uses = _count_history(game, actor, "treasure_card_skill", "poison", before=number)
        if uses:
            return _result("unavailable", "treasure_poison_spent")
    if required_action in {"guard", "dream"}:
        prior = _previous(previous, actor, slot)
        seats = _all_seats(game)
        if seats is None:
            return _result("unknown", "treasure_skill_targets_unknown", legal_targets=None)
        blocked = set()
        if (required_action == "guard" and prior and prior.get("round") == number - 1
                and prior.get("action") == required_action):
            blocked.update(prior.get("targets") or [])
        legal = [seat for seat in seats if seat not in blocked]
        chosen = _targets(event)
        if _has_action(event) and (len(chosen) != 1 or any(target not in legal for target in chosen)):
            reason = ("treasure_card_skill_target_repeat" if set(chosen).intersection(blocked)
                      else "treasure_card_skill_target_invalid")
            return _result("unavailable", reason, legal_targets=legal)
        result = _result("available", "treasure_skill_available", legal_targets=legal)
        if required_action == "dream":
            consequences = _dream_consequences(
                game, number, event, actor=actor, slot=slot, previous=previous,
            )
            if consequences:
                result["consequences"] = consequences
        return result
    return _result("available", "treasure_skill_available")


def _treasure_attack_constraint(game, number, event, *, actor, dead_before):
    code = _board_code(game)
    if family(code) != "treasure_master":
        return None
    if number == 1:
        return _result("unavailable", "treasure_first_night_attack_forbidden")
    if not _treasure_dynamic(game, code):
        return _result("unknown", "legacy_treasure_knife_rule_unknown")
    if _actor_role(game, actor) != "盗宝大师":
        return None
    state = _wolves_for_treasure_state(game, number, dead_before)
    if state == "unknown":
        return _result("unknown", "treasure_wolf_departure_unknown")
    if state == "wolves_alive":
        return _result("unavailable", "treasure_wolf_knife_locked")
    return _result("available", "treasure_wolf_knife_available")


def _one_shot_constraint(game, number, phase, event, *, actor, uses, slot, allowed_phase, role):
    unknown_actor = _role_known(game, actor, role, f"{slot}_actor_unknown")
    if unknown_actor is not None:
        return unknown_actor
    if phase != allowed_phase:
        return _result("unavailable", f"{slot}_wrong_phase")
    count = _use_count(uses, actor, slot)
    if count is None:
        return _result("unknown", f"{slot}_history_unknown")
    if count >= 1:
        return _result("unavailable", f"{slot}_spent")
    return _result("available", f"{slot}_available")


def _prince_constraint(game, number, phase, event, *, actor, uses, previous):
    slot = event.get("slot")
    unknown_actor = _role_known(game, actor, "定序王子", f"{slot}_actor_unknown")
    if unknown_actor is not None:
        return unknown_actor
    if phase != "day":
        return _result("unavailable", f"{slot}_wrong_phase")
    skill_uses = _use_count(uses, actor, "sequential_prince_skill")
    speech_uses = _use_count(uses, actor, "extra_speech")
    if skill_uses is None or speech_uses is None:
        return _result("unknown", "sequential_prince_history_unknown")
    if slot == "sequential_prince_skill":
        speech = _previous(previous, actor, "extra_speech")
        already_spoken = speech_uses and (not speech or speech.get("round") != number)
        if skill_uses or already_spoken:
            return _result("unavailable", "sequential_prince_skill_spent")
        return _result("available", "sequential_prince_skill_available")

    if speech_uses:
        return _result("unavailable", "extra_speech_spent")
    skill = _previous(previous, actor, "sequential_prince_skill")
    if skill_uses:
        if skill and skill.get("round") == number and skill.get("action") == "reveal":
            return _result("available", "extra_speech_available")
        if skill and skill.get("round") == number and skill.get("action") == "unknown":
            return _result("unknown", "sequential_prince_trigger_unknown")
        return _result("unavailable", "extra_speech_trigger_unavailable")
    if skill and skill.get("round") == number and skill.get("action") == "unknown":
        return _result("unknown", "sequential_prince_trigger_unknown")
    if skill and skill.get("round") == number and skill.get("action") == "reveal":
        return _result("available", "extra_speech_available")
    return _result("unavailable", "extra_speech_requires_prince_skill")


def event_constraint(
    game: dict,
    number: int,
    phase: str,
    event: dict,
    *,
    actor: int | None,
    dead_before,
    uses,
    used_targets,
    previous,
    learning,
) -> dict:
    """Return known role constraints for one event opportunity.

    ``uses`` is a Counter keyed by ``(actor, slot)``; target history and the
    most recent slot event are supplied separately.  Callers remain responsible
    for general survival, vote and death-trigger timing.
    """
    code = _board_code(game)
    board_family = family(code)
    slot = event.get("slot")

    if slot in {"witch_save", "witch_poison"}:
        return _medicine_constraint(game, number, phase, event, actor=actor,
                                    uses=uses, previous=previous)

    if board_family == "mixed_blood" and slot == "mixed_blood_model":
        unknown_actor = _role_known(game, actor, "混血儿", "mixed_blood_actor_unknown")
        if unknown_actor is not None:
            return unknown_actor
        return _mixed_blood_constraint(number, phase, event, actor=actor, uses=uses)

    if board_family == "mechanical_wolf_seer" and slot in {
        "mechanical_action", "mechanical_day_skill", "mechanical_knife_status",
    }:
        return _mechanical_constraint(
            game, number, phase, event, actor=actor, dead_before=dead_before,
            uses=uses, previous=previous, learning=learning,
        )

    if slot == "wolf_attack":
        if phase != "night":
            return _result("unavailable", "wolf_attack_wrong_phase", legal_targets=None)
        constraint = _treasure_attack_constraint(
            game, number, event, actor=actor, dead_before=dead_before,
        )
        if constraint is not None:
            return constraint
        return _wolf_attack_constraint(game, number, event, actor=actor, dead_before=dead_before)

    if slot == "seer_check":
        return _seer_check_constraint(game, phase, event, actor=actor,
                                      dead_before=dead_before)

    if board_family == "treasure_master":
        constraint = _treasure_choice_constraint(
            game, number, phase, event, actor=actor, previous=previous,
        )
        if constraint is not None:
            return constraint

    if slot in {"guard", "dreamer_action"}:
        if phase != "night":
            return _result("unavailable", "night_skill_wrong_phase")
        expected = "守卫" if slot == "guard" else "摄梦人"
        unknown_actor = _role_known(game, actor, expected, "target_actor_unknown")
        if unknown_actor is not None:
            return unknown_actor
        if slot == "dreamer_action":
            return _dreamer_constraint(game, number, event, actor=actor, previous=previous)
        return _same_target_rule(
            game, number, event, actor=actor, slot=slot, previous=previous,
            used_targets=used_targets, repeat_mode="consecutive", rule=slot,
            target_count=1,
        )

    if board_family == "masquerade":
        constraint = _masquerade_constraint(
            game, number, phase, event, actor=actor,
            previous=previous, used_targets=used_targets,
        )
        if constraint is not None:
            return constraint

    if board_family == "guile_realm" and slot == "guile_exchange":
        unknown_actor = _role_known(game, actor, "诡术师", "guile_actor_unknown")
        if unknown_actor is not None:
            return unknown_actor
        return _guile_constraint(game, number, phase, event, actor=actor,
                                 used_targets=used_targets, previous=previous)

    if slot in {"sequential_prince_skill", "extra_speech"}:
        return _prince_constraint(game, number, phase, event, actor=actor,
                                  uses=uses, previous=previous)

    if slot == "knight_duel":
        result = _one_shot_constraint(
            game, number, phase, event, actor=actor, uses=uses, slot=slot,
            allowed_phase="day", role="骑士",
        )
        if result["status"] != "available" or not _has_action(event):
            return result
        seats = _all_seats(game)
        if seats is None:
            return _result("unknown", "knight_duel_targets_unknown", legal_targets=None)
        legal = [seat for seat in seats if seat != actor]
        targets = _targets(event)
        if len(targets) != 1 or targets[0] not in legal:
            return _result("unavailable", "knight_duel_target_invalid", legal_targets=legal)
        return _result("available", "knight_duel_available", legal_targets=legal)

    if board_family == "all_in" and slot == "warden_trade_targets":
        if _season(game, code) == "S21" or (isinstance(code, str) and code.startswith("s21_")):
            return _result("unknown", "legacy_all_in_trade_rule_unconfirmed")
        unknown_actor = _role_known(game, actor, "典狱长", "warden_actor_unknown")
        if unknown_actor is not None:
            return unknown_actor
        if phase != "night":
            return _result("unavailable", "warden_trade_wrong_phase")
        if number == 1:
            return _result("unavailable", "warden_trade_starts_second_night")
        return _same_target_rule(
            game, number, event, actor=actor, slot=slot, previous=previous,
            used_targets=used_targets, repeat_mode="never", rule="warden_trade",
            target_count=2,
        )

    if slot in {"hunter_state", "hunter_shot", "wolf_king_state", "wolf_king_shot"}:
        is_wolf_king = slot.startswith("wolf_king_")
        expected_phase = "night" if slot.endswith("_state") else "day"
        expected_role = "狼王" if is_wolf_king else "猎人"
        role_name = "wolf_king" if is_wolf_king else "hunter"
        unknown_actor = _role_known(game, actor, expected_role, f"{role_name}_actor_unknown")
        if unknown_actor is not None:
            return unknown_actor
        if phase != expected_phase:
            return _result("unavailable", f"{role_name}_skill_wrong_phase")
        if (slot.endswith("_state") and _dream_death_blocks_shot(game, number, actor)):
            return _result("unavailable", "dream_death_blocks_shot")
        poison_state = _hunter_poison_state(game, actor, number, learning)
        if poison_state == "poisoned":
            return _result("unavailable", f"{role_name}_poisoned")
        if poison_state == "unknown":
            return _result("unknown", f"{role_name}_poison_unknown")
        return _result("available", f"{role_name}_not_poisoned")

    return _result("unknown", "no_applicable_rule")

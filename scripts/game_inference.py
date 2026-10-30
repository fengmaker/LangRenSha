"""Conservative, read-only event projection for public game details.

The source rounds are complete archival facts.  This module only prepares a
quieter presentation and marks any inferred status on its copied event.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re
from typing import Any

try:
    from .board_config import load_canonical_template
    from .role_constraints import event_constraint, family, mechanical_knife_constraint, nine_tail_knife_constraint, wolf_king_rules
except ImportError:
    from board_config import load_canonical_template
    from role_constraints import event_constraint, family, mechanical_knife_constraint, nine_tail_knife_constraint, wolf_king_rules


_EMPTY_ACTIONS = {None, "unknown"}
PRESENTATION_VERSION = 11
_KEEP_UNKNOWN_SLOTS = {
    # Unknown actions that can change survival, information, or skill access.
    "guard", "wolf_attack", "witch_save", "witch_poison", "seer_check",
    "hunter_state", "mechanical_knife_status", "mechanical_action",
    "puppet_select", "puppet_skill_effect", "wolf_king_state",
    "mixed_blood_model", "night_deaths", "wolf_king_shot", "exile_result",
    "mechanical_day_skill", "puppet_hunter_eligibility", "nine_tail_kill",
}
_DEATH_ACTIONS = {"die", "die_after_speech", "suicide", "exile", "disqualify"}
_TERMINAL_GOD_ROLES = {
    "mechanical_wolf_seer": {"通灵师", "女巫", "猎人", "守卫"},
}


def terminal_from_events(game: dict) -> dict | None:
    """Read an explicit unplayed-day boundary from existing event notes."""
    boundaries: set[int] = set()
    patterns = (
        r"D\s*(\d+)\s*未开始(?!放逐|投票)",
        r"未进入\s*D\s*(\d+)(?!\s*(?:放逐|投票))",
        r"不再有\s*D\s*(\d+)\s*白天",
    )
    for round_ in game.get('rounds', []):
        for phase in ('night', 'day'):
            for event in round_.get(phase, []):
                result = event.get('result')
                if isinstance(result, str):
                    for pattern in patterns:
                        boundaries.update(int(match.group(1)) for match in re.finditer(pattern, result))
    if len(boundaries) > 1:
        raise ValueError('正式事件记录互相指向不同终局白天，需核对终局边界')
    return {'round': next(iter(boundaries)), 'phase': 'night'} if boundaries else None


def terminal_day_events(events: list[dict]) -> list[dict]:
    """Keep terminal outcomes recorded beside the unplayed day's slots."""
    return [
        event for event in events
        if (event.get('slot') == 'night_deaths'
            and (event.get('action') not in {None, 'unknown'} or event.get('targets') or event.get('result')))
        or (event.get('slot') in {'hunter_shot', 'wolf_king_shot'}
            and (event.get('action') not in {None, 'unknown', 'unavailable'}
                 or event.get('targets') or event.get('result') or event.get('effects')
                 or event.get('blocked_by_game_end') is True))
        or (event.get('slot') == 'exile_result'
            and event.get('action') in {'none', 'unknown', 'not_held'} and not event.get('targets')
            and isinstance(event.get('result'), str)
            and re.search(r'游戏结束|终局|未进入\s*D\d+|D\d+未开始|交牌', event['result']))
    ]


def _as_int(value: Any) -> int | None:
    return value if type(value) is int else None


def _seat_rows(game: dict) -> list[dict]:
    rows = game.get("seats")
    if not isinstance(rows, list):
        rows = game.get("players")
    return [row for row in rows or [] if isinstance(row, dict)]


def _role_seats(game: dict) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for seat in _seat_rows(game):
        number = _as_int(seat.get("seat", seat.get("number")))
        role = seat.get("role")
        if number is not None and isinstance(role, str):
            result.setdefault(role, []).append(number)
    return result


def _known_god_seats(game: dict) -> set[int] | None:
    """Return a complete, board-known god roster when this board defines one here."""
    code = _board_code(game)
    board_family = family(code)
    god_roles = _TERMINAL_GOD_ROLES.get(board_family)
    if board_family == "mixed_blood":
        season = game.get("season") or ("S23" if isinstance(code, str) and code.startswith("s23_") else None)
        if isinstance(season, str) and season.upper() == "S23":
            god_roles = {"预言家", "女巫", "猎人", "白神"}
    seats = _seat_rows(game)
    if (god_roles is None or len(seats) != 12
            or any(type(row.get("seat", row.get("number"))) is not int
                   or not isinstance(row.get("role"), str)
                   or row.get("role") in {"", "unknown", "未知", "身份未知"}
                   for row in seats)):
        return None
    gods = {
        number
        for row in seats
        if (number := _as_int(row.get("seat", row.get("number")))) is not None
        and row.get("role") in god_roles
    }
    return gods or None


def terminal_god_departure(
    game: dict, number: int, phase: str, previously_eliminated: set[int],
    phase_events: list[dict], terminal: dict | None,
) -> bool:
    """Whether a confirmed terminal phase begins after its last god departs."""
    if (not isinstance(terminal, dict) or terminal.get("round") != number
            or terminal.get("phase") != phase):
        return False
    gods = _known_god_seats(game)
    if not gods:
        return False
    departed_now: set[int] = set()
    for event in phase_events:
        slot, action = event.get("slot"), event.get("action")
        targets = event.get("targets") if isinstance(event.get("targets"), list) else []
        if slot == "night_deaths" and action == "die":
            departed_now.update(value for value in targets if type(value) is int)
        elif slot == "exile_result" and action == "exile":
            departed_now.update(value for value in targets if type(value) is int)
        elif action in {"die_after_speech", "suicide", "disqualify"}:
            departed_now.update(value for value in targets if type(value) is int)
            if not targets and (actor := _as_int(event.get("actor"))) is not None:
                departed_now.add(actor)
    return gods <= previously_eliminated | departed_now


def terminal_wolf_attack_kills_last_god(
    game: dict, number: int, previously_eliminated: set[int],
    events: list[dict], terminal: dict | None,
) -> bool:
    """Confirm the terminal night ends at the wolf attack, before later wakes."""
    if (family(_board_code(game)) != "mechanical_wolf_seer"
            or not isinstance(terminal, dict)
            or terminal.get("round") != number
            or terminal.get("phase") != "night"):
        return False
    gods = _known_god_seats(game)
    remaining = gods - previously_eliminated if gods else set()
    if len(remaining) != 1:
        return False
    last_god = next(iter(remaining))
    attacks = [event for event in events
               if event.get("slot") == "wolf_attack" and event.get("action") == "attack"]
    terminal_events = terminal.get("events")
    death_events = events + (terminal_events if isinstance(terminal_events, list) else [])
    confirmed_deaths = {
        seat for event in death_events
        if event.get("slot") == "night_deaths" and event.get("action") == "die"
        for seat in (event.get("targets") if isinstance(event.get("targets"), list) else [])
        if type(seat) is int
    }
    return any(last_god in event.get("targets", []) for event in attacks) and last_god in confirmed_deaths


def night_slot_after_wolf_attack(game: dict, slot: str) -> bool:
    """Whether the board's confirmed wake order puts Medium check after wolf action."""
    if slot != "seer_check":
        return False
    template = load_canonical_template(_board_code(game) or "")
    wake_order = template.get("wake_order", [])
    if "狼人" not in wake_order:
        return False
    actors = {row.get("code"): row.get("actor_role") for row in template.get("night_slots", [])}
    seer_role = actors.get(slot)
    if seer_role not in wake_order:
        return False
    return wake_order.index(seer_role) > wake_order.index("狼人")


def _board_code(game: dict) -> str | None:
    board = game.get("board")
    if isinstance(board, dict):
        code = board.get("code")
        return code if isinstance(code, str) else None
    return board if isinstance(board, str) else None


def _actor_for_tracking(event: dict, slot_roles: dict[str, list[int]]) -> int | None:
    actor = _as_int(event.get("actor"))
    if actor is not None:
        return actor
    slot = event.get("slot")
    # Empty template events often omit actor. Resolve only a unique physical
    # role owner so the existing departure/resource filters still apply.
    roles = {
        "seer_check": ("预言家", "通灵师"), "guard": ("守卫",),
        "witch_save": ("女巫",), "witch_poison": ("女巫", "毒师"),
        "mixed_blood_model": ("混血儿",), "mixed_blood_alignment": ("混血儿",),
        "mixed_blood_victory": ("混血儿",),
        "hunter_state": ("猎人",), "hunter_shot": ("猎人",), "puppet_hunter_eligibility": ("猎人",),
        "mechanical_action": ("机械狼",), "mechanical_knife_status": ("机械狼",),
        "mechanical_day_skill": ("机械狼",),
        "wolf_king_state": ("狼王", "黑狼王"), "wolf_king_shot": ("狼王", "黑狼王"),
        "magician_exchange": ("魔术师",), "magic_duel_magician_swap": ("魔术师",),
        "sorcerer_exchange": ("狼术师",), "magic_duel_wolf_sorcerer_swap": ("狼术师",),
        "guile_exchange": ("诡术师",), "dreamer_action": ("摄梦人",),
        "masquerade_mask": ("假面",), "masquerade_verify": ("假面",), "dancer_dance": ("舞者",),
        "white_god_reveal": ("白神", "白痴"), "idiot_reveal": ("白痴", "白神"), "knight_duel": ("骑士",),
        "whiteze_clear": ("白泽",), "whiteze_clear_mark": ("白泽",),
        "nine_tail_mark": ("九尾狐",), "nine_tail_hunt": ("九尾狐",), "nine_tail_kill": ("九尾狐",),
        "nine_tail_skill": ("九尾狐",), "nine_tail_vote_mark": ("九尾狐",),
        "warden_trade_targets": ("典狱长",), "warden_wolf_join": ("典狱长",),
        "s21_treasure_action": ("盗宝大师",), "s21_reveal": ("白神", "白痴"),
        "treasure_choice": ("盗宝大师",), "treasure_remainder": ("盗宝大师",),
        "treasure_alignment": ("盗宝大师",), "treasure_card_skill": ("盗宝大师",),
        "treasure_extra_attack": ("盗宝大师",), "treasure_masked_evasion": ("盗宝大师",),
        "masked_wound": ("蒙面人",), "masked_delayed_death": ("蒙面人",),
        "ghost_bride_select_groom": ("鬼魂新娘",),
        "extra_speech": ("定序王子",), "sequential_prince_skill": ("定序王子",),
    }.get(slot, ())
    matches = [seat for role in roles for seat in slot_roles.get(role, [])]
    return matches[0] if len(matches) == 1 else None


def _has_recorded_content(event: dict) -> bool:
    """Whether an unknown event carries anything beyond its template slot."""
    for key in (
        "targets", "votes", "effects", "result", "availability", "start_seat",
        "direction", "random_point", "speech_scope",
    ):
        value = event.get(key)
        if value not in (None, [], {}):
            return True
    return False


def _has_recorded_seer_check(event: dict) -> bool:
    """Only targets, feedback, or a structured effect make an empty check recorded."""
    targets = event.get("targets")
    if isinstance(targets, list) and targets:
        return True
    result = event.get("result")
    if result not in (None, "", "unknown"):
        return True
    effects = event.get("effects")
    return isinstance(effects, list) and bool(effects)


def _is_empty_unknown(event: dict) -> bool:
    return event.get("action") in _EMPTY_ACTIONS and not _has_recorded_content(event)


def _inferred_description(event: dict, replacement: str, note: str) -> str:
    description = event.get("description")
    if not isinstance(description, str) or not description:
        return f"{replacement}；展示推断：{note}"
    for placeholder in ("记录未知", "记录动作 unknown"):
        if placeholder in description:
            description = description.replace(placeholder, replacement, 1)
            return f"{description}；展示推断依据：{note}"
    return f"{description}；展示推断为{replacement}；依据：{note}"


def _effect_dead_seats(event: dict) -> set[int]:
    dead: set[int] = set()
    effects = event.get("effects")
    if not isinstance(effects, list):
        return dead
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        kind = effect.get("kind")
        # A reflected poison is still an actual poison result.  Use dead_seat,
        # never intended_target or the event's pre-reflection targets.
        if isinstance(kind, str) and "poison" in kind:
            seat = _as_int(effect.get("dead_seat"))
            if seat is not None:
                dead.add(seat)
    return dead


def _poison_effects(event: dict) -> list[dict]:
    effects = event.get("effects")
    if not isinstance(effects, list):
        return []
    return [
        effect for effect in effects
        if isinstance(effect, dict)
        and isinstance(effect.get("kind"), str)
        and "poison" in effect["kind"]
    ]


def _poison_reflection_possible(
    targets: set[int], events: list[dict], game: dict,
) -> bool:
    if not targets:
        return False
    if _board_code(game) != "mechanical_wolf_seer":
        return False
    for event in events:
        if event.get("slot") == "mechanical_action" and event.get("action") == "guard":
            guard_targets = event.get("targets")
            if isinstance(guard_targets, list) and targets.intersection(
                value for value in guard_targets if type(value) is int
            ):
                return True
        result = event.get("result")
        if isinstance(result, str) and "反弹" in result and "毒" in result:
            return True
    return False


def _resolved_poison_seats(
    event: dict,
    *,
    night_events: list[dict],
    day_events: list[dict],
    game: dict,
) -> tuple[set[int], bool]:
    """Resolve actual poison victims, preferring effects over intended targets."""
    if event.get("result") == "failed":
        return set(), False
    effects = event.get("effects")
    poison_effects = _poison_effects(event)
    if poison_effects:
        victims = {
            dead_seat
            for effect in poison_effects
            if (dead_seat := _as_int(effect.get("dead_seat"))) is not None
        }
        unresolved = any(_as_int(effect.get("dead_seat")) is None for effect in poison_effects)
        return victims, unresolved
    if effects not in (None, []):
        # A populated effect record takes precedence even if it does not give a
        # usable poison victim; do not fall back to the original target.
        return set(), True

    targets = event.get("resolved_targets") or event.get("targets")
    intended = {
        value for value in (targets if isinstance(targets, list) else [])
        if type(value) is int
    }
    if not intended or _poison_reflection_possible(intended, night_events, game):
        return set(), True

    confirmed_night_deaths = [
        row for row in day_events
        if row.get("slot") == "night_deaths" and row.get("action") == "die"
    ]
    if not confirmed_night_deaths:
        return set(), True
    dead = {
        value
        for row in confirmed_night_deaths
        for value in (row.get("targets") if isinstance(row.get("targets"), list) else [])
        if type(value) is int
    }
    victims = intended & dead
    return victims, bool(intended - dead)


def _known_poison_victims(
    night_events: list[dict], day_events: list[dict], game: dict,
) -> set[int]:
    victims: set[int] = set()
    for event in night_events:
        victims.update(_effect_dead_seats(event))
        if event.get("action") == "poison":
            resolved, _ = _resolved_poison_seats(
                event, night_events=night_events, day_events=day_events, game=game,
            )
            victims.update(resolved)
    return victims


def _actual_deaths(events: list[dict]) -> set[int]:
    """Seats known out from explicit result events, never from attack targets."""
    dead: set[int] = set()
    for event in events:
        slot = event.get("slot")
        action = event.get("action")
        targets = event.get("targets")
        targets = targets if isinstance(targets, list) else []
        target_seats = {seat for value in targets if (seat := _as_int(value)) is not None}

        if slot == "night_deaths" and action == "die":
            dead.update(target_seats)
        elif slot == "exile_result" and action == "exile":
            dead.update(target_seats)
        elif action in _DEATH_ACTIONS:
            dead.update(target_seats)
            if not target_seats and (actor := _as_int(event.get("actor"))) is not None:
                dead.add(actor)
        elif action == "self_destruct":
            if (actor := _as_int(event.get("actor"))) is not None:
                dead.add(actor)
        elif action == "shoot":
            # The shot targets are actual outcomes.  The shooter is only
            # considered out for roles whose shot is a death-triggered skill;
            # mechanical daytime shots do not eliminate their shooter.
            dead.update(target_seats)
            if slot in {"hunter_shot", "wolf_king_shot"}:
                if (actor := _as_int(event.get("actor"))) is not None:
                    dead.add(actor)

        dead.update(_effect_dead_seats(event))
    return dead


def _ordinary_wolf_king_seat(role_seats: dict[str, list[int]]) -> int | None:
    kings = role_seats.get("狼王", [])
    return kings[0] if len(kings) == 1 else None


def _wolf_king_exiles(game: dict, number: int, events: list[dict]) -> set[int]:
    exiled = {
        seat for event in events
        if event.get("slot") == "exile_result" and event.get("action") == "exile"
        for seat in (event.get("targets") if isinstance(event.get("targets"), list) else [])
        if type(seat) is int
    }
    for ballot in (game.get("voting") or {}).get("ballots", []):
        if ballot.get("day") == number and ballot.get("kind") == "exile" and type(ballot.get("winner")) is int:
            exiled.add(ballot["winner"])
    return exiled


def ordinary_wolf_king_shot_triggered(game: dict, number: int, actor: int,
                                      events: list[dict], exiles: set[int] | None = None) -> bool | None:
    """Return True/False for a proven trigger, None when a night death's cause is unknown."""
    rules = wolf_king_rules()
    triggers = rules.get("ordinary_shot_triggers", [])
    exiled = actor in (exiles if exiles is not None else _wolf_king_exiles(game, number, events))
    if exiled and "exile" in triggers:
        return True
    if any(event.get("slot") == "self_destruct" and event.get("action") == "self_destruct"
           and event.get("actor") == actor for event in events):
        return False
    died_at_night = any(
        event.get("slot") == "night_deaths" and event.get("action") == "die"
        and actor in (event.get("targets") or []) for event in events
    )
    if not died_at_night:
        return False
    attacks = [event for event in events if event.get("slot") == "wolf_attack"]
    for event in attacks:
        if (event.get("action") == "attack" and actor in (event.get("targets") or [])
                and "wolf_attack_death" in triggers):
            return True
    if not attacks:
        return None
    if any(event.get("action") in {"unknown", None} for event in attacks):
        return None
    if any(event.get("action") not in {"pass", "forbidden", "unavailable", "attack"}
           for event in attacks):
        return None
    # A confirmed pass proves the wolf attack did not cause this night death.
    if any(event.get("action") in {"pass", "forbidden", "unavailable"} for event in attacks):
        return False
    # An attack on another seat plus this death leaves the cause unresolved.
    return None


def terminal_last_wolf_king_exile(
    game: dict, number: int, previously_eliminated: set[int],
    current_departures: set[int], current_exiles: set[int], terminal: dict | None,
) -> bool:
    """Confirm a known ordinary king is the final wolf exiled at a day terminal."""
    if not wolf_king_rules().get("last_wolf_exiled_game_end_prevents_shot"):
        return False
    if (not isinstance(terminal, dict) or terminal.get("round") != number
            or terminal.get("phase") != "day" or game.get("winner") != "good"):
        return False
    seats = _seat_rows(game)
    if (len(seats) != 12
            or any(row.get("role") in {None, "", "unknown", "未知", "身份未知"}
                   or row.get("faction") not in {"good", "werewolf"} for row in seats)):
        return False
    king = _ordinary_wolf_king_seat(_role_seats(game))
    wolf_seats = {
        seat for row in seats
        if row.get("faction") == "werewolf"
        and (seat := _as_int(row.get("seat", row.get("number")))) is not None
    }
    departed = previously_eliminated | current_departures
    return bool(king is not None and king in current_exiles
                and wolf_seats and wolf_seats <= departed)


def _wolf_king_shot_status(game: dict, number: int, actor: int) -> dict:
    return event_constraint(
        game, number, "day", {"slot": "wolf_king_shot", "action": "unknown", "actor": actor,
                               "targets": []},
        actor=actor, dead_before=set(), uses=Counter(), used_targets={}, previous={}, learning={},
    )


def _wolf_king_shot_has_recorded_outcome(event: dict) -> bool:
    return bool(event.get("targets") or event.get("result") or event.get("effects"))


def _project_wolf_king_qualification(
    state: dict, shot: dict | None, *, game: dict, number: int, actor: int,
    triggered: bool | None,
) -> None:
    constraint = _wolf_king_shot_status(game, number, actor)
    if constraint.get("status") == "unavailable":
        action = "cannot_shoot"
        reason = constraint.get("reason")
        note = ("狼王本轮因中毒或摄梦结算不能开枪。"
                if reason in {"wolf_king_poisoned", "dream_death_blocks_shot"}
                else "狼王本轮不具备开枪资格。")
    elif shot and shot.get("action") == "shoot":
        action = "can_shoot"
        note = "档案记录狼王本轮实际开枪，确认具备开枪资格。"
    elif shot and shot.get("action") in {"unavailable", "cannot_shoot", "forbidden"}:
        action = "cannot_shoot"
        note = "档案记录本轮狼王不能开枪。"
    elif triggered is False:
        action = "unavailable"
        note = "狼王本轮出局方式不触发开枪。"
    elif triggered is None:
        action = "unknown"
        note = "狼王本轮夜间出局原因未确认，开枪触发条件仍待核。"
    else:
        if constraint.get("status") == "available":
            action = "can_shoot"
            note = "狼王本轮出局，规则确认具备开枪资格。"
        elif constraint.get("status") == "unavailable":
            action = "cannot_shoot"
            reason = constraint.get("reason")
            note = ("狼王本轮因中毒或摄梦结算不能开枪。"
                    if reason in {"wolf_king_poisoned", "dream_death_blocks_shot"}
                    else "狼王本轮不具备开枪资格。")
        else:
            action = state.get("action") or "unknown"
            note = "狼王本轮出局，开枪资格仍待核。"
    if state.get("action") != action:
        state["inferred"] = True
    state["action"] = action
    state["actor"] = actor
    state["inference_note"] = note
    state["_wolf_king_qualification_projection"] = True


def _annotate_exchange_settlement(events: list[dict], game: dict) -> None:
    """Link explicit settled exchange notes to their original actions.

    The board's general interaction order is not fully established.  An
    exchange pair alone is therefore insufficient to manufacture a mapping.
    """
    if _board_code(game) != "guile_realm":
        return
    seats = {row.get("seat"): row for row in _seat_rows(game)}
    exchanges = [e for e in events if e.get("slot") == "magician_exchange"
                 and e.get("action") == "exchange" and len(e.get("targets") or []) == 2]
    if len(exchanges) != 1:
        return
    exchange = exchanges[0]
    pair = set(exchange["targets"])
    if len(pair) != 2 or not pair <= seats.keys():
        return
    if any(e.get("slot") == "guile_exchange" and e.get("action") == "exchange"
           and set(e.get("targets") or []) == pair for e in events):
        return  # Same-pair cancellation must not be mistaken for redirection.
    note = exchange.get("result") or ""
    if not isinstance(note, str):
        return
    patterns = {
        "seer_check": r"(?:查验|预言家)[^，。；;]*?实际(?:查验|验|到|为|落在)?\s*(\d{1,2})(?!\d)",
        "wolf_attack": r"(?:狼刀|原刀)[^，。；;]*?实际\s*(\d{1,2})(?!\d)",
        "witch_poison": r"(?:女巫|毒药)[^，。；;]*?实际(?:毒杀|毒|到|为)?\s*(\d{1,2})(?!\d)",
    }
    feedback_by_role = {
        "狼人": "werewolf", "诡术师": "werewolf", "预言家": "good",
        "女巫": "good", "魔术师": "good", "定序王子": "good", "平民": "good",
    }
    for slot, pattern in patterns.items():
        actuals = {int(value) for value in re.findall(pattern, note)}
        actions = [e for e in events if e.get("slot") == slot
                   and e.get("action") == {"seer_check": "check", "wolf_attack": "attack", "witch_poison": "poison"}[slot]]
        if len(actuals) != 1 or len(actions) != 1:
            continue
        actual = next(iter(actuals))
        event = actions[0]
        targets = event.get("targets") or []
        if len(targets) != 1 or targets[0] not in pair or pair - {targets[0]} != {actual}:
            continue
        if slot == "seer_check":
            actor = seats.get(event.get("actor"), {})
            feedback = feedback_by_role.get(seats[actual].get("role"))
            if actor.get("role") != "预言家" or feedback is None:
                continue
            existing = event.get("result")
            expected = {"good": {"good", "好人"}, "werewolf": {"werewolf", "wolf", "狼人"}}[feedback]
            # Some archives put the feedback and redirection in one sentence.
            # Keep explicit conflicting feedback rather than replacing it.
            embedded = re.search(r"(?:反馈|结果(?:为|是)?)\s*(好人|狼人)", existing or "")
            if embedded:
                existing = embedded.group(1)
            if existing not in (None, "", "unknown") and existing not in expected:
                continue  # Keep conflicting recorded feedback for review.
            event["result"] = feedback
            reason = f"本夜交换结算明确实际查验{actual}号，其底牌为{seats[actual]['role']}，预言家反馈为{'好人' if feedback == 'good' else '狼人'}。"
        elif slot == "wolf_attack":
            reason = f"本夜交换结算明确狼刀原目标{targets[0]}号，实际刀口为{actual}号。"
        else:
            reason = f"本夜交换结算明确原用毒目标{targets[0]}号，实际毒药目标为{actual}号。"
        event["resolved_targets"] = [actual]
        event["inferred"] = True
        event["inference_note"] = reason


def _annotate_identity_feedback(events: list[dict], game: dict) -> None:
    """The treasure board's medium reports physical identity, not victory side."""
    if _board_code(game) != "treasure_master":
        return
    seats = {row.get("seat"): row for row in _seat_rows(game)}
    known_roles = {"通灵师", "毒师", "猎人", "摄梦人", "蒙面人", "平民", "狼王", "狼人", "盗宝大师"}
    for event in events:
        targets = event.get("targets") or []
        if (event.get("slot") != "seer_check" or event.get("action") != "check"
                or event.get("result") not in (None, "", "unknown") or len(targets) != 1
                or seats.get(event.get("actor"), {}).get("role") != "通灵师"):
            continue
        role = seats.get(targets[0], {}).get("role")
        if role in known_roles:
            event["result"] = role
            event["inferred"] = True
            event["inference_note"] = f"通灵师反馈实际底牌；{targets[0]}号底牌为{role}，不按其临时能力或胜利阵营改写。"


def _witch_poison_use_nights(game: dict, role_seats: dict[str, list[int]]) -> dict[int, int]:
    """Find a single, nonconflicting later use of a witch/poisoner's bottle."""
    uses: dict[int, list[tuple[int, bool]]] = {}
    eliminated: set[int] = set()
    for round_ in game.get("rounds") or []:
        if not isinstance(round_, dict) or type(round_.get("number")) is not int:
            continue
        night = [e for e in (round_.get("night") or []) if isinstance(e, dict)]
        day = [deepcopy(e) for e in (round_.get("day") or []) if isinstance(e, dict)]
        for event in day:
            _voting_exile_result(event, game, round_["number"])
        saves = {_actor_for_tracking(e, role_seats) for e in night
                 if e.get("slot") == "witch_save" and e.get("action") == "save"}
        for event in night:
            if event.get("slot") != "witch_poison":
                continue
            actor = _actor_for_tracking(event, role_seats)
            if actor not in role_seats.get("女巫", []) + role_seats.get("毒师", []):
                continue
            if event.get("action") == "poison" or _poison_effects(event):
                valid = actor not in eliminated and actor not in saves
                uses.setdefault(actor, []).append((round_["number"], valid))
        # Confirmed deaths, rather than attack targets, delimit a witch's life.
        eliminated.update(_actual_deaths(night + day))
    return {actor: rows[0][0] for actor, rows in uses.items()
            if len(rows) == 1 and rows[0][1]}


def _annotate_held_poison(events: list[dict], *, number: int, use_nights: dict[int, int],
                          role_seats: dict[str, list[int]], eliminated: set[int],
                          spent: set[int], saved: set[int]) -> None:
    for event in events:
        if event.get("slot") != "witch_poison" or not _is_empty_unknown(event):
            continue
        actor = _actor_for_tracking(event, role_seats)
        later_night = use_nights.get(actor)
        if (later_night is None or later_night <= number
                or actor in eliminated or actor in spent or actor in saved):
            continue
        role = "毒师" if actor in role_seats.get("毒师", []) else "女巫"
        event["actor"] = actor
        event["action"] = "pass"
        event["inferred"] = True
        event["inference_note"] = f"同一{role}第{later_night}夜才使用这瓶毒药，结合此前出局记录，本夜推断为压毒。"
        event["description"] = f"{actor}号{role}压毒，本夜未使用毒药。"


def _annotate_poison_from_deaths(events: list[dict], day: list[dict], game: dict, *,
                                  number: int, role_seats: dict[str, list[int]],
                                  eliminated: set[int], spent: set[int], saved: set[int]) -> None:
    # This board has only the ordinary wolf knife and witch poison at night.
    # A single death cannot rule out knife and poison hitting the same seat.
    if _board_code(game) != "mixed_blood":
        return
    knives = [e for e in events if e.get("slot") == "wolf_attack" and e.get("action") == "attack"]
    deaths = [e for e in day if e.get("slot") == "night_deaths" and e.get("action") == "die"]
    poisons = [e for e in events if e.get("slot") == "witch_poison"]
    if len(knives) != 1 or len(deaths) != 1 or len(poisons) != 1:
        return
    knife = knives[0].get("targets") or []
    dead = set(deaths[0].get("targets") or [])
    event = poisons[0]
    actor = _actor_for_tracking(event, role_seats)
    if (len(knife) != 1 or len(dead) != 2 or knife[0] not in dead
            or actor not in role_seats.get("女巫", []) or actor in eliminated
            or actor in spent or actor in saved or not _is_empty_unknown(event)):
        return
    # A later recorded use of the same bottle would contradict this deduction.
    for round_ in game.get("rounds") or []:
        if round_.get("number", 0) <= number:
            continue
        if any(e.get("slot") == "witch_poison" and e.get("action") == "poison"
               and _actor_for_tracking(e, role_seats) == actor for e in round_.get("night") or []):
            return
    victim = next(iter(dead - set(knife)))
    event["action"] = "poison"
    event["actor"] = actor
    event["targets"] = [victim]
    event["inferred"] = True
    event["inference_note"] = f"本版无其他夜间致死技能；完整天亮记录为{knife[0]}号、{victim}号双死，已知狼刀命中{knife[0]}号，因此补出毒口{victim}号。"
    event["description"] = f"{actor}号女巫使用毒药，毒杀{victim}号。"


def _annotate_lost_badge(events: list[dict], game: dict, number: int) -> None:
    lost_days = [row.get("day") for row in (game.get("voting") or {}).get("days", [])
                 if row.get("sheriff") == "badge_lost" and type(row.get("day")) is int]
    if not lost_days or number != min(lost_days):
        return
    for event in events:
        if (event.get("slot") == "badge" and not event.get("targets")
                and (event.get("action") == "none" or _is_empty_unknown(event))):
            event["action"] = "badge_lost"
            event["inferred"] = True
            event["inference_note"] = "逐日竞选记录确认警徽流失；具体原因未据此推断。"
            event["description"] = "警徽流失，本局不再进行警长竞选。"


def _poison_sources(
    events: list[dict],
    *,
    day_events: list[dict],
    game: dict,
    role_seats: dict[str, list[int]],
    eliminated_before_night: set[int],
    spent_witch_poison: set[int],
    saved_this_night: set[int],
    spent_mechanical_poison: set[int],
) -> tuple[set[int], bool]:
    """Return proven poisoned seats and whether a possible poison is unresolved."""
    poisoned: set[int] = set()
    uncertain = False
    witch_seats = role_seats.get("女巫", []) + role_seats.get("毒师", [])
    mechanical_seats = role_seats.get("机械狼", [])
    seat_by_number = {
        _as_int(row.get("seat", row.get("number"))): row
        for row in _seat_rows(game)
        if _as_int(row.get("seat", row.get("number"))) is not None
    }
    event_slots = {event.get("slot") for event in events}

    # Missing an available witch slot is a gap, not evidence that no poison
    # was used.  A same-night save or a previously spent bottle rules it out.
    if witch_seats and "witch_poison" not in event_slots:
        if any(
            seat not in eliminated_before_night
            and seat not in spent_witch_poison
            and seat not in saved_this_night
            for seat in witch_seats
        ):
            uncertain = True

    mechanical_poison_possible = False
    for seat in mechanical_seats:
        seat_row = seat_by_number.get(seat, {})
        if (seat_row.get("learned_role") == "机械女巫"
                and seat not in eliminated_before_night
                and seat not in spent_mechanical_poison):
            mechanical_poison_possible = True
    if mechanical_poison_possible and "mechanical_action" not in event_slots:
        uncertain = True

    for event in events:
        slot = event.get("slot")
        action = event.get("action")
        actor = _actor_for_tracking(event, role_seats)
        poison_effects = _poison_effects(event)
        for effect in poison_effects:
            dead_seat = _as_int(effect.get("dead_seat"))
            if dead_seat is not None:
                poisoned.add(dead_seat)

        if slot == "witch_poison":
            if actor is None:
                continue
            # The same witch cannot use both bottles on one night.  A saved
            # night rules out poison without spending the poison bottle.
            if (action in _EMPTY_ACTIONS and not poison_effects
                    and (actor in eliminated_before_night
                         or actor in spent_witch_poison
                         or actor in saved_this_night)):
                continue
            if action == "poison":
                victims, unresolved = _resolved_poison_seats(
                    event, night_events=events, day_events=day_events, game=game,
                )
                poisoned.update(victims)
                uncertain = uncertain or unresolved
            elif action in _EMPTY_ACTIONS and not poison_effects:
                uncertain = True
        elif slot == "mechanical_action":
            if actor is None:
                continue
            if (action in _EMPTY_ACTIONS and not poison_effects
                    and (actor in eliminated_before_night or actor in spent_mechanical_poison)):
                continue
            seat_row = seat_by_number.get(actor, {})
            learned_role = seat_row.get("learned_role")
            # On the learning night the mechanical wolf cannot use the new
            # skill.  On later nights an empty mechanical-witch slot is open.
            learning_this_night = action == "learn" or event.get("availability") == "learning"
            if action == "poison":
                victims, unresolved = _resolved_poison_seats(
                    event, night_events=events, day_events=day_events, game=game,
                )
                poisoned.update(victims)
                uncertain = uncertain or unresolved
            elif (action in _EMPTY_ACTIONS and not poison_effects
                  and learned_role == "机械女巫" and not learning_this_night):
                uncertain = True
        elif action == "poison":
            # Cover other configured role slots that can record poison use.
            victims, unresolved = _resolved_poison_seats(
                event, night_events=events, day_events=day_events, game=game,
            )
            poisoned.update(victims)
            uncertain = uncertain or unresolved

    return poisoned, uncertain


def _puppet_hunter_seats(
    events: list[dict], role_seats: dict[str, list[int]],
) -> set[int]:
    puppet_seats: set[int] = set()
    hunter_seats = set(role_seats.get("猎人", []))
    for event in events:
        if event.get("slot") == "puppet_select" and event.get("action") == "select":
            targets = event.get("targets")
            if isinstance(targets, list):
                puppet_seats.update(
                    value for value in targets
                    if type(value) is int and value in hunter_seats
                )
        elif event.get("slot") == "puppet_skill_effect" and event.get("action") == "skill_disabled":
            targets = event.get("targets")
            if isinstance(targets, list):
                puppet_seats.update(
                    value for value in targets
                    if type(value) is int and value in hunter_seats
                )
            result = event.get("result")
            if isinstance(result, str):
                for match in re.finditer(r"(\d+)号", result):
                    seat = int(match.group(1))
                    if seat in hunter_seats:
                        puppet_seats.add(seat)
    return puppet_seats


def _annotate_hunter_state(
    events: list[dict],
    *,
    day_events: list[dict],
    game: dict,
    role_seats: dict[str, list[int]],
    eliminated_before_night: set[int],
    spent_witch_poison: set[int],
    saved_this_night: set[int],
    spent_mechanical_poison: set[int],
    puppet_hunter_seats: set[int],
) -> None:
    hunter_seats = role_seats.get("猎人", [])
    if len(hunter_seats) != 1 or any(
        not isinstance(row.get("role"), str) for row in _seat_rows(game)
    ):
        return
    hunter = hunter_seats[0]
    if hunter in eliminated_before_night:
        return

    state_events = [event for event in events if event.get("slot") == "hunter_state"]
    if len(state_events) != 1:
        return
    event = state_events[0]
    if (not _is_empty_unknown(event)
            or event.get("availability") is not None):
        return
    event_actor = _actor_for_tracking(event, role_seats)
    if event_actor != hunter:
        return

    # Puppet Hunter qualification has a separate explicit event.  Its outcome
    # is not derivable from poison status, so leave an unknown state for review.
    if _board_code(game) == "neighbor_puppet" and hunter in puppet_hunter_seats:
        return

    poisoned, poison_uncertain = _poison_sources(
        events,
        day_events=day_events,
        game=game,
        role_seats=role_seats,
        eliminated_before_night=eliminated_before_night,
        spent_witch_poison=spent_witch_poison,
        saved_this_night=saved_this_night,
        spent_mechanical_poison=spent_mechanical_poison,
    )
    if hunter in poisoned:
        action = "cannot_shoot"
        note = "本夜毒药结算确认命中该猎人；被毒中的猎人不能开枪。"
    elif poison_uncertain:
        return
    else:
        action = "can_shoot"
        note = "该座位是本局唯一且仍在场的猎人；可核实的本夜用药结算未命中该猎人，因此可以开枪。"

    event["action"] = action
    event["inferred"] = True
    event["inference_note"] = note
    replacement = "可开枪" if action == "can_shoot" else "不能开枪"
    event["description"] = _inferred_description(event, replacement, note)


def _should_omit(
    event: dict,
    *,
    phase: str,
    eliminated_before_round: set[int],
    role_seats: dict[str, list[int]],
    spent_saves: set[int],
    spent_witch_poison: set[int],
    spent_mechanical_poison: set[int],
    saved_this_night: set[int],
    poisoned_this_night: set[int],
    model_chosen: set[int],
    mixed_alignment_resolved: set[int],
    poisoner_absent: bool = False,
) -> bool:
    slot = event.get("slot")
    actor = _actor_for_tracking(event, role_seats)
    if actor in eliminated_before_round and slot in {"hunter_state", "wolf_king_state", "mechanical_knife_status"}:
        return True
    if slot == "mechanical_knife_status":
        return phase != "night" or event.get("action") != "carrying"
    if (phase == "night" and event.get("action") in {None, "unknown", "pass", "unavailable", "not_applicable", "none"}
            and not any(event.get(key) for key in ("targets", "votes", "effects"))):
        if slot == "witch_poison" and actor is not None and actor in saved_this_night:
            return True
        if slot == "witch_save" and actor is not None and actor in poisoned_this_night:
            return True
    if (slot in {"mechanical_action", "mechanical_day_skill"}
            and event.get("action") == "unavailable" and not _has_recorded_content(event)
            and not event.get("blocked_by_game_end")):
        return True
    if not any(event.get(key) for key in ('targets', 'votes', 'effects')) and not event.get('blocked_by_game_end'):
        if slot == 'self_destruct' and event.get('action') == 'none':
            return True
        if (slot == 'hunter_shot' and event.get('action') == 'unavailable'
                and isinstance(event.get('result'), str)
                and re.search(r'未出局|未死亡', event['result'])):
            return True
    if (event.get("action") in {"unavailable", "not_applicable", "pass", "none"}
            and not any(event.get(key) for key in ("targets", "votes", "effects"))):
        if actor is not None and actor in eliminated_before_round:
            return True
        if slot == "witch_save" and actor in spent_saves:
            return True
        if slot == "witch_poison" and actor in spent_witch_poison:
            return True
    if not _is_empty_unknown(event):
        return False
    if slot == "witch_poison" and poisoner_absent:
        return True

    # A role's blank night slots after it has actually left play add no useful
    # event.  Explicit actions and outcome data have already been kept above.
    if actor is not None and actor in eliminated_before_round:
        return True

    if slot == "hunter_shot" and event.get("inferred") is True and event.get("inference_note"):
        return False

    if slot == "mixed_blood_model" and actor is not None and actor in model_chosen:
        return True
    if slot == "mixed_blood_alignment" and actor is not None and actor in mixed_alignment_resolved:
        return True
    if slot == "witch_save" and actor is not None and actor in spent_saves:
        return True
    if slot == "witch_poison" and actor is not None and actor in spent_witch_poison:
        return True
    if slot == "mechanical_action" and actor is not None and actor in spent_mechanical_poison:
        return True

    # Empty unknown placeholders in noncritical template slots can disappear;
    # the omitted count keeps this presentation's filtering visible.
    return slot not in _KEEP_UNKNOWN_SLOTS


def _record_resource_uses(
    events: list[dict],
    *,
    role_seats: dict[str, list[int]],
    spent_saves: set[int],
    spent_witch_poison: set[int],
    spent_mechanical_poison: set[int],
    saved_this_night: set[int],
    poisoned_this_night: set[int],
    model_chosen: set[int],
    mixed_alignment_resolved: set[int],
) -> None:
    for event in events:
        actor = _actor_for_tracking(event, role_seats)
        action = event.get("action")
        slot = event.get("slot")
        if actor is None:
            continue
        if slot == "witch_save" and action == "save":
            spent_saves.add(actor)
            saved_this_night.add(actor)
        elif slot == "witch_poison" and action == "poison":
            spent_witch_poison.add(actor)
            poisoned_this_night.add(actor)
        elif slot == "mechanical_action" and action == "poison":
            spent_mechanical_poison.add(actor)
        elif slot == "mixed_blood_model" and action == "choose":
            model_chosen.add(actor)
        elif slot == "mixed_blood_alignment" and action in {"good", "wolf"}:
            mixed_alignment_resolved.add(actor)


def _voting_exile_result(event: dict, game: dict, day_number: int) -> str | None:
    """Use explicit voting records to resolve or omit an empty exile slot.

    Returns ``"omit"`` when the day record proves no exile result was held,
    ``"inferred"`` after filling a completed voting outcome, or ``None`` when
    the voting archive does not settle the question.
    """
    if event.get("slot") != "exile_result":
        return None
    empty_result = _is_empty_unknown(event)
    recorded_no_exile = event.get("action") == "none" and not event.get("targets")
    if not empty_result and not recorded_no_exile:
        return None
    voting = game.get("voting")
    if not isinstance(voting, dict):
        return None

    day_record = next(
        (row for row in voting.get("days", [])
         if isinstance(row, dict) and row.get("day") == day_number),
        None,
    )
    if not isinstance(day_record, dict):
        return None
    status = day_record.get("exile")
    if status in {"interrupted_self_destruct", "not_applicable", "not_held"}:
        return "omit" if empty_result or event.get("result") == "interrupted_self_destruct" else None
    if status != "recorded":
        return None

    ballots = [
        row for row in voting.get("ballots", [])
        if isinstance(row, dict)
        and row.get("day") == day_number
        and row.get("kind") == "exile"
    ]
    if not ballots:
        return None
    # Voting records are stored in their played order.  An earlier complete
    # round cannot stand in for a later incomplete or unresolved one.
    ballot = ballots[-1]
    if ballot.get("status") != "complete":
        return None
    winner = _as_int(ballot.get("winner"))
    # A completed initial vote followed by a completed, tied PK ends this
    # day's exile.  The PK stage itself establishes the initial tie even if
    # that older ballot has no tied_candidates annotation.  Do not infer this
    # from a lone tie, incomplete PK, or an earlier pair before a later vote.
    if (winner is None and len(ballots) >= 2
            and ballot.get("stage") == "pk"
            and len(set(ballot.get("tied_candidates") or [])) >= 2
            and ballots[-2].get("stage") == "initial"
            and ballots[-2].get("status") == "complete"
            and _as_int(ballots[-2].get("winner")) is None):
        event["action"] = "none"
        event["targets"] = []
        event["result"] = "double_tie"
        if empty_result:
            event["inferred"] = True
            event["inference_note"] = "完整放逐首轮与 PK 轮均平票，按规则本日无人被放逐。"
        event["description"] = "放逐首轮与 PK 轮均平票，本日无人被放逐。"
        return "inferred"
    if not empty_result:
        return None
    if winner is None:
        return None

    event["action"] = "exile"
    event["targets"] = [winner]
    note = f"第{day_number}天完整放逐票的最终结果记录为{winner}号出局，据此补记。"
    event["inferred"] = True
    event["inference_note"] = note
    event["description"] = _inferred_description(event, f"{winner}号出局", note)
    return "inferred"


def _annotate_pending_hunter_shot(
    night_events: list[dict],
    day_events: list[dict],
    *,
    known_deaths: set[int],
    previously_eliminated: set[int],
    known_poison_victims: set[int],
    role_seats: dict[str, list[int]],
    puppet_hunter_seats: set[int],
    game: dict,
    terminal: dict | None,
    number: int,
) -> None:
    hunter_seats = role_seats.get("猎人", [])
    if len(hunter_seats) != 1:
        return
    hunter = hunter_seats[0]
    if any(
        event.get("action") == "disqualify"
        and (hunter in (event.get("targets") or []) or event.get("actor") == hunter)
        for event in night_events + day_events
    ):
        return
    if hunter not in known_deaths:
        return
    if hunter in known_poison_victims:
        return
    if hunter in puppet_hunter_seats:
        return

    if terminal_god_departure(
        game, number, "day", previously_eliminated, night_events + day_events, terminal,
    ):
        return

    if any(event.get("slot") == "hunter_shot"
           and _actor_for_tracking(event, role_seats) == hunter
           and event.get("blocked_by_game_end") is True for event in day_events):
        return

    # S23 pre/witch/hunter/white/mixed has a confirmed terminal rule: when its
    # last god, the Hunter, leaves play, the game ends before a shot window.
    if game.get("season") == "S23" and _board_code(game) == "mixed_blood":
        god_seats = {
            seat for role in ("预言家", "女巫", "猎人", "白神")
            for seat in role_seats.get(role, [])
        }
        if (god_seats and hunter in god_seats
                and god_seats <= known_deaths | previously_eliminated):
            return

    state_events = [
        event for event in night_events
        if event.get("slot") == "hunter_state"
        and _actor_for_tracking(event, role_seats) == hunter
    ]
    status = state_events[-1].get("action") if state_events else None
    if status in {"cannot_shoot", "unavailable", "forbidden"}:
        return

    puppet_events = [
        event for event in day_events
        if event.get("slot") == "puppet_hunter_eligibility"
        and _actor_for_tracking(event, role_seats) == hunter
    ]
    puppet_status = puppet_events[-1].get("action") if puppet_events else None
    if puppet_status in {"cannot_shoot", "unavailable", "forbidden"}:
        return

    qualification_known = status == "can_shoot" or puppet_status == "can_shoot"
    note = (
        "档案确认猎人本日出局且具备开枪资格，但未记录开枪目标，请复核。"
        if qualification_known else
        "猎人本日出局，开枪资格或开枪目标仍待核；档案未记录枪口，请复核。"
    )
    for event in day_events:
        if (event.get("slot") == "hunter_shot"
                and _actor_for_tracking(event, role_seats) == hunter
                and _is_empty_unknown(event)):
            event["inferred"] = True
            event["inference_note"] = note
            event["description"] = _inferred_description(event, "开枪情况待核", note)


def _project_mechanical_knife_status(events: list[dict], game: dict, number: int, *,
                                    role_seats: dict[str, list[int]], departed: set[int]) -> int:
    recorded = [e for e in events if e.get("slot") == "mechanical_knife_status"]
    events[:] = [e for e in events if e.get("slot") != "mechanical_knife_status"]
    mechanical = role_seats.get("机械狼", [])
    if len(mechanical) != 1:
        return len(recorded)
    actor = mechanical[0]
    state = mechanical_knife_constraint(game, number, "night", actor=actor, dead_before=departed)
    if state["status"] != "available":
        return len(recorded)
    event = recorded[0] if recorded else {"slot": "mechanical_knife_status"}
    if event.get("action") != "carrying" or event.get("actor") != actor:
        event["inferred"] = True
        event["inference_note"] = "本夜开始前，其他狼人均已确认出局。"
    event.update(action="carrying", actor=actor)
    events.append(event)
    return max(0, len(recorded) - 1)


def _project_nine_tail_knife(events: list[dict], game: dict, number: int, *,
                             role_seats: dict[str, list[int]], departed: set[int]) -> int:
    foxes = role_seats.get("九尾狐", [])
    if len(foxes) != 1:
        return 0
    actor = foxes[0]
    state = nine_tail_knife_constraint(game, number, "night", actor=actor, dead_before=departed)
    fox_kill = next((e for e in events if e.get("slot") == "nine_tail_kill"), None)
    if state["status"] != "available":
        if fox_kill is not None:
            events.remove(fox_kill)
            return 1
        return 0
    attacks = [e for e in events if e.get("slot") in {"wolf_attack", "nine_tail_kill"}]
    # Older archives store the same normal knife in wolf_attack. Keep its
    # factual target and outcome when the dedicated fox slot is still blank.
    chosen = fox_kill if fox_kill is not None and not _is_empty_unknown(fox_kill) else next(
        (e for e in attacks if e.get("slot") == "wolf_attack"), fox_kill,
    )
    event = deepcopy(chosen) if chosen is not None else {"action": "unknown", "targets": []}
    event.update(slot="nine_tail_kill", actor=actor, slot_label="九尾狐击杀")
    if event.get("action") == "attack":
        event["action"] = "kill"
    if chosen is None or chosen.get("slot") != "nine_tail_kill":
        event.update(inferred=True, inference_note="本夜开始前普通狼人均已出局，普通狼刀由九尾狐接手。")
    events[:] = [e for e in events if e not in attacks]
    events.append(event)
    return max(0, len(attacks) - 1)


def _display_result(event: dict, roles: dict[str, list[int]]) -> str | None:
    value = event.get("result")
    if not isinstance(value, str) or not value:
        return None
    if event.get("action") == "check":
        feedback = sorted({*roles, "好人", "狼人", "平民", "守卫", "猎人", "女巫", "通灵师"}, key=len, reverse=True)
        match = re.search(r"(?:为|是|反馈[：:]?)\s*(" + "|".join(map(re.escape, feedback)) + r")(?:身份)?(?:[，。；,;]|$)", value)
        return match.group(1) if match else value
    if event.get("action") == "learn":
        forms = {"mechanical_double_attack_werewolf": "机械双刀狼人", "mechanical_guard": "机械守卫",
                 "mechanical_witch": "机械女巫", "mechanical_hunter": "机械猎人",
                 "mechanical_seer": "机械通灵师", "mechanical_villager": "机械平民"}
        match = re.search(r"机械(?:双刀(?:狼人?)?|守卫|女巫|猎人|通灵师|平民)", value)
        return forms.get(value) or ("机械双刀狼人" if match and match.group(0).startswith("机械双刀") else match.group(0) if match else None)
    if event.get("action") in {"pass", "register", "deferred", "elected", "exile", "self_destruct", "shoot", "transfer", "badge_lost", "peaceful", "no_death", "die", "carrying", "not_carrying"}:
        return None
    if value in {"good", "werewolf", "wolf", "unknown", "peaceful", "success", "failed", "double_tie",
                 "guarded", "saved", "immune", "protected_by_dance_pool", "badge_lost", "badge_destroyed"}:
        return value
    if event.get("action") in {"attack", "guard", "save", "poison", "unknown", "unavailable", "none"}:
        # Routine action summaries and editorial notes stay in the source.
        # Keep an additional effect only when it adds an actual game outcome.
        clauses = [part for part in re.split(r"[；;。]", value)
                   if re.search(r"中毒|失败|失效|免疫|奶穿|奶死|反弹|被守|舞池保护|最后一神|终局", part)]
        return "；".join(clauses) or None
    return value


def _display_events(events: list[dict], phase: str, template: dict, roles: dict[str, list[int]]) -> list[dict]:
    slots = template.get(phase + "_slots", [])
    codes = [slot["code"] for slot in slots]
    if phase == "day":
        # Archive templates can list day actions before the morning results.
        morning = ["sheriff_candidates", "sheriff_vote", "sheriff_result", "night_deaths", "badge"]
        codes = morning + [code for code in codes if code not in morning]
    order = {code: index for index, code in enumerate(codes)}
    labels = {slot["code"]: slot["label"] for slot in slots}
    positions: dict[int, float] = {}
    if phase == "day":
        for departed, anchor in [
            ({s for e in events if e.get("slot") == "night_deaths" and e.get("action") == "die" for s in e.get("targets", [])}, "night_deaths"),
            ({s for e in events if e.get("action") == "exile" for s in e.get("targets", [])}, "exile_result"),
        ]:
            pending = [e for e in events if e.get("action") == "shoot"]
            while True:
                shot = next((e for e in pending if e.get("actor") in departed), None)
                if shot is None:
                    break
                positions[id(shot)] = order.get(anchor, len(order)) + .1 + len(positions) / 100
                departed.update(shot.get("targets", []))
                pending.remove(shot)
    for event in events:
        wolf_king_qualification = event.pop("_wolf_king_qualification_projection", False)
        if event.get("slot") in labels and not wolf_king_qualification:
            event["slot_label"] = labels[event["slot"]]
        if wolf_king_qualification:
            event["slot_label"] = "狼王开枪资格"
            event["description"] = "狼王本轮出局；开枪资格在出局阶段展示。"
            actor = _actor_for_tracking(event, roles)
            actual_shot = next((row for row in events
                                if row.get("slot") == "wolf_king_shot"
                                and row.get("action") == "shoot"
                                and _actor_for_tracking(row, roles) == actor), None)
            if actual_shot is not None and id(actual_shot) in positions:
                positions[id(event)] = positions[id(actual_shot)] - .01
            else:
                departure = next((row for row in events
                                  if actor in (row.get("targets") or [])
                                  and row.get("action") in {"die", "exile"}), None)
                if departure is None:
                    departure = next((row for row in events
                                      if row.get("action") == "self_destruct"
                                      and _actor_for_tracking(row, roles) == actor), None)
                if departure is None:
                    positions[id(event)] = order.get("wolf_king_shot", len(order)) - .1
                else:
                    departure_pos = positions.get(
                        id(departure), order.get(departure.get("slot"), len(order)))
                    positions[id(event)] = departure_pos + .01
        if event.get("slot") == "witch_poison" and _actor_for_tracking(event, roles) in roles.get("毒师", []):
            event["slot_label"] = "毒师毒药"
        event["display_result"] = _display_result(event, roles)
    return sorted(events, key=lambda e: positions.get(id(e), order.get(e.get("slot"), len(order))))


def build_game_presentation(game: dict) -> dict:
    """Build a filtered, inferred presentation without changing ``game``.

    Source events are copied, while knife confirmation is projected from
    departures before each night. Inferred statuses and voting outcomes gain
    ``inferred`` and ``inference_note``. Explicit terminal boundaries exclude
    unplayed phases, including snapshots published before boundary recognition.
    """
    source_rounds = game.get("rounds")
    source_rounds = source_rounds if isinstance(source_rounds, list) else []
    terminal_observation = game.get('terminal_observation') or terminal_from_events(game)
    terminal = None
    if (isinstance(terminal_observation, dict)
            and type(terminal_observation.get('round')) is int
            and terminal_observation.get('phase') in {'night', 'day'}):
        terminal = {**terminal_observation, 'events': deepcopy(game.get('terminal_events') or [])}
    role_seats = _role_seats(game)
    code = _board_code(game)
    if code:
        display_template = load_canonical_template(code)
    else:
        display_template = {}
    poison_use_nights = _witch_poison_use_nights(game, role_seats)
    seats = _seat_rows(game)
    poisoner_absent = (len(seats) == 12
                       and all(row.get("role") not in {None, "", "unknown", "未知", "身份未知"} for row in seats)
                       and not role_seats.get("女巫") and not role_seats.get("毒师"))

    eliminated: set[int] = set()
    spent_saves: set[int] = set()
    spent_witch_poison: set[int] = set()
    spent_mechanical_poison: set[int] = set()
    model_chosen: set[int] = set()
    mixed_alignment_resolved: set[int] = set()
    puppet_hunter_seats: set[int] = set()
    output_rounds: list[dict] = []
    omitted = 0
    rule_states = {(s["round"], s["phase"], s["slot"]): s for s in (game.get("rules_state") or {}).get("slots", [])}

    for source_round in source_rounds:
        if not isinstance(source_round, dict):
            output_rounds.append({"number": None, "night": [], "day": []})
            omitted += 1
            continue
        number = source_round.get("number")
        if terminal and type(number) is int and number > terminal['round']:
            omitted += sum(len(source_round.get(phase) or []) for phase in ('night', 'day'))
            continue
        source_night = source_round.get("night")
        source_day = source_round.get("day")
        source_night = source_night if isinstance(source_night, list) else []
        source_day = source_day if isinstance(source_day, list) else []
        eliminated_before_round = set(eliminated)

        # Do analysis on copies so inference and presentation never mutate the
        # database-backed event dictionaries passed by the API.
        night = [deepcopy(event) for event in source_night if isinstance(event, dict)]
        day = [deepcopy(event) for event in source_day if isinstance(event, dict)]
        wolf_killed_last_god = bool(
            terminal and type(number) is int
            and terminal_wolf_attack_kills_last_god(
                game, number, eliminated_before_round, night + day, terminal,
            )
        )
        # Storage variants may lack an unavailable action enum. The prepared
        # rule state still proves that their empty slot cannot be played.
        for phase, events in (("night", night), ("day", day)):
            kept = []
            for event in events:
                if (phase == "night" and number == 1 and display_template.get("code") == "masquerade"
                        and event.get("slot") in {"masquerade_verify", "masquerade_mask", "dancer_dance"}
                        and event.get("action") in {None, "unknown", "unavailable", "pass"}
                        and not any(event.get(key) for key in ("targets", "votes", "effects"))):
                    omitted += 1
                    continue
                if (phase == "night" and wolf_killed_last_god
                        and night_slot_after_wolf_attack(game, event.get("slot"))
                        and event.get("action") in {None, "unknown", "unavailable"}
                        and not _has_recorded_seer_check(event)):
                    omitted += 1
                    continue
                state = rule_states.get((number, phase, event.get("slot")), {})
                absent_hunter = (event.get("slot") == "hunter_state" and len(seats) == 12
                                 and all(s.get("role") not in {None, "", "unknown", "未知", "身份未知"} for s in seats)
                                 and not role_seats.get("猎人"))
                if _is_empty_unknown(event) and (state.get("status") == "unavailable" or absent_hunter):
                    omitted += 1
                    continue
                if (event.get("slot") in {"hunter_state", "wolf_king_state"} and _is_empty_unknown(event)
                        and state.get("status") == "available" and state.get("reason") in {"hunter_not_poisoned", "wolf_king_not_poisoned"}
                        and not (display_template.get("code") == "neighbor_puppet" and
                                 _actor_for_tracking(event, role_seats) in _puppet_hunter_seats(night + day, role_seats))):
                    event.update(action="can_shoot", actor=_actor_for_tracking(event, role_seats), inferred=True,
                                 inference_note="已确认的用药结算未命中该角色，具备开枪资格。")
                kept.append(event)
            events[:] = kept
        ordinary_wolf_king = _ordinary_wolf_king_seat(role_seats)
        current_events = night + day
        current_departures = _actual_deaths(current_events)
        current_exiles = _wolf_king_exiles(game, number, current_events) if type(number) is int else set()
        terminal_last_wolf_king = bool(
            ordinary_wolf_king is not None and type(number) is int
            and terminal_last_wolf_king_exile(
                game, number, eliminated_before_round, current_departures,
                current_exiles, terminal,
            )
        )
        if ordinary_wolf_king is not None and type(number) is int:
            state_event = next((event for event in night
                                if event.get("slot") == "wolf_king_state"
                                and _actor_for_tracking(event, role_seats) == ordinary_wolf_king), None)
            if (state_event is None
                    and (ordinary_wolf_king in current_departures
                         or ordinary_wolf_king in current_exiles)):
                state_event = {"slot": "wolf_king_state", "action": "unknown",
                               "actor": ordinary_wolf_king, "targets": [], "inferred": True}
            if state_event is not None:
                if state_event in night:
                    night.remove(state_event)
                if ordinary_wolf_king in eliminated_before_round or ordinary_wolf_king not in current_departures:
                    omitted += 1
                elif terminal_last_wolf_king:
                    omitted += 1
                else:
                    shot_event = next((event for event in day
                                       if event.get("slot") == "wolf_king_shot"
                                       and _actor_for_tracking(event, role_seats) == ordinary_wolf_king), None)
                    triggered = ordinary_wolf_king_shot_triggered(
                        game, number, ordinary_wolf_king, current_events,
                    )
                    _project_wolf_king_qualification(
                        state_event, shot_event, game=game, number=number,
                        actor=ordinary_wolf_king, triggered=triggered,
                    )
                    if terminal and terminal.get("round") == number and terminal.get("phase") == "night":
                        terminal["events"].append(state_event)
                    else:
                        day.append(state_event)
        if display_template.get("code") == "mechanical_wolf_seer":
            omitted += _project_mechanical_knife_status(night, game, number,
                role_seats=role_seats, departed=eliminated_before_round)
        if display_template.get("code") == "qingqiu_night":
            omitted += _project_nine_tail_knife(night, game, number,
                role_seats=role_seats, departed=eliminated_before_round)
        if terminal and number == terminal['round'] and terminal['phase'] == 'night':
            outcomes = terminal_day_events(day)
            terminal['events'].extend(outcomes)
            omitted += len(day) - len(outcomes)
            day = []
            night_outcomes = [event for event in night
                              if event.get('slot') == 'night_deaths' and not _is_empty_unknown(event)]
            terminal['events'].extend(night_outcomes)
            night = [event for event in night if event not in night_outcomes]
        if any(event.get('slot') == 'night_deaths' and not _is_empty_unknown(event) for event in night + day):
            for events in (night, day):
                blanks = [event for event in events if event.get('slot') == 'night_deaths' and _is_empty_unknown(event)]
                omitted += len(blanks)
                events[:] = [event for event in events if event not in blanks]
        elif any(event.get('slot') == 'night_deaths' for event in day):
            blanks = [event for event in night if event.get('slot') == 'night_deaths' and _is_empty_unknown(event)]
            omitted += len(blanks)
            night[:] = [event for event in night if event not in blanks]
        for event in night:
            if (event.get("slot") == "witch_poison"
                    and _actor_for_tracking(event, role_seats) in role_seats.get("毒师", [])):
                event["slot_label"] = "毒师毒药"

        saved_this_night = {
            _actor_for_tracking(event, role_seats)
            for event in night
            if event.get("slot") == "witch_save" and event.get("action") == "save"
        }
        poisoned_this_night = {
            _actor_for_tracking(event, role_seats)
            for event in night
            if event.get("slot") == "witch_poison" and event.get("action") == "poison"
        }
        saved_this_night.discard(None)
        poisoned_this_night.discard(None)

        _annotate_exchange_settlement(night, game)
        _annotate_identity_feedback(night, game)
        _annotate_poison_from_deaths(
            night, day, game, number=number if type(number) is int else 0,
            role_seats=role_seats, eliminated=eliminated_before_round,
            spent=spent_witch_poison, saved=saved_this_night,
        )
        _annotate_held_poison(
            night, number=number if type(number) is int else 0,
            use_nights=poison_use_nights, role_seats=role_seats,
            eliminated=eliminated_before_round, spent=spent_witch_poison,
            saved=saved_this_night,
        )
        _annotate_lost_badge(day, game, number)

        puppet_hunter_seats.update(_puppet_hunter_seats(night, role_seats))
        puppet_hunter_seats.update(_puppet_hunter_seats(day, role_seats))
        _annotate_hunter_state(
            night,
            game=game,
            day_events=day,
            role_seats=role_seats,
            eliminated_before_night=eliminated_before_round,
            spent_witch_poison=spent_witch_poison,
            saved_this_night=saved_this_night,
            spent_mechanical_poison=spent_mechanical_poison,
            puppet_hunter_seats=puppet_hunter_seats,
        )

        for event in night:
            slot = event.get("slot")
            if slot == "witch_save" and event.get("action") == "save":
                saved_this_night.add(_actor_for_tracking(event, role_seats))
            elif slot == "witch_poison" and event.get("action") == "poison":
                poisoned_this_night.add(_actor_for_tracking(event, role_seats))
        saved_this_night.discard(None)
        poisoned_this_night.discard(None)

        filtered_night = []
        for event in night:
            if _should_omit(
                event,
                phase="night",
                eliminated_before_round=eliminated_before_round,
                role_seats=role_seats,
                spent_saves=spent_saves,
                spent_witch_poison=spent_witch_poison,
                spent_mechanical_poison=spent_mechanical_poison,
                saved_this_night=saved_this_night,
                poisoned_this_night=poisoned_this_night,
                model_chosen=model_chosen,
                mixed_alignment_resolved=mixed_alignment_resolved,
                poisoner_absent=poisoner_absent,
            ):
                omitted += 1
            else:
                filtered_night.append(event)

        # Resolve/omit unsupported empty exile placeholders first, so a
        # completed ballot winner is included in the current day's deaths.
        omitted_day_event_ids: set[int] = set()
        for event in day:
            exile_status = _voting_exile_result(
                event, game, number if type(number) is int else 0,
            )
            if exile_status == "omit":
                omitted += 1
                omitted_day_event_ids.add(id(event))

        # Night result events belong to the day row, but deaths take effect
        # after night actions and before day actions.  Include inferred exile
        # results before deciding who can act on a later night.
        night_out = _actual_deaths(night) | _actual_deaths(day)
        known_poison_victims = _known_poison_victims(night, day, game)
        _annotate_pending_hunter_shot(
            night,
            day,
            known_deaths=night_out,
            previously_eliminated=eliminated_before_round,
            known_poison_victims=known_poison_victims,
            role_seats=role_seats,
            puppet_hunter_seats=puppet_hunter_seats,
            game=game,
            terminal=terminal,
            number=number if type(number) is int else 0,
        )
        filtered_day = []
        for event in day:
            if id(event) in omitted_day_event_ids:
                continue
            if (event.get("slot") in {"white_god_reveal", "idiot_reveal"}
                    and event.get("action") in {None, "unknown", "unavailable", "pass", "none"}
                    and not any(event.get(key) for key in ("targets", "votes", "effects"))):
                if _actor_for_tracking(event, role_seats) in current_exiles:
                    filtered_day.append(event)
                else:
                    omitted += 1
                continue
            if (ordinary_wolf_king is not None
                    and event.get("slot") == "wolf_king_shot"
                    and _actor_for_tracking(event, role_seats) == ordinary_wolf_king
                    and event.get("action") in {None, "unknown", "unavailable"}
                    and not _wolf_king_shot_has_recorded_outcome(event)
                    and event.get("blocked_by_game_end") is not True
                    and (terminal_last_wolf_king
                         or ordinary_wolf_king in eliminated_before_round
                         or (ordinary_wolf_king in current_departures
                             and _wolf_king_shot_status(game, number, ordinary_wolf_king).get("status") == "unavailable")
                         or ordinary_wolf_king_shot_triggered(
                             game, number, ordinary_wolf_king, current_events,
                         ) is False)):
                omitted += 1
                continue
            if (event.get("slot") in {"hunter_shot", "wolf_king_shot", "mechanical_day_skill"}
                    and event.get("action") == "unavailable"
                    and not _has_recorded_content(event)
                    and not event.get("blocked_by_game_end")
                    and _actor_for_tracking(event, role_seats) not in night_out):
                omitted += 1
                continue
            registration = next((row for row in (game.get("voting") or {}).get("registrations", [])
                                 if row.get("day") == number), None)
            if (event.get("slot") == "sheriff_candidates" and event.get("action") == "register"
                    and registration and registration.get("on_police") is not None
                    and set(event.get("targets", [])) == set(registration["on_police"])):
                omitted += 1
                continue
            if _should_omit(
                event,
                phase="day",
                eliminated_before_round=eliminated_before_round,
                role_seats=role_seats,
                spent_saves=spent_saves,
                spent_witch_poison=spent_witch_poison,
                spent_mechanical_poison=spent_mechanical_poison,
                saved_this_night=saved_this_night,
                poisoned_this_night=poisoned_this_night,
                model_chosen=model_chosen,
                mixed_alignment_resolved=mixed_alignment_resolved,
                poisoner_absent=poisoner_absent,
            ):
                omitted += 1
            else:
                filtered_day.append(event)

        output_rounds.append({"number": number,
                              "night": _display_events(filtered_night, "night", display_template, role_seats),
                              "day": _display_events(filtered_day, "day", display_template, role_seats)})

        # Update persistent once-per-game actions after projecting this night.
        _record_resource_uses(
            night,
            role_seats=role_seats,
            spent_saves=spent_saves,
            spent_witch_poison=spent_witch_poison,
            spent_mechanical_poison=spent_mechanical_poison,
            saved_this_night=set(),
            poisoned_this_night=set(),
            model_chosen=model_chosen,
            mixed_alignment_resolved=mixed_alignment_resolved,
        )
        eliminated.update(night_out)

    # Source events that were not dictionaries are malformed for the public
    # GameEvent contract, but count as omitted instead of changing numbering.
    omitted += sum(
        1
        for round_ in source_rounds
        for phase in ("night", "day")
        for event in (round_.get(phase) if isinstance(round_, dict) else []) or []
        if not isinstance(event, dict)
    )
    if terminal:
        terminal['events'] = [{**event, 'terminal': True} for event in
                              _display_events(terminal['events'], terminal['phase'], display_template, role_seats)]
    return {"version": PRESENTATION_VERSION, "rounds": output_rounds,
            "omitted_events": omitted, "terminal": terminal}

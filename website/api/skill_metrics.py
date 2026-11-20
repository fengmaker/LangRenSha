"""Skill-use metrics derived from immutable published game snapshots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from scripts.role_constraints import mechanical_form_name, puppet_target


_SPECS = {
    "witch_poison": {
        "slot": "witch_poison",
        "use": "poison",
        "keys": ("witch_poison_count", "witch_poison_wolf_rate", "witch_poison_wolf_kills"),
    },
    "hunter_shot": {
        "slot": "hunter_shot",
        "use": "shoot",
        "keys": ("hunter_shot_count", "hunter_shot_wolf_rate", "hunter_shot_wolf_kills"),
    },
    "mechanical_poison": {
        "slot": "mechanical_action",
        "use": "poison",
        "keys": ("mechanical_poison_count", "mechanical_poison_god_kills"),
    },
    "mechanical_shot": {
        "slot": "mechanical_day_skill",
        "use": "shoot",
        "keys": ("mechanical_shot_count", "mechanical_shot_god_kills"),
    },
    "guard": {
        "slot": "guard",
        "use": "guard",
        "keys": ("guard_count", "guard_knife_hits", "guard_knife_hit_rate"),
    },
    "mechanical_guard": {
        "slot": "mechanical_action",
        "use": "guard",
        "keys": ("mechanical_guard_count", "mechanical_reflect_god_kills"),
    },
    "mechanical_check": {
        "slot": "mechanical_action",
        "use": "check",
        "keys": ("mechanical_check_count",),
    },
    "mechanical_extra_attack": {
        "slot": "mechanical_action",
        "use": "attack",
        "keys": ("mechanical_extra_attack_count",),
    },
}

_MECHANICAL_SKILLS = {
    "机械女巫": "mechanical_poison",
    "机械猎人": "mechanical_shot",
    "机械守卫": "mechanical_guard",
    "机械通灵师": "mechanical_check",
    "机械双刀狼": "mechanical_extra_attack",
}


class MechanicalLearning(NamedTuple):
    learned: bool | None
    form: str | None
    round_number: int | None


def mechanical_learning(game: dict[str, Any], seat: dict[str, Any]) -> MechanicalLearning:
    """Read the confirmed learning and form, retaining unresolved records."""
    seat_number = seat.get("seat")
    unique_wolf = sum(row.get("role") == "机械狼" for row in game["seats"]) == 1
    rounds = game.get("rounds") or []
    actions = [
        (round_.get("number"), [event for event in round_.get("night") or []
                                if event.get("slot") == "mechanical_action"
                                and (event.get("actor") == seat_number
                                     or (unique_wolf and event.get("actor") is None))])
        for round_ in rounds
    ]
    learns = [(number, event) for number, events in actions for event in events
              if event.get("action") == "learn"]
    number, event = learns[0] if len(learns) == 1 else (None, {})
    targets = event.get("targets") or []
    target = seat.get("learning_target") or (targets[0] if len(targets) == 1 else None)
    target_role = next((row.get("role") for row in game["seats"]
                        if target is not None and row.get("seat") == target), None)
    if target_role == "预言家":
        target_role = "通灵师"
    recorded_form = mechanical_form_name(seat.get("learned_role"))
    form = recorded_form or mechanical_form_name(target_role) or mechanical_form_name(event.get("result"))
    if learns or target is not None or recorded_form or form:
        return MechanicalLearning(True, form, number)
    if (game.get("winner") in {"good", "werewolf"} and actions
            and [n for n, _ in actions] == list(range(1, len(actions) + 1))
            and all(len(events) == 1 and events[0].get("action") in {"pass", "unavailable"}
                    for _, events in actions)):
        return MechanicalLearning(False, None, None)
    return MechanicalLearning(None, None, None)


def _skill_for_seat(seat: dict[str, Any], form: str | None) -> str | None:
    role = seat.get("role")
    if role in {"女巫", "毒师"}:
        return "witch_poison"
    if role == "猎人":
        return "hunter_shot"
    if role == "守卫":
        return "guard"
    return _MECHANICAL_SKILLS.get(form)


def _empty_metric() -> dict[str, int]:
    return {"positive": 0, "negative": 0, "excluded": 0}


def _record(metric: dict[str, int], success: bool) -> None:
    metric["positive" if success else "negative"] += 1


def _exclude(metric: dict[str, int], count: int = 1) -> None:
    metric["excluded"] += count


def _observe(metric: dict[str, int], result: bool | None) -> None:
    if result is None:
        _exclude(metric)
    else:
        _record(metric, result)


def _metric_result(metric: dict[str, int], game_id: str) -> dict[str, Any]:
    positive = metric["positive"]
    negative = metric["negative"]
    denominator = positive + negative
    return {
        "numerator": positive,
        "denominator": denominator,
        "rate": positive / denominator if denominator else None,
        "excluded": metric["excluded"],
        "game_ids": [game_id] if denominator else [],
        "samples": ([{"game_id": game_id, "positive": positive, "negative": negative}]
                    if denominator else []),
    }


def _presentation(game: dict[str, Any], needs_poison_projection: bool) -> dict[str, Any] | None:
    published = game.get("presentation")
    if (isinstance(published, dict) and isinstance(published.get("rounds"), list)
            and not needs_poison_projection):
        return published
    if not needs_poison_projection:
        return None

    # This is a projection over the same immutable snapshot. It resolves such
    # cases as target exchanges without changing the source action record.
    from scripts.game_inference import build_game_presentation

    return build_game_presentation(game)


def _poison_needs_exchange_resolution(event: dict[str, Any], round_: dict[str, Any]) -> bool:
    if event.get("slot") != "witch_poison" or event.get("action") != "poison":
        return False
    effects = event.get("effects") or []
    if event.get("result") == "failed" or any(
            isinstance(effect, dict) and "poison" in str(effect.get("kind") or "")
            for effect in effects):
        return False
    targets = set(event.get("targets") or [])
    for phase in ("night", "day"):
        for exchange in round_.get(phase) or []:
            if (exchange.get("slot") != "magician_exchange"
                    or exchange.get("action") != "exchange"):
                continue
            pair = set(exchange.get("targets") or [])
            if not targets.intersection(pair):
                continue
            cancelled = any(
                event.get("slot") == "guile_exchange"
                and event.get("action") == "exchange"
                and set(event.get("targets") or []) == pair
                for event in (round_.get("night") or []) + (round_.get("day") or [])
            )
            if not cancelled:
                return True
    return False


def _needs_poison_projection(game: dict[str, Any], rounds: list[dict[str, Any]]) -> bool:
    published = game.get("presentation")
    projected = _presentation_events(published) if isinstance(published, dict) else {}
    for round_ in rounds:
        number = round_.get("number")
        for event in round_.get("night") or []:
            if not isinstance(event, dict) or not _poison_needs_exchange_resolution(event, round_):
                continue
            resolved = projected.get((number, event.get("slot"), event.get("actor")))
            if not resolved or not resolved.get("resolved_targets"):
                return True
    return False


def _presentation_events(presentation: dict[str, Any] | None) -> dict[tuple[int, str, int | None], dict[str, Any]]:
    indexed: dict[tuple[int, str, int | None], dict[str, Any]] = {}
    if not presentation:
        return indexed
    for round_ in presentation.get("rounds", []):
        if not isinstance(round_, dict):
            continue
        number = round_.get("number")
        if type(number) is not int:
            continue
        for phase in ("night", "day"):
            for event in round_.get(phase, []) or []:
                if not isinstance(event, dict):
                    continue
                key = (number, event.get("slot"), event.get("actor"))
                indexed[key] = event
    return indexed


def _poison_resolution(
    event: dict[str, Any], round_: dict[str, Any], game: dict[str, Any],
    projected_event: dict[str, Any],
) -> set[int] | None:
    from scripts.game_inference import _resolved_poison_seats

    resolved_targets = projected_event.get("resolved_targets")
    if not resolved_targets and _poison_needs_exchange_resolution(event, round_):
        return None
    victims, unresolved = _resolved_poison_seats(
        {**event, "resolved_targets": resolved_targets} if resolved_targets is not None else event,
        night_events=round_.get("night") or [],
        day_events=round_.get("day") or [],
        game=game,
    )
    return None if unresolved else victims


def _puppet_disabled_actions(game: dict[str, Any], puppet: int | None) -> set[tuple[int, str, str, int, str]]:
    """Read disabled skill outcomes from the existing presentation timeline."""
    if puppet is None:
        return set()
    relevant = any(
        event.get("actor") == puppet
        and event.get("slot") in {"witch_poison", "hunter_shot"}
        and event.get("action") in {"poison", "shoot"}
        for round_ in (game.get("rounds") or [])
        for phase in ("night", "day")
        for event in (round_.get(phase) or [])
        if isinstance(event, dict)
    )
    if not relevant:
        return set()

    # game_timeline owns the current puppet rule and exposes its result as a
    # puppet_note on the corresponding projected event.
    from scripts.game_timeline import build_game_timeline

    disabled: set[tuple[int, str, str, int, str]] = set()
    for phase in build_game_timeline(game).get("phases", []):
        number = phase.get("number")
        phase_name = phase.get("phase")
        if type(number) is not int or phase_name not in {"night", "day"}:
            continue
        for item in phase.get("items", []):
            for event in item.get("events", []):
                if (event.get("puppet_note") and event.get("slot") in {"witch_poison", "hunter_shot"}
                        and event.get("actor") == puppet):
                    disabled.add((number, phase_name, event["slot"], puppet, event.get("action")))
    return disabled


def _is_god(seat: dict[str, Any] | None) -> bool | None:
    role = (seat or {}).get("role")
    if role in {None, "", "unknown", "未知", "身份未知"}:
        return None
    return role in {"预言家", "通灵师", "女巫", "毒师", "猎人", "守卫"}


def _guard_knife_hit(event: dict[str, Any], round_: dict[str, Any]) -> bool | None:
    knives = [row for row in round_.get("night") or [] if row.get("slot") == "wolf_attack"]
    targets = event.get("targets") or []
    if len(knives) != 1 or len(targets) != 1 or type(targets[0]) is not int:
        return None
    knife = knives[0]
    if knife.get("action") in {"pass", "forbidden", "unavailable"}:
        return False
    chosen = knife.get("targets") or []
    if knife.get("action") != "attack" or not chosen or any(type(n) is not int for n in chosen):
        return None
    return targets[0] in chosen


def _reflect_god_kill(
    seat_number: int, event: dict[str, Any], round_: dict[str, Any], seats: dict[int, dict[str, Any]],
) -> bool | None:
    poisons = [row for row in round_.get("night") or [] if row.get("slot") == "witch_poison"]
    if len(poisons) != 1:
        return None
    poison = poisons[0]
    if (poison.get("action") in {"pass", "unavailable"}
            or poison.get("result") == "failed" or poison.get("invalidated")
            or poison.get("blocked_by_game_end")):
        return False
    if poison.get("action") != "poison":
        return None
    for effect in poison.get("effects") or []:
        if effect.get("kind") == "poison_reflected":
            return effect.get("shield_actor") == seat_number and _is_god(seats.get(effect.get("dead_seat")))
        if effect.get("kind") == "poison_death":
            return False
    guarded = event.get("targets") or []
    poisoned = poison.get("targets") or []
    if len(guarded) == len(poisoned) == 1 and guarded != poisoned:
        return False
    return None


def skill_metrics(
    game: dict[str, Any],
    faction_for_seat: Callable[[dict[str, Any]], str | None],
) -> dict[int, dict[str, dict[str, Any]]]:
    """Return one-game skill metrics keyed by seat number.

    Witch poison use is classified once per game. Other count metrics record
    explicit use/pass decisions. Wolf-target rates use the chosen target, and
    kill metrics require a resolved outcome. Unknown choices and missing
    whole-skill records are excluded.
    """
    game_id = str(game.get("id") or "")
    seats = {
        seat.get("seat"): seat
        for seat in game.get("seats", [])
        if type(seat.get("seat")) is int
    }
    learning_by_seat = {number: mechanical_learning(game, seat) for number, seat in seats.items()
                        if seat.get("role") == "机械狼"}
    skills_by_seat: dict[int, str] = {}
    holders_by_slot: dict[str, list[int]] = {}
    metrics: dict[int, dict[str, dict[str, int]]] = {}
    for seat_number, seat in seats.items():
        learning = learning_by_seat.get(seat_number)
        if learning is not None:
            learned_metric = _empty_metric()
            learned_identity = learning.learned
            if learned_identity is True:
                learned_identity = None if learning.form is None else learning.form != "机械平民"
            _observe(learned_metric, learned_identity)
            metrics[seat_number] = {"mechanical_learn_rate": learned_metric}
        skill = _skill_for_seat(seat, learning.form if learning else None)
        if skill is not None:
            skills_by_seat[seat_number] = skill
            spec = _SPECS[skill]
            holders_by_slot.setdefault(spec["slot"], []).append(seat_number)
            metrics.setdefault(seat_number, {}).update({key: _empty_metric() for key in spec["keys"]})

    if not metrics:
        return {}

    rounds = [round_ for round_ in (game.get("rounds") or []) if isinstance(round_, dict)]
    needs_poison_projection = _needs_poison_projection(game, rounds)
    puppet = puppet_target(game)
    puppet_disabled = _puppet_disabled_actions(game, puppet)
    projected = _presentation_events(_presentation(game, needs_poison_projection))
    seen_seats: set[int] = set()
    witch_no_use_nights: dict[int, set[int]] = {}

    for round_ in rounds:
        number = round_.get("number")
        if type(number) is not int:
            number = -1
        for phase in ("night", "day"):
            for source_event in round_.get(phase) or []:
                if not isinstance(source_event, dict):
                    continue
                slot = source_event.get("slot")
                holders = holders_by_slot.get(slot)
                if not holders:
                    continue
                actor = source_event.get("actor")
                action = source_event.get("action")
                for seat_number in holders:
                    if actor is not None and actor != seat_number:
                        continue
                    skill = skills_by_seat[seat_number]
                    spec = _SPECS[skill]
                    use = spec["use"]
                    state = metrics[seat_number]
                    keys = spec["keys"]
                    ambiguous_actor = actor is None and len(holders) > 1
                    if (skill == "witch_poison" and phase == "night" and not ambiguous_actor
                            and action in {"pass", "unavailable"}):
                        witch_no_use_nights.setdefault(seat_number, set()).add(number)
                    if action == "unavailable":
                        seen_seats.add(seat_number)
                        continue
                    if action not in {use, "pass", None, "unknown"}:
                        continue
                    learning = learning_by_seat.get(seat_number)
                    if (action != use and learning and learning.round_number is not None
                            and (number < learning.round_number
                                 or (number == learning.round_number and phase == "night"))):
                        # A pass before the skill unlocks concerns learning.
                        continue

                    seen_seats.add(seat_number)
                    if action in {None, "unknown"} or ambiguous_actor:
                        for key in keys:
                            _exclude(state[key])
                        continue
                    _record(state[keys[0]], action == use)
                    if action == "pass":
                        continue
                    if skill == "guard":
                        hit = _guard_knife_hit(source_event, round_)
                        _observe(state["guard_knife_hits"], hit)
                        _observe(state["guard_knife_hit_rate"], hit)
                        continue
                    if skill == "mechanical_guard":
                        _observe(state["mechanical_reflect_god_kills"],
                                 _reflect_god_kill(seat_number, source_event, round_, seats))
                        continue
                    if use not in {"poison", "shoot"}:
                        continue

                    tracks_wolves = skill in {"witch_poison", "hunter_shot"}
                    kill_metric = state[keys[-1]]
                    targets = source_event.get("targets")
                    target = targets[0] if isinstance(targets, list) and len(targets) == 1 else None
                    if tracks_wolves:
                        # Target rates use the player's intended choice.
                        target_seat = seats.get(target) if type(target) is int else None
                        target_faction = faction_for_seat(target_seat) if target_seat else None
                        _observe(state[keys[1]], target_faction == "werewolf"
                                 if target_faction in {"good", "werewolf"} else None)

                    if (source_event.get("blocked_by_game_end") or source_event.get("result") == "failed"
                            or source_event.get("invalidated")
                            or (number, phase, slot, seat_number, action) in puppet_disabled):
                        victims = set()
                    elif use == "poison":
                        victims = _poison_resolution(source_event, round_, game,
                                                     projected.get((number, slot, actor), {}))
                    else:
                        # An unblocked shot establishes the chosen target's death.
                        victims = {target} if type(target) is int else None
                    if victims is None:
                        _exclude(kill_metric)
                    elif tracks_wolves:
                        victim_factions = [faction_for_seat(seats[victim]) if victim in seats else None
                                           for victim in victims]
                        if any(faction not in {"good", "werewolf"} for faction in victim_factions):
                            _exclude(kill_metric)
                        else:
                            _record(kill_metric, "werewolf" in victim_factions)
                    else:
                        victim_roles = [_is_god(seats.get(victim)) for victim in victims]
                        _observe(kill_metric, any(victim_roles) if None not in victim_roles else None)

    for seat_number, skill in skills_by_seat.items():
        if seat_number not in seen_seats:
            # A known skill-holder with no slot record is an unknown appearance.
            for key in _SPECS[skill]["keys"]:
                _exclude(metrics[seat_number][key])
        if skill == "witch_poison":
            count = metrics[seat_number]["witch_poison_count"]
            used = count["positive"] > 0
            no_use = (not used and count["excluded"] == 0
                      and len(witch_no_use_nights.get(seat_number, ())) == len(rounds) > 0)
            count.update(positive=int(used), negative=int(no_use), excluded=int(not (used or no_use)))

    return {
        seat_number: {
            key: _metric_result(metric, game_id)
            for key, metric in seat_metrics.items()
        }
        for seat_number, seat_metrics in metrics.items()
    }

"""Skill-use metrics derived from immutable published game snapshots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


_SPECS = {
    "witch_poison": {
        "slot": "witch_poison",
        "use": "poison",
        "pass": "pass",
        "keys": ("witch_poison_count", "witch_poison_wolf_rate", "witch_poison_wolf_kills"),
    },
    "hunter_shot": {
        "slot": "hunter_shot",
        "use": "shoot",
        "pass": "pass",
        "keys": ("hunter_shot_count", "hunter_shot_wolf_rate", "hunter_shot_wolf_kills"),
    },
    "mechanical_poison": {
        "slot": "mechanical_action",
        "use": "poison",
        "pass": "pass",
        "keys": ("mechanical_poison_count", "mechanical_poison_wolf_rate",
                 "mechanical_poison_wolf_kills"),
    },
    "mechanical_shot": {
        "slot": "mechanical_day_skill",
        "use": "shoot",
        "pass": "pass",
        "keys": ("mechanical_shot_count", "mechanical_shot_wolf_rate",
                 "mechanical_shot_wolf_kills"),
    },
}


def _skill_for_seat(seat: dict[str, Any]) -> str | None:
    role = seat.get("role")
    learned_role = seat.get("learned_role")
    if role == "女巫":
        return "witch_poison"
    if role == "猎人":
        return "hunter_shot"
    if role == "机械狼" and learned_role == "机械女巫":
        return "mechanical_poison"
    if role == "机械狼" and learned_role == "机械猎人":
        return "mechanical_shot"
    return None


def _empty_metric() -> dict[str, int]:
    return {"positive": 0, "negative": 0, "excluded": 0}


def _record(metric: dict[str, int], success: bool) -> None:
    metric["positive" if success else "negative"] += 1


def _exclude(metric: dict[str, int], count: int = 1) -> None:
    metric["excluded"] += count


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
) -> tuple[set[int], bool]:
    from scripts.game_inference import _resolved_poison_seats

    return _resolved_poison_seats(
        event,
        night_events=round_.get("night") or [],
        day_events=round_.get("day") or [],
        game=game,
    )


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


def skill_metrics(
    game: dict[str, Any],
    faction_for_seat: Callable[[dict[str, Any]], str | None],
) -> dict[int, dict[str, dict[str, Any]]]:
    """Return one-game skill metrics keyed by seat number.

    Count metrics record explicit use/pass decisions. Wolf-target rates use
    the chosen target, while kill metrics require a resolved outcome. Unknown
    choices and missing whole-skill records are excluded instead of treated as
    no-use decisions.
    """
    game_id = str(game.get("id") or "")
    seats = {
        seat.get("seat"): seat
        for seat in game.get("seats", [])
        if type(seat.get("seat")) is int
    }
    skill_holders: dict[str, list[int]] = {name: [] for name in _SPECS}
    metrics: dict[int, dict[str, dict[str, int]]] = {}
    for seat_number, seat in seats.items():
        skill = _skill_for_seat(seat)
        if skill is None:
            continue
        skill_holders[skill].append(seat_number)
        metrics[seat_number] = {
            key: _empty_metric() for key in _SPECS[skill]["keys"]
        }

    if not metrics:
        return {}

    rounds = [round_ for round_ in (game.get("rounds") or []) if isinstance(round_, dict)]
    needs_poison_projection = _needs_poison_projection(game, rounds)
    from scripts.role_constraints import puppet_target

    puppet = puppet_target(game)
    puppet_disabled = _puppet_disabled_actions(game, puppet)
    projected = _presentation_events(_presentation(game, needs_poison_projection))
    seen_by_seat: dict[int, int] = {seat_number: 0 for seat_number in metrics}

    for round_ in rounds:
        number = round_.get("number")
        if type(number) is not int:
            number = -1
        for phase in ("night", "day"):
            for source_event in round_.get(phase) or []:
                if not isinstance(source_event, dict):
                    continue
                slot = source_event.get("slot")
                skill = next((name for name, spec in _SPECS.items() if spec["slot"] == slot), None)
                if skill is None:
                    continue
                actor = source_event.get("actor")
                holders = skill_holders[skill]
                candidates = ([actor] if type(actor) is int and actor in holders else [])
                if not candidates and actor is None and len(holders) == 1:
                    candidates = holders
                if not candidates and actor is None and len(holders) > 1:
                    action = source_event.get("action")
                    if action in {None, "unknown", _SPECS[skill]["use"], _SPECS[skill]["pass"]}:
                        for seat_number in holders:
                            seen_by_seat[seat_number] += 1
                            for key in _SPECS[skill]["keys"]:
                                _exclude(metrics[seat_number][key])
                    continue
                for seat_number in candidates:
                    state = metrics[seat_number]
                    count_metric, target_metric, kill_metric = (
                        state[key] for key in _SPECS[skill]["keys"]
                    )
                    action = source_event.get("action")
                    spec = _SPECS[skill]
                    if action in {spec["use"], spec["pass"], "unknown", None, "unavailable"}:
                        seen_by_seat[seat_number] += 1
                    if action in {None, "unknown"}:
                        _exclude(count_metric)
                        _exclude(target_metric)
                        _exclude(kill_metric)
                        continue
                    if action not in {spec["use"], spec["pass"]}:
                        # unavailable means there was no decision opportunity;
                        # learn/guard/check/etc. belong to a different skill.
                        continue

                    _record(count_metric, action == spec["use"])
                    if action == spec["pass"]:
                        continue

                    # Targets remain the player's intended choice, even when
                    # the published resolution later redirects or reflects it.
                    targets = source_event.get("targets")
                    target = targets[0] if isinstance(targets, list) and len(targets) == 1 else None
                    target_seat = seats.get(target) if type(target) is int else None
                    target_faction = faction_for_seat(target_seat) if target_seat else None
                    if target_faction in {"good", "werewolf"}:
                        _record(target_metric, target_faction == "werewolf")
                    else:
                        _exclude(target_metric)

                    if (source_event.get("blocked_by_game_end")
                            or source_event.get("invalidated")
                            or (number, phase, slot, seat_number, action) in puppet_disabled):
                        _record(kill_metric, False)
                        continue

                    if skill in {"witch_poison", "mechanical_poison"}:
                        projected_event = projected.get((number, slot, actor))
                        if (_poison_needs_exchange_resolution(source_event, round_)
                                and (not projected_event or not projected_event.get("resolved_targets"))):
                            _exclude(kill_metric)
                            continue
                        resolution_event = dict(source_event)
                        if projected_event:
                            # Keep the chosen target and action from source;
                            # only reuse the presentation's resolved target.
                            if projected_event.get("resolved_targets") is not None:
                                resolution_event["resolved_targets"] = projected_event["resolved_targets"]
                        victims, unresolved = _poison_resolution(resolution_event, round_, game)
                        if unresolved:
                            _exclude(kill_metric)
                            continue
                        victim_factions = [
                            faction_for_seat(seats[victim])
                            for victim in victims if victim in seats
                        ]
                        if len(victim_factions) != len(victims) or any(
                                faction not in {"good", "werewolf"} for faction in victim_factions):
                            _exclude(kill_metric)
                        else:
                            _record(kill_metric, "werewolf" in victim_factions)
                        continue

                    # The source contract treats an unblocked hunter shoot as
                    # a resolved death of its chosen target.
                    if target_faction in {"good", "werewolf"}:
                        _record(kill_metric, target_faction == "werewolf")
                    else:
                        _exclude(kill_metric)

    for skill, holders in skill_holders.items():
        for seat_number in holders:
            if seen_by_seat[seat_number] == 0:
                # A known skill-holder with no slot record is an unknown
                # appearance, not a zero-use appearance.
                for key in _SPECS[skill]["keys"]:
                    _exclude(metrics[seat_number][key])

    return {
        seat_number: {
            key: _metric_result(metric, game_id)
            for key, metric in seat_metrics.items()
        }
        for seat_number, seat_metrics in metrics.items()
    }

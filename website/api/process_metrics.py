"""Per-game observations for metrics derived from public snapshots."""

from __future__ import annotations

from typing import Any


NATIVE_SEER_ROLES = {"预言家", "通灵师"}


def _round_one(game: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in game.get("rounds", [])
            if isinstance(row, dict) and type(row.get("number")) is int and row["number"] == 1]


def _attack_observations(game: dict[str, Any], seats: list[int]) -> dict[int, bool | None]:
    events = [event for round_ in _round_one(game) for event in round_.get("night", [])
              if event.get("slot") == "wolf_attack"]
    if not events:
        return {seat: None for seat in seats}

    per_event: list[dict[int, bool | None]] = []
    for event in events:
        action = event.get("action")
        targets = event.get("targets")
        valid_targets = isinstance(targets, list) and all(type(target) is int for target in targets)

        if valid_targets and targets:
            if action == "attack":
                per_event.append({seat: seat in targets for seat in seats})
            else:
                # A recorded target proves a selection, but an unknown action
                # cannot establish that seats outside the list were not selected.
                per_event.append({seat: True if seat in targets else None for seat in seats})
        elif action == "forbidden" and valid_targets and not targets:
            per_event.append({seat: False for seat in seats})
        else:
            per_event.append({seat: None for seat in seats})

    result: dict[int, bool | None] = {}
    for seat in seats:
        known = {row[seat] for row in per_event if row[seat] is not None}
        result[seat] = next(iter(known)) if len(known) == 1 else None
    return result


def _night_death_observations(game: dict[str, Any], seats: list[int]) -> dict[int, bool | None]:
    living_rows = [row for row in ((game.get("rules_state") or {}).get("living") or [])
                   if isinstance(row, dict) and row.get("day") == 1]
    state = living_rows[0] if len(living_rows) == 1 else None
    state_targets = state.get("night_deaths") if state else None
    state_targets_valid = (isinstance(state_targets, list)
                           and all(type(target) is int for target in state_targets))
    state_positive = set(state_targets) if state_targets_valid else set()
    state_complete = bool(state and state.get("night_deaths_complete") is True and state_targets_valid)

    events = [event for round_ in _round_one(game) for event in round_.get("day", [])
              if event.get("slot") == "night_deaths"]
    event_positive: set[int] = set()
    event_no_deaths = False
    if len(events) == 1:
        event = events[0]
        targets = event.get("targets")
        targets_valid = isinstance(targets, list) and all(type(target) is int for target in targets)
        if event.get("action") == "die" and targets_valid:
            event_positive = set(targets)
        elif event.get("action") in {"peaceful", "no_death"} and targets_valid and not targets:
            event_no_deaths = True

    positives = state_positive | event_positive
    complete_sources = []
    if state_complete:
        complete_sources.append(state_positive)
    if event_no_deaths:
        complete_sources.append(set())

    result: dict[int, bool | None] = {}
    for seat in seats:
        if any((seat in positives) != (seat in complete)
               for complete in complete_sources):
            result[seat] = None
        elif seat in positives:
            result[seat] = True
        elif complete_sources:
            result[seat] = False
        else:
            result[seat] = None
    return result


def election_badge(game: dict[str, Any], seat: int) -> bool | None:
    """Return whether a seat won a sheriff election, preserving unknown results."""
    from website.api.bluffs import _badge_result

    value, questions = _badge_result(game, seat)
    return value if not questions else None


def _first_day_exiles(game: dict[str, Any], seats: list[int]) -> dict[int, bool | None]:
    from website.api.bluffs import _final_exile

    target, known, questions = _final_exile(game, 1)
    if not known or questions:
        return {seat: None for seat in seats}
    return {seat: target is not None and seat == target for seat in seats}


def _seer_campaign_observations(game: dict[str, Any], seats: list[int]) -> dict[int, bool | None]:
    # Use analytics' established first-registration ordering contract.
    from website.api.analytics import _first_registration

    first = _first_registration(game.get("voting") or {})
    result: dict[int, bool | None] = {}
    for seat in seats:
        if first is None:
            result[seat] = None
            continue
        on_police = first.get("on_police")
        off_police = first.get("off_police")
        on = isinstance(on_police, list) and seat in on_police
        off = isinstance(off_police, list) and seat in off_police
        result[seat] = True if on and not off else False if off and not on else None
    return result


def process_observations(game: dict[str, Any]) -> dict[int, dict[str, bool | None]]:
    """Return definite per-seat observations for the metrics supported here.

    Each value is a per-game yes/no observation. ``None`` means the public
    snapshot does not establish either result.
    """
    seat_rows = [row for row in (game.get("seats") or [])
                 if isinstance(row, dict) and type(row.get("seat")) is int]
    seat_numbers = [row["seat"] for row in seat_rows]
    observations: dict[int, dict[str, bool | None]] = {
        seat: {} for seat in seat_numbers
    }

    for key, values in (
        ("first_night_targeted", _attack_observations(game, seat_numbers)),
        ("first_night_death", _night_death_observations(game, seat_numbers)),
        ("first_day_exiled", _first_day_exiles(game, seat_numbers)),
    ):
        for seat, value in values.items():
            observations[seat][key] = value

    seer_seats = [row["seat"] for row in seat_rows if row.get("role") in NATIVE_SEER_ROLES]
    if seer_seats:
        campaigns = _seer_campaign_observations(game, seer_seats)
        for seat in seer_seats:
            observations[seat].update({
                "seer_campaign_count": campaigns[seat],
                "seer_badge_count": election_badge(game, seat),
                "seer_first_day_exiled": observations[seat]["first_day_exiled"],
            })

    return observations

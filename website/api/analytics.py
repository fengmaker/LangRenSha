"""Pure analytics over immutable public game snapshots."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from typing import Any
from scripts.role_constraints import puppet_target


PHASES = {"all", "regular", "finals_week"}
DECIDED_WINNERS = {"good", "werewolf"}
SEER_ROLE = "预言家"
MEDIUM_ROLE = "通灵师"
MIXED_BLOOD_ROLE = "混血儿"
SELF_EXPLOSION_ACTIONS = {"self_destruct"}
PLAYER_RANKING_KEYS = (
    "points", "appearances", "attendance", "total_win_rate", "wins", "losses",
    "werewolf_win_rate", "good_win_rate", "sheriff_registration_rate",
    "seer_follow_rate", "sheriff_seer_vote_rate",
    "good_wins", "wolf_vote_rate", "good_sheriff_registration_rate",
    "werewolf_appearances", "werewolf_wins", "werewolf_draw_rate",
    "werewolf_self_explosion_rate", "werewolf_sheriff_registration_rate",
    "bluff_count", "bluff_rate", "bluff_success_rate",
)


def scope_games(games: list[dict[str, Any]], season: str | list[str], phase: str = "all") -> list[dict[str, Any]]:
    """Select and chronologically order the requested season(s)/phase snapshots."""
    if phase not in PHASES:
        raise ValueError(f"unsupported phase: {phase}")
    seasons = {season} if isinstance(season, str) else set(season)
    selected = [game for game in games
                if game.get("season") in seasons and (phase == "all" or game.get("phase") == phase)]
    return sorted(selected, key=_game_sort_key)


def _game_sort_key(game: dict[str, Any]) -> tuple[Any, ...]:
    number = game.get("game_number")
    return (str(game.get("date") or ""), number is None, number if number is not None else 0,
            str(game.get("id") or ""))


def _seat_person_id(seat: dict[str, Any]) -> str | None:
    value = seat.get("person_id", seat.get("id"))
    return str(value) if value is not None else None


def _role(seat: dict[str, Any]) -> str:
    return seat.get("role") or "身份未知"


def _effective_faction_detail(game: dict[str, Any], seat: dict[str, Any]) -> tuple[str | None, bool]:
    """Resolve a recorded puppet's victory faction or a missing mixed-blood side.

    The source snapshot remains untouched. An explicit puppet follows wolves;
    otherwise a recorded faction is authoritative.
    a missing mixed-blood faction is inferred only from one unique `choose`
    event and a known exemplar faction, with a recorded alignment event used as
    a consistency check.
    """
    faction = seat.get("faction")
    if (puppet := puppet_target(game)) is not None and seat.get('seat') == puppet:
        return 'werewolf', faction != 'werewolf'
    if faction is not None or seat.get("role") != MIXED_BLOOD_ROLE:
        return faction, False

    seat_number = seat.get("seat")
    choices = []
    alignments = set()
    for round_ in game.get("rounds", []):
        for part in ("night", "day"):
            for event in round_.get(part, []):
                if event.get("actor") != seat_number:
                    continue
                if event.get("slot") == "mixed_blood_model" and event.get("action") == "choose":
                    targets = event.get("targets") or []
                    if len(targets) == 1:
                        choices.append(targets[0])
                elif event.get("slot") == "mixed_blood_alignment":
                    action = event.get("action")
                    if action == "good":
                        alignments.add("good")
                    elif action == "wolf":
                        alignments.add("werewolf")
    if not choices or len(set(choices)) != 1 or len(alignments) > 1:
        return None, False
    exemplar = next((item for item in game.get("seats", []) if item.get("seat") == choices[0]), None)
    exemplar_faction = exemplar.get("faction") if exemplar else None
    if exemplar_faction not in DECIDED_WINNERS:
        return None, False
    if alignments and exemplar_faction not in alignments:
        return None, False
    return exemplar_faction, True


def effective_faction(game: dict[str, Any], seat: dict[str, Any]) -> str | None:
    """Return the effective personal victory faction without mutating a snapshot."""
    return _effective_faction_detail(game, seat)[0]


def _unique_information_seat(seats: list[dict[str, Any]]) -> int | None:
    """Return the sole seer/medium seat; ambiguous or absent records stay unknown."""
    matches = [seat.get("seat") for seat in _information_seats(seats)]
    return matches[0] if len(matches) == 1 else None


def _information_seats(seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [seat for seat in seats if seat.get("role") in (SEER_ROLE, MEDIUM_ROLE)]


def _has_unknown_role(seats: list[dict[str, Any]]) -> bool:
    return any(seat.get("role") is None for seat in seats)


def _candidate_coverage(games: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Count missing candidate pools that are potentially in-scope.

    Returns applicable missing pools, same-round cast-vote evidence, and
    known non-applicable pools (the game has no seer/medium and no unknown role).
    """
    missing = evidence = not_applicable = 0
    for game in games:
        seats = game.get("seats", [])
        information = _information_seats(seats)
        information_seat = _unique_information_seat(seats)
        for ballot in (game.get("voting") or {}).get("ballots", []):
            if ballot.get("kind") != "sheriff" or ballot.get("candidates") is not None:
                continue
            if not information and not _has_unknown_role(seats):
                not_applicable += 1
                continue
            missing += 1
            if information_seat is not None and any(
                    vote.get("state") == "cast" and vote.get("target") == information_seat
                    for vote in ballot.get("votes", [])):
                evidence += 1
    return missing, evidence, not_applicable


def _metric_result(acc: dict[str, Any]) -> dict[str, Any]:
    denominator = acc["denominator"]
    return {
        "numerator": acc["numerator"],
        "denominator": denominator,
        "rate": acc["numerator"] / denominator if denominator else None,
        "excluded": acc["excluded"],
        "game_ids": list(dict.fromkeys(acc["game_ids"])),
        "samples": [
            {"game_id": game_id, **counts}
            for game_id, counts in acc["samples_by_game"].items()
        ],
    }


def _new_metric() -> dict[str, Any]:
    return {"numerator": 0, "denominator": 0, "excluded": 0, "game_ids": [], "samples_by_game": {}}


def _add_denominator(metric: dict[str, Any], game_id: str, *, success: bool = False) -> None:
    metric["denominator"] += 1
    metric["numerator"] += int(success)
    metric["game_ids"].append(game_id)
    counts = metric["samples_by_game"].setdefault(game_id, {"positive": 0, "negative": 0})
    counts["positive" if success else "negative"] += 1


def _add_excluded(metric: dict[str, Any]) -> None:
    metric["excluded"] += 1


def _rank_values(values: dict[str, int | Fraction], *, descending: bool = True) -> dict[str, dict[str, Any]]:
    """Assign competition ranks, grouping exact values and leaving ties at the same rank."""
    groups: dict[int | Fraction, list[str]] = defaultdict(list)
    for player_id, value in values.items():
        groups[value].append(player_id)

    result: dict[str, dict[str, Any]] = {}
    position = 1
    total = len(values)
    for value in sorted(groups, reverse=descending):
        player_ids = groups[value]
        ranking = {"rank": position, "total": total, "tied": len(player_ids) > 1}
        for player_id in player_ids:
            result[player_id] = ranking.copy()
        position += len(player_ids)
    return result


def _player_rank_value(acc: dict[str, Any], key: str) -> tuple[int | Fraction | None, int]:
    """Return an exact ranking value and its sample count for one profile metric."""
    known_results = acc["wins"] + acc["losses"]
    if key == "points":
        return (acc["points_half"], known_results) if known_results else (None, 0)
    if key == "wins":
        return (acc["wins"], known_results) if known_results else (None, 0)
    if key == "losses":
        return (acc["losses"], known_results) if known_results else (None, 0)
    if key == "appearances":
        appearances = acc["appearances"]
        return (appearances, appearances) if appearances else (None, 0)
    if key == "attendance":
        if acc["scope_games"] <= 0 or acc["appearances"] <= 0:
            return None, 0
        return Fraction(acc["appearances"], acc["scope_games"]), acc["scope_games"]
    if key == "werewolf_appearances":
        known_factions = acc["werewolf_draw"]["denominator"]
        return (acc["werewolf_appearances"], known_factions) if known_factions else (None, 0)
    if key in {"good_wins", "werewolf_wins"}:
        metric = acc["faction_win_rates"]["good" if key == "good_wins" else "werewolf"]
        return (metric["numerator"], metric["denominator"]) if metric["denominator"] else (None, 0)
    if key in {"bluff_count", "bluff_rate", "bluff_success_rate"}:
        review = acc.get("bluffs")
        if review is None:
            return None, 0
        if key == "bluff_count":
            return ((review["bluff_count"], review["bluff_rate"]["denominator"])
                    if review["bluff_count_complete"] else (None, 0))
        metric = review[key]
        denominator = metric["denominator"]
        return (Fraction(metric["numerator"], denominator), denominator) if denominator else (None, 0)

    metric_sources = {
        "total_win_rate": acc["total_win_rate"],
        "werewolf_win_rate": acc["faction_win_rates"]["werewolf"],
        "good_win_rate": acc["faction_win_rates"]["good"],
        "sheriff_registration_rate": acc["registration"],
        "seer_follow_rate": acc["follow"],
        "sheriff_seer_vote_rate": acc["sheriff_seer"],
        "wolf_vote_rate": acc["wolf_vote"],
        "good_sheriff_registration_rate": acc["good_registration"],
        "werewolf_draw_rate": acc["werewolf_draw"],
        "werewolf_self_explosion_rate": acc["werewolf_self_explosion"],
        "werewolf_sheriff_registration_rate": acc["werewolf_registration"],
    }
    metric = metric_sources[key]
    denominator = metric["denominator"]
    if denominator <= 0:
        return None, 0
    return Fraction(metric["numerator"], denominator), denominator


def _ranked_order(values: dict[str, int | Fraction], players: dict[str, dict[str, Any]],
                  *, descending: bool = True) -> list[str]:
    """Order a ranked cohort by value, then stable name and ID tie-breakers."""
    return sorted(values, key=lambda player_id: (
        -values[player_id] if descending else values[player_id],
        str(players[player_id]["name"]).casefold(), str(players[player_id]["name"]), player_id,
    ))


def _board_value(value: int | Fraction, *, points: bool = False) -> int | float:
    if points:
        return value / 2
    return float(value) if isinstance(value, Fraction) else value


def _player_rankings(
    players: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, dict[str, Any] | None]], dict[str, list[dict[str, Any]]]]:
    """Build player ranks and ordered boards from one already accumulated scope."""
    values: dict[str, dict[str, int | Fraction]] = {key: {} for key in PLAYER_RANKING_KEYS}
    samples: dict[str, dict[str, int]] = {key: {} for key in PLAYER_RANKING_KEYS}
    for player_id, acc in players.items():
        for key in PLAYER_RANKING_KEYS:
            value, sample_count = _player_rank_value(acc, key)
            if value is not None:
                values[key][player_id] = value
                samples[key][player_id] = sample_count

    rankings: dict[str, dict[str, dict[str, Any] | None]] = {
        player_id: {key: None for key in PLAYER_RANKING_KEYS} for player_id in players
    }
    boards: dict[str, list[dict[str, Any]]] = {}
    vote_metric_sources = {
        "sheriff_registration_rate": "registration",
        "seer_follow_rate": "follow",
        "sheriff_seer_vote_rate": "sheriff_seer",
        "wolf_vote_rate": "wolf_vote",
    }
    for key, cohort in values.items():
        descending = key != "losses"
        ranked = _rank_values(cohort, descending=descending)
        for player_id, ranking in ranked.items():
            rankings[player_id][key] = ranking
        board_rows = []
        for player_id in _ranked_order(cohort, players, descending=descending):
            row = {
                "id": player_id, "name": players[player_id]["name"],
                "rank": ranked[player_id]["rank"], "tied": ranked[player_id]["tied"],
                "value": _board_value(cohort[player_id], points=(key == "points")),
                "sample_count": samples[key][player_id],
                "appearances": players[player_id]["appearances"],
            }
            metric_source = vote_metric_sources.get(key)
            if metric_source is not None:
                metric = players[player_id][metric_source]
                row["effective_game_count"] = len(set(metric["game_ids"]))
            board_rows.append(row)
        boards[key] = board_rows
    return rankings, boards


def _role_rankings(
    players: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, dict[str, Any] | None]], dict[str, list[dict[str, Any]]]]:
    """Build role ranks and boards within each role's decided-result cohort."""
    role_cohorts: dict[str, dict[str, Fraction]] = defaultdict(dict)
    for player_id, acc in players.items():
        for role, role_acc in acc["roles"].items():
            metric = role_acc["win_loss_metric"]
            if metric["denominator"] > 0:
                role_cohorts[role][player_id] = Fraction(metric["numerator"], metric["denominator"])

    rankings: dict[str, dict[str, dict[str, Any] | None]] = {
        player_id: {role: None for role in acc["roles"]}
        for player_id, acc in players.items()
    }
    boards: dict[str, list[dict[str, Any]]] = {}
    for role, cohort in role_cohorts.items():
        ranked = _rank_values(cohort)
        for player_id, ranking in ranked.items():
            rankings[player_id][role] = ranking
        boards[role] = [{
            "id": player_id, "name": players[player_id]["name"],
            "rank": ranked[player_id]["rank"], "tied": ranked[player_id]["tied"],
            "value": float(cohort[player_id]),
            "sample_count": players[player_id]["roles"][role]["win_loss_metric"]["denominator"],
            "appearances": players[player_id]["roles"][role]["appearances"],
        } for player_id in _ranked_order(cohort, players)]
    return rankings, boards


def _board_identity(game: dict[str, Any]) -> tuple[tuple[str, str], str | None, str | None]:
    """Return a stable board key, grouping by code or falling back to name."""
    board = game.get("board") or {}
    raw_code = board.get("code")
    raw_name = board.get("name")
    code = str(raw_code).strip() if raw_code is not None and str(raw_code).strip() else None
    name = str(raw_name).strip() if raw_name is not None and str(raw_name).strip() else None
    if code is not None:
        return ("code", code), code, name
    return ("name", name or ""), None, name


def _board_rankings(
    players: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[tuple[str, str], dict[str, Any] | None]],
    dict[tuple[str, str], list[dict[str, Any]]],
]:
    """Rank each board's players by win rate using decided results only."""
    board_cohorts: dict[tuple[str, str], dict[str, Fraction]] = defaultdict(dict)
    for player_id, acc in players.items():
        for board_key, board_acc in acc["boards"].items():
            metric = board_acc["metric"]
            if metric["denominator"] > 0:
                board_cohorts[board_key][player_id] = Fraction(metric["numerator"], metric["denominator"])

    rankings: dict[str, dict[tuple[str, str], dict[str, Any] | None]] = {
        player_id: {board_key: None for board_key in acc["boards"]}
        for player_id, acc in players.items()
    }
    ranking_boards: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for board_key, cohort in board_cohorts.items():
        ranked = _rank_values(cohort)
        for player_id, ranking in ranked.items():
            rankings[player_id][board_key] = ranking
        ranking_boards[board_key] = [{
            "id": player_id, "name": players[player_id]["name"],
            "rank": ranked[player_id]["rank"], "tied": ranked[player_id]["tied"],
            "value": float(cohort[player_id]),
            "sample_count": players[player_id]["boards"][board_key]["metric"]["denominator"],
            "appearances": players[player_id]["boards"][board_key]["appearances"],
        } for player_id in _ranked_order(cohort, players)]
    return rankings, ranking_boards


def _new_player_acc(seat: dict[str, Any], game_count: int) -> dict[str, Any]:
    return {
        "id": _seat_person_id(seat), "name": seat.get("name", ""),
        "appearances": 0, "wins": 0, "losses": 0, "pending_games": 0,
        "werewolf_appearances": 0,
        "points_half": 0, "pending_game_ids": [],
        "total_win_rate": _new_metric(),
        "roles": defaultdict(lambda: {"appearances": 0, "wins": 0, "losses": 0, "pending_games": 0,
                                       "game_ids": [], "pending_game_ids": [],
                                       "win_loss_metric": _new_metric()}),
        "faction_win_rates": {"werewolf": _new_metric(), "good": _new_metric()},
        "boards": {},
        "registration": _new_metric(), "follow": _new_metric(), "sheriff_seer": _new_metric(),
        "wolf_vote": _new_metric(), "werewolf_draw": _new_metric(),
        "werewolf_self_explosion": _new_metric(), "werewolf_registration": _new_metric(),
        "good_registration": _new_metric(),
        "exile_abstentions": 0,
        "scope_games": game_count,
    }


def _result(faction: str | None, winner: str | None) -> str:
    if faction not in DECIDED_WINNERS or winner not in DECIDED_WINNERS:
        return "unknown"
    return "win" if faction == winner else "loss"


def _first_registration(voting: dict[str, Any]) -> dict[str, Any] | None:
    registrations = voting.get("registrations") or []
    if not registrations:
        return None
    # The first record in the source order is the original first registration.
    # day/id are tie-breakers for stable snapshots whose records are unsorted.
    return min(registrations, key=lambda row: (row.get("day", 2**31), row.get("id", "")))


def _off_police_metric(registration: dict[str, Any]) -> dict[str, Any]:
    return _metric_result({
        **registration,
        "numerator": registration["denominator"] - registration["numerator"],
        "samples_by_game": {game_id: {"positive": counts["negative"], "negative": counts["positive"]}
                            for game_id, counts in registration["samples_by_game"].items()},
    })


def _self_explosion_actors(game: dict[str, Any]) -> set[int]:
    """Return seats with an explicitly recorded self-explosion action."""
    actors: set[int] = set()
    for round_ in game.get("rounds", []):
        for part in ("night", "day"):
            for event in round_.get(part, []):
                actor = event.get("actor")
                if event.get("action") in SELF_EXPLOSION_ACTIONS and actor is not None:
                    actors.add(actor)
    return actors


def _known_information_candidate(game: dict[str, Any], ballot: dict[str, Any]) -> tuple[int | None, bool]:
    """Return the unique information-role seat and whether it is a candidate.

    An explicit candidate list is authoritative. If it is absent, a same-round
    recorded vote to the sole information-role seat is the only permitted
    eligibility evidence. A missing/ambiguous identity is never guessed.
    """
    information_seat = _unique_information_seat(game.get("seats", []))
    if information_seat is None:
        return None, False
    candidates = ballot.get("candidates")
    if candidates is not None:
        return information_seat, information_seat in candidates
    voted_for_role = any(vote.get("state") == "cast" and vote.get("target") == information_seat
                         for vote in ballot.get("votes", []))
    return information_seat, voted_for_role


def _accumulate(games: list[dict[str, Any]], season: str | list[str], phase: str,
                *, include_boards: bool = False) -> tuple[dict[str, dict[str, Any]], list[str]]:
    scoped = scope_games(games, season, phase)
    game_count = len(scoped)
    players: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    for game in scoped:
        game_id = str(game.get("id", ""))
        seats = game.get("seats") or []
        information_roles = _information_seats(seats)
        game_players: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        if include_boards:
            board_key, board_code, board_name = _board_identity(game)
        explosion_actors = _self_explosion_actors(game)
        first = _first_registration(game.get("voting") or {})

        # Outcome, role, and point ledger are accumulated once per appearance.
        for seat in seats:
            player_id = _seat_person_id(seat)
            if player_id is None:
                continue
            acc = players.setdefault(player_id, _new_player_acc(seat, game_count))
            game_players[player_id] = (seat, acc)
            acc["appearances"] += 1
            role_name = _role(seat)
            role_acc = acc["roles"][role_name]
            role_acc["appearances"] += 1
            board_acc = None
            if include_boards:
                board_acc = acc["boards"].get(board_key)
                if board_acc is None:
                    board_acc = {
                        "code": board_code, "name": board_name, "appearances": 0,
                        "wins": 0, "losses": 0, "pending_games": 0, "metric": _new_metric(),
                    }
                    acc["boards"][board_key] = board_acc
                elif board_acc["name"] is None and board_name is not None:
                    board_acc["name"] = board_name
                board_acc["appearances"] += 1
            faction, _ = _effective_faction_detail(game, seat)
            if faction in DECIDED_WINNERS:
                _add_denominator(acc["werewolf_draw"], game_id, success=(faction == "werewolf"))
                if faction == "werewolf":
                    acc["werewolf_appearances"] += 1
                    _add_denominator(acc["werewolf_self_explosion"], game_id,
                                     success=(seat.get("seat") in explosion_actors))
            else:
                _add_excluded(acc["werewolf_draw"])
                _add_excluded(acc["werewolf_self_explosion"])
            result = _result(faction, game.get("winner"))
            if result == "win":
                acc["wins"] += 1
                role_acc["wins"] += 1
                role_acc["game_ids"].append(game_id)
                _add_denominator(acc["total_win_rate"], game_id, success=True)
                _add_denominator(role_acc["win_loss_metric"], game_id, success=True)
                if board_acc is not None:
                    board_acc["wins"] += 1
                    _add_denominator(board_acc["metric"], game_id, success=True)
                acc["points_half"] += 3 if faction == "werewolf" else 2
            elif result == "loss":
                acc["losses"] += 1
                role_acc["losses"] += 1
                role_acc["game_ids"].append(game_id)
                _add_denominator(acc["total_win_rate"], game_id)
                _add_denominator(role_acc["win_loss_metric"], game_id)
                if board_acc is not None:
                    board_acc["losses"] += 1
                    _add_denominator(board_acc["metric"], game_id)
                acc["points_half"] -= 2
            else:
                acc["pending_games"] += 1
                role_acc["pending_games"] += 1
                acc["pending_game_ids"].append(game_id)
                role_acc["pending_game_ids"].append(game_id)
                _add_excluded(acc["total_win_rate"])
                _add_excluded(role_acc["win_loss_metric"])
                if board_acc is not None:
                    board_acc["pending_games"] += 1
                    _add_excluded(board_acc["metric"])

            if faction is None:
                for metric in acc["faction_win_rates"].values():
                    _add_excluded(metric)
            elif faction in acc["faction_win_rates"]:
                if game.get("winner") not in DECIDED_WINNERS:
                    _add_excluded(acc["faction_win_rates"][faction])
                else:
                    _add_denominator(acc["faction_win_rates"][faction], game_id,
                                     success=(game.get("winner") == faction))

        # Attendance and first sheriff registration have explicit denominators.
        on_police = set(first.get("on_police") or []) if first else set()
        off_police = set(first.get("off_police") or []) if first else set()
        for seat, acc in game_players.values():
            seat_number = seat.get("seat")
            faction = effective_faction(game, seat)
            metrics = [acc["registration"]]
            if faction in DECIDED_WINNERS:
                metrics.append(acc[f"{faction}_registration"])
            else:
                _add_excluded(acc["good_registration"])
                _add_excluded(acc["werewolf_registration"])
            for metric in metrics:
                if seat_number in on_police:
                    _add_denominator(metric, game_id, success=True)
                elif seat_number in off_police:
                    _add_denominator(metric, game_id)
                else:
                    _add_excluded(metric)

        for ballot in (game.get("voting") or {}).get("ballots", []):
            kind = ballot.get("kind")
            eligible_raw = ballot.get("eligible_voters")
            eligible = set(eligible_raw) if isinstance(eligible_raw, list) else None
            vote_by_seat = {vote.get("voter"): vote for vote in ballot.get("votes", [])
                            if vote.get("voter") is not None}

            if kind == "exile":
                information_seat = information_roles[0].get("seat") if len(information_roles) == 1 else None
                information_vote = vote_by_seat.get(information_seat) if information_seat is not None else None
                for player_id, (seat, acc) in game_players.items():
                    voter = seat.get("seat")
                    faction, role = _effective_faction_detail(game, seat)[0], seat.get("role")
                    vote = vote_by_seat.get(voter)
                    if (faction == "good" and vote is not None and vote.get("state") == "abstained"
                            and (eligible is None or voter in eligible)):
                        acc["exile_abstentions"] += 1
                    if eligible is None or voter not in eligible:
                        continue
                    if faction == "good":
                        if vote is None:
                            _add_excluded(acc["wolf_vote"])
                        elif vote.get("state") == "abstained":
                            _add_denominator(acc["wolf_vote"], game_id)
                        elif vote.get("state") == "cast" and vote.get("target") is not None:
                            target_seat = next((item for item in seats
                                                if item.get("seat") == vote.get("target")), None)
                            target_faction = (_effective_faction_detail(game, target_seat)[0]
                                              if target_seat is not None else None)
                            if target_faction in DECIDED_WINNERS:
                                _add_denominator(acc["wolf_vote"], game_id,
                                                 success=(target_faction == "werewolf"))
                            else:
                                _add_excluded(acc["wolf_vote"])
                        else:
                            _add_excluded(acc["wolf_vote"])
                    elif faction is None:
                        _add_excluded(acc["wolf_vote"])

                    if faction not in ("good", None):
                        continue
                    if faction == "good" and role in (SEER_ROLE, MEDIUM_ROLE):
                        continue
                    if information_seat is None:
                        if information_roles or _has_unknown_role(seats):
                            _add_excluded(acc["follow"])
                        continue
                    if information_seat not in eligible:
                        continue
                    if faction is None or role is None:
                        _add_excluded(acc["follow"])
                        continue
                    if information_vote is None:
                        _add_excluded(acc["follow"])
                        continue
                    # The reference information role explicitly abstained, so
                    # this ballot round has no stance to follow.
                    if information_vote.get("state") == "abstained":
                        continue
                    if information_vote.get("state") != "cast" or information_vote.get("target") is None:
                        _add_excluded(acc["follow"])
                        continue
                    vote = vote_by_seat.get(voter)
                    if vote is None:
                        _add_excluded(acc["follow"])
                    else:
                        _add_denominator(acc["follow"], game_id,
                                         success=(vote.get("state") == "cast" and
                                                  vote.get("target") == information_vote.get("target")))

            elif kind == "sheriff":
                information_seat, information_is_candidate = _known_information_candidate(game, ballot)
                # A known candidate pool without the real seer means the seer
                # withdrew or was never eligible; this is outside the metric.
                candidate_list_known = ballot.get("candidates") is not None
                for player_id, (seat, acc) in game_players.items():
                    voter = seat.get("seat")
                    faction, role = _effective_faction_detail(game, seat)[0], seat.get("role")
                    if faction != "good" or role == SEER_ROLE:
                        continue
                    if eligible is not None and voter not in eligible:
                        continue
                    if eligible is None:
                        # Without a voter list, eligibility is not established;
                        # do not turn that uncertainty into a failed vote.
                        continue
                    if information_seat is None:
                        possible_info = {item.get("seat") for item in seats
                                         if item.get("role") in (SEER_ROLE, MEDIUM_ROLE)}
                        unknown_role_seats = {item.get("seat") for item in seats if item.get("role") is None}
                        if (information_roles or _has_unknown_role(seats)) and (
                                not candidate_list_known
                                or possible_info.intersection(ballot.get("candidates") or [])
                                or unknown_role_seats.intersection(ballot.get("candidates") or [])):
                            _add_excluded(acc["sheriff_seer"])
                        continue
                    if candidate_list_known and not information_is_candidate:
                        continue
                    if not candidate_list_known and not information_is_candidate:
                        _add_excluded(acc["sheriff_seer"])
                        continue
                    if role is None:
                        _add_excluded(acc["sheriff_seer"])
                        continue
                    vote = vote_by_seat.get(voter)
                    if vote is None:
                        _add_excluded(acc["sheriff_seer"])
                    else:
                        _add_denominator(acc["sheriff_seer"], game_id,
                                         success=(vote.get("state") == "cast" and
                                                  vote.get("target") == information_seat))

    # Data-quality notes that apply only where the player participates.
    has_unknown_faction = any(
        _effective_faction_detail(game, seat)[0] is None
        for game in scoped for seat in (game.get("seats") or [])
    )
    has_inferred_faction = any(
        _effective_faction_detail(game, seat)[1]
        for game in scoped for seat in (game.get("seats") or [])
    )
    if has_unknown_faction:
        notes.append("无法由唯一榜样及一致阵营记录确定的个人阵营按待定计，不作为败场或零分。")
    if has_inferred_faction:
        notes.append("明确被选为傀儡的玩家跟随狼人阵营；混血儿阵营缺失时按唯一明确榜样及一致的阵营说明推导。")
    notes.extend(_methodology_notes(scoped))
    return players, notes


def _methodology_notes(games: list[dict[str, Any]]) -> list[str]:
    unknown_candidates, candidate_evidence, not_applicable = _candidate_coverage(games)
    unresolved = unknown_candidates - candidate_evidence
    notes = [
        "胜负依据每位玩家的个人胜利阵营与整局胜方；混血按其个人胜利阵营计分。",
        "整季榜累计全部正式对局积分；狼人胜 +1.5，好人胜 +1，个人败 -1。决赛周冠军榜只累计决赛周对局。",
        "站边率只计算放逐票中好人且身份不是预言家或通灵师，并且双方同轮都有票权的轮次；按该局唯一的预言家或通灵师的明确投向比较，弃票算失败，缺失投票记录列为排除。",
        "警徽票率只计算好人（预言家本人除外）有票权且该局唯一的预言家或通灵师是合法候选的轮次；PK 和技能复投均计入，明确弃票算失败。",
        "版型没有预言家或通灵师时不适用这两类比例；身份未记录或信息神不唯一时无法判定，符合票权条件的样本列为排除。",
        "候选名单缺失时，仅用同轮实际投向该局唯一预言家或通灵师的选票作为其可参选证据；没有该证据的轮次按缺失排除，每位玩家只在其为好人且有票权时增加排除数。",
        "每项比例附带对应对局列表，方便回查分母；无法判定的战绩保留为待定，不按败场或零分处理。",
        "混血儿阵营缺失时依据本局唯一榜样的个人胜利阵营推导；已记录的阵营说明必须一致。",
        "投狼率计算有票权的好人放逐票，包含预言家和通灵师；PK及技能复投逐轮计入，明确弃票算失败，缺失选票及目标阵营未知时排除。放逐弃票次数只计好人放逐票中的明确弃票，包括规则默认弃票。",
        "拿狼率以已知个人阵营出场为分母，未知阵营排除；狼人自爆率只按明确的主动自爆事件计数并按选手每局去重；好人、狼人上警率和警下率按每局首次报名及已知警上/警下名单统计，阵营或名单未知时排除。",
    ]
    if unknown_candidates or not_applicable:
        notes.append(
            f"本筛选范围有 {unknown_candidates} 轮适用对局的警徽候选名单缺失；{candidate_evidence} 轮有同轮投给唯一信息神的资格证据，"
            f"其余 {unresolved} 轮排除；另有 {not_applicable} 轮版型未配置预言家或通灵师，不适用。"
        )
    return notes


def _serialize_player(acc: dict[str, Any], games: list[dict[str, Any]], phase: str, notes: list[str],
                      attendance_games: list[dict[str, Any]] | None = None,
                      rankings: dict[str, dict[str, Any] | None] | None = None,
                      role_rankings: dict[str, dict[str, Any] | None] | None = None,
                      ranking_boards: dict[str, list[dict[str, Any]]] | None = None,
                      role_ranking_boards: dict[str, list[dict[str, Any]]] | None = None,
                      board_rankings: dict[tuple[str, str], dict[str, Any] | None] | None = None,
                      board_ranking_boards: dict[tuple[str, str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    player_id = acc["id"]
    appearances = acc["appearances"]
    attendance_games = attendance_games if attendance_games is not None else games
    attendance_appearances = sum(
        any(_seat_person_id(seat) == player_id for seat in game.get("seats", []))
        for game in attendance_games
    )
    metric_overall = _metric_result(acc["total_win_rate"])
    faction_metrics = {faction: _metric_result(metric)
                       for faction, metric in acc["faction_win_rates"].items()}

    roles = []
    for role, value in sorted(acc["roles"].items()):
        role_metric = _metric_result(value["win_loss_metric"])
        roles.append({
            "role": role, "appearances": value["appearances"], "wins": value["wins"],
            "losses": value["losses"], "pending_games": value["pending_games"],
            "win_rate": role_metric["rate"], "metric": role_metric,
            "ranking": (role_rankings or {}).get(role),
            "ranking_board": (role_ranking_boards or {}).get(role, []),
        })

    board_stats = []
    if board_rankings is not None:
        for board_key, board_acc in sorted(
                acc["boards"].items(),
                key=lambda item: (-item[1]["appearances"],
                                  str(item[1]["name"] or "").casefold(),
                                  str(item[1]["name"] or ""), str(item[1]["code"] or ""))):
            metric = _metric_result(board_acc["metric"])
            board_stats.append({
                "code": board_acc["code"], "name": board_acc["name"],
                "appearances": board_acc["appearances"], "wins": board_acc["wins"],
                "losses": board_acc["losses"], "pending_games": board_acc["pending_games"],
                "win_rate": metric["rate"], "metric": metric,
                "ranking": board_rankings.get(board_key),
                "ranking_board": (board_ranking_boards or {}).get(board_key, []),
            })

    cumulative_half_points = 0
    cumulative_pending = 0
    ledger = []
    player_games = [game for game in games if any(_seat_person_id(seat) == player_id for seat in game.get("seats", []))]
    for game in player_games:
        seat = next(seat for seat in game.get("seats", []) if _seat_person_id(seat) == player_id)
        game_phase = str(game.get("phase") or phase)
        faction, faction_inferred = _effective_faction_detail(game, seat)
        result = _result(faction, game.get("winner"))
        if result == "win":
            points_half = 3 if faction == "werewolf" else 2
            cumulative_half_points += points_half
            ledger_points = points_half / 2
        elif result == "loss":
            points_half = -2
            cumulative_half_points += points_half
            ledger_points = -1
        else:
            ledger_points = None
            cumulative_pending += 1
        ledger.append({
            "game_id": game.get("id"), "season": game.get("season"),
            "date": game.get("date"), "game_number": game.get("game_number"),
            "phase": game.get("phase"), "board_name": (game.get("board") or {}).get("name"),
            "role": seat.get("role"), "faction": faction, "faction_inferred": faction_inferred,
            "result": result,
            "points": ledger_points, "cumulative_points": cumulative_half_points / 2,
            "pending_count": cumulative_pending,
        })

    result = {
        "appearances": appearances,
        "scope_games": acc["scope_games"],
        "wins": acc["wins"], "losses": acc["losses"], "pending_games": acc["pending_games"],
        "points": acc["points_half"] / 2,
        "points_complete": acc["pending_games"] == 0,
        "attendance": {
            "numerator": attendance_appearances, "denominator": len(attendance_games),
            "rate": attendance_appearances / len(attendance_games) if attendance_games else None,
            "excluded": 0, "game_ids": [str(game.get("id", "")) for game in attendance_games],
            "samples": [{"game_id": game["id"], "positive": int(present), "negative": int(not present)}
                        for game in attendance_games
                        for present in [any(_seat_person_id(seat) == player_id for seat in game.get("seats", []))]],
        },
        "total_win_rate": metric_overall,
        "werewolf_win_rate": faction_metrics["werewolf"],
        "good_win_rate": faction_metrics["good"],
        "sheriff_registration_rate": _metric_result(acc["registration"]),
        "seer_follow_rate": _metric_result(acc["follow"]),
        "sheriff_seer_vote_rate": _metric_result(acc["sheriff_seer"]),
        "wolf_vote_rate": _metric_result(acc["wolf_vote"]),
        "exile_abstentions": acc["exile_abstentions"],
        "werewolf_appearances": acc["werewolf_appearances"],
        "werewolf_draw_rate": _metric_result(acc["werewolf_draw"]),
        "werewolf_self_explosion_rate": _metric_result(acc["werewolf_self_explosion"]),
        "werewolf_sheriff_registration_rate": _metric_result(acc["werewolf_registration"]),
        "good_sheriff_registration_rate": _metric_result(acc["good_registration"]),
        "good_off_police_rate": _off_police_metric(acc["good_registration"]),
        "werewolf_off_police_rate": _off_police_metric(acc["werewolf_registration"]),
        "roles": roles,
        "ledger": ledger,
        "notes": notes,
    }
    if rankings is not None:
        result["rankings"] = rankings
        result["ranking_boards"] = ranking_boards or {key: [] for key in PLAYER_RANKING_KEYS}
    if board_rankings is not None:
        result["boards"] = board_stats
    return result


def compute_player_stats(player_id: str, games: list[dict[str, Any]], *, season: str = "S22",
                         phase: str = "all", name: str | None = None,
                         seasons: list[str] | None = None,
                         minimum_appearances: int = 0,
                         bluff_stats: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compute one player's metrics and scoring ledger across selected seasons.

    `phase` is accepted for API compatibility; player analytics always describe
    the full selected scope, including attendance and the chronological cumulative ledger.
    `minimum_appearances` restricts ranking cohorts by total scope appearances only.
    """
    selected_seasons: str | list[str] = seasons if seasons is not None else season
    season_games = scope_games(games, selected_seasons, "all")
    players, notes = _accumulate(season_games, selected_seasons, "all", include_boards=True)
    if bluff_stats is not None:
        for pid, player_acc in players.items():
            player_acc["bluffs"] = bluff_stats.get(pid)
    player_id = str(player_id)
    if player_id not in players:
        acc = _new_player_acc({"person_id": player_id, "name": name or ""}, len(season_games))
    else:
        acc = players[player_id]
    ranking_players = {pid: player for pid, player in players.items()
                       if player["appearances"] >= minimum_appearances}
    rankings_by_player, ranking_boards = _player_rankings(ranking_players)
    role_rankings_by_player, role_ranking_boards = _role_rankings(ranking_players)
    board_rankings_by_player, board_ranking_boards = _board_rankings(ranking_players)
    ranking = rankings_by_player.get(
        player_id, {key: None for key in PLAYER_RANKING_KEYS},
    )
    role_ranking = role_rankings_by_player.get(player_id, {})
    board_ranking = board_rankings_by_player.get(player_id, {})
    result = _serialize_player(acc, season_games, "all", notes, attendance_games=season_games,
                               rankings=ranking, role_rankings=role_ranking,
                               ranking_boards=ranking_boards, role_ranking_boards=role_ranking_boards,
                               board_rankings=board_ranking, board_ranking_boards=board_ranking_boards)
    if bluff_stats is not None:
        result.update(bluff_stats.get(player_id, {}))
    return result


def compute_player_summaries(games: list[dict[str, Any]], *, season: str = "S22",
                             phase: str = "all") -> list[dict[str, Any]]:
    """Aggregate season-wide player cards from one in-memory game collection."""
    season_games = scope_games(games, season, "all")
    players, notes = _accumulate(season_games, season, "all")
    output = []
    for player_id, acc in players.items():
        stats = _serialize_player(acc, season_games, "all", notes, attendance_games=season_games)
        role_counts = [{"role": role, "count": value["appearances"]}
                       for role, value in sorted(acc["roles"].items())]
        output.append({"id": player_id, "name": acc["name"], "appearances": acc["appearances"],
                       "roles": role_counts, "stats": {
                           key: stats[key] for key in (
                               "wins", "losses", "pending_games", "points", "points_complete",
                               "total_win_rate", "werewolf_win_rate", "good_win_rate", "attendance",
                           )
                       }})
    return sorted(output, key=lambda item: (-item["appearances"], item["name"], item["id"]))


def build_leaderboard(games: list[dict[str, Any]], *, season: str = "S22",
                      phase: str = "all") -> list[dict[str, Any]]:
    """Build the season points board or the finals-week champion board.

    `regular` remains an alias for the all-season board for older callers.
    Non-scoring player metrics always describe the complete season.
    """
    if phase not in {"all", "regular", "finals_week"}:
        raise ValueError("leaderboard phase must be all or finals_week")
    season_games = scope_games(games, season, "all")
    scoring_phase = "finals_week" if phase == "finals_week" else "all"
    scoring_games = (scope_games(season_games, season, "finals_week")
                     if phase == "finals_week" else season_games)
    all_players, all_notes = _accumulate(season_games, season, "all")
    if scoring_phase == "all":
        scoring_players, scoring_notes = all_players, all_notes
    else:
        scoring_players, scoring_notes = _accumulate(scoring_games, season, scoring_phase)
    rows = []
    for player_id, scoring_acc in scoring_players.items():
        overall_acc = all_players[player_id]
        stats = _serialize_player(overall_acc, season_games, "all", all_notes,
                                  attendance_games=season_games)
        scoring_stats = (stats if scoring_phase == "all" else
                         _serialize_player(scoring_acc, scoring_games, scoring_phase,
                                           scoring_notes, attendance_games=season_games))
        rows.append({
            "id": player_id, "name": overall_acc["name"], "appearances": stats["appearances"],
            "wins": stats["wins"], "losses": stats["losses"],
            "pending_games": scoring_stats["pending_games"],
            "season_pending_games": stats["pending_games"],
            "points": scoring_stats["points"], "points_complete": scoring_stats["points_complete"],
            "_points_half": scoring_acc["points_half"],
            "scoring_appearances": scoring_stats["appearances"],
            "scoring_wins": scoring_stats["wins"], "scoring_losses": scoring_stats["losses"],
            "scoring_pending_games": scoring_stats["pending_games"],
            "total_win_rate": stats["total_win_rate"],
            "werewolf_win_rate": stats["werewolf_win_rate"],
            "good_win_rate": stats["good_win_rate"], "attendance": stats["attendance"],
            "sheriff_registration_rate": stats["sheriff_registration_rate"],
            "seer_follow_rate": stats["seer_follow_rate"],
            "sheriff_seer_vote_rate": stats["sheriff_seer_vote_rate"],
            "wolf_vote_rate": stats["wolf_vote_rate"],
            "exile_abstentions": stats["exile_abstentions"],
            "werewolf_appearances": stats["werewolf_appearances"],
            "werewolf_draw_rate": stats["werewolf_draw_rate"],
            "werewolf_self_explosion_rate": stats["werewolf_self_explosion_rate"],
            "werewolf_sheriff_registration_rate": stats["werewolf_sheriff_registration_rate"],
            "good_sheriff_registration_rate": stats["good_sheriff_registration_rate"],
            "good_off_police_rate": stats["good_off_police_rate"],
            "werewolf_off_police_rate": stats["werewolf_off_police_rate"],
        })
    rows.sort(key=lambda item: (-item["_points_half"], item["name"], item["id"]))
    last_points: int | None = None
    last_rank = 0
    for index, item in enumerate(rows, start=1):
        if item["_points_half"] != last_points:
            last_rank = index
            last_points = item["_points_half"]
        item["rank"] = last_rank
        item.pop("_points_half")
    return rows


def analytics_notes(games: list[dict[str, Any]], *, season: str = "S22", phase: str = "all") -> list[str]:
    """Return methodology notes for API responses in the requested scope."""
    scoped = scope_games(games, season, phase)
    notes = _methodology_notes(scoped)
    has_unknown = any(_effective_faction_detail(game, seat)[0] is None
                      for game in scoped for seat in game.get("seats", []))
    has_inferred = any(_effective_faction_detail(game, seat)[1]
                       for game in scoped for seat in game.get("seats", []))
    if has_unknown:
        notes.insert(0, "无法由唯一榜样及一致阵营记录确定的个人阵营按待定计，不作为败场或零分。")
    if has_inferred:
        notes.insert(0, "明确被选为傀儡的玩家跟随狼人阵营；混血儿阵营缺失时按唯一明确榜样及一致的阵营说明推导。")
    # The full S22 coverage audit is helpful context on the separately scoped
    # regular/finals boards as well as the all-season player view.
    if season == "S22" and phase != "all":
        full_season = [game for game in games if game.get("season") == season]
        missing, information_evidence, not_applicable = _candidate_coverage(full_season)
        notes.append(
            f"S22全季候选覆盖核查：{missing}轮适用对局的警徽候选名单缺失；{information_evidence}轮有同轮投向唯一信息神的资格证据，"
            f"其余 {missing - information_evidence} 轮排除；{not_applicable}轮版型未配置预言家或通灵师，不适用。"
        )
    return notes

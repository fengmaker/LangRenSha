"""Pure analytics over immutable public game snapshots."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


PHASES = {"all", "regular", "finals_week"}
DECIDED_WINNERS = {"good", "werewolf"}
SEER_ROLE = "预言家"
MEDIUM_ROLE = "通灵师"
MIXED_BLOOD_ROLE = "混血儿"
SELF_EXPLOSION_ACTIONS = {"self_destruct"}


def scope_games(games: list[dict[str, Any]], season: str, phase: str = "all") -> list[dict[str, Any]]:
    """Select and chronologically order the requested season/phase snapshots."""
    if phase not in PHASES:
        raise ValueError(f"unsupported phase: {phase}")
    selected = [game for game in games
                if game.get("season") == season and (phase == "all" or game.get("phase") == phase)]
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
    """Resolve only an explicitly missing mixed-blood faction from its exemplar.

    The source snapshot remains untouched. A recorded faction is authoritative;
    a missing mixed-blood faction is inferred only from one unique `choose`
    event and a known exemplar faction, with a recorded alignment event used as
    a consistency check.
    """
    faction = seat.get("faction")
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
    }


def _new_metric() -> dict[str, Any]:
    return {"numerator": 0, "denominator": 0, "excluded": 0, "game_ids": []}


def _add_denominator(metric: dict[str, Any], game_id: str, *, success: bool = False) -> None:
    metric["denominator"] += 1
    metric["numerator"] += int(success)
    metric["game_ids"].append(game_id)


def _add_excluded(metric: dict[str, Any]) -> None:
    metric["excluded"] += 1


def _new_player_acc(seat: dict[str, Any], game_count: int) -> dict[str, Any]:
    return {
        "id": _seat_person_id(seat), "name": seat.get("name", ""),
        "appearances": 0, "wins": 0, "losses": 0, "pending_games": 0,
        "werewolf_appearances": 0,
        "points_half": 0, "known_result_game_ids": [], "pending_game_ids": [],
        "roles": defaultdict(lambda: {"appearances": 0, "wins": 0, "losses": 0, "pending_games": 0,
                                       "game_ids": [], "pending_game_ids": []}),
        "registration": _new_metric(), "follow": _new_metric(), "sheriff_seer": _new_metric(),
        "wolf_vote": _new_metric(), "werewolf_draw": _new_metric(),
        "werewolf_self_explosion": _new_metric(), "werewolf_registration": _new_metric(),
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


def _accumulate(games: list[dict[str, Any]], season: str, phase: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    scoped = scope_games(games, season, phase)
    game_count = len(scoped)
    players: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    for game in scoped:
        game_id = str(game.get("id", ""))
        seats = game.get("seats") or []
        information_roles = _information_seats(seats)
        game_players: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
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
            faction, _ = _effective_faction_detail(game, seat)
            if faction in DECIDED_WINNERS:
                _add_denominator(acc["werewolf_draw"], game_id, success=(faction == "werewolf"))
                if faction == "werewolf":
                    acc["werewolf_appearances"] += 1
                    _add_denominator(acc["werewolf_self_explosion"], game_id,
                                     success=(seat.get("seat") in explosion_actors))
                    if first is not None:
                        on_police = set(first.get("on_police") or [])
                        off_police = set(first.get("off_police") or [])
                        if seat.get("seat") in on_police:
                            _add_denominator(acc["werewolf_registration"], game_id, success=True)
                        elif seat.get("seat") in off_police:
                            _add_denominator(acc["werewolf_registration"], game_id)
                        else:
                            _add_excluded(acc["werewolf_registration"])
                    else:
                        _add_excluded(acc["werewolf_registration"])
            else:
                _add_excluded(acc["werewolf_draw"])
                _add_excluded(acc["werewolf_self_explosion"])
                _add_excluded(acc["werewolf_registration"])
            result = _result(faction, game.get("winner"))
            if result == "win":
                acc["wins"] += 1
                role_acc["wins"] += 1
                acc["known_result_game_ids"].append(game_id)
                role_acc["game_ids"].append(game_id)
                acc["points_half"] += 3 if faction == "werewolf" else 2
            elif result == "loss":
                acc["losses"] += 1
                role_acc["losses"] += 1
                acc["known_result_game_ids"].append(game_id)
                role_acc["game_ids"].append(game_id)
                acc["points_half"] -= 2
            else:
                acc["pending_games"] += 1
                role_acc["pending_games"] += 1
                acc["pending_game_ids"].append(game_id)
                role_acc["pending_game_ids"].append(game_id)

        # Attendance and first sheriff registration have explicit denominators.
        if first is not None:
            on_police = set(first.get("on_police") or [])
            off_police = set(first.get("off_police") or [])
            for player_id, (seat, acc) in game_players.items():
                seat_number = seat.get("seat")
                if seat_number in on_police:
                    _add_denominator(acc["registration"], game_id, success=True)
                elif seat_number in off_police:
                    _add_denominator(acc["registration"], game_id)
                else:
                    _add_excluded(acc["registration"])
        else:
            for _, acc in game_players.values():
                _add_excluded(acc["registration"])

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
        notes.append("已登记的个人胜利阵营优先；缺失的混血儿阵营只按唯一明确榜样及一致的阵营说明推导。")
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
        "拿狼率以已知个人阵营出场为分母，未知阵营排除；狼人自爆率只按明确的主动自爆事件计数并按选手每局去重；狼人上警率按每局首次报名及已知警上/警下名单统计。",
    ]
    if unknown_candidates or not_applicable:
        notes.append(
            f"本筛选范围有 {unknown_candidates} 轮适用对局的警徽候选名单缺失；{candidate_evidence} 轮有同轮投给唯一信息神的资格证据，"
            f"其余 {unresolved} 轮排除；另有 {not_applicable} 轮版型未配置预言家或通灵师，不适用。"
        )
    return notes


def _serialize_player(acc: dict[str, Any], games: list[dict[str, Any]], phase: str, notes: list[str],
                      attendance_games: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    player_id = acc["id"]
    appearances = acc["appearances"]
    attendance_games = attendance_games if attendance_games is not None else games
    attendance_appearances = sum(
        any(_seat_person_id(seat) == player_id for seat in game.get("seats", []))
        for game in attendance_games
    )
    metric_overall = {
        "numerator": acc["wins"],
        "denominator": acc["wins"] + acc["losses"],
        "excluded": acc["pending_games"],
        "game_ids": list(dict.fromkeys(acc["known_result_game_ids"])),
    }
    metric_overall["rate"] = (metric_overall["numerator"] / metric_overall["denominator"]
                               if metric_overall["denominator"] else None)

    faction_metrics = {}
    faction_results = {"werewolf": [0, 0, 0, []], "good": [0, 0, 0, []]}
    for game in games:
        seat = next((item for item in game.get("seats", []) if _seat_person_id(item) == player_id), None)
        if seat is None:
            continue
        faction, _ = _effective_faction_detail(game, seat)
        winner = game.get("winner")
        if faction is None:
            for value in faction_results.values():
                value[2] += 1
            continue
        if faction not in faction_results:
            continue
        values = faction_results[faction]
        if winner not in DECIDED_WINNERS:
            values[2] += 1
        else:
            values[1] += 1
            values[0] += int(winner == faction)
            values[3].append(str(game.get("id", "")))
    for faction, (numerator, denominator, excluded, game_ids) in faction_results.items():
        faction_metrics[faction] = {
            "numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None,
            "excluded": excluded, "game_ids": list(dict.fromkeys(game_ids)),
        }

    roles = []
    for role, value in sorted(acc["roles"].items()):
        denominator = value["wins"] + value["losses"]
        roles.append({
            "role": role, "appearances": value["appearances"], "wins": value["wins"],
            "losses": value["losses"], "pending_games": value["pending_games"],
            "win_rate": value["wins"] / denominator if denominator else None,
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
            "game_id": game.get("id"), "date": game.get("date"), "game_number": game.get("game_number"),
            "phase": game.get("phase"), "board_name": (game.get("board") or {}).get("name"),
            "role": seat.get("role"), "faction": faction, "faction_inferred": faction_inferred,
            "result": result,
            "points": ledger_points, "cumulative_points": cumulative_half_points / 2,
            "pending_count": cumulative_pending,
        })

    return {
        "appearances": appearances,
        "scope_games": acc["scope_games"],
        "wins": acc["wins"], "losses": acc["losses"], "pending_games": acc["pending_games"],
        "points": acc["points_half"] / 2,
        "points_complete": acc["pending_games"] == 0,
        "attendance": {
            "numerator": attendance_appearances, "denominator": len(attendance_games),
            "rate": attendance_appearances / len(attendance_games) if attendance_games else None,
            "excluded": 0, "game_ids": [str(game.get("id", "")) for game in attendance_games],
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
        "roles": roles,
        "ledger": ledger,
        "notes": notes,
    }


def compute_player_stats(player_id: str, games: list[dict[str, Any]], *, season: str = "S22",
                         phase: str = "all", name: str | None = None) -> dict[str, Any]:
    """Compute one player's season-wide metrics and scoring ledger.

    `phase` is accepted for API compatibility; player analytics always describe
    the full season, including attendance and the chronological cumulative ledger.
    """
    season_games = scope_games(games, season, "all")
    players, notes = _accumulate(season_games, season, "all")
    player_id = str(player_id)
    if player_id not in players:
        acc = _new_player_acc({"person_id": player_id, "name": name or ""}, len(season_games))
    else:
        acc = players[player_id]
    result = _serialize_player(acc, season_games, "all", notes, attendance_games=season_games)
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
    scoring_players, _ = _accumulate(scoring_games, season, scoring_phase)
    rows = []
    for player_id, scoring_acc in scoring_players.items():
        overall_acc = all_players[player_id]
        stats = _serialize_player(overall_acc, season_games, "all", all_notes,
                                  attendance_games=season_games)
        scoring_stats = _serialize_player(scoring_acc, scoring_games, scoring_phase,
                                          _methodology_notes(scoring_games),
                                          attendance_games=season_games)
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
        notes.insert(0, "已登记的个人胜利阵营优先；缺失的混血儿阵营只按唯一明确榜样及一致的阵营说明推导。")
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

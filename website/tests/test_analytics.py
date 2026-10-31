from __future__ import annotations

from fractions import Fraction

from website.api.analytics import (
    build_leaderboard,
    compute_player_stats,
    compute_player_summaries,
    effective_faction,
    _rank_values,
    scope_games,
)


def seat(number: int, person: str, role: str, faction: str | None, name: str | None = None) -> dict:
    return {"seat": number, "person_id": person, "name": name or person, "role": role, "faction": faction}


def game(game_id: str, *, phase: str = "regular", winner: str | None = "good",
         seats: list[dict] | None = None, ballots: list[dict] | None = None,
         registrations: list[dict] | None = None, date: str = "2026-06-01", number: int = 1) -> dict:
    return {
        "id": game_id, "season": "S22", "date": date, "phase": phase, "game_number": number,
        "board": {"code": "test", "name": "测试版型"}, "winner": winner,
        "seats": seats or [],
        "voting": {"ballots": ballots or [], "registrations": registrations or []},
    }


def vote(voter: int, target: int | None, state: str = "cast") -> dict:
    return {"voter": voter, "target": target, "state": state}


def test_points_use_half_units_and_mixed_blood_uses_personal_faction():
    games = [
        game("g1", winner="werewolf", seats=[seat(1, "wolf", "狼人", "werewolf"),
                                                seat(2, "villager", "平民", "good")]),
        game("g2", winner="good", seats=[seat(1, "wolf", "狼人", "werewolf"),
                                          seat(2, "villager", "平民", "good")], date="2026-06-02"),
        game("g3", winner="werewolf", seats=[seat(1, "mixed", "混血儿", "werewolf")], date="2026-06-03"),
    ]

    wolf = compute_player_stats("wolf", games)
    villager = compute_player_stats("villager", games)
    mixed = compute_player_stats("mixed", games)

    assert wolf["points"] == 0.5  # +1.5 for a wolf win, then -1 for a loss
    assert wolf["wins"] == 1 and wolf["losses"] == 1
    assert wolf["ledger"][0]["points"] == 1.5
    assert wolf["ledger"][1]["points"] == -1
    assert villager["points"] == 0  # +1 for good win, then -1 for a loss
    assert villager["ledger"][0]["points"] == -1
    assert villager["ledger"][1]["points"] == 1
    assert mixed["wins"] == 1 and mixed["points"] == 1.5


def test_attendance_samples_include_both_appearances_and_absences():
    games = [game('present', seats=[seat(1, 'p', '平民', 'good')]),
             game('absent', seats=[seat(1, 'other', '平民', 'good')])]
    metric = compute_player_stats('p', games)['attendance']
    assert metric['numerator'] == 1 and metric['denominator'] == 2
    assert {s['game_id']: (s['positive'], s['negative']) for s in metric['samples']} == {
        'present': (1, 0), 'absent': (0, 1),
    }


def test_unknown_faction_is_pending_not_a_loss_or_zero_point_result():
    games = [game("unknown", winner="good", seats=[seat(1, "mixed", "混血儿", None)])]
    stats = compute_player_stats("mixed", games)

    assert stats["wins"] == 0 and stats["losses"] == 0
    assert stats["pending_games"] == 1
    assert stats["points"] == 0
    assert stats["points_complete"] is False
    assert stats["ledger"][0]["result"] == "unknown"
    assert stats["ledger"][0]["points"] is None
    assert stats["ledger"][0]["pending_count"] == 1
    assert stats["total_win_rate"]["rate"] is None
    assert stats["total_win_rate"]["game_ids"] == []
    assert stats["total_win_rate"]["samples"] == []


def test_result_metrics_record_positive_negative_and_excluded_games_separately():
    games = [
        game("good-win", winner="good", seats=[seat(1, "p", "村民", "good")], date="2026-06-01"),
        game("good-loss", winner="werewolf", seats=[seat(1, "p", "村民", "good")], date="2026-06-02"),
        game("wolf-win", winner="werewolf", seats=[seat(1, "p", "狼人", "werewolf")], date="2026-06-03"),
        game("wolf-loss", winner="good", seats=[seat(1, "p", "狼人", "werewolf")], date="2026-06-04"),
        game("unknown-faction", winner="good", seats=[seat(1, "p", "混血儿", None)], date="2026-06-05"),
        game("unknown-result", winner=None, seats=[seat(1, "p", "村民", "good")], date="2026-06-06"),
    ]

    stats = compute_player_stats("p", games)

    assert stats["total_win_rate"]["samples"] == [
        {"game_id": "good-win", "positive": 1, "negative": 0},
        {"game_id": "good-loss", "positive": 0, "negative": 1},
        {"game_id": "wolf-win", "positive": 1, "negative": 0},
        {"game_id": "wolf-loss", "positive": 0, "negative": 1},
    ]
    assert stats["total_win_rate"]["excluded"] == 2
    assert stats["good_win_rate"]["samples"] == [
        {"game_id": "good-win", "positive": 1, "negative": 0},
        {"game_id": "good-loss", "positive": 0, "negative": 1},
    ]
    assert stats["good_win_rate"]["excluded"] == 2
    assert stats["werewolf_win_rate"]["samples"] == [
        {"game_id": "wolf-win", "positive": 1, "negative": 0},
        {"game_id": "wolf-loss", "positive": 0, "negative": 1},
    ]
    assert stats["werewolf_win_rate"]["excluded"] == 1


def test_player_ledger_is_season_cumulative_even_when_phase_is_requested():
    games = [
        game("r1", phase="regular", winner="good", seats=[seat(1, "p", "村民", "good")]),
        game("f1", phase="finals_week", winner="werewolf", seats=[seat(1, "p", "村民", "good")],
             date="2026-09-01"),
        game("f2", phase="finals_week", winner="good", seats=[seat(1, "p", "村民", "good")],
             date="2026-09-02"),
    ]

    all_stats = compute_player_stats("p", games, phase="all")
    finals = compute_player_stats("p", games, phase="finals_week")
    assert [row["cumulative_points"] for row in all_stats["ledger"]] == [1, 0, 1]
    assert [row["cumulative_points"] for row in finals["ledger"]] == [1, 0, 1]
    assert finals["appearances"] == 3
    assert finals["points"] == 1
    assert finals["attendance"] == all_stats["attendance"]


def test_attendance_is_identical_across_phase_arguments_and_for_absent_phase_player():
    games = [
        game("r", phase="regular", seats=[seat(1, "p", "平民", "good")]),
        game("f", phase="finals_week", date="2026-09-01", seats=[seat(1, "p", "平民", "good")]),
        game("f-other", phase="finals_week", date="2026-09-02", seats=[seat(1, "other", "平民", "good")]),
    ]
    overall = compute_player_stats("p", games, phase="all")
    regular = compute_player_stats("p", games, phase="regular")
    finals = compute_player_stats("p", games, phase="finals_week")
    absent_from_finals = compute_player_stats("other", games, phase="regular")

    assert overall["attendance"] == regular["attendance"] == finals["attendance"]
    assert overall["attendance"]["numerator"] == 2
    assert overall["attendance"]["denominator"] == 3
    assert overall["appearances"] == finals["appearances"] == 2
    assert absent_from_finals["attendance"]["numerator"] == 1
    assert absent_from_finals["attendance"]["denominator"] == 3
    summary = next(item for item in compute_player_summaries(games, phase="finals_week") if item["id"] == "p")
    assert summary["stats"]["attendance"] == overall["attendance"]


def test_registration_counts_once_from_first_record_and_empty_metrics_are_null():
    games = [game("reg", seats=[seat(1, "p", "村民", "good")], registrations=[
        {"day": 1, "id": "registration-1", "on_police": [1], "off_police": [2]},
        {"day": 2, "id": "registration-2", "on_police": [1], "off_police": [2]},
    ])]
    stats = compute_player_stats("p", games)
    assert stats["sheriff_registration_rate"] == {
        "numerator": 1, "denominator": 1, "rate": 1, "excluded": 0, "game_ids": ["reg"],
        "samples": [{"game_id": "reg", "positive": 1, "negative": 0}],
    }

    no_sample = compute_player_stats("absent", games)
    assert no_sample["seer_follow_rate"]["rate"] is None
    assert no_sample["sheriff_seer_vote_rate"]["rate"] is None
    assert no_sample["total_win_rate"]["rate"] is None
    assert no_sample["attendance"]["rate"] == 0


def test_wolf_vote_rate_counts_good_exile_votes_and_excludes_unknown_or_missing_records():
    seats = [seat(1, "seer", "预言家", "good"), seat(2, "p", "村民", "good"),
             seat(3, "wolf", "狼人", "werewolf"), seat(4, "unknown", "混血儿", None)]
    ballots = [
        # PK/revote ballots count independently. Information roles are included.
        {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(1, 3), vote(2, 3)]},
        {"kind": "exile", "stage": "pk", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(2, None, "abstained"), vote(3, None, "abstained"),
                   vote(4, None, "abstained")]},
        {"kind": "exile", "stage": "revote", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(2, 1)]},
        # The target's faction is unknown, so the ballot is excluded.
        {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(2, 4)]},
        # The player has a recorded right but no vote record.
        {"kind": "exile", "stage": "pk", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(1, 3)]},
        # A vote outside the known eligibility list is not a sample.
        {"kind": "exile", "stage": "revote", "eligible_voters": [1, 3, 4],
         "votes": [vote(2, 3)]},
        # Non-exile abstentions are not part of the abstention count.
        {"kind": "sheriff", "stage": "pk", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(2, None, "abstained")]},
    ]
    snapshot = game("wolf-vote", seats=seats, ballots=ballots)
    snapshot["voting"]["ballots"][1]["votes"][0]["basis"] = "rule_default"
    stats = compute_player_stats("p", [snapshot])
    seer_stats = compute_player_stats("seer", [snapshot])

    metric = stats["wolf_vote_rate"]
    assert metric["numerator"] == 1
    assert metric["denominator"] == 3
    assert metric["rate"] == 1 / 3
    assert metric["excluded"] == 2
    assert metric["game_ids"] == ["wolf-vote"]
    assert stats["exile_abstentions"] == 1
    assert snapshot["voting"]["ballots"][1]["votes"][0]["basis"] == "rule_default"
    assert seer_stats["wolf_vote_rate"]["numerator"] == 2
    assert seer_stats["wolf_vote_rate"]["denominator"] == 2


def test_abstention_record_cannot_override_explicitly_missing_vote_rights():
    seats = [seat(1, "p", "平民", "good"), seat(2, "wolf", "狼人", "werewolf")]
    ballots = [
        {"kind": "exile", "eligible_voters": [2], "votes": [vote(1, None, "abstained")]},
        {"kind": "exile", "eligible_voters": None, "votes": [vote(1, None, "abstained")]},
    ]
    stats = compute_player_stats("p", [game("rights", seats=seats, ballots=ballots)])
    assert stats["exile_abstentions"] == 1
    assert stats["wolf_vote_rate"]["denominator"] == 0


def test_werewolf_appearance_explosion_and_sheriff_rates_use_confirmed_personal_faction():
    first_wolf_game = game("wolf-first", seats=[seat(1, "p", "狼人", "werewolf")], registrations=[
        # Earliest day wins even if records arrive out of order.
        {"day": 2, "id": "registration-2", "on_police": [], "off_police": [1]},
        {"day": 1, "id": "registration-1", "on_police": [1], "off_police": []},
    ])
    first_wolf_game["rounds"] = [
        {"number": 1, "night": [{"actor": 1, "action": "self_destruct"}],
         "day": [{"actor": 1, "action": "self_destruct"}]},
    ]
    second_wolf_game = game("wolf-second", date="2026-06-02",
                            seats=[seat(1, "p", "狼人", "werewolf")], registrations=[
                                {"day": 1, "id": "registration-1", "on_police": [], "off_police": [1]},
                            ])
    good_game = game("good", date="2026-06-03", seats=[seat(1, "p", "村民", "good")])
    unknown_game = game("unknown", date="2026-06-04", seats=[seat(1, "p", "混血儿", None)])
    stats = compute_player_stats("p", [first_wolf_game, second_wolf_game, good_game, unknown_game])

    assert stats["werewolf_appearances"] == 2
    assert stats["werewolf_draw_rate"]["numerator"] == 2
    assert stats["werewolf_draw_rate"]["denominator"] == 3
    assert stats["werewolf_draw_rate"]["rate"] == 2 / 3
    assert stats["werewolf_draw_rate"]["excluded"] == 1
    explosion = stats["werewolf_self_explosion_rate"]
    assert explosion["numerator"] == 1  # duplicate events in wolf-first count once
    assert explosion["denominator"] == 2
    assert explosion["rate"] == 0.5
    assert explosion["excluded"] == 1
    registration = stats["werewolf_sheriff_registration_rate"]
    assert registration["numerator"] == 1  # first, not later, registration record
    assert registration["denominator"] == 2
    assert registration["rate"] == 0.5
    assert registration["excluded"] == 1


def test_faction_registration_and_off_police_rates_exclude_unknown_lists_and_factions():
    games = [
        game(f'{faction}-{where}', seats=[seat(1, 'p', '平民' if faction == 'good' else '狼人', faction)],
             registrations=[{'day': 1, 'on_police': [1] if where == 'on' else [],
                             'off_police': [1] if where == 'off' else []}])
        for faction in ('good', 'werewolf') for where in ('on', 'off', 'missing')
    ]
    games.append(game('unknown', seats=[seat(1, 'p', '混血儿', None)],
                      registrations=[{'day': 1, 'on_police': [], 'off_police': [1]}]))
    stats = compute_player_stats('p', games)

    for faction in ('good', 'werewolf'):
        on = stats[f'{faction}_sheriff_registration_rate']
        off = stats[f'{faction}_off_police_rate']
        assert (on['numerator'], on['denominator'], on['excluded'], on['rate']) == (1, 2, 2, 0.5)
        assert (off['numerator'], off['denominator'], off['excluded'], off['rate']) == (1, 2, 2, 0.5)
        assert set(off['game_ids']) == {f'{faction}-on', f'{faction}-off'}
        assert {sample['game_id']: (sample['positive'], sample['negative'])
                for sample in off['samples']} == {f'{faction}-on': (0, 1), f'{faction}-off': (1, 0)}


def test_leaderboard_exposes_new_and_existing_vote_metrics_as_full_season_values():
    seats = [seat(1, "seer", "预言家", "good"), seat(2, "p", "村民", "good"),
             seat(3, "wolf", "狼人", "werewolf")]
    ballot = {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2, 3],
              "votes": [vote(1, 3), vote(2, 3)]}
    games = [
        game("regular", seats=seats, ballots=[ballot], registrations=[
            {"day": 1, "id": "registration-1", "on_police": [1], "off_police": [2, 3]},
        ]),
        game("final", phase="finals_week", date="2026-09-01", seats=seats, ballots=[ballot],
             registrations=[{"day": 1, "id": "registration-1", "on_police": [1], "off_police": [2, 3]}]),
    ]
    season_board = {row["id"]: row for row in build_leaderboard(games, phase="all")}
    finals_board = {row["id"]: row for row in build_leaderboard(games, phase="finals_week")}
    p_stats = compute_player_stats("p", games)

    fields = (
        "seer_follow_rate", "sheriff_seer_vote_rate", "wolf_vote_rate", "exile_abstentions",
        "werewolf_appearances", "werewolf_draw_rate", "werewolf_self_explosion_rate",
        "werewolf_sheriff_registration_rate", "good_sheriff_registration_rate",
        "good_off_police_rate", "werewolf_off_police_rate",
    )
    for field in fields:
        assert season_board["p"][field] == p_stats[field]
        assert finals_board["p"][field] == season_board["p"][field]
    assert season_board["p"]["points"] != finals_board["p"]["points"]


def test_seer_follow_counts_abstention_as_failure_but_missing_vote_as_excluded():
    seats = [seat(1, "seer", "预言家", "good"), seat(2, "p", "平民", "good"),
             seat(3, "witch", "女巫", "good"), seat(4, "wolf", "狼人", "werewolf")]
    ballots = [
        # Follow success means choosing the same target as the information role.
        {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(1, 4), vote(2, 4)]},
        # An explicit voter abstention is a denominator failure.
        {"kind": "exile", "stage": "pk", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(1, 4), vote(2, None, "abstained")]},
        # The guide abstained: there is no target to follow, so this round is not applicable.
        {"kind": "exile", "stage": "revote", "eligible_voters": [1, 2, 3, 4],
         "votes": [vote(1, None, "abstained"), vote(2, 4)]},
        # No guide vote record despite vote rights is excluded.
        {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2, 3, 4], "votes": [vote(2, 4)]},
        # The player has no vote record despite guide and player vote rights.
        {"kind": "exile", "stage": "pk", "eligible_voters": [1, 2, 3, 4], "votes": [vote(1, 4)]},
        # The guide lacks vote rights, so the round is outside the metric.
        {"kind": "exile", "stage": "revote", "eligible_voters": [2, 3, 4], "votes": [vote(2, 4)]},
    ]
    stats = compute_player_stats("p", [game("follow", seats=seats, ballots=ballots)])

    metric = stats["seer_follow_rate"]
    assert metric["numerator"] == 1
    assert metric["denominator"] == 2
    assert metric["excluded"] == 2
    assert metric["rate"] == 0.5
    assert metric["game_ids"] == ["follow"]
    assert metric["samples"] == [{"game_id": "follow", "positive": 1, "negative": 1}]

    # The true seer has no ballot right in this round, so it is not applicable.
    no_seer_right = {"kind": "exile", "stage": "pk", "eligible_voters": [2, 3, 4], "votes": [vote(2, 1)]}
    second = compute_player_stats("p", [game("no-seer-vote", seats=seats, ballots=[no_seer_right])])
    assert second["seer_follow_rate"]["denominator"] == 0
    assert second["seer_follow_rate"]["excluded"] == 0

    only_excluded = compute_player_stats("p", [game("excluded", seats=seats, ballots=[ballots[3]])])
    assert only_excluded["seer_follow_rate"]["game_ids"] == []
    assert only_excluded["seer_follow_rate"]["excluded"] == 1
    assert only_excluded["seer_follow_rate"]["samples"] == []

    unknown_rights = {"kind": "exile", "stage": "initial", "eligible_voters": None,
                      "votes": [vote(1, 4), vote(2, 4)]}
    no_right_evidence = compute_player_stats("p", [game("unknown-rights", seats=seats,
                                                           ballots=[unknown_rights])])
    assert no_right_evidence["seer_follow_rate"]["denominator"] == 0
    assert no_right_evidence["seer_follow_rate"]["excluded"] == 0
    assert no_right_evidence["seer_follow_rate"]["game_ids"] == []


def test_vote_ranking_rows_separate_valid_games_from_round_sample_count():
    seats = [seat(1, "seer", "预言家", "good"), seat(2, "p", "平民", "good"),
             seat(3, "wolf", "狼人", "werewolf")]
    valid_ballots = [
        {"kind": "exile", "eligible_voters": [1, 2, 3], "votes": [vote(1, 3), vote(2, 3)]},
        {"kind": "exile", "eligible_voters": [1, 2, 3],
         "votes": [vote(1, 3), vote(2, None, "abstained")]},
        {"kind": "sheriff", "candidates": [1, 3], "eligible_voters": [2, 3], "votes": [vote(2, 1)]},
        {"kind": "sheriff", "candidates": [1, 3], "eligible_voters": [2, 3],
         "votes": [vote(2, None, "abstained")]},
    ]
    excluded_ballots = [
        # Missing reference vote makes this follow sample excluded.
        {"kind": "exile", "eligible_voters": [1, 2, 3], "votes": [vote(2, 3)]},
        # The omitted candidate list has no vote evidence for the seer.
        {"kind": "sheriff", "candidates": None, "eligible_voters": [2, 3], "votes": [vote(2, 3)]},
    ]
    games = [
        game("g1", seats=seats, ballots=valid_ballots, registrations=[
            {"day": 1, "id": "first", "on_police": [2], "off_police": [1, 3]},
            {"day": 2, "id": "later", "on_police": [], "off_police": [2]},
        ], date="2026-06-01"),
        game("g2", seats=seats, ballots=valid_ballots, registrations=[
            {"day": 1, "id": "first", "on_police": [1, 3], "off_police": [2]},
        ], date="2026-06-02"),
        game("g3-excluded", seats=seats, ballots=excluded_ballots, registrations=[
            {"day": 1, "id": "first", "on_police": [1], "off_police": [3]},
        ], date="2026-06-03"),
    ]

    stats = compute_player_stats("p", games)

    expected = {
        "sheriff_registration_rate": (2, 2, 1),
        "seer_follow_rate": (4, 2, 1),
        "sheriff_seer_vote_rate": (4, 2, 1),
    }
    for key, (sample_count, effective_game_count, excluded) in expected.items():
        row = next(row for row in stats["ranking_boards"][key] if row["id"] == "p")
        assert row["sample_count"] == sample_count
        assert row["effective_game_count"] == effective_game_count
        assert row["appearances"] == 3
        metric_key = key
        assert stats[metric_key]["excluded"] == excluded
        assert stats[metric_key]["game_ids"] == ["g1", "g2"]

    assert [row["sample_count"] for row in stats["ranking_boards"]["points"] if row["id"] == "p"] == [3]
    assert "effective_game_count" not in stats["ranking_boards"]["points"][0]


def test_medium_only_game_is_reference_and_learned_medium_is_not_a_role():
    medium_seats = [seat(1, "medium", "通灵师", "good"), seat(2, "p", "平民", "good"),
                    seat(3, "wolf", "狼人", "werewolf")]
    medium_ballot = {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2, 3],
                     "votes": [vote(1, 3), vote(2, 3)]}
    sheriff_ballot = {"kind": "sheriff", "stage": "pk", "candidates": [1, 3],
                      "eligible_voters": [2, 3], "votes": [vote(2, 1)]}
    stats = compute_player_stats("p", [game("medium-only", seats=medium_seats,
                                               ballots=[medium_ballot, sheriff_ballot])])
    assert stats["seer_follow_rate"]["numerator"] == 1
    assert stats["seer_follow_rate"]["denominator"] == 1
    assert stats["sheriff_seer_vote_rate"]["numerator"] == 1
    assert stats["sheriff_seer_vote_rate"]["denominator"] == 1

    mechanical_seats = [seat(1, "mechanical", "机械狼", "werewolf"), seat(2, "p", "平民", "good")]
    mechanical_seats[0]["learned_role"] = "通灵师"
    no_real_medium = {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2],
                      "votes": [vote(2, 1)]}
    no_real_medium_sheriff = {"kind": "sheriff", "stage": "initial", "candidates": None,
                              "eligible_voters": [2], "votes": [vote(2, 1)]}
    learned = compute_player_stats("p", [game("learned-medium", seats=mechanical_seats,
                                                ballots=[no_real_medium, no_real_medium_sheriff])])
    assert learned["seer_follow_rate"]["denominator"] == 0
    assert learned["seer_follow_rate"]["excluded"] == 0
    assert learned["sheriff_seer_vote_rate"]["excluded"] == 0

    missing_role_seats = [seat(1, "p", "平民", "good"), seat(2, "unknown", "身份未知", "good")]
    missing_role_seats[1]["role"] = None
    missing_role_vote = {"kind": "exile", "stage": "initial", "eligible_voters": [1, 2],
                         "votes": [vote(1, 2)]}
    missing_role = compute_player_stats("p", [game("missing-role", seats=missing_role_seats,
                                                      ballots=[missing_role_vote])])
    assert missing_role["seer_follow_rate"]["denominator"] == 0
    assert missing_role["seer_follow_rate"]["excluded"] == 1


def test_sheriff_rate_includes_pk_revote_and_requires_proven_seer_candidate():
    seats = [seat(1, "seer", "预言家", "good"), seat(2, "p", "平民", "good"),
             seat(3, "witch", "女巫", "good"), seat(4, "wolf", "狼人", "werewolf")]
    ballots = [
        # Explicit candidate list; first vote for the seer succeeds.
        {"kind": "sheriff", "stage": "initial", "candidates": [1, 3], "eligible_voters": [2, 3, 4],
         "votes": [vote(2, 1)]},
        # PK ballot counts as another opportunity; abstention is a failed vote.
        {"kind": "sheriff", "stage": "pk", "candidates": [1, 3], "eligible_voters": [2, 3, 4],
         "votes": [vote(2, None, "abstained")]},
        # Unknown list, but an actual vote to the seer proves candidacy.
        {"kind": "sheriff", "stage": "revote", "candidates": None, "eligible_voters": [2, 3, 4],
         "votes": [vote(2, 1), vote(3, 1)]},
        # Candidate list is missing and nobody voted to the seer: excluded.
        {"kind": "sheriff", "stage": "initial", "candidates": None, "eligible_voters": [2, 3, 4],
         "votes": [vote(2, 4), {"voter": 3, "target": 1, "state": "abstained"}]},
        # A known list with no true seer proves that the seer was not eligible.
        {"kind": "sheriff", "stage": "initial", "candidates": [3], "eligible_voters": [2, 3, 4],
         "votes": [vote(2, 3)]},
        # Missing vote entry differs from an explicit abstention.
        {"kind": "sheriff", "stage": "revote", "candidates": [1, 3], "eligible_voters": [2, 3, 4],
         "votes": [vote(3, 1)]},
        # Player has no vote right: not a denominator or excluded sample.
        {"kind": "sheriff", "stage": "pk", "candidates": [1], "eligible_voters": [1, 3, 4],
         "votes": [vote(3, 1)]},
    ]
    stats = compute_player_stats("p", [game("sheriff", seats=seats, ballots=ballots)])

    metric = stats["sheriff_seer_vote_rate"]
    assert metric["numerator"] == 2
    assert metric["denominator"] == 3
    assert metric["excluded"] == 2  # unknown candidate pool and missing vote
    assert metric["rate"] == 2 / 3
    assert metric["game_ids"] == ["sheriff"]
    assert metric["samples"] == [{"game_id": "sheriff", "positive": 2, "negative": 1}]

    no_eligibility_list = {
        "kind": "sheriff", "stage": "initial", "candidates": [1], "eligible_voters": None,
        "votes": [vote(2, 1)],
    }
    unknown_eligibility = compute_player_stats("p", [game("unknown-rights", seats=seats,
                                                              ballots=[no_eligibility_list])])
    assert unknown_eligibility["sheriff_seer_vote_rate"]["denominator"] == 0
    assert unknown_eligibility["sheriff_seer_vote_rate"]["excluded"] == 0
    assert unknown_eligibility["sheriff_seer_vote_rate"]["game_ids"] == []


def test_missing_or_ambiguous_true_seer_is_never_guessed():
    seats = [seat(1, "seer", "预言家", "good"), seat(2, "medium", "通灵师", "good"),
             seat(3, "p", "平民", "good")]
    ballot = {"kind": "sheriff", "stage": "initial", "candidates": [1, 2],
              "eligible_voters": [1, 2, 3], "votes": [vote(3, 1)]}
    stats = compute_player_stats("p", [game("ambiguous", seats=seats, ballots=[ballot])])
    assert stats["sheriff_seer_vote_rate"]["denominator"] == 0
    assert stats["sheriff_seer_vote_rate"]["numerator"] == 0
    assert stats["sheriff_seer_vote_rate"]["excluded"] == 1


def test_mixed_blood_faction_infers_from_unique_exemplar_without_mutating_snapshot():
    mixed = seat(1, "mixed", "混血儿", None)
    exemplar = seat(2, "exemplar", "女巫", "good")
    snapshot = game("inferred", winner="good", seats=[mixed, exemplar])
    snapshot["rounds"] = [{"number": 1, "night": [
        {"slot": "mixed_blood_model", "actor": 1, "action": "choose", "targets": [2]},
        {"slot": "mixed_blood_alignment", "actor": 1, "action": "good", "targets": []},
    ], "day": []}]

    assert effective_faction(snapshot, mixed) == "good"
    stats = compute_player_stats("mixed", [snapshot])
    assert stats["wins"] == 1 and stats["points"] == 1
    assert stats["ledger"][0]["faction"] == "good"
    assert stats["ledger"][0]["faction_inferred"] is True
    assert mixed["faction"] is None

    explicit = seat(1, "explicit", "混血儿", "werewolf")
    conflict = game("explicit-priority", winner="werewolf", seats=[explicit, exemplar])
    conflict["rounds"] = snapshot["rounds"]
    assert effective_faction(conflict, explicit) == "werewolf"

    inconsistent = seat(1, "inconsistent", "混血儿", None)
    conflict["seats"] = [inconsistent, exemplar]
    conflict["rounds"] = [{"number": 1, "night": [
        {"slot": "mixed_blood_model", "actor": 1, "action": "choose", "targets": [2]},
        {"slot": "mixed_blood_alignment", "actor": 1, "action": "wolf", "targets": []},
    ], "day": []}]
    assert effective_faction(conflict, inconsistent) is None
    pending = compute_player_stats("inconsistent", [conflict])
    assert pending["pending_games"] == 1
    assert pending["ledger"][0]["faction_inferred"] is False


def test_leaderboard_ties_share_competition_rank_and_match_ledger_points():
    games = [
        game("g1", winner="good", seats=[seat(1, "a", "平民", "good"), seat(2, "b", "平民", "good"),
                                            seat(3, "c", "狼人", "werewolf"), seat(4, "d", "平民", "good")]),
        game("g2", winner="good", seats=[seat(1, "a", "平民", "good"), seat(2, "b", "平民", "good"),
                                            seat(3, "c", "狼人", "werewolf")], date="2026-06-02"),
    ]

    board = build_leaderboard(games, phase="regular")
    by_id = {item["id"]: item for item in board}
    assert by_id["a"]["points"] == by_id["b"]["points"] == 2
    assert by_id["a"]["rank"] == by_id["b"]["rank"] == 1
    assert by_id["d"]["rank"] == 3
    for player_id in ("a", "b", "c", "d"):
        stats = compute_player_stats(player_id, games, phase="regular")
        assert by_id[player_id]["points"] == stats["points"]

    summaries = compute_player_summaries(games, phase="regular")
    assert {item["id"] for item in summaries} == set(by_id)

    half_tie = build_leaderboard([game("half-tie", winner="werewolf", seats=[
        seat(1, "wolf-a", "狼人", "werewolf"), seat(2, "wolf-b", "狼人", "werewolf"),
        seat(3, "villager", "平民", "good"),
    ])], phase="all")
    assert half_tie[0]["points"] == half_tie[1]["points"] == 1.5
    assert half_tie[0]["rank"] == half_tie[1]["rank"] == 1


def test_finals_board_ranks_only_finals_points_but_shows_season_metrics():
    games = [
        game("r1", phase="regular", winner="good",
             seats=[seat(1, "a", "平民", "good"), seat(2, "b", "狼人", "werewolf")]),
        game("f1", phase="finals_week", winner="werewolf", date="2026-09-01",
             seats=[seat(1, "a", "平民", "good"), seat(2, "b", "狼人", "werewolf")]),
        game("f2", phase="finals_week", winner="good", date="2026-09-02",
             seats=[seat(1, "a", "平民", "good"), seat(2, "b", "狼人", "werewolf"),
                    seat(3, "c", "混血儿", None)]),
    ]
    season_board = {row["id"]: row for row in build_leaderboard(games, phase="all")}
    finals_board = {row["id"]: row for row in build_leaderboard(games, phase="finals_week")}

    assert season_board["a"]["points"] == 1  # +1 regular, -1 then +1 finals
    assert finals_board["a"]["points"] == 0  # -1 then +1 in the championship scope
    assert finals_board["a"]["scoring_appearances"] == 2
    assert finals_board["a"]["scoring_wins"] == 1
    assert finals_board["a"]["appearances"] == 3
    assert finals_board["a"]["wins"] == 2
    assert finals_board["a"]["losses"] == 1
    assert finals_board["a"]["attendance"] == season_board["a"]["attendance"]
    assert finals_board["c"]["points_complete"] is False
    assert finals_board["c"]["pending_games"] == 1
    assert finals_board["c"]["scoring_appearances"] == 1


def test_profile_minimum_appearances_filters_all_rank_cohorts_and_preserves_metrics():
    games = [
        game('g1', seats=[seat(1, 'a', '平民', 'good'), seat(2, 'b', '平民', 'good'),
                          seat(3, 'guest', '平民', 'good'), seat(4, 'c', '预言家', 'good')]),
        game('g2', winner='werewolf', seats=[seat(1, 'a', '平民', 'good'),
             seat(2, 'b', '平民', 'good'), seat(4, 'c', '狼人', 'werewolf')]),
        game('g3', seats=[seat(1, 'a', '平民', 'good'), seat(2, 'b', '平民', 'good'),
                          seat(4, 'c', '狼人', 'werewolf')]),
    ]
    games[0]['board'] = {'code': 'special', 'name': '特殊版型'}
    baseline = compute_player_stats('a', games)
    filtered = compute_player_stats('a', games, minimum_appearances=3)
    assert baseline['rankings']['total_win_rate']['rank'] == 2
    assert filtered['rankings']['total_win_rate'] == {'rank': 1, 'total': 3, 'tied': True}
    for key in ('appearances', 'wins', 'losses', 'points', 'total_win_rate', 'ledger'):
        assert filtered[key] == baseline[key]
    assert all(row['id'] != 'guest' for rows in filtered['ranking_boards'].values() for row in rows)
    specialist = compute_player_stats('c', games, minimum_appearances=3)
    seer = next(row for row in specialist['roles'] if row['role'] == '预言家')
    assert seer['appearances'] == 1 and seer['ranking']['rank'] == 1
    special = next(row for row in specialist['boards'] if row['code'] == 'special')
    assert special['appearances'] == 1 and special['ranking'] is not None
    assert all(row['id'] != 'guest' for row in special['ranking_board'])
    excluded = compute_player_stats('guest', games, minimum_appearances=3)
    assert excluded['appearances'] == 1 and excluded['wins'] == 1
    assert all(rank is None for rank in excluded['rankings'].values())
    assert all(role['ranking'] is None for role in excluded['roles'])
    assert all(board['ranking'] is None for board in excluded['boards'])


def test_profile_new_metrics_have_rankings_and_obey_the_global_appearance_filter():
    games = [
        game('g1', seats=[seat(1, 'p', '平民', 'good'), seat(2, 'q', '平民', 'good'),
                         seat(3, 'wolf', '狼人', 'werewolf')],
             registrations=[{'day': 1, 'on_police': [1, 3], 'off_police': [2]}],
             ballots=[{'kind': 'exile', 'eligible_voters': [1, 2], 'votes': [vote(1, 3), vote(2, 1)]}]),
        game('g2', winner='werewolf', seats=[seat(1, 'p', '狼人', 'werewolf')],
             registrations=[{'day': 1, 'on_police': [1], 'off_police': []}]),
        game('g3', seats=[seat(1, 'p', '平民', 'good'), seat(2, 'q', '狼人', 'werewolf')]),
    ]
    games[1]['rounds'] = [{'number': 1, 'day': [{'actor': 1, 'action': 'self_destruct'}]}]
    review_stats = {'p': {
        'bluff_count': 1, 'bluff_count_complete': True,
        'bluff_rate': {'numerator': 1, 'denominator': 1},
        'bluff_success_rate': {'numerator': 1, 'denominator': 1},
    }, 'q': {
        'bluff_count': 0, 'bluff_count_complete': False,
        'bluff_rate': {'numerator': 0, 'denominator': 0},
        'bluff_success_rate': {'numerator': 0, 'denominator': 0},
    }}
    stats = compute_player_stats('p', games, minimum_appearances=3, bluff_stats=review_stats)
    for key in ['good_wins', 'wolf_vote_rate', 'good_sheriff_registration_rate',
                'werewolf_appearances', 'werewolf_wins', 'werewolf_draw_rate',
                'werewolf_self_explosion_rate', 'werewolf_sheriff_registration_rate',
                'bluff_count', 'bluff_rate', 'bluff_success_rate']:
        assert stats['rankings'][key] == {'rank': 1, 'total': 1, 'tied': False}, key
        assert [row['id'] for row in stats['ranking_boards'][key]] == ['p']
    unconfirmed = compute_player_stats('q', games, bluff_stats=review_stats)
    assert unconfirmed['rankings']['bluff_count'] is None


def test_profile_minimum_appearances_uses_the_entire_selected_season_range():
    games = [game('s22', seats=[seat(1, 'p', '平民', 'good')]),
             {**game('s23', seats=[seat(1, 'p', '平民', 'good')]), 'season': 'S23'}]
    single = compute_player_stats('p', games, season='S22', minimum_appearances=2)
    combined = compute_player_stats('p', games, seasons=['S22', 'S23'], minimum_appearances=2)
    assert single['rankings']['total_win_rate'] is None
    assert combined['appearances'] == 2
    assert combined['rankings']['total_win_rate'] == {'rank': 1, 'total': 1, 'tied': False}


def test_scope_filters_season_and_phase():
    games = [game("r", phase="regular"), game("f", phase="finals_week", date="2026-09-01"),
             {**game("other", phase="regular"), "season": "S21"}]
    assert [item["id"] for item in scope_games(games, "S22", "all")] == ["r", "f"]
    assert [item["id"] for item in scope_games(games, "S22", "finals_week")] == ["f"]


def test_player_stats_aggregate_seasons_with_weighted_rates_and_full_scope_attendance():
    games = [
        game("s22-player", winner="good", seats=[seat(1, "p", "平民", "good")], date="2026-06-01"),
        game("s22-other", winner="good", seats=[seat(1, "other", "平民", "good")], date="2026-06-02"),
        {**game("s23-loss-1", winner="werewolf", seats=[seat(1, "p", "平民", "good")],
                date="2026-07-01"), "season": "S23"},
        {**game("s23-loss-2", winner="werewolf", seats=[seat(1, "p", "平民", "good")],
                date="2026-07-02"), "season": "S23"},
        {**game("s23-other", winner="good", seats=[seat(1, "other", "平民", "good")],
                date="2026-07-03"), "season": "S23"},
    ]

    stats = compute_player_stats("p", games, seasons=["S22", "S23"])

    assert stats["appearances"] == 3
    assert stats["scope_games"] == 5
    assert stats["total_win_rate"]["numerator"] == 1
    assert stats["total_win_rate"]["denominator"] == 3
    assert stats["total_win_rate"]["rate"] == 1 / 3
    assert stats["attendance"]["numerator"] == 3
    assert stats["attendance"]["denominator"] == 5
    assert [row["season"] for row in stats["ledger"]] == ["S22", "S23", "S23"]
    assert stats["total_win_rate"]["samples"] == [
        {"game_id": "s22-player", "positive": 1, "negative": 0},
        {"game_id": "s23-loss-1", "positive": 0, "negative": 1},
        {"game_id": "s23-loss-2", "positive": 0, "negative": 1},
    ]


def test_player_rankings_use_selected_scope_competition_ranks_and_role_cohorts():
    games = [
        game("s22-win", winner="good", seats=[
            seat(1, "a", "平民", "good"), seat(2, "b", "平民", "good"),
            seat(3, "c", "平民", "good"), seat(4, "pending", "混血儿", None),
        ], date="2026-06-01"),
        game("s22-loss", winner="werewolf", seats=[
            seat(1, "a", "平民", "good"), seat(2, "b", "平民", "good"), seat(3, "c", "平民", "good"),
        ], date="2026-06-02"),
        {**game("s23-win", winner="good", seats=[
            seat(1, "a", "平民", "good"), seat(2, "d", "平民", "good"),
        ], date="2026-07-01"), "season": "S23"},
        {**game("s23-loss", winner="werewolf", seats=[], date="2026-07-02"), "season": "S23"},
        {**game("outside-range", winner="good", seats=[seat(1, "outsider", "平民", "good")],
                date="2026-08-01"), "season": "S24"},
    ]

    stats = compute_player_stats("a", games, seasons=["S22", "S23"])
    rankings = stats["rankings"]

    assert rankings["points"] == {"rank": 1, "total": 4, "tied": True}
    assert rankings["appearances"] == {"rank": 1, "total": 5, "tied": False}
    assert rankings["attendance"] == {"rank": 1, "total": 5, "tied": False}
    assert rankings["total_win_rate"] == {"rank": 2, "total": 4, "tied": False}
    assert rankings["wins"] == {"rank": 1, "total": 4, "tied": False}
    assert rankings["losses"] == {"rank": 2, "total": 4, "tied": True}
    assert rankings["good_win_rate"] == {"rank": 2, "total": 4, "tied": False}
    assert rankings["werewolf_win_rate"] is None
    assert rankings["sheriff_registration_rate"] is None
    assert rankings["seer_follow_rate"] is None
    assert rankings["sheriff_seer_vote_rate"] is None
    ranking_boards = stats["ranking_boards"]
    assert set(ranking_boards) == set(rankings)
    assert ranking_boards["points"] == [
        {"id": "a", "name": "a", "rank": 1, "tied": True,
         "value": 1.0, "sample_count": 3, "appearances": 3},
        {"id": "d", "name": "d", "rank": 1, "tied": True,
         "value": 1.0, "sample_count": 1, "appearances": 1},
        {"id": "b", "name": "b", "rank": 3, "tied": True,
         "value": 0.0, "sample_count": 2, "appearances": 2},
        {"id": "c", "name": "c", "rank": 3, "tied": True,
         "value": 0.0, "sample_count": 2, "appearances": 2},
    ]
    assert ranking_boards["attendance"][0] == {
        "id": "a", "name": "a", "rank": 1, "tied": False,
        "value": 0.75, "sample_count": 4, "appearances": 3,
    }
    assert ranking_boards["attendance"][-1] == {
        "id": "pending", "name": "pending", "rank": 4, "tied": True,
        "value": 0.25, "sample_count": 4, "appearances": 1,
    }
    a_total_win_rate = next(row for row in ranking_boards["total_win_rate"] if row["id"] == "a")
    assert a_total_win_rate["value"] == 2 / 3
    assert a_total_win_rate["sample_count"] == 3
    assert a_total_win_rate["rank"] == 2
    assert ranking_boards["wins"][0]["value"] == 2
    assert ranking_boards["wins"][0]["sample_count"] == 3
    assert ranking_boards["losses"][0]["id"] == "d"
    assert [row["rank"] for row in ranking_boards["losses"]] == [1, 2, 2, 2]
    assert ranking_boards["werewolf_win_rate"] == []
    assert all(row["id"] != "outsider" for row in ranking_boards["appearances"])

    role = stats["roles"][0]
    assert role["role"] == "平民"
    assert role["metric"] == {
        "numerator": 2, "denominator": 3, "rate": 2 / 3, "excluded": 0,
        "game_ids": ["s22-win", "s22-loss", "s23-win"],
        "samples": [
            {"game_id": "s22-win", "positive": 1, "negative": 0},
            {"game_id": "s22-loss", "positive": 0, "negative": 1},
            {"game_id": "s23-win", "positive": 1, "negative": 0},
        ],
    }
    assert role["ranking"] == {"rank": 2, "total": 4, "tied": False}
    assert role["ranking_board"] == [
        {"id": "d", "name": "d", "rank": 1, "tied": False,
         "value": 1.0, "sample_count": 1, "appearances": 1},
        {"id": "a", "name": "a", "rank": 2, "tied": False,
         "value": 2 / 3, "sample_count": 3, "appearances": 3},
        {"id": "b", "name": "b", "rank": 3, "tied": True,
         "value": 0.5, "sample_count": 2, "appearances": 2},
        {"id": "c", "name": "c", "rank": 3, "tied": True,
         "value": 0.5, "sample_count": 2, "appearances": 2},
    ]

    pending_stats = compute_player_stats("pending", games, seasons=["S22", "S23"])
    assert pending_stats["rankings"]["points"] is None
    assert pending_stats["rankings"]["wins"] is None
    assert pending_stats["rankings"]["losses"] is None
    assert pending_stats["rankings"]["appearances"] == {"rank": 4, "total": 5, "tied": True}
    mixed_role = pending_stats["roles"][0]
    assert mixed_role["metric"]["denominator"] == 0
    assert mixed_role["metric"]["excluded"] == 1
    assert mixed_role["metric"]["samples"] == []
    assert mixed_role["ranking"] is None
    assert mixed_role["ranking_board"] == []


def test_rank_values_compare_exact_ratios_without_float_rounding_ties():
    ranks = _rank_values({
        "one-third": Fraction(1, 3),
        "close-below": Fraction(3333333333333333, 10_000_000_000_000_000),
        "equal-half-a": Fraction(1, 2),
        "equal-half-b": Fraction(2, 4),
    })

    assert ranks["equal-half-a"] == {"rank": 1, "total": 4, "tied": True}
    assert ranks["equal-half-b"] == {"rank": 1, "total": 4, "tied": True}
    assert ranks["one-third"] == {"rank": 3, "total": 4, "tied": False}
    assert ranks["close-below"] == {"rank": 4, "total": 4, "tied": False}


def test_player_board_stats_group_by_code_then_name_and_rank_board_cohorts_across_seasons():
    games = [
        {**game("s22-board-win", winner="good", seats=[
            seat(1, "p", "村民", "good"), seat(2, "q", "村民", "good"),
            seat(3, "t", "村民", "good"),
        ], date="2026-06-01"), "board": {"code": "classic", "name": "经典版型"}},
        {**game("s22-board-loss", winner="werewolf", seats=[
            seat(1, "p", "村民", "good"), seat(2, "q", "狼人", "werewolf"),
            seat(3, "r", "预言家", "good"),
        ], date="2026-06-02"), "board": {"code": "classic", "name": "经典版型"}},
        {**game("s23-board-pending", winner="good", seats=[
            seat(1, "p", "混血儿", None),
        ], date="2026-07-01"), "season": "S23",
         "board": {"code": "classic", "name": "S23经典版型"}},
        {**game("s23-name-fallback", winner="good", seats=[
            seat(1, "p", "村民", "good"), seat(2, "d", "狼人", "werewolf"),
        ], date="2026-07-02"), "season": "S23", "board": {"name": "备用版型"}},
        {**game("outside-range-board", winner="good", seats=[
            seat(1, "p", "村民", "good"), seat(2, "outsider", "村民", "good"),
        ], date="2026-08-01"), "season": "S24",
         "board": {"code": "classic", "name": "经典版型"}},
    ]

    stats = compute_player_stats("p", games, seasons=["S22", "S23"])

    assert len(stats["boards"]) == 2
    classic, fallback = stats["boards"]
    assert classic["code"] == "classic" and classic["name"] == "经典版型"
    assert classic["appearances"] == 3
    assert classic["wins"] == 1 and classic["losses"] == 1 and classic["pending_games"] == 1
    assert classic["win_rate"] == 0.5
    assert classic["metric"] == {
        "numerator": 1, "denominator": 2, "rate": 0.5, "excluded": 1,
        "game_ids": ["s22-board-win", "s22-board-loss"],
        "samples": [
            {"game_id": "s22-board-win", "positive": 1, "negative": 0},
            {"game_id": "s22-board-loss", "positive": 0, "negative": 1},
        ],
    }
    assert classic["ranking"] == {"rank": 3, "total": 4, "tied": False}
    assert classic["ranking_board"] == [
        {"id": "q", "name": "q", "rank": 1, "tied": True,
         "value": 1.0, "sample_count": 2, "appearances": 2},
        {"id": "t", "name": "t", "rank": 1, "tied": True,
         "value": 1.0, "sample_count": 1, "appearances": 1},
        {"id": "p", "name": "p", "rank": 3, "tied": False,
         "value": 0.5, "sample_count": 2, "appearances": 3},
        {"id": "r", "name": "r", "rank": 4, "tied": False,
         "value": 0.0, "sample_count": 1, "appearances": 1},
    ]
    assert fallback["code"] is None and fallback["name"] == "备用版型"
    assert fallback["appearances"] == 1 and fallback["wins"] == 1 and fallback["losses"] == 0
    assert fallback["ranking_board"][0]["id"] == "p"
    assert all(row["id"] != "outsider" for row in classic["ranking_board"])

    village_role = next(row for row in stats["roles"] if row["role"] == "村民")
    assert village_role["ranking"]["total"] == 3
    assert [row["id"] for row in village_role["ranking_board"]] == ["q", "t", "p"]
    summary = compute_player_summaries(games, season="S22")
    assert all("boards" not in row["stats"] for row in summary)
    assert all("ranking_boards" not in row for row in build_leaderboard(games, season="S22"))

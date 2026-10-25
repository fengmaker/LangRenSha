from __future__ import annotations

from website.api.analytics import (
    build_leaderboard,
    compute_player_stats,
    compute_player_summaries,
    effective_faction,
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
        "numerator": 1, "denominator": 1, "rate": 1, "excluded": 0, "game_ids": ["reg"]
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
        "werewolf_sheriff_registration_rate",
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

    # The true seer has no ballot right in this round, so it is not applicable.
    no_seer_right = {"kind": "exile", "stage": "pk", "eligible_voters": [2, 3, 4], "votes": [vote(2, 1)]}
    second = compute_player_stats("p", [game("no-seer-vote", seats=seats, ballots=[no_seer_right])])
    assert second["seer_follow_rate"]["denominator"] == 0
    assert second["seer_follow_rate"]["excluded"] == 0

    only_excluded = compute_player_stats("p", [game("excluded", seats=seats, ballots=[ballots[3]])])
    assert only_excluded["seer_follow_rate"]["game_ids"] == []
    assert only_excluded["seer_follow_rate"]["excluded"] == 1

    unknown_rights = {"kind": "exile", "stage": "initial", "eligible_voters": None,
                      "votes": [vote(1, 4), vote(2, 4)]}
    no_right_evidence = compute_player_stats("p", [game("unknown-rights", seats=seats,
                                                           ballots=[unknown_rights])])
    assert no_right_evidence["seer_follow_rate"]["denominator"] == 0
    assert no_right_evidence["seer_follow_rate"]["excluded"] == 0
    assert no_right_evidence["seer_follow_rate"]["game_ids"] == []


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


def test_scope_filters_season_and_phase():
    games = [game("r", phase="regular"), game("f", phase="finals_week", date="2026-09-01"),
             {**game("other", phase="regular"), "season": "S21"}]
    assert [item["id"] for item in scope_games(games, "S22", "all")] == ["r", "f"]
    assert [item["id"] for item in scope_games(games, "S22", "finals_week")] == ["f"]

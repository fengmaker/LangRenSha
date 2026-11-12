from copy import deepcopy

from website.api.analytics import compute_player_stats


def snapshot(game_id, season, *, use_poison=True):
    game = {
        "id": game_id, "season": season, "date": "2026-09-01", "phase": "regular",
        "game_number": 1, "board": {"code": "test", "name": "测试版型"}, "winner": "good",
        "seats": [
            {"seat": 1, "person_id": "witch", "name": "女巫选手", "role": "女巫", "faction": "good"},
            {"seat": 2, "person_id": "wolf", "name": "狼人选手", "role": "狼人", "faction": "werewolf"},
            {"seat": 3, "person_id": "seer", "name": "预言家选手", "role": "预言家", "faction": "good"},
        ],
        "rounds": [{"number": 1, "night": [
            {"slot": "wolf_attack", "action": "attack", "targets": [1]},
            {"slot": "witch_poison", "action": "poison" if use_poison else "pass", "actor": 1,
             "targets": [2] if use_poison else [], "effects": [
                 {"kind": "poison_death", "intended_target": 2, "dead_seat": 2}
             ] if use_poison else []},
        ], "day": [
            {"slot": "night_deaths", "action": "die" if use_poison else "peaceful",
             "targets": [2] if use_poison else []},
            {"slot": "sheriff_result", "action": "elected", "targets": [3]},
            {"slot": "exile_result", "action": "not_held", "targets": []},
        ]}],
        "voting": {"registrations": [{"day": 1, "on_police": [2, 3], "off_police": [1]}],
                   "ballots": [], "days": [{"day": 1, "sheriff": "recorded", "exile": "not_held"}]},
        "rules_state": {"living": [{"day": 1, "night_deaths": [2] if use_poison else [],
                                     "night_deaths_complete": True}]},
    }
    game["presentation"] = {"rounds": deepcopy(game["rounds"])}
    return game


def test_performance_samples_merge_across_selected_seasons_and_retain_rank_scope():
    games = [snapshot("s22", "S22"), snapshot("s23", "S23", use_poison=False)]
    original = deepcopy(games)
    player = compute_player_stats("witch", games, seasons=["S22", "S23"])
    metrics = player["performance"]
    assert metrics["witch_poison_count"]["numerator"] == 1
    assert metrics["witch_poison_wolf_rate"]["rate"] == 1
    assert metrics["witch_poison_wolf_rate"]["game_ids"] == ["s22"]
    assert metrics["witch_poison_wolf_kills"]["numerator"] == 1
    assert metrics["first_night_targeted"]["numerator"] == 2
    assert metrics["first_night_death"]["numerator"] == 0
    assert metrics["first_day_exiled"]["denominator"] == 2
    assert player["rankings"]["witch_poison_wolf_rate"] == {"rank": 1, "total": 1, "tied": False}
    assert player["ranking_boards"]["witch_poison_wolf_rate"][0]["sample_count"] == 1
    assert "first_night_targeted" not in player["rankings"]
    assert games == original

    single = compute_player_stats("witch", games, season="S23")
    assert single["performance"]["witch_poison_count"]["numerator"] == 0
    assert single["performance"]["witch_poison_wolf_rate"]["denominator"] == 0
    excluded = compute_player_stats("witch", games, seasons=["S22", "S23"], minimum_appearances=3)
    assert excluded["rankings"]["witch_poison_wolf_rate"] is None
    assert excluded["performance"] == player["performance"]


def test_information_role_counts_do_not_include_non_information_roles():
    games = [snapshot("s22", "S22")]
    seer = compute_player_stats("seer", games)
    assert seer["performance"]["seer_campaign_count"]["numerator"] == 1
    assert seer["performance"]["seer_badge_count"]["numerator"] == 1
    assert seer["performance"]["seer_first_day_exiled"]["numerator"] == 0
    witch = compute_player_stats("witch", games)
    assert "seer_badge_count" not in witch["performance"]


def test_unrecorded_counts_do_not_enter_a_complete_count_ranking():
    games = [snapshot("recorded", "S22"), snapshot("missing", "S22")]
    games[1]["rounds"] = []
    games[1]["rules_state"] = {}
    player = compute_player_stats("witch", games)
    metric = player["performance"]["witch_poison_count"]
    assert metric["numerator"] == 1 and metric["excluded"] > 0
    assert player["rankings"]["witch_poison_count"] is None
    assert player["performance"]["first_night_targeted"]["excluded"] == 1

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
    assert player["rankings"]["first_night_targeted"] == {"rank": 1, "total": 3, "tied": False}
    assert player["rankings"]["first_night_death"] == {"rank": 2, "total": 3, "tied": True}
    assert player["rankings"]["first_day_exiled"] == {"rank": 1, "total": 3, "tied": True}
    assert player["ranking_boards"]["first_night_targeted"][0]["sample_count"] == 2
    assert games == original

    single = compute_player_stats("witch", games, season="S23")
    assert single["performance"]["witch_poison_count"]["numerator"] == 0
    assert single["performance"]["witch_poison_wolf_rate"]["denominator"] == 0
    excluded = compute_player_stats("witch", games, seasons=["S22", "S23"], minimum_appearances=3)
    assert excluded["rankings"]["witch_poison_wolf_rate"] is None
    assert excluded["rankings"]["first_night_targeted"] is None
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
    assert player["rankings"]["first_night_targeted"] is None


def test_poisoner_and_witch_share_skill_stats_but_retain_their_roles():
    witch = snapshot("witch-game", "S22")
    poisoner = snapshot("poisoner-game", "S23")
    poisoner["seats"][0]["role"] = "毒师"

    player = compute_player_stats("witch", [witch, poisoner], seasons=["S22", "S23"])

    assert player["performance"]["witch_poison_count"]["numerator"] == 2
    assert player["performance"]["witch_poison_wolf_kills"]["numerator"] == 2
    assert {game["role"] for game in player["ledger"]} == {"女巫", "毒师"}


def test_mechanical_learning_and_skill_stats_use_confirmed_learning_and_scope():
    def mechanical_game(game_id, season, actions):
        game = snapshot(game_id, season)
        game["seats"][0].update(role="机械狼", faction="werewolf")
        game["rounds"] = [
            {"number": number, "night": [{"slot": "mechanical_action", "actor": 1,
                                         "action": action, "targets": targets}], "day": []}
            for number, (action, targets) in enumerate(actions, 1)
        ]
        game.pop("presentation")
        return game

    learned = mechanical_game("learned", "S22", [("pass", []), ("learn", [2]), ("attack", [3])])
    civilian = mechanical_game("civilian", "S22", [("learn", [3])])
    civilian["seats"][2]["role"] = "平民"
    did_not_learn = mechanical_game("did-not-learn", "S22", [("pass", [])])
    unknown = mechanical_game("unknown", "S23", [("unknown", [])])
    unknown_form = mechanical_game("unknown-form", "S23", [("learn", [])])
    games = [learned, civilian, did_not_learn, unknown, unknown_form]

    player = compute_player_stats("witch", games, seasons=["S22", "S23"])
    rate = player["performance"]["mechanical_learn_rate"]
    assert (rate["numerator"], rate["denominator"], rate["excluded"]) == (1, 3, 2)
    assert {row["game_id"]: row["negative"] for row in rate["samples"]} == {
        "learned": 0, "civilian": 1, "did-not-learn": 1,
    }
    assert player["rankings"]["mechanical_learn_rate"]["total"] == 1
    assert {row["game_id"]: row["mechanical_learned_role"] for row in player["ledger"]} == {
        "learned": "机械双刀狼", "civilian": "机械平民", "did-not-learn": None,
        "unknown": None, "unknown-form": None,
    }
    assert player["performance"]["mechanical_extra_attack_count"]["samples"] == [
        {"game_id": "learned", "positive": 1, "negative": 0},
    ]
    assert compute_player_stats("witch", games, season="S23")["performance"]["mechanical_learn_rate"]["rate"] is None


def test_mechanical_wolf_draw_rate_uses_only_wolf_appearances_on_mechanical_boards():
    def appearance(game_id, season, board, role, faction):
        game = snapshot(game_id, season)
        game["board"]["code"] = board
        game["seats"][0].update(role=role, faction=faction)
        return game

    games = [
        appearance("mechanical", "S22", "mechanical_wolf_seer", "机械狼", "werewolf"),
        appearance("ordinary", "S23", "s23_mechanical_wolf_seer", "狼人", "werewolf"),
        appearance("good", "S23", "s23_mechanical_wolf_seer", "女巫", "good"),
        appearance("other-board", "S23", "wolf_king_guard", "狼王", "werewolf"),
    ]

    player = compute_player_stats("witch", games, seasons=["S22", "S23"])

    rate = player["performance"]["mechanical_wolf_rate"]
    assert (rate["numerator"], rate["denominator"], rate["rate"]) == (1, 2, 0.5)
    assert rate["samples"] == [
        {"game_id": "mechanical", "positive": 1, "negative": 0},
        {"game_id": "ordinary", "positive": 0, "negative": 1},
    ]
    assert player["performance"]["mechanical_wolf_count"] == rate
    assert player["rankings"]["mechanical_wolf_count"]["rank"] == 1
    assert player["rankings"]["mechanical_wolf_rate"]["rank"] == 1
    assert compute_player_stats("witch", games, season="S23")["performance"]["mechanical_wolf_rate"]["rate"] == 0

from collections import Counter

from scripts.role_constraints import event_constraint, family


def game(board, seats, *, season=None, rounds=None):
    return {
        "board": {"code": board},
        "season": season,
        "seats": [{"seat": seat, "role": role} for seat, role in seats],
        "rounds": rounds or [],
    }


def check(game_, number, phase, slot, *, actor, action="unknown", targets=None,
          result=None, dead_before=frozenset(), uses=None, used_targets=None,
          previous=None, learning=None):
    return event_constraint(
        game_, number, phase,
        {"slot": slot, "action": action, "actor": actor,
         "targets": list(targets or []), "result": result},
        actor=actor,
        dead_before=dead_before,
        uses=Counter() if uses is None else uses,
        used_targets={} if used_targets is None else used_targets,
        previous={} if previous is None else previous,
        learning={} if learning is None else learning,
    )


def test_family_normalizes_cross_season_aliases_without_merging_distinct_boards():
    assert family("s21_seer_witch_hunter_white_mixed") == "mixed_blood"
    assert family("s23_masquerade") == "masquerade"
    assert family("s21_neighbor_puppet") == "neighbor_puppet"
    assert family("s23_magic_duel") == "magic_duel"
    assert family("s21_treasure_master") == "treasure_master"


def test_failed_poison_does_not_disable_the_wolf_kings_shot():
    source = game("s21_neighbor_puppet", [(6, "女巫"), (7, "狼王")], rounds=[{
        "number": 2,
        "night": [{"slot": "witch_poison", "actor": 6, "action": "poison",
                   "targets": [7], "result": "failed"}],
    }])
    result = check(source, 2, "day", "wolf_king_shot", actor=7)
    assert result["status"] == "available"
    assert result["reason"] == "wolf_king_not_poisoned"


def test_witch_keeps_first_night_antidote_available_and_spends_each_bottle_once():
    source = game("s21_seer_witch_hunter_white_mixed", [(2, "女巫"), (5, "狼人")])
    save = check(source, 1, "night", "witch_save", actor=2)
    assert save["status"] == "available"
    assert save["legal_targets"] == [5]

    assert check(source, 1, "night", "witch_save", actor=2, targets=[2], action="save")["reason"] == "witch_cannot_save_self"
    spent = check(source, 2, "night", "witch_save", actor=2,
                  uses=Counter({(2, "witch_save"): 1}))
    assert spent["status"] == "unavailable" and spent["reason"] == "witch_save_spent"
    sibling = game("mixed_blood", [(2, "女巫"), (5, "狼人")], rounds=[{
        "number": 1, "night": [{"slot": "witch_poison", "actor": 2, "action": "poison", "targets": [5]}],
    }])
    same_night = check(sibling, 1, "night", "witch_save", actor=2)
    assert same_night["status"] == "unavailable"
    assert same_night["reason"] == "one_witch_medicine_per_night"


def test_poisoner_has_one_poison_bottle_without_an_antidote():
    source = game("s23_treasure_master", [(1, "毒师"), (2, "平民"), (3, "盗宝大师")], season="S23")
    result = check(source, 2, "night", "witch_poison", actor=1,
                   uses=Counter({(1, "witch_poison"): 1}))
    assert result["status"] == "unavailable" and result["reason"] == "witch_poison_spent"


def test_mixed_blood_choice_is_first_night_only_and_once_across_aliases():
    source = game("s21_seer_witch_hunter_white_mixed", [(1, "混血儿"), (2, "狼人")])
    first = check(source, 1, "night", "mixed_blood_model", actor=1, action="choose", targets=[2])
    assert first["status"] == "available"
    assert check(source, 2, "night", "mixed_blood_model", actor=1)["reason"] == "mixed_blood_choice_first_night_only"
    spent = check(source, 1, "night", "mixed_blood_model", actor=1,
                  uses=Counter({(1, "mixed_blood_model"): 1}))
    assert spent["reason"] == "mixed_blood_choice_spent"


def test_mechanical_learning_unlock_and_double_wolf_gate():
    source = game("s21_mechanical_wolf_seer", [
        (1, "机械狼"), (2, "猎人"), (3, "狼人"), (4, "狼人"),
    ])
    learn = check(source, 2, "night", "mechanical_action", actor=1,
                  action="learn", targets=[2])
    assert learn["status"] == "available" and learn["availability"] == "learning"
    assert 1 not in learn["legal_targets"]

    for form in ("狼人", "机械双刀狼", "机械双刀狼人", "mechanical_double_attack_werewolf"):
        learned = {1: {"round": 1, "target": 3, "form": form}}
        n1 = check(source, 1, "night", "mechanical_action", actor=1,
                   action="attack", targets=[4], learning=learned)
        assert n1["status"] == "unavailable" and n1["availability"] == "learning"
        alive = check(source, 2, "night", "mechanical_action", actor=1,
                      action="attack", targets=[4], learning=learned, dead_before={3})
        assert alive["reason"] == "ordinary_wolves_alive"
        departed = check(source, 2, "night", "mechanical_action", actor=1,
                         action="attack", targets=[4], learning=learned, dead_before={3, 4})
        assert departed["status"] == "available" and departed["availability"] == "available"


def test_mechanical_knife_confirmation_is_nightly_and_independent_of_learned_form():
    for board in ('mechanical_wolf_seer', 's21_mechanical_wolf_seer', 's23_mechanical_wolf_seer'):
        source = game(board, [(1, '机械狼'), (2, '狼人'), (3, '狼人'), (4, '狼人'), (5, '平民')])
        assert check(source, 1, 'night', 'mechanical_knife_status', actor=1, dead_before={2, 3, 4})['status'] == 'unavailable'
        assert check(source, 2, 'day', 'mechanical_knife_status', actor=1, dead_before={2, 3, 4})['status'] == 'unavailable'
        assert check(source, 2, 'night', 'mechanical_knife_status', actor=1, dead_before={2, 3})['status'] == 'unavailable'
        assert check(source, 2, 'night', 'mechanical_knife_status', actor=1, dead_before={2, 3, 4})['status'] == 'available'
        assert check(source, 2, 'night', 'mechanical_knife_status', actor=1, dead_before={1, 2, 3, 4})['status'] == 'unavailable'


def test_mechanical_learning_is_single_use_and_mechanical_poison_is_one_bottle():
    source = game("s23_mechanical_wolf_seer", [
        (1, "机械狼"), (2, "女巫"), (3, "平民"), (4, "狼人"),
    ])
    learned = {1: {"round": 1, "target": 2, "form": "女巫"}}
    assert check(source, 2, "night", "mechanical_action", actor=1,
                 action="learn", targets=[3], learning=learned)["reason"] == "mechanical_learning_spent"
    available = check(source, 2, "night", "mechanical_action", actor=1,
                      action="poison", targets=[3], learning=learned)
    assert available["status"] == "available"
    source["rounds"] = [{"number": 2, "night": [
        {"slot": "mechanical_action", "actor": 1, "action": "poison", "targets": [3]},
    ]}]
    spent = check(source, 3, "night", "mechanical_action", actor=1,
                  action="poison", targets=[4], learning=learned)
    assert spent["status"] == "unavailable" and spent["reason"] == "mechanical_poison_spent"


def test_mechanical_double_wolf_stays_unknown_when_prior_departures_are_incomplete():
    source = game("mechanical_wolf_seer", [
        (1, "机械狼"), (2, "狼人"), (3, "狼人"), (4, "平民"),
    ], rounds=[{"number": 1, "day": [
        {"slot": "night_deaths", "action": "unknown", "targets": []},
    ]}])
    learned = {1: {"round": 1, "target": 2, "form": "mechanical_double_attack_werewolf"}}
    result = check(source, 2, "night", "mechanical_action", actor=1,
                   action="attack", targets=[4], learning=learned, dead_before=set())
    assert result["status"] == "unknown"
    assert result["reason"] == "ordinary_wolf_departure_unknown"


def test_later_confirmed_wolf_departure_rules_out_an_earlier_mechanical_takeover():
    source = game("mechanical_wolf_seer", [(1, "机械狼"), (2, "狼人"), (3, "平民")], rounds=[
        {"number": 1, "day": [{"slot": "night_deaths", "action": "unknown", "targets": []}]},
        {"number": 3, "day": [{"slot": "self_destruct", "action": "self_destruct", "actor": 2, "targets": []}]},
    ])
    learned = {1: {"round": 1, "target": 2, "form": "机械双刀狼"}}
    state = check(source, 2, "night", "mechanical_action", actor=1, learning=learned)
    assert state["status"] == "unavailable" and state["reason"] == "ordinary_wolves_alive"
    source["rounds"][1] = {"number": 3, "night": [{"slot": "wolf_attack", "action": "attack", "targets": [2]}]}
    assert check(source, 2, "night", "mechanical_action", actor=1, learning=learned)["status"] == "unknown"


def test_treasure_opening_knife_ban_does_not_depend_on_season_specific_card_pool():
    for board in ("s21_treasure_master", "treasure_master", "s23_treasure_master"):
        source = game(board, [(1, "盗宝大师"), (2, "狼人"), (3, "平民")])
        result = check(source, 1, "night", "wolf_attack", actor=None)
        assert result["status"] == "unavailable"
        assert result["reason"] == "treasure_first_night_attack_forbidden"


def test_mechanical_hunter_day_skill_respects_unlock_and_poison_without_alive_gate():
    source = game("mechanical_wolf_seer", [
        (1, "机械狼"), (2, "女巫"), (3, "猎人"), (4, "狼人"),
    ], rounds=[{"number": 2, "night": [
        {"slot": "witch_poison", "actor": 2, "action": "poison", "targets": [1],
         "effects": [{"kind": "poison_death", "intended_target": 1, "dead_seat": 1}]},
    ]}])
    learned = {1: {"round": 1, "target": 3, "form": "猎人"}}
    # The shooter is dead when the triggered skill runs; death triggering is
    # handled by replay, while poison still disables this particular shot.
    result = check(source, 2, "day", "mechanical_day_skill", actor=1,
                   action="shoot", targets=[4], learning=learned, dead_before={1})
    assert result["status"] == "unavailable"
    assert result["availability"] == "poisoned"


def test_ordinary_hunter_poison_is_unavailable_and_unknown_poison_stays_unknown():
    source = game("wolf_king_guard", [(1, "猎人"), (2, "女巫"), (3, "狼人")], rounds=[{
        "number": 1, "night": [{"slot": "witch_poison", "actor": 2, "action": "poison", "targets": [1]}],
    }])
    assert check(source, 1, "day", "hunter_shot", actor=1, action="shoot", targets=[3])["reason"] == "hunter_poisoned"
    source["rounds"][0]["night"][0]["action"] = "unknown"
    state = check(source, 1, "night", "hunter_state", actor=1)
    assert state["status"] == "unknown" and state["reason"] == "hunter_poison_unknown"
    unknown = check(source, 1, "day", "hunter_shot", actor=1, action="shoot", targets=[3])
    assert unknown["status"] == "unknown" and unknown["reason"] == "hunter_poison_unknown"


def test_treasure_selected_medium_does_not_create_a_physical_medium_slot():
    source = game("treasure_master", [(1, "盗宝大师")] + [(n, "平民") for n in range(2, 13)])
    state = check(source, 1, "night", "seer_check", actor=None)
    assert state["status"] == "unavailable" and state["reason"] == "seer_check_role_absent"
    source["seats"][-1]["role"] = None
    assert check(source, 1, "night", "seer_check", actor=None)["status"] == "unknown"


def test_mechanical_wolf_regular_knife_is_separate_from_its_learned_skill():
    source = game("mechanical_wolf_seer", [(1, "机械狼"), (2, "狼人"), (3, "守卫"), (4, "平民")])
    source["seats"][0]["learned_role"] = "机械守卫"
    assert check(source, 2, "night", "wolf_attack", actor=1, action="attack", targets=[4])["reason"] == "ordinary_wolves_alive"
    inherited = check(source, 2, "night", "wolf_attack", actor=1, action="attack", targets=[4], dead_before={2})
    assert inherited["status"] == "available"
    assert inherited["reason"] == "ordinary_wolves_departed"
    assert inherited["legal_targets"] == [1, 3, 4]


def test_seer_and_medium_checks_match_role_phase_and_single_living_target_but_allow_repeats():
    source = game("s23_mixed_blood", [(1, "预言家"), (2, "狼人"), (3, "平民")], season="S23")
    first = check(source, 1, "night", "seer_check", actor=1, action="check", targets=[2])
    assert first["status"] == "available" and first["legal_targets"] == [1, 2, 3]

    repeated = check(source, 2, "night", "seer_check", actor=1, action="check", targets=[2],
                     previous={(1, "seer_check"): {"round": 1, "action": "check", "targets": [2]}})
    assert repeated["status"] == "available" and 2 in repeated["legal_targets"]
    assert check(source, 1, "day", "seer_check", actor=1)["reason"] == "seer_check_wrong_phase"
    assert check(source, 1, "night", "seer_check", actor=2)["reason"] == "seer_check_actor_role_mismatch"
    assert check(source, 1, "night", "seer_check", actor=1, action="check",
                 targets=[2, 3])["reason"] == "seer_check_target_count_invalid"
    missing_check_target = check(source, 1, "night", "seer_check", actor=1, action="check")
    assert missing_check_target["status"] == "unknown"
    assert missing_check_target["reason"] == "seer_check_target_unknown"
    assert missing_check_target["legal_targets"] == [1, 2, 3]
    departed_target = check(source, 1, "night", "seer_check", actor=1, action="check",
                            targets=[2], dead_before={2})
    assert departed_target["status"] == "unavailable"
    assert departed_target["reason"] == "seer_check_target_invalid"
    assert departed_target["legal_targets"] == [1, 3]

    mechanical = game("s23_mechanical_wolf_seer", [(1, "机械狼"), (2, "通灵师"), (3, "狼人")], season="S23")
    medium = check(mechanical, 1, "night", "seer_check", actor=2, action="check", targets=[3])
    assert medium["status"] == "available" and 3 in medium["legal_targets"]


def test_information_role_can_check_on_first_night_before_same_night_death():
    source = game("s23_mixed_blood", [(1, "预言家"), (2, "狼人"), (3, "平民")], season="S23", rounds=[{
        "number": 1,
        "night": [
            {"slot": "seer_check", "actor": 1, "action": "check", "targets": [2]},
            {"slot": "night_deaths", "action": "die", "targets": [1]},
        ],
    }])
    result = check(source, 1, "night", "seer_check", actor=1, action="check", targets=[2])
    assert result["status"] == "available"
    assert result["legal_targets"] == [1, 2, 3]
    assert "consequences" not in result


def test_wolf_knife_uses_physical_identity_not_mixed_blood_victory_faction():
    source = game("s23_mixed_blood", [
        (1, "狼人"), (2, "混血儿"), (3, "平民"), (4, "狼人"),
    ], season="S23")
    source["seats"][1]["victory_faction"] = "werewolf"
    attack = check(source, 1, "night", "wolf_attack", actor=1, action="attack", targets=[2])
    assert attack["status"] == "available"
    assert 2 in attack["legal_targets"]

    mixed_actor = check(source, 1, "night", "wolf_attack", actor=2,
                        action="attack", targets=[3])
    assert mixed_actor["status"] == "unavailable"
    assert mixed_actor["reason"] == "mixed_blood_has_no_wolf_knife"
    assert mixed_actor["legal_targets"] == [1, 2, 3, 4]

    bad_count = check(source, 1, "night", "wolf_attack", actor=1,
                      action="attack", targets=[2, 3])
    assert bad_count["reason"] == "wolf_attack_target_count_invalid"
    invalid_target = check(source, 1, "night", "wolf_attack", actor=1,
                           action="attack", targets=[3], dead_before={3})
    assert invalid_target["reason"] == "wolf_attack_target_invalid"
    assert invalid_target["legal_targets"] == [1, 2, 4]
    assert check(source, 1, "day", "wolf_attack", actor=1)["reason"] == "wolf_attack_wrong_phase"

    actorless = check(source, 1, "night", "wolf_attack", actor=None,
                      action="attack", targets=[2])
    assert actorless["status"] == "unknown"
    assert actorless["reason"] == "wolf_attack_actor_unknown"
    assert actorless["legal_targets"] == [1, 2, 3, 4]
    actorless_departed_target = check(source, 1, "night", "wolf_attack", actor=None,
                                      action="attack", targets=[3], dead_before={3})
    assert actorless_departed_target["status"] == "unavailable"
    assert actorless_departed_target["reason"] == "wolf_attack_target_invalid"
    assert actorless_departed_target["legal_targets"] == [1, 2, 4]
    actorless_missing_target = check(source, 1, "night", "wolf_attack", actor=None,
                                     action="attack")
    assert actorless_missing_target["status"] == "unknown"
    assert actorless_missing_target["reason"] == "wolf_attack_target_unknown"
    assert actorless_missing_target["legal_targets"] == [1, 2, 3, 4]


def test_guard_cannot_repeat_but_dreamer_repeat_causes_death_consequence():
    source = game("wolf_king_guard", [
        (1, "守卫"), (2, "摄梦人"), (3, "猎人"), (4, "狼王"), (5, "狼人"),
    ])
    history = {
        (1, "guard"): {"round": 2, "action": "guard", "targets": [4]},
        (2, "dreamer_action"): {"round": 2, "action": "dream", "targets": [3]},
    }
    guard = check(source, 3, "night", "guard", actor=1, action="guard", targets=[4], previous=history)
    assert guard["status"] == "unavailable" and 4 not in guard["legal_targets"]
    dream = check(source, 3, "night", "dreamer_action", actor=2,
                  action="dream", targets=[3], previous=history)
    assert dream["status"] == "available" and 3 in dream["legal_targets"]
    assert dream["consequences"] == [
        {"type": "wolf_attack_immunity", "seat": 3,
         "rule": "dreamer_target_immune_to_wolf_attack_that_night"},
        {"type": "repeat_dream_death", "seat": 3,
         "rule": "dreamer_same_target_on_two_consecutive_nights_dies"},
    ]


def test_dreamer_night_death_links_current_target_and_blocks_hunter_or_wolf_king_shot():
    for target_role, state_slot in (("猎人", "hunter_state"), ("狼王", "wolf_king_state")):
        source = game("wolf_king_guard", [
            (1, "守卫"), (2, "摄梦人"), (3, "狼人"), (4, target_role), (5, "平民"),
        ], rounds=[{
            "number": 2,
            "night": [{"slot": "dreamer_action", "action": "dream", "actor": 2, "targets": [4]}],
            "day": [{"slot": "night_deaths", "action": "die", "targets": [2, 4]}],
        }])
        dream = check(source, 2, "night", "dreamer_action", actor=2,
                      action="dream", targets=[4])
        assert {"type": "dreamer_night_death_link", "seat": 4,
                "rule": "dreamer_night_death_links_current_night_dream_target"} in dream["consequences"]
        state = check(source, 2, "night", state_slot, actor=4)
        assert state["status"] == "unavailable" and state["reason"] == "dream_death_blocks_shot"


def test_repeat_dream_death_blocks_shot_only_when_target_is_a_confirmed_night_death():
    source = game("wolf_king_guard", [
        (1, "守卫"), (2, "摄梦人"), (3, "猎人"), (4, "狼王"), (5, "狼人"),
    ], rounds=[
        {"number": 1, "night": [
            {"slot": "dreamer_action", "action": "dream", "actor": 2, "targets": [3]},
        ], "day": [{"slot": "night_deaths", "action": "peaceful", "targets": []}]},
        {"number": 2, "night": [
            {"slot": "dreamer_action", "action": "dream", "actor": 2, "targets": [3]},
        ], "day": [{"slot": "night_deaths", "action": "die", "targets": [3]}]},
    ])
    blocked = check(source, 2, "night", "hunter_state", actor=3)
    assert blocked["status"] == "unavailable" and blocked["reason"] == "dream_death_blocks_shot"
    source["rounds"][1]["day"][0] = {"slot": "night_deaths", "action": "peaceful", "targets": []}
    not_dead = check(source, 2, "night", "hunter_state", actor=3)
    assert not_dead["status"] == "available"


def test_treasure_dream_skill_allows_repeating_target_and_emits_dream_consequences():
    source = game("s23_treasure_master", [(1, "盗宝大师"), (2, "平民"), (3, "狼人")],
                  season="S23", rounds=[{"number": 3, "night": [
                      {"slot": "treasure_choice", "action": "choose", "actor": 1, "result": "摄梦人"},
                  ]}])
    previous = {(1, "treasure_card_skill"): {"round": 2, "action": "dream", "targets": [2]}}
    result = check(source, 3, "night", "treasure_card_skill", actor=1,
                   action="dream", targets=[2], previous=previous)
    assert result["status"] == "available" and 2 in result["legal_targets"]
    assert result["consequences"][0]["type"] == "wolf_attack_immunity"


def test_masquerade_tracks_one_time_dance_participants_and_season_scoped_first_night_rules():
    source = game("masquerade", [(1, "舞者"), (2, "假面"), (3, "预言家"), (4, "女巫"), (5, "狼人")], season="S22")
    assert check(source, 1, "night", "dancer_dance", actor=1)["reason"] == "dance_starts_second_night"
    danced = check(source, 2, "night", "dancer_dance", actor=1, action="dance",
                   targets=[3, 4, 5], used_targets={(1, "dancer_dance"): {4}})
    assert danced["status"] == "unavailable" and 4 not in danced["legal_targets"]
    assert check(source, 1, "night", "masquerade_mask", actor=2)["reason"] == "masquerade_skills_start_second_night"
    s23 = game("s23_masquerade", [(1, "舞者"), (2, "假面")], season="S23")
    assert check(s23, 1, "night", "masquerade_verify", actor=2)["reason"] == "masquerade_skills_start_second_night"


def test_masquerade_mask_and_verification_cannot_repeat_on_consecutive_nights():
    source = game("s23_masquerade", [(1, "假面"), (2, "舞者"), (3, "狼人")], season="S23")
    previous = {
        (1, "masquerade_verify"): {"round": 2, "action": "verify", "targets": [3]},
        (1, "masquerade_mask"): {"round": 2, "action": "give_mask", "targets": [2]},
    }
    verify = check(source, 3, "night", "masquerade_verify", actor=1,
                   action="verify", targets=[3], previous=previous)
    mask = check(source, 3, "night", "masquerade_mask", actor=1,
                 action="give_mask", targets=[2], previous=previous)
    assert verify["reason"] == "masquerade_verify_target_repeat"
    assert mask["reason"] == "masquerade_mask_target_repeat"


def test_guile_exchange_targets_are_one_time_but_magic_duel_is_a_distinct_board():
    source = game("s21_guile_realm", [(1, "诡术师"), (2, "狼人"), (3, "平民"), (4, "女巫")])
    result = check(source, 2, "night", "guile_exchange", actor=1,
                   action="exchange", targets=[2, 3],
                   used_targets={(1, "guile_exchange"): {3}})
    assert result["status"] == "unavailable" and result["reason"] == "guile_exchange_target_repeat"
    assert 3 not in result["legal_targets"]
    duel = game("s23_magic_duel", [(1, "狼术师"), (2, "魔术师"), (3, "平民")], season="S23")
    unrelated = check(duel, 2, "night", "magic_duel_wolf_sorcerer_swap", actor=1,
                      action="swap", targets=[2, 3], used_targets={(1, "magic_duel_wolf_sorcerer_swap"): {3}})
    assert unrelated["reason"] == "no_applicable_rule"


def test_prince_and_knight_skills_are_once_per_actor():
    source = game("guile_realm", [(1, "定序王子"), (2, "骑士"), (3, "狼人")])
    prince = check(source, 2, "day", "sequential_prince_skill", actor=1,
                   uses=Counter({(1, "sequential_prince_skill"): 1}))
    knight = check(source, 2, "day", "knight_duel", actor=2,
                   uses=Counter({(2, "knight_duel"): 1}))
    assert prince["reason"] == "sequential_prince_skill_spent"
    assert knight["reason"] == "knight_duel_spent"
    speech = check(source, 2, "day", "extra_speech", actor=1,
                   uses=Counter({(1, "sequential_prince_skill"): 1}),
                   previous={(1, "sequential_prince_skill"): {"round": 2, "action": "reveal", "targets": []}})
    assert speech["status"] == "available"
    assert check(source, 2, "day", "extra_speech", actor=1)["reason"] == "extra_speech_requires_prince_skill"


def test_warden_trade_is_second_night_onward_and_each_player_can_trade_once():
    source = game("all_in", [(1, "典狱长"), (2, "狼人"), (3, "平民"), (4, "女巫")], season="S22")
    assert check(source, 1, "night", "warden_trade_targets", actor=1)["reason"] == "warden_trade_starts_second_night"
    result = check(source, 2, "night", "warden_trade_targets", actor=1,
                   action="select_pair", targets=[2, 3],
                   used_targets={(1, "warden_trade_targets"): {3}})
    assert result["status"] == "unavailable" and result["reason"] == "warden_trade_target_repeat"
    assert 3 not in result["legal_targets"]


def test_dynamic_treasure_choice_uses_remainder_and_cannot_repeat_consecutively():
    seats = [(1, "盗宝大师"), (2, "狼王"), (3, "狼人"), (4, "狼人"), (5, "狼人"),
             (6, "通灵师"), (7, "猎人"), (8, "摄梦人"), (9, "蒙面人"),
             (10, "平民"), (11, "平民"), (12, "平民")]
    rounds = [
        {"number": 1, "night": [{"slot": "treasure_choice", "actor": 1, "action": "choose", "result": "毒师"}]},
        {"number": 2, "night": [{"slot": "treasure_choice", "actor": 1, "action": "choose", "result": "平民"}]},
    ]
    source = game("s23_treasure_master", seats, season="S23", rounds=rounds)
    same_as_last = check(source, 3, "night", "treasure_choice", actor=1,
                         action="choose", result="平民",
                         previous={(1, "treasure_choice"): {"round": 2, "action": "choose", "targets": []}})
    assert same_as_last["reason"] == "treasure_choice_cannot_repeat_consecutively"
    repeated_after_gap = check(source, 3, "night", "treasure_choice", actor=1,
                              action="choose", result="毒师",
                              previous={(1, "treasure_choice"): {"round": 2, "action": "choose", "targets": []}})
    assert repeated_after_gap["status"] == "available"


def test_treasure_card_skill_matches_choice_and_master_knife_waits_for_all_wolves():
    seats = [(1, "盗宝大师"), (2, "狼王"), (3, "狼人"), (4, "狼人"), (5, "狼人"),
             (6, "通灵师"), (7, "猎人"), (8, "摄梦人"), (9, "蒙面人"),
             (10, "平民"), (11, "平民"), (12, "平民")]
    rounds = [{"number": 2, "night": [
        {"slot": "treasure_choice", "actor": 1, "action": "choose", "result": "毒师"},
    ]}]
    source = game("treasure_master", seats, season="S22", rounds=rounds)
    mismatch = check(source, 2, "night", "treasure_card_skill", actor=1,
                     action="guard", targets=[3])
    assert mismatch["reason"] == "treasure_skill_does_not_match_choice"
    poison = check(source, 2, "night", "treasure_card_skill", actor=1,
                   action="poison", targets=[3])
    assert poison["status"] == "available"
    locked = check(source, 2, "night", "wolf_attack", actor=1, action="attack",
                   targets=[3], dead_before={3, 4, 5})
    assert locked["reason"] == "treasure_wolf_knife_locked"
    ready = check(source, 2, "night", "wolf_attack", actor=1, action="attack",
                  targets=[3], dead_before={2, 3, 4, 5})
    assert ready["status"] == "available"
    first_night = check(source, 1, "night", "wolf_attack", actor=3, action="attack", targets=[1])
    assert first_night["reason"] == "treasure_first_night_attack_forbidden"


def test_legacy_s21_treasure_does_not_inherit_dynamic_card_pool_rules():
    source = game("s21_treasure_master", [(1, "盗宝大师"), (2, "狼人")], season="S21")
    result = check(source, 2, "night", "treasure_choice", actor=1, action="choose", result="猎人")
    assert result["status"] == "unknown"
    assert result["reason"] == "legacy_treasure_rules_not_shared"

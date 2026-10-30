import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from board_outcomes import derive_board_outcomes


def event(slot, action="unknown", *, actor=None, targets=None, result=None):
    return {"slot": slot, "action": action, "actor": actor,
            "targets": list(targets or []), "result": result}


def game(board, roles, rounds, *, season="S22"):
    return {"board": board, "season": season,
            "seats": [{"seat": seat, "role": role,
                       "faction": "werewolf" if role in {"狼人", "狼王", "假面", "典狱长", "九尾狐"} else "good"}
                      for seat, role in roles.items()],
            "rounds": rounds}


def constraint(report, slot):
    return next(row for row in report["constraints"] if row["slot"] == slot)


def test_neighbor_puppet_uses_circular_wolf_neighbors_and_unknown_living_boundary():
    source = game("s21_neighbor_puppet", {
        1: "狼人", 2: "平民", 3: "平民", 4: "预言家", 5: "女巫", 6: "猎人",
        7: "平民", 8: "平民", 9: "守卫", 10: "狼王", 11: "平民", 12: "平民",
    }, [{"number": 1, "night": [event("puppet_select", "select", actor=1, targets=[12])], "day": []}])

    unknown = derive_board_outcomes(source, 1)
    assert constraint(unknown, "puppet_select")["status"] == "unknown"
    assert "legal_targets" not in constraint(unknown, "puppet_select")

    report = derive_board_outcomes(source, 1, living_before_night=range(1, 13))
    assert constraint(report, "puppet_select")["legal_targets"] == [2, 9, 11, 12]
    assert not report["issues"]
    second = derive_board_outcomes(source, 2, living_before_night=range(1, 13))
    assert constraint(second, "puppet_select")["status"] == "unavailable"


def test_puppet_seer_feedback_is_reversed_without_changing_observed_result():
    source = game("neighbor_puppet", {1: "预言家", 2: "狼人", 3: "女巫", 4: "猎人"}, [
        {"number": 1, "night": [event("puppet_select", "select", actor=2, targets=[1])], "day": []},
        {"number": 2, "night": [event("seer_check", "check", actor=1, targets=[2], result="werewolf")], "day": []},
    ])
    before = copy.deepcopy(source)

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3, 4])

    assert any(row["type"] == "expected_seer_feedback" and row["result"] == "good"
               for row in report["consequences"])
    assert any(row["code"] == "puppet_seer_feedback_conflict" for row in report["issues"])
    assert source == before


def test_puppet_effect_projection_keeps_first_night_timing_unknown():
    for role, action in [("预言家", "reverse_check"), ("猎人", "skill_disabled"), ("平民", "no_effect")]:
        source = game("neighbor_puppet", {1: "狼人", 2: role}, [
            {"number": 1, "night": [event("puppet_select", "select", targets=[2])], "day": []},
            {"number": 2, "night": [], "day": []},
        ])
        first = derive_board_outcomes(source, 1, living_before_night=[1, 2])
        second = derive_board_outcomes(source, 2, living_before_night=[1, 2])
        assert any(e["type"] == "puppet_effect" for e in first["consequences"]) == (role == "平民")
        assert next(e for e in second["consequences"] if e["type"] == "puppet_effect")["result"] == action
        assert constraint(second, "puppet_hunter_eligibility")["status"] == "unavailable"


def test_puppet_records_witch_action_as_ineffective_without_claiming_conflict():
    source = game("neighbor_puppet", {1: "狼人", 2: "女巫", 3: "平民"}, [
        {"number": 1, "night": [event("puppet_select", "select", actor=1, targets=[2])], "day": []},
        {"number": 2, "night": [event("witch_poison", "poison", actor=2, targets=[3])], "day": []},
    ])
    before = copy.deepcopy(source)

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3])

    observed = next(row for row in report["consequences"]
                    if row["type"] == "observed_ineffective_action")
    assert (observed["slot"], observed["actor"], observed["targets"]) == ("witch_poison", 2, [3])
    assert constraint(report, "witch_save")["status"] == "unavailable"
    assert not any(row["code"] == "puppet_disabled_skill_result_conflict" for row in report["issues"])
    assert source["seats"][1]["role"] == "女巫"
    assert source == before


def test_puppet_disabled_guard_reports_conflict_only_for_explicit_success_result():
    source = game("neighbor_puppet", {1: "狼人", 2: "守卫", 3: "平民"}, [
        {"number": 1, "night": [event("puppet_select", "select", actor=1, targets=[2])], "day": []},
        {"number": 2, "night": [event("guard", "guard", actor=2, targets=[3], result="protected")], "day": []},
    ])

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3])

    observed = next(row for row in report["consequences"]
                    if row["type"] == "observed_ineffective_action")
    assert (observed["slot"], observed["actor"], observed["targets"]) == ("guard", 2, [3])
    assert any(row["code"] == "puppet_disabled_skill_result_conflict"
               and row["observed_result"] == "protected" for row in report["issues"])


def test_masquerade_masked_faction_drives_dance_minority_and_protects_pool():
    source = game("s21_masquerade", {1: "舞者", 2: "假面", 3: "狼人", 4: "女巫"}, [
        {"number": 1, "night": [event("masquerade_mask", "pass"), event("dancer_dance", "pass")], "day": []},
        {"number": 2, "night": [
            event("masquerade_mask", "give_mask", actor=2, targets=[2], result="good"),
            event("dancer_dance", "dance", actor=1, targets=[1, 2, 3]),
            event("dance_resolution"),
            event("witch_poison", "poison", actor=4, targets=[2]),
            event("wolf_attack", "attack", actor=3, targets=[1]),
        ], "day": []},
    ])
    source["rounds"][1]["night"][2]["action"] = "no_death"
    before = copy.deepcopy(source)

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3, 4])

    result = next(row for row in report["consequences"] if row["type"] == "dance_result")
    assert (result["result"], result["expected_deaths"]) == ("minority_dies", [3])
    assert any(row["type"] == "poison_immunity" and row["seat"] == 2 for row in report["consequences"])
    assert any(row["type"] == "wolf_attack_blocked" and row["seats"] == [1] for row in report["consequences"])
    assert any(row["code"] == "dance_resolution_conflict" for row in report["issues"])
    assert source == before


def test_masquerade_does_not_resolve_dance_when_mask_faction_is_unknown():
    source = game("masquerade", {1: "舞者", 2: "平民", 3: "狼人"}, [{
        "number": 2, "night": [event("masquerade_mask", "give_mask", actor=3, targets=[2]),
                             event("dancer_dance", "dance", actor=1, targets=[1, 2, 3])], "day": []}])

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3])

    assert not any(row["type"] == "dance_result" for row in report["consequences"])
    assert any(row["code"] == "dance_mask_faction_unknown" for row in report["issues"])


def test_masquerade_same_faction_dance_has_no_extra_death_and_first_night_dance_is_unavailable():
    source = game("s23_masquerade", {1: "舞者", 2: "平民", 3: "预言家"}, [
        {"number": 1, "night": [event("masquerade_mask", "unavailable"),
                               event("masquerade_verify", "unavailable"),
                               event("dancer_dance", "unavailable")], "day": []},
        {"number": 2, "night": [event("masquerade_mask", "pass"),
                               event("masquerade_verify", "pass"),
                               event("dancer_dance", "dance", actor=1, targets=[1, 2, 3]),
                               event("dance_resolution")], "day": []},
    ], season="S23")

    first = derive_board_outcomes(source, 1, living_before_night=[1, 2, 3])
    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3])

    assert constraint(first, "dancer_dance")["status"] == "unavailable"
    assert not any(row["slot"] in {"masquerade_mask", "masquerade_verify"}
                   for row in first["constraints"])
    assert next(row for row in report["consequences"] if row["type"] == "dance_result")["result"] == "no_death"


def test_all_in_trade_pair_choice_resolves_mixed_trade_without_mutating_targets():
    source = game("s21_all_in", {1: "典狱长", 2: "女巫", 3: "平民", 4: "狼人"}, [
        {"number": 1, "night": [event("warden_trade_targets", "pass", actor=1),
                               event("trade_decisions", "pass")], "day": []},
        {"number": 2, "night": [event("warden_trade_targets", "select_pair", actor=1, targets=[2, 3]),
                               event("trade_decisions", "trade_betray", targets=[2, 3]),
                               event("trade_resolution")], "day": []},
    ])
    before = copy.deepcopy(source)

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3, 4])

    assert constraint(report, "warden_trade_targets")["status"] == "available"
    assert any(row["type"] == "expected_death" and row["seat"] == 2
               for row in report["consequences"])
    trade_result = next(row for row in report["consequences"] if row["type"] == "trade_result")
    assert (trade_result["result"], trade_result["targets"]) == ("betrayal_death", [2, 3])
    assert not any(event["slot"] == "night_deaths" for event in source["rounds"][1]["day"])
    assert source == before


def test_all_in_both_trade_are_immune_and_each_participant_is_used_once():
    source = game("all_in", {1: "典狱长", 2: "女巫", 3: "平民", 4: "狼人"}, [
        {"number": 1, "night": [event("warden_trade_targets", "pass", actor=1),
                               event("trade_decisions", "pass")], "day": []},
        {"number": 2, "night": [event("warden_trade_targets", "select_pair", actor=1, targets=[2, 3]),
                               event("trade_decisions", "trade", targets=[2, 3])], "day": []},
        {"number": 3, "night": [event("warden_trade_targets", "select_pair", actor=1, targets=[3, 4]),
                               event("trade_decisions", "trade_betray", targets=[3, 4])], "day": []},
    ])

    second = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3, 4])
    third = derive_board_outcomes(source, 3, living_before_night=[1, 2, 3, 4])

    assert any(row["type"] == "night_damage_immunity" and row["seats"] == [2, 3]
               for row in second["consequences"])
    assert constraint(third, "warden_trade_targets")["legal_targets"] == [1, 4]
    assert any(row["code"] == "warden_trade_participant_reused" for row in third["issues"])


def test_all_in_double_betray_reports_target_exchange_without_inventing_order():
    source = game("all_in", {1: "典狱长", 2: "预言家", 3: "女巫"}, [
        {"number": 1, "night": [event("warden_trade_targets", "pass"), event("trade_decisions", "pass")], "day": []},
        {"number": 2, "night": [
            event("warden_trade_targets", "select_pair", actor=1, targets=[2, 3]),
            event("trade_decisions", "betray", targets=[2, 3]),
            event("seer_check", "check", actor=2, targets=[3]),
            event("witch_poison", "poison", actor=3, targets=[2]),
        ], "day": []},
    ])
    before = copy.deepcopy(source)

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2, 3])

    exchange = next(row for row in report["consequences"] if row["type"] == "skill_target_exchange")
    assert exchange["seats"] == [2, 3]
    assert exchange["resolution_order"] == "unknown"
    assert source == before


def test_warden_pair_uses_same_vs_different_choice_exception():
    source = game("all_in", {1: "典狱长", 2: "狼人"}, [
        {"number": 1, "night": [event("warden_trade_targets", "pass"), event("trade_decisions", "pass")], "day": []},
        {"number": 2, "night": [event("warden_trade_targets", "select_pair", actor=1, targets=[1, 2]),
                               event("trade_decisions", "trade", targets=[1, 2])], "day": []},
    ])

    report = derive_board_outcomes(source, 2, living_before_night=[1, 2])

    assert any(row["type"] == "expected_death" and row["seat"] == 1
               and row["reason"] == "warden_same_choice" for row in report["consequences"])
    source["rounds"][1]["night"][1] = event("trade_decisions", "trade_betray", targets=[1, 2])
    different = derive_board_outcomes(source, 2, living_before_night=[1, 2])
    assert any(row["type"] == "expected_death" and row["seat"] == 2
               and row["reason"] == "warden_different_choice" for row in different["consequences"])


def _fox_round(number, mark_action, mark_targets=None, *, vote_action="pass", vote_targets=None,
               hunt_action="unknown", hunt_result=None, poison_targets=None,
               skill_action="unknown"):
    night = [event("nine_tail_mark", mark_action, actor=9, targets=mark_targets),
             event("whiteze_clear_mark", "pass"), event("whiteze_clear", "pass"),
             event("witch_poison", "poison", actor=5, targets=poison_targets or [])]
    day = [event("nine_tail_vote_mark", vote_action, actor=9, targets=vote_targets),
           event("nine_tail_hunt", hunt_action, actor=9, result=hunt_result),
           event("nine_tail_skill", skill_action, actor=9)]
    return {"number": number, "night": night, "day": day}


def test_fox_hunt_uses_cumulative_marks_strict_threshold_and_poison_immunity():
    source = game("s23_qingqiu_night", {
        1: "平民", 2: "预言家", 3: "平民", 4: "白泽", 5: "女巫",
        6: "平民", 7: "守卫", 8: "狼人", 9: "九尾狐",
    }, [
        _fox_round(1, "mark", [1]),
        _fox_round(2, "mark", [2], vote_action="mark", vote_targets=[2]),
        _fox_round(3, "pass", hunt_action="hunt", hunt_result="failure", poison_targets=[9],
                   vote_action="unknown"),
    ])

    report = derive_board_outcomes(source, 3, living_before_vote=[1, 2, 3, 5, 9])

    assert constraint(report, "nine_tail_hunt")["status"] == "available"
    outcome = next(row for row in report["consequences"] if row["type"] == "fox_hunt_result")
    assert outcome["result"] == "success"
    assert outcome["expected_deaths"] == [3, 5]
    assert any(row["type"] == "poison_immunity" and row["seat"] == 9 for row in report["consequences"])
    assert any(row["code"] == "fox_hunt_result_conflict" for row in report["issues"])


def test_fox_equality_fails_and_missing_living_set_is_not_assumed_alive():
    source = game("s23_qingqiu_night", {1: "平民", 2: "平民", 3: "狼人", 9: "九尾狐"}, [
        _fox_round(1, "mark", [1]), _fox_round(2, "pass", skill_action="attempt"),
    ])
    exact = derive_board_outcomes(source, 2, living_before_vote=[1, 2, 3, 9])
    assert constraint(exact, "nine_tail_hunt")["status"] == "unavailable"
    assert next(row for row in exact["consequences"] if row["type"] == "fox_hunt_result")["result"] == "failure"

    unknown = derive_board_outcomes(source, 2)
    assert constraint(unknown, "nine_tail_hunt")["status"] == "unknown"
    assert not any(row["type"] == "fox_hunt_result" for row in unknown["consequences"])


def test_s23_canonical_board_code_receives_fox_derivations():
    source = game("qingqiu_night", {1: "平民", 2: "九尾狐"}, [
        _fox_round(1, "pass", skill_action="attempt"),
    ], season="S23")

    report = derive_board_outcomes(source, 1, living_before_vote=[1, 2])

    assert constraint(report, "nine_tail_hunt")["status"] == "unavailable"

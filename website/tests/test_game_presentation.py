from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from website.api.game_presentation import build_game_presentation


ROOT = Path(__file__).resolve().parents[2]


def event(slot, action="unknown", *, actor=None, targets=None, result=None,
          effects=None, availability=None, description=None):
    return {
        "slot": slot,
        "action": action,
        "actor": actor,
        "targets": list(targets or []),
        "result": result,
        "description": description or f"记录槽：{slot}",
        "effects": deepcopy(effects or []),
        "availability": availability,
        "votes": [],
    }


def game(seats, rounds, *, board="mixed_blood", voting=None):
    return {
        "board": {"code": board, "name": board},
        "seats": [
            {"seat": seat, "role": role, "learned_role": learned_role}
            for seat, role, learned_role in seats
        ],
        "rounds": rounds,
        "voting": voting or {"days": [], "ballots": []},
    }


def get_event(presentation, number, phase, slot):
    round_ = next(row for row in presentation["rounds"] if row["number"] == number)
    return next((row for row in round_[phase] if row["slot"] == slot), None)


@pytest.mark.parametrize('board', ['mechanical_wolf_seer', 's21_mechanical_wolf_seer', 's23_mechanical_wolf_seer'])
@pytest.mark.parametrize('recorded_slot', [True, False])
def test_mechanical_knife_is_only_shown_on_nights_after_all_ordinary_wolves_depart(board, recorded_slot):
    def knife(action='unknown'):
        return [event('mechanical_knife_status', action, actor=12)] if recorded_slot else []
    source = game([(1, '狼人', None), (2, '狼人', None), (3, '狼人', None),
                   (5, '平民', None), (12, '机械狼', '机械平民')], [
        {'number': 1, 'night': knife('carrying'), 'day': [event('self_destruct', 'self_destruct', actor=1)]},
        {'number': 2, 'night': knife('not_carrying'), 'day': [event('night_deaths', 'die', targets=[2]),
                                                            event('exile_result', 'exile', targets=[3])]},
        {'number': 3, 'night': knife(), 'day': knife('carrying')},
        {'number': 4, 'night': knife('unavailable'), 'day': [event('exile_result', 'exile', targets=[12])]},
        {'number': 5, 'night': knife('carrying'), 'day': []},
    ], board=board)
    before = deepcopy(source)
    result = build_game_presentation(source)
    assert [(r['number'], e['action'], e['actor']) for r in result['rounds']
            for e in r['night'] if e['slot'] == 'mechanical_knife_status'] == [(3, 'carrying', 12), (4, 'carrying', 12)]
    assert all(e['slot'] != 'mechanical_knife_status' for r in result['rounds'] for e in r['day'])
    assert source == before


def test_mechanical_knife_does_not_use_current_night_deaths_or_unknown_departures():
    source = game([(1, '狼人', None), (2, '狼人', None), (3, '狼人', None), (12, '机械狼', None)], [
        {'number': 1, 'night': [], 'day': [event('night_deaths', 'die', targets=[1, 2])]},
        {'number': 2, 'night': [event('mechanical_knife_status', 'carrying', actor=12)],
         'day': [event('night_deaths', 'die', targets=[3])]},
        {'number': 3, 'night': [event('mechanical_knife_status', actor=12)], 'day': []},
    ], board='mechanical_wolf_seer')
    result = build_game_presentation(source)
    assert get_event(result, 2, 'night', 'mechanical_knife_status') is None
    assert get_event(result, 3, 'night', 'mechanical_knife_status')['action'] == 'carrying'
    source['rounds'][1]['day'][0].update(action='unknown', targets=[])
    assert get_event(build_game_presentation(source), 3, 'night', 'mechanical_knife_status') is None


def test_prepared_unavailability_hides_only_empty_template_slots():
    source = game([], [{'number': 2, 'night': [event('puppet_select')], 'day': []}], board='s21_neighbor_puppet')
    source['rules_state'] = {'slots': [{'round': 2, 'phase': 'night', 'slot': 'puppet_select',
                                       'status': 'unavailable', 'reason': 'puppet_selection_is_first_night_only'}]}
    assert build_game_presentation(source)['rounds'][0]['night'] == []
    source['rounds'][0]['night'][0].update(action='select', targets=[3])
    assert get_event(build_game_presentation(source), 2, 'night', 'puppet_select')['targets'] == [3]


def test_absent_hunter_placeholder_requires_complete_roster():
    source = game([(n, '平民', None) for n in range(1, 13)], [
        {'number': 1, 'night': [event('hunter_state')], 'day': []},
    ], board='treasure_master')
    assert get_event(build_game_presentation(source), 1, 'night', 'hunter_state') is None
    source['seats'][0]['role'] = None
    assert get_event(build_game_presentation(source), 1, 'night', 'hunter_state') is not None


def test_unknown_night_death_is_only_shown_once_in_its_day_phase():
    source = game([], [{'number': 1, 'night': [event('night_deaths')], 'day': [event('night_deaths')]}])
    result = build_game_presentation(source)
    assert get_event(result, 1, 'night', 'night_deaths') is None
    assert get_event(result, 1, 'day', 'night_deaths')['action'] == 'unknown'


@pytest.mark.parametrize("board", ["s21_mechanical_wolf_seer", "mechanical_wolf_seer", "s23_mechanical_wolf_seer"])
def test_shared_witch_projection_hides_the_other_unused_bottle_even_with_a_source_note(board):
    source = game([(7, "女巫", None)], [{"number": 1, "night": [
        event("witch_poison", "pass", actor=7, result="本夜压毒，复盘核实说明"),
        event("witch_save", "save", actor=7, targets=[5], result="女巫7号用药解救5号"),
    ], "day": []}], board=board)
    original = deepcopy(source)
    result = build_game_presentation(source)
    assert get_event(result, 1, "night", "witch_poison") is None
    assert get_event(result, 1, "night", "witch_save")["targets"] == [5]
    assert source == original


@pytest.mark.parametrize("morning", [True, False])
def test_shared_day_order_distinguishes_morning_and_post_exile_shots(morning):
    source = game([(6, "猎人", None)], [{"number": 1, "night": [], "day": [
        event("exile_result", "exile", targets=[11 if morning else 6]),
        event("hunter_shot", "shoot", actor=6, targets=[10]),
        event("night_deaths", "die" if morning else "peaceful", targets=[6] if morning else []),
    ]}], board="s21_mechanical_wolf_seer")
    slots = [e["slot"] for e in build_game_presentation(source)["rounds"][0]["day"]]
    assert slots.index("night_deaths") < slots.index("exile_result")
    assert (slots.index("hunter_shot") < slots.index("exile_result")) == morning


def test_common_display_labels_and_results_preserve_source_notes_outside_the_display_text():
    source = game([(4, "守卫", None), (9, "通灵师", None)], [{"number": 1, "night": [
        {**event("guard", "pass", actor=4, result="首位通过按守卫空过的ASR同音转写保存"), "slot_label": "旧守卫槽"},
        event("seer_check", "check", actor=9, targets=[12], result="通灵师9号验证12号为平民"),
    ], "day": []}], board="s21_mechanical_wolf_seer")
    original = deepcopy(source)
    result = build_game_presentation(source)
    guard = get_event(result, 1, "night", "guard")
    assert guard["slot_label"] == "守卫守护"
    assert guard["display_result"] is None
    assert get_event(result, 1, "night", "seer_check")["display_result"] == "平民"
    assert source == original


def test_real_s23_untriggered_hunter_and_no_self_destruct_slots_are_hidden():
    folder = next((ROOT / 'data/games/S23').glob('*BV17QJh6qEur'))
    source = json.loads((folder / 'dossier.json').read_text(encoding='utf-8'))
    before = deepcopy(source)
    presentation = build_game_presentation(source)
    for number in (1, 2):
        assert get_event(presentation, number, 'day', 'hunter_shot') is None
        assert get_event(presentation, number, 'day', 'self_destruct')['action'] == 'self_destruct'
    assert get_event(presentation, 3, 'day', 'hunter_shot')['action'] == 'shoot'
    assert get_event(presentation, 3, 'day', 'exile_result')['action'] == 'exile'
    assert get_event(presentation, 3, 'day', 'self_destruct') is None
    assert source == before


def test_unavailable_hunter_explanations_and_actual_outcomes_remain_visible():
    for result, flags in [
        ('猎人中毒，不能开枪', {}),
        ('最后一神出局，对局结束', {'blocked_by_game_end': True}),
    ]:
        shot = event('hunter_shot', 'unavailable', actor=6, result=result)
        shot.update(flags)
        source = game([(6, '猎人', None)], [{'number': 1, 'night': [], 'day': [shot]}])
        assert get_event(build_game_presentation(source), 1, 'day', 'hunter_shot') is not None


def test_untriggered_unavailable_shots_are_hidden_but_death_trigger_is_preserved():
    source = game([(6, '猎人', None)], [{'number': 1, 'night': [], 'day': [
        event('hunter_shot', 'unavailable', actor=6),
    ]}])
    assert get_event(build_game_presentation(source), 1, 'day', 'hunter_shot') is None
    source['rounds'][0]['day'].append(event('night_deaths', 'die', targets=[6]))
    assert get_event(build_game_presentation(source), 1, 'day', 'hunter_shot') is not None


def test_initial_sheriff_signup_is_only_displayed_by_the_voting_panel():
    source = game([], [{'number': 1, 'night': [], 'day': [
        event('sheriff_candidates', 'register', targets=[1, 2, 3]),
    ]}])
    source['voting'] = {'registrations': [{'day': 1, 'on_police': [1, 2, 3], 'off_police': [4]}]}
    assert get_event(build_game_presentation(source), 1, 'day', 'sheriff_candidates') is None
    source['rounds'][0]['day'][0]['targets'] = [1, 2]
    assert get_event(build_game_presentation(source), 1, 'day', 'sheriff_candidates') is not None


def test_inactive_mechanical_slots_are_omitted_and_learned_form_is_shared():
    source = game([(11, '机械狼', None)], [
        {'number': 1, 'night': [event('mechanical_action', 'learn', actor=11, targets=[3],
                                    result='机械狼11号首夜模仿3号狼人同伴，复盘说明为机械双刀版型')], 'day': []},
        {'number': 2, 'night': [event('mechanical_action', 'unavailable')],
         'day': [event('mechanical_day_skill', 'unavailable')]},
    ])
    presentation = build_game_presentation(source)
    assert get_event(presentation, 1, 'night', 'mechanical_action')['display_result'] == '机械双刀狼人'
    assert presentation['rounds'][1]['night'] == []
    assert presentation['rounds'][1]['day'] == []


def test_real_s23_explicit_terminal_hides_d4_and_keeps_the_final_double_death():
    folder = next((ROOT / 'data/games/S23').glob('*BV17QJh6qEid'))
    source = json.loads((folder / 'dossier.json').read_text(encoding='utf-8'))
    before = deepcopy(source)
    presentation = build_game_presentation(source)
    assert get_event(presentation, 1, 'night', 'night_deaths') is None
    assert get_event(presentation, 1, 'day', 'night_deaths')['action'] == 'peaceful'
    assert presentation['rounds'][-1]['day'] == []
    terminal = presentation['terminal']
    assert (terminal['round'], terminal['phase']) == (4, 'night')
    assert [(e['slot'], e['targets']) for e in terminal['events']] == [('night_deaths', [3, 7])]
    assert terminal['events'][0]['terminal'] is True
    assert get_event(presentation, 4, 'night', 'night_deaths') is None
    assert source == before


def test_exchange_settlement_resolves_the_seer_feedback_and_actual_knife():
    source = game(
        [(2, "预言家", None), (4, "狼人", None), (6, "魔术师", None)],
        [{"number": 2, "night": [
            event("wolf_attack", "attack", targets=[6]),
            event("seer_check", "check", actor=2, targets=[4]),
            event("magician_exchange", "exchange", actor=6, targets=[4, 6],
                  result="魔术师交换4号与6号，狼刀原6实际4，查验实际到6号魔术师"),
        ], "day": [event("night_deaths", "die", targets=[4])]}],
        board="guile_realm",
    )
    before = deepcopy(source)
    presentation = build_game_presentation(source)
    seer = get_event(presentation, 2, "night", "seer_check")
    assert seer["result"] == "good"
    assert seer["targets"] == [4]
    assert seer["resolved_targets"] == [6]
    assert get_event(presentation, 2, "night", "wolf_attack")["resolved_targets"] == [4]
    assert source == before


def test_later_poison_use_proves_an_earlier_living_witch_held_poison():
    source = game(
        [(11, "女巫", None)],
        [
            {"number": 2, "night": [event("witch_poison", actor=11)],
             "day": [event("night_deaths", "die", targets=[4])]},
            {"number": 4, "night": [event("witch_poison", "poison", actor=11, targets=[1])],
             "day": [event("night_deaths", "die", targets=[1, 2])]},
        ],
    )
    before = deepcopy(source)
    held = get_event(build_game_presentation(source), 2, "night", "witch_poison")
    assert held["action"] == "pass"
    assert held["actor"] == 11
    assert held["inferred"] is True
    assert "第4夜" in held["inference_note"]
    assert source == before


def test_badge_none_is_lost_after_a_confirmed_deferred_election_is_interrupted():
    source = game([], [{"number": 2, "night": [], "day": [
        event("badge", "none"), event("self_destruct", "self_destruct", actor=4),
    ]}], voting={"days": [{"day": 1, "sheriff": "deferred"},
                           {"day": 2, "sheriff": "badge_lost"}]})
    before = deepcopy(source)
    badge = get_event(build_game_presentation(source), 2, "day", "badge")
    assert badge["action"] == "badge_lost"
    assert source == before


def test_exchange_inference_requires_explicit_nonconflicting_settlement():
    source = game(
        [(2, "预言家", None), (4, "狼人", None), (6, "魔术师", None)],
        [{"number": 1, "night": [
            event("seer_check", "check", actor=2, targets=[4]),
            event("magician_exchange", "exchange", actor=6, targets=[4, 6]),
        ], "day": []}], board="guile_realm",
    )
    assert get_event(build_game_presentation(source), 1, "night", "seer_check")["result"] is None

    exchange = source["rounds"][0]["night"][1]
    exchange["result"] = "查验实际到6号魔术师"
    source["rounds"][0]["night"].append(event("guile_exchange", "exchange", actor=9, targets=[6, 4]))
    assert get_event(build_game_presentation(source), 1, "night", "seer_check")["result"] is None

    source["rounds"][0]["night"].pop()
    source["rounds"][0]["night"][0]["result"] = "狼人"
    recorded = get_event(build_game_presentation(source), 1, "night", "seer_check")
    assert recorded["result"] == "狼人"
    assert "resolved_targets" not in recorded


def test_held_poison_requires_the_same_witch_and_a_valid_single_later_use():
    source = game([(11, "女巫", None), (12, "女巫", None)], [
        {"number": 2, "night": [event("witch_poison", actor=11)], "day": []},
        {"number": 4, "night": [event("witch_poison", "poison", actor=11, targets=[1])], "day": []},
    ])
    for variant in ("different_witch", "dead_before_use", "repeated_use", "no_later_use", "conflicting_save", "ballot_exiled"):
        uncertain = deepcopy(source)
        if variant == "different_witch":
            uncertain["rounds"][1]["night"][0]["actor"] = 12
        elif variant == "dead_before_use":
            uncertain["rounds"][0]["day"] = [event("night_deaths", "die", targets=[11])]
        elif variant == "repeated_use":
            uncertain["rounds"].append({"number": 5, "night": [event("witch_poison", "poison", actor=11, targets=[2])], "day": []})
        elif variant == "no_later_use":
            uncertain["rounds"][1]["night"] = []
        elif variant == "conflicting_save":
            uncertain["rounds"][1]["night"].append(event("witch_save", "save", actor=11, targets=[2]))
        else:
            uncertain["rounds"][0]["day"] = [event("exile_result")]
            uncertain["voting"] = {"days": [{"day": 2, "exile": "recorded"}], "ballots": [
                {"day": 2, "kind": "exile", "status": "complete", "winner": 11},
            ]}
        held = get_event(build_game_presentation(uncertain), 2, "night", "witch_poison")
        assert held["action"] == "unknown", variant


def test_real_guile_game_links_exchange_poison_history_and_badge():
    folder = next((ROOT / "data/games/S22").glob("*BV1jM8B6jEkF"))
    source = json.loads((folder / "dossier.json").read_text(encoding="utf-8"))
    source["voting"] = json.loads((folder / "voting.json").read_text(encoding="utf-8"))
    before = deepcopy(source)
    presentation = build_game_presentation(source)
    seer = get_event(presentation, 2, "night", "seer_check")
    assert seer["targets"] == [4] and seer["resolved_targets"] == [6]
    assert seer["result"] == "good"
    assert get_event(presentation, 2, "day", "badge")["action"] == "badge_lost"
    assert get_event(presentation, 1, "night", "witch_poison") is None
    for number in (2, 3):
        assert get_event(presentation, number, "night", "witch_poison")["action"] == "pass"
    assert get_event(presentation, 4, "night", "witch_poison")["action"] == "poison"
    assert source == before


def test_other_real_games_share_exchange_and_poisoner_inference():
    for bvid, number, slot, actual in [
        ("BV1W6jG6HELj", 3, "seer_check", 8),
        ("BV1hZMp63Esx", 2, "witch_poison", 8),
    ]:
        folder = next((ROOT / "data/games/S22").glob(f"*{bvid}"))
        source = json.loads((folder / "dossier.json").read_text(encoding="utf-8"))
        source["voting"] = json.loads((folder / "voting.json").read_text(encoding="utf-8"))
        before = deepcopy(source)
        action = get_event(build_game_presentation(source), number, "night", slot)
        assert action["resolved_targets"] == [actual], bvid
        if slot == "seer_check":
            assert action["result"] == "good"
        assert source == before

    folder = next((ROOT / "data/games/S22").glob("*BV1aXgW6nE6E"))
    source = json.loads((folder / "dossier.json").read_text(encoding="utf-8"))
    presentation = build_game_presentation(source)
    assert get_event(presentation, 1, "night", "witch_poison")["action"] == "pass"
    assert get_event(presentation, 1, "night", "witch_poison")["slot_label"] == "毒师毒药"
    assert get_event(presentation, 2, "night", "seer_check")["result"] == "平民"
    assert next(seat for seat in source["seats"] if seat["seat"] == 7)["role"] == "盗宝大师"


def test_empty_poison_slot_is_hidden_when_all_dealt_roles_exclude_a_poisoner():
    source = game([(number, "平民", None) for number in range(1, 13)], [
        {"number": 1, "night": [event("witch_poison")], "day": []},
    ], board="treasure_master")
    assert get_event(build_game_presentation(source), 1, "night", "witch_poison") is None
    source["seats"][0]["role"] = None
    assert get_event(build_game_presentation(source), 1, "night", "witch_poison") is not None


def test_mixed_board_double_death_resolves_the_only_extra_poison_victim():
    source = game([(10, "女巫", None), (3, "预言家", None), (11, "狼人", None)], [
        {"number": 2, "night": [event("wolf_attack", "attack", targets=[3]), event("witch_poison")],
         "day": [event("night_deaths", "die", targets=[3, 11])]},
        {"number": 3, "night": [event("witch_poison")], "day": []},
    ])
    before = deepcopy(source)
    presentation = build_game_presentation(source)
    poison = get_event(presentation, 2, "night", "witch_poison")
    assert poison["action"] == "poison" and poison["targets"] == [11] and poison["actor"] == 10
    assert get_event(presentation, 3, "night", "witch_poison") is None
    assert source == before

    for variant in ("single_death", "other_mechanics", "conflicting_later_use"):
        unresolved = deepcopy(source)
        if variant == "single_death":
            unresolved["rounds"][0]["day"][0]["targets"] = [3]
        elif variant == "other_mechanics":
            unresolved["board"]["code"] = "mechanical_wolf_seer"
        else:
            unresolved["rounds"][1]["night"] = [event("witch_poison", "poison", actor=10, targets=[11])]
        poison = get_event(build_game_presentation(unresolved), 2, "night", "witch_poison")
        assert poison["action"] != "poison", variant


def test_same_night_bottle_limit_does_not_spend_the_other_bottle():
    source = game(
        [(4, "女巫", None), (6, "猎人", None), (9, "混血儿", None)],
        [
            {
                "number": 1,
                "night": [
                    event("witch_save", "save", actor=4, targets=[9]),
                    event("witch_poison", actor=4),
                    event("hunter_state", actor=6),
                    event("wolf_attack", "attack", targets=[9]),
                ],
                "day": [],
            },
            {
                "number": 2,
                "night": [
                    event("witch_save", actor=4),
                    event("witch_poison", actor=4),
                    event("hunter_state", actor=6),
                    event("wolf_attack", "attack", targets=[1]),
                ],
                "day": [],
            },
        ],
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "night", "witch_poison") is None
    first_hunter = get_event(presentation, 1, "night", "hunter_state")
    assert first_hunter["action"] == "can_shoot"
    assert first_hunter["inferred"] is True
    assert "唯一" in first_hunter["inference_note"]
    # The antidote was spent, but the poison remains an unknown live option.
    assert get_event(presentation, 2, "night", "witch_save") is None
    assert get_event(presentation, 2, "night", "witch_poison")["action"] == "unknown"
    assert get_event(presentation, 2, "night", "hunter_state")["action"] == "unknown"


def test_spent_bottle_unavailable_marker_is_also_omitted_without_hiding_new_action():
    source = game([(4, "女巫", None)], [
        {"number": 1, "night": [event("witch_save", "save", actor=4, targets=[9])], "day": []},
        {"number": 2, "night": [event("witch_save", "unavailable", actor=4), event("witch_poison", "poison", actor=4, targets=[5])], "day": []},
    ])
    result = build_game_presentation(source)
    assert get_event(result, 2, "night", "witch_save") is None
    assert get_event(result, 2, "night", "witch_poison")["targets"] == [5]


def test_poisoning_uses_only_the_poison_bottle_and_leaves_antidote_available():
    source = game(
        [(4, "女巫", None), (6, "猎人", None)],
        [
            {
                "number": 1,
                "night": [
                    event("witch_poison", "poison", actor=4, targets=[8],
                          effects=[{"kind": "poison", "intended_target": 8, "dead_seat": 8}]),
                    event("witch_save", actor=4),
                    event("hunter_state", actor=6),
                ],
                "day": [],
            },
            {
                "number": 2,
                "night": [
                    event("witch_poison", actor=4),
                    event("witch_save", actor=4),
                    event("hunter_state", actor=6),
                ],
                "day": [],
            },
        ],
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "night", "witch_save") is None
    assert get_event(presentation, 1, "night", "witch_poison")["action"] == "poison"
    # Poison use does not consume the antidote; this empty save slot stays
    # available for review on the next night.
    assert get_event(presentation, 2, "night", "witch_save")["action"] == "unknown"
    assert get_event(presentation, 2, "night", "witch_poison") is None
    assert presentation["omitted_events"] == 2


def test_dead_roles_are_removed_from_later_nights_without_losing_facts():
    source = game(
        [
            (6, "猎人", None), (7, "预言家", None), (8, "白神", None),
            (10, "机械狼", "机械双刀狼"),
        ],
        [
            {
                "number": 1,
                "night": [
                    event("wolf_attack", "attack", targets=[8]),
                    event("seer_check", "check", actor=7, targets=[6]),
                ],
                "day": [
                    event("night_deaths", "die", targets=[6]),
                    event("hunter_shot", "shoot", actor=6, targets=[11]),
                    event("exile_result", "exile", targets=[7]),
                    event("self_destruct", "self_destruct", actor=10),
                    event("white_god_reveal", "reveal", actor=8),
                ],
            },
            {
                "number": 2,
                "night": [
                    event("seer_check", actor=7),
                    event("mechanical_action", actor=10),
                    event("white_god_reveal", actor=8),
                    event("hunter_state", actor=6),
                    event("wolf_attack", "attack", targets=[8]),
                ],
                "day": [],
            },
        ],
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "night", "wolf_attack")["targets"] == [8]
    assert get_event(presentation, 1, "day", "hunter_shot")["action"] == "shoot"
    assert get_event(presentation, 2, "night", "seer_check") is None
    assert get_event(presentation, 2, "night", "mechanical_action") is None
    # The day 1 wolf target was not a death, and flipping the White God was not a death.
    assert get_event(presentation, 2, "night", "white_god_reveal") is None
    assert get_event(presentation, 2, "night", "wolf_attack")["targets"] == [8]
    assert get_event(presentation, 2, "night", "hunter_state") is None


def test_real_s23_seer_slots_end_after_the_confirmed_d2_death():
    folder = next((ROOT / 'data/games/S23').glob('*BV17QJh6qEid'))
    source = json.loads((folder / 'dossier.json').read_text(encoding='utf-8'))
    before = deepcopy(source)
    presentation = build_game_presentation(source)
    assert get_event(presentation, 2, 'night', 'seer_check')['actor'] == 6
    assert get_event(presentation, 2, 'day', 'night_deaths')['targets'] == [6]
    for number in (3, 4):
        assert get_event(presentation, number, 'night', 'seer_check') is None
    assert source == before


@pytest.mark.parametrize('slot,role', [
    ('seer_check', '预言家'), ('seer_check', '通灵师'), ('guard', '守卫'),
    ('witch_save', '女巫'), ('witch_poison', '毒师'), ('hunter_state', '猎人'),
    ('mechanical_knife_status', '机械狼'), ('mechanical_action', '机械狼'),
    ('magician_exchange', '魔术师'), ('sorcerer_exchange', '狼术师'),
    ('magic_duel_magician_swap', '魔术师'), ('magic_duel_wolf_sorcerer_swap', '狼术师'),
    ('masquerade_verify', '假面'), ('dancer_dance', '舞者'), ('dreamer_action', '摄梦人'),
    ('nine_tail_mark', '九尾狐'), ('whiteze_clear_mark', '白泽'),
])
def test_role_owned_slots_without_an_actor_do_not_return_after_departure(slot, role):
    source = game([(6, role, None)], [
        {'number': 1, 'night': [], 'day': [event('night_deaths', 'die', targets=[6])]},
        {'number': 2, 'night': [event(slot), event(slot, 'unavailable'), event(slot, 'pass')], 'day': []},
    ])
    before = deepcopy(source)
    assert build_game_presentation(source)['rounds'][1]['night'] == []
    assert source == before


def test_anonymous_slot_owner_must_be_unique_and_death_triggered_skills_remain():
    source = game([(6, '猎人', None), (7, '狼王', None)], [
        {'number': 1, 'night': [], 'day': [
            event('night_deaths', 'die', targets=[6, 7]),
            event('hunter_shot', 'shoot', actor=6, targets=[3]),
            event('wolf_king_shot', 'shoot', actor=7, targets=[4]),
        ]},
        {'number': 2, 'night': [event('hunter_state'), event('wolf_king_state')], 'day': [event('wolf_king_shot')]},
    ])
    presentation = build_game_presentation(source)
    assert get_event(presentation, 1, 'day', 'hunter_shot')['targets'] == [3]
    assert get_event(presentation, 1, 'day', 'wolf_king_shot')['targets'] == [4]
    assert presentation['rounds'][1]['night'] == []
    assert presentation['rounds'][1]['day'] == []

    ambiguous = game([(6, '预言家', None), (7, '通灵师', None)], [
        {'number': 1, 'night': [], 'day': [event('night_deaths', 'die', targets=[6])]},
        {'number': 2, 'night': [event('seer_check')], 'day': []},
    ])
    assert get_event(build_game_presentation(ambiguous), 2, 'night', 'seer_check') is not None


def test_hunter_who_shot_does_not_return_for_a_later_night_slot():
    source = game(
        [(6, "猎人", None), (9, "平民", None)],
        [
            {"number": 1, "night": [], "day": [
                event("hunter_shot", "shoot", actor=6, targets=[9]),
            ]},
            {"number": 2, "night": [
                event("hunter_state", actor=6),
                event("wolf_attack", "attack", targets=[1]),
            ], "day": []},
        ],
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "day", "hunter_shot")["action"] == "shoot"
    assert get_event(presentation, 2, "night", "hunter_state") is None


def test_empty_optional_unknown_slots_are_omitted_but_actual_events_remain():
    source = game(
        [
            (2, "狼人", None), (6, "猎人", None),
            (8, "白神", None), (9, "混血儿", None),
        ],
        [
            {"number": 1, "night": [
                event("mixed_blood_model", "choose", actor=9, targets=[2]),
                event("mixed_blood_alignment", "wolf", actor=9),
            ], "day": [
                event("hunter_shot", actor=6),
                event("white_god_reveal", actor=8),
                event("self_destruct", actor=2),
                event("white_god_reveal", "reveal", actor=8),
                event("self_destruct", "self_destruct", actor=2),
            ]},
            {"number": 2, "night": [
                event("mixed_blood_model", actor=9),
                event("mixed_blood_alignment", actor=9),
            ], "day": []},
        ],
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "day", "hunter_shot") is None
    assert get_event(presentation, 1, "day", "white_god_reveal")["action"] == "reveal"
    assert get_event(presentation, 1, "day", "self_destruct")["action"] == "self_destruct"
    assert get_event(presentation, 2, "night", "mixed_blood_model") is None
    assert get_event(presentation, 2, "night", "mixed_blood_alignment") is None


def test_poison_reflection_uses_effect_dead_seat_not_original_target():
    source = game(
        [(1, "女巫", None), (2, "机械狼", "机械守卫"), (3, "猎人", None)],
        [
            {
                "number": 1,
                "night": [
                    event("witch_poison", "poison", actor=1, targets=[3], effects=[
                        {
                            "kind": "poison_reflected",
                            "intended_target": 3,
                            "dead_seat": 1,
                            "shield_actor": 2,
                        },
                    ]),
                    event("mechanical_action", "guard", actor=2, targets=[3]),
                    event("hunter_state", actor=3),
                ],
                "day": [event("night_deaths", "die", targets=[1])],
            },
            {
                "number": 2,
                "night": [
                    event("hunter_state", actor=3),
                    event("wolf_attack", "attack", targets=[3]),
                ],
                "day": [],
            },
        ],
        board="mechanical_wolf_seer",
    )

    presentation = build_game_presentation(source)

    first_hunter = get_event(presentation, 1, "night", "hunter_state")
    assert first_hunter["action"] == "can_shoot"
    assert first_hunter["inferred"] is True
    rebound = get_event(presentation, 1, "night", "witch_poison")
    assert rebound["effects"][0]["dead_seat"] == 1
    assert get_event(presentation, 2, "night", "hunter_state")["action"] == "can_shoot"


def test_mechanical_witch_poison_effect_can_disable_hunter():
    source = game(
        [(1, "女巫", None), (2, "机械狼", "机械女巫"), (6, "猎人", None)],
        [{
            "number": 1,
            "night": [
                event("witch_poison", "pass", actor=1),
                event("mechanical_action", "poison", actor=2, targets=[3], effects=[
                    {"kind": "poison", "intended_target": 3, "dead_seat": 6},
                ]),
                event("hunter_state", actor=6),
            ],
            "day": [event("night_deaths", "die", targets=[6])],
        }],
        board="mechanical_wolf_seer",
    )

    hunter = get_event(build_game_presentation(source), 1, "night", "hunter_state")

    assert hunter["action"] == "cannot_shoot"
    assert hunter["inferred"] is True
    assert "毒药结算确认命中" in hunter["inference_note"]


def test_mechanical_witch_target_and_night_deaths_resolve_without_effects():
    source = game(
        [(1, "女巫", None), (2, "机械狼", "机械女巫"), (6, "猎人", None)],
        [{
            "number": 1,
            "night": [
                event("witch_poison", "pass", actor=1),
                event("mechanical_action", "poison", actor=2, targets=[3]),
                event("hunter_state", actor=6),
            ],
            "day": [event("night_deaths", "die", targets=[3])],
        }],
        board="mechanical_wolf_seer",
    )

    hunter = get_event(build_game_presentation(source), 1, "night", "hunter_state")

    assert hunter["action"] == "can_shoot"
    assert hunter["inferred"] is True


def test_puppet_hunter_and_explicit_unavailable_are_not_promoted_to_can_shoot():
    source = game(
        [(4, "女巫", None), (7, "猎人", None)],
        [{
            "number": 1,
            "night": [
                event("puppet_select", "select", targets=[7]),
                event("witch_save", "save", actor=4, targets=[2]),
                event("witch_poison", actor=4),
                event("puppet_skill_effect", "skill_disabled", result="7号底牌猎人成为傀儡，技能失效"),
                event("hunter_state", actor=7),
            ],
            "day": [event("puppet_hunter_eligibility", "unknown", actor=7)],
        }],
        board="neighbor_puppet",
    )

    presentation = build_game_presentation(source)
    unknown_hunter = get_event(presentation, 1, "night", "hunter_state")
    assert unknown_hunter["action"] == "unknown"
    assert "inferred" not in unknown_hunter

    source["rounds"][0]["night"][-1]["action"] = "unavailable"
    explicit_unavailable = get_event(build_game_presentation(source), 1, "night", "hunter_state")
    assert explicit_unavailable["action"] == "unavailable"
    assert "inferred" not in explicit_unavailable

    source["rounds"][0]["night"][-1]["action"] = "cannot_shoot"
    explicit_cannot = get_event(build_game_presentation(source), 1, "night", "hunter_state")
    assert explicit_cannot["action"] == "cannot_shoot"
    assert "inferred" not in explicit_cannot


def test_unresolved_poison_or_death_cause_does_not_infer_hunter_eligibility():
    source = game(
        [(4, "女巫", None), (6, "猎人", None)],
        [{
            "number": 1,
            "night": [
                event("witch_poison", "poison", actor=4, targets=[6]),
                event("hunter_state", actor=6),
                event("wolf_attack", "unknown"),
            ],
            "day": [event("night_deaths", "unknown")],
        }],
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "night", "hunter_state")["action"] == "unknown"
    assert get_event(presentation, 1, "night", "wolf_attack")["action"] == "unknown"
    assert get_event(presentation, 1, "day", "night_deaths")["action"] == "unknown"


def test_voting_records_omit_interrupted_exile_and_infer_completed_winner():
    source = game(
        [(2, "狼人", None), (9, "平民", None)],
        [
            {"number": 1, "night": [], "day": [
                event("self_destruct", "self_destruct", actor=2),
                event("exile_result"),
                event("sheriff_candidates"),
            ]},
            {"number": 2, "night": [], "day": [event("exile_result")]},
            {"number": 3, "night": [], "day": [event("exile_result")]},
        ],
        voting={
            "days": [
                {"day": 1, "exile": "interrupted_self_destruct"},
                {"day": 2, "exile": "recorded"},
                {"day": 3, "exile": "recorded"},
            ],
            "ballots": [
                {"day": 2, "kind": "exile", "number": 1,
                 "status": "complete", "winner": 9},
                {"day": 3, "kind": "exile", "number": 1,
                 "status": "complete", "winner": 2},
                {"day": 3, "kind": "exile", "number": 2,
                 "status": "partial", "winner": None},
            ],
        },
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "day", "exile_result") is None
    assert get_event(presentation, 1, "day", "sheriff_candidates") is None
    exile = get_event(presentation, 2, "day", "exile_result")
    assert exile["action"] == "exile"
    assert exile["targets"] == [9]
    assert exile["inferred"] is True
    assert "完整放逐票" in exile["inference_note"]
    unresolved = get_event(presentation, 3, "day", "exile_result")
    assert unresolved["action"] == "unknown"
    assert "inferred" not in unresolved


def test_ballot_inferred_exile_removes_player_from_the_next_night():
    source = game(
        [(3, "预言家", None), (9, "平民", None)],
        [
            {"number": 1, "night": [], "day": [event("exile_result")]},
            {"number": 2, "night": [event("seer_check", actor=3)], "day": []},
        ],
        voting={
            "days": [{"day": 1, "exile": "recorded"}],
            "ballots": [{
                "day": 1, "kind": "exile", "number": 1,
                "status": "complete", "winner": 3,
            }],
        },
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "day", "exile_result")["targets"] == [3]
    assert get_event(presentation, 2, "night", "seer_check") is None


def test_double_tie_means_no_exile_and_both_candidates_can_act_next_night():
    source = game(
        [(3, "预言家", None), (4, "女巫", None)],
        [
            {"number": 1, "night": [], "day": [event("exile_result")]},
            {"number": 2, "night": [
                event("seer_check", actor=3), event("witch_save", actor=4),
            ], "day": []},
        ],
        voting={
            "days": [{"day": 1, "exile": "recorded"}],
            "ballots": [
                {"day": 1, "kind": "exile", "number": 1, "stage": "initial",
                 "status": "complete", "winner": None, "tied_candidates": []},
                {"day": 1, "kind": "exile", "number": 2, "stage": "pk",
                 "status": "complete", "winner": None, "tied_candidates": [3, 4]},
            ],
        },
    )
    before = deepcopy(source)

    presentation = build_game_presentation(source)

    exile = get_event(presentation, 1, "day", "exile_result")
    assert exile["action"] == "none"
    assert exile["targets"] == []
    assert exile["result"] == "double_tie"
    assert get_event(presentation, 2, "night", "seer_check") is not None
    assert get_event(presentation, 2, "night", "witch_save") is not None
    assert source == before

    already_recorded = deepcopy(source)
    already_recorded["rounds"][0]["day"] = [event("exile_result", "none")]
    already_recorded["voting"]["days"][0]["exile"] = "not_held"
    assert get_event(build_game_presentation(already_recorded), 1, "day", "exile_result")["action"] == "none"

    # A single tie, incomplete PK, sheriff tie, or later unresolved revote
    # does not establish that the final exile outcome is no elimination.
    for variant in ("single", "partial", "sheriff", "later_vote", "initial_winner"):
        unresolved = deepcopy(source)
        ballots = unresolved["voting"]["ballots"]
        if variant == "single":
            del ballots[-1]
        elif variant == "partial":
            ballots[-1]["status"] = "partial"
        elif variant == "sheriff":
            for ballot in ballots:
                ballot["kind"] = "sheriff"
        elif variant == "later_vote":
            ballots.append({"day": 1, "kind": "exile", "number": 3,
                            "stage": "skill_revote", "status": "partial"})
        else:
            ballots[0]["winner"] = 3
        result = get_event(build_game_presentation(unresolved), 1, "day", "exile_result")
        assert result["action"] == "unknown", variant


def test_real_double_ties_have_an_explicit_no_exile_result():
    for bvid, day in [("BV1pGVC6cEbW", 4), ("BV18ijD6BExE", 2),
                      ("BV1TDun6wEqw", 1), ("BV1jM8B6jEkF", 4)]:
        folder = next((ROOT / "data/games/S22").glob(f"*{bvid}"))
        source = json.loads((folder / "dossier.json").read_text(encoding="utf-8"))
        source["voting"] = json.loads((folder / "voting.json").read_text(encoding="utf-8"))
        before = deepcopy(source)

        result = get_event(build_game_presentation(source), day, "day", "exile_result")

        assert result["action"] == "none", bvid
        assert result["targets"] == [], bvid
        assert result["result"] == "double_tie", bvid
        assert source == before, bvid


def test_unknown_hunter_shot_is_kept_for_dead_eligible_or_unresolved_hunter():
    known_eligible = game(
        [(6, "猎人", None)],
        [{
            "number": 1,
            "night": [event("hunter_state", "can_shoot", actor=6)],
            "day": [
                event("night_deaths", "die", targets=[6]),
                event("hunter_shot", actor=6),
            ],
        }],
    )
    known_hunter = get_event(build_game_presentation(known_eligible), 1, "day", "hunter_shot")
    assert known_hunter["action"] == "unknown"
    assert known_hunter["inferred"] is True
    assert "具备开枪资格" in known_hunter["inference_note"]

    unresolved = game(
        [(4, "女巫", None), (6, "猎人", None)],
        [{
            "number": 1,
            "night": [
                event("witch_poison", actor=4),
                event("hunter_state", actor=6),
            ],
            "day": [
                event("night_deaths", "die", targets=[6]),
                event("hunter_shot", actor=6),
            ],
        }],
    )
    pending_hunter = get_event(build_game_presentation(unresolved), 1, "day", "hunter_shot")
    assert pending_hunter["action"] == "unknown"
    assert pending_hunter["inferred"] is True
    assert "仍待核" in pending_hunter["inference_note"]


def test_empty_hunter_shot_is_omitted_when_poison_proves_hunter_cannot_shoot():
    source = game(
        [(4, "女巫", None), (6, "猎人", None)],
        [{
            "number": 1,
            "night": [
                event("witch_poison", "poison", actor=4, targets=[6],
                      effects=[{"kind": "poison", "dead_seat": 6}]),
                event("hunter_state", actor=6),
            ],
            "day": [
                event("night_deaths", "die", targets=[6]),
                event("hunter_shot", actor=6),
            ],
        }],
    )

    presentation = build_game_presentation(source)

    assert get_event(presentation, 1, "night", "hunter_state")["action"] == "cannot_shoot"
    assert get_event(presentation, 1, "day", "hunter_shot") is None

    source["rounds"][0]["night"][1]["action"] = "can_shoot"
    explicit_pre_settlement = build_game_presentation(source)
    assert get_event(explicit_pre_settlement, 1, "night", "hunter_state")["action"] == "can_shoot"
    assert get_event(explicit_pre_settlement, 1, "day", "hunter_shot") is None


def test_bv1j_sample_projection_preserves_rounds_and_source_and_uses_ballot_evidence():
    folder = ROOT / "data" / "games" / "S22" / "2026-08-21_g01_BV1jM8B6jE2i"
    dossier = json.loads((folder / "dossier.json").read_text(encoding="utf-8"))
    dossier["voting"] = json.loads((folder / "voting.json").read_text(encoding="utf-8"))
    for round_ in dossier["rounds"]:
        for phase in ("night", "day"):
            for item in round_[phase]:
                item.setdefault("description", f"第{round_['number']}轮来源事件")
                item.setdefault("slot_label", item["slot"])
    original = deepcopy(dossier)

    presentation = build_game_presentation(dossier)

    assert dossier == original
    assert [round_["number"] for round_ in presentation["rounds"]] == [1, 2, 3, 4]
    assert get_event(presentation, 1, "night", "witch_poison") is None
    assert get_event(presentation, 1, "night", "mixed_blood_model")["action"] == "choose"
    for number in (2, 3, 4):
        assert get_event(presentation, number, "night", "mixed_blood_model") is None
    assert get_event(presentation, 2, "night", "witch_save") is None
    assert get_event(presentation, 2, "night", "witch_poison")["action"] == "poison"
    assert get_event(presentation, 3, "night", "witch_save") is None
    assert get_event(presentation, 3, "night", "witch_poison") is None
    assert get_event(presentation, 3, "night", "seer_check") is None
    assert get_event(presentation, 1, "day", "exile_result") is None
    assert get_event(presentation, 2, "day", "exile_result")["targets"] == [9]
    # The local dossier already records this result; it must remain a source fact.
    assert get_event(presentation, 2, "day", "exile_result")["action"] == "exile"
    assert get_event(presentation, 3, "day", "exile_result") is None
    assert get_event(presentation, 4, "day", "exile_result")["targets"] == [7]
    assert get_event(presentation, 4, "day", "exile_result")["action"] == "exile"
    for number in (2, 3, 4):
        assert get_event(presentation, number, "night", "mixed_blood_alignment") is None
    for number in (1, 2, 3, 4):
        hunter = get_event(presentation, number, "night", "hunter_state")
        assert hunter["action"] == "can_shoot"
        assert hunter["inferred"] is True
    for round_ in presentation["rounds"]:
        for phase in ("night", "day"):
            for item in round_[phase]:
                assert {
                    "slot", "action", "actor", "targets", "description", "result",
                    "effects", "availability",
                } <= item.keys()


def test_real_mechanical_rebound_and_puppet_examples_project_conservatively():
    paths = [
        ROOT / "data" / "games" / "S22" / "2026-06-12_g03_BV11KJ56PEPY" / "dossier.json",
        ROOT / "data" / "games" / "S22" / "2026-06-12_局次待核_BV1yKJ56PEak" / "dossier.json",
        ROOT / "data" / "games" / "S22" / "2026-06-24_g03_BV13Ajo6xEY8" / "dossier.json",
    ]
    dossiers = [json.loads(path.read_text(encoding="utf-8")) for path in paths]

    rebound = build_game_presentation(dossiers[0])
    reflected = get_event(rebound, 2, "night", "witch_poison")
    assert reflected["effects"][0]["dead_seat"] == 6
    # The intended target was the mechanical shield, but the actual poison
    # death was the Witch; the unique hunter is therefore not treated as poisoned.
    assert get_event(rebound, 2, "night", "hunter_state")["action"] == "can_shoot"

    puppet = build_game_presentation(dossiers[1])
    assert get_event(puppet, 1, "night", "hunter_state")["action"] == "unknown"
    assert get_event(puppet, 1, "night", "hunter_state").get("inferred") is not True

    mechanical_witch = build_game_presentation(dossiers[2])
    ordinary_poison = get_event(mechanical_witch, 2, "night", "witch_poison")
    mechanical_poison = get_event(mechanical_witch, 2, "night", "mechanical_action")
    assert ordinary_poison["action"] == "poison" and ordinary_poison["targets"] == [11]
    assert mechanical_poison["action"] == "poison" and mechanical_poison["targets"] == [5]
    assert 3 not in ordinary_poison["targets"] and 3 not in mechanical_poison["targets"]
    assert get_event(mechanical_witch, 2, "night", "hunter_state")["action"] == "can_shoot"
    assert next(seat for seat in dossiers[2]["seats"] if seat["seat"] == 3)["role"] == "猎人"
    assert get_event(mechanical_witch, 3, "night", "mechanical_action") is None

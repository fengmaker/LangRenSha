"""Focused tests for conservative special-board recap extraction."""

from __future__ import annotations

from scripts.recap_specials import extract_specials


def _base(*roles: tuple[int, str], rounds: tuple[int, ...] = (1, 2)) -> dict:
    return {
        "seats": [{"seat": seat, "role": role} for seat, role in roles],
        "rounds": [{"number": n, "night": [], "day": []} for n in rounds],
    }


def _segments(*texts: str) -> list[dict[str, str]]:
    return [{"text": text} for text in texts]


def test_treasure_choice_requires_a_verb_and_accepts_explicit_switch() -> None:
    result = extract_specials(_segments(
        "首夜盗宝大师选择切换为蒙面人身份。入夜盗宝大师选择切换为平民身份，摄梦人再次梦游6号盗宝大师6号盗宝大师被梦亡出局。"),
        "盗宝大师", _base((6, "盗宝大师")))
    choices = [e for e in result["events"] if e["slot"] == "treasure_choice"]
    assert [(e["number"], e["result"]) for e in choices] == [(1, "蒙面人"), (2, "平民")]


def test_mixed_blood_model_is_first_night_metadata() -> None:
    result = extract_specials(
        _segments("首夜。", "混血儿5号，榜样是7号狼人。", "第二天白天。"),
        "预女猎白混",
        _base((5, "混血儿"), (7, "狼人")),
    )
    assert result["events"] == [{
        "number": 1, "phase": "night", "slot": "mixed_blood_model",
        "action": "choose", "actor": 5, "targets": [7], "result": None,
    }]


def test_mixed_blood_model_before_first_night_cue_maps_to_round_one() -> None:
    result = extract_specials(
        _segments("本游戏混血儿5号榜样是7号狼人。首夜狼队击杀3号。"),
        "预女猎白混",
        _base((5, "混血儿"), (7, "狼人"), rounds=(1,)),
    )
    assert [(e["number"], e["phase"], e["slot"], e["actor"], e["targets"])
            for e in result["events"]] == [
        (1, "night", "mixed_blood_model", 5, [7]),
    ]


def test_mixed_blood_explicit_target_before_benchmark_word() -> None:
    result = extract_specials(
        _segments("本局混血儿选择5号狼人为榜样。首夜狼队击杀3号。"),
        "预女猎白混",
        _base((8, "混血儿"), (5, "狼人"), rounds=(1,)),
    )
    assert [(e["actor"], e["targets"]) for e in result["events"]] == [(8, [5])]


def test_masquerade_dance_keeps_all_three_targets() -> None:
    result = extract_specials(
        _segments("第二夜。舞者2号选择1号、4号和9号共舞。"),
        "假面舞会",
        _base((2, "舞者"), rounds=(2,)),
    )
    assert result["events"] == [{
        "number": 2, "phase": "night", "slot": "dancer_dance",
        "action": "dance", "actor": 2, "targets": [1, 4, 9], "result": None,
    }]


def test_dance_requires_three_distinct_seats_and_stops_before_later_action() -> None:
    result = extract_specials(
        _segments("第二夜。舞者共舞的对象为1号预言家和2号女巫，3号狼人击杀4号。"),
        "假面舞会",
        _base((4, "舞者"), rounds=(2,)),
    )
    assert not any(e["slot"] == "dancer_dance" for e in result["events"])
    assert any("三个不同座位" in issue for issue in result["issues"])

    repeated = extract_specials(
        _segments("第二夜。舞者选择1号、2号和2号共舞。"),
        "假面舞会",
        _base((4, "舞者"), rounds=(2,)),
    )
    assert not repeated["events"]
    assert any("三个不同座位" in issue for issue in repeated["issues"])


def test_masquerade_verification_and_mask_are_distinct_events() -> None:
    result = extract_specials(
        _segments("第二夜。假面验证5号舞者不在舞池，给9号扣了面具。"),
        "假面舞会",
        _base((3, "假面"), rounds=(2,)),
    )
    assert [(e["slot"], e["action"], e["targets"], e["result"]) for e in result["events"]] == [
        ("masquerade_verify", "verify", [5], "不在舞池"),
        ("masquerade_mask", "give_mask", [9], None),
    ]


def test_guile_board_records_each_exchange_pair() -> None:
    result = extract_specials(
        _segments("第二夜。魔术师交换3号和8号。鬼术师交换4号、11号。"),
        "诡术之境",
        _base((1, "魔术师"), (6, "诡术师"), rounds=(2,)),
    )
    assert [(e["slot"], e["actor"], e["targets"]) for e in result["events"]] == [
        ("magician_exchange", 1, [3, 8]),
        ("guile_exchange", 6, [4, 11]),
    ]


def test_hypothesis_sentence_is_not_extracted() -> None:
    result = extract_specials(
        _segments("第二夜。假面可能验证5号在不在舞池，如果是这样就会影响结果。"),
        "假面舞会",
        _base((3, "假面"), rounds=(2,)),
    )
    assert result["events"] == []
    assert any("推测" in issue for issue in result["issues"])


def test_duplicate_mentions_are_preserved_as_separate_events() -> None:
    result = extract_specials(
        _segments("第二夜。魔术师交换3号和8号。魔术师交换3号和8号。"),
        "诡术之境",
        _base((1, "魔术师"), rounds=(2,)),
    )
    assert len(result["events"]) == 2
    assert result["events"][0] == result["events"][1]


def test_treasure_remainder_and_card_choice_are_explicit_roles() -> None:
    result = extract_specials(
        _segments("首夜。余牌为女巫、平民和猎人，本夜盗宝选择狼人牌。"),
        "盗宝大师赛",
        _base((12, "盗宝大师"), rounds=(1,)),
    )
    assert [(e["slot"], e["action"], e["result"]) for e in result["events"]] == [
        ("treasure_remainder", "view", "余牌：女巫、平民、猎人"),
        ("treasure_choice", "choose", "狼人"),
    ]


def test_prince_revote_is_recorded_only_in_an_existing_day_round() -> None:
    result = extract_specials(
        _segments("第二天白天。定序王子翻牌发动后重投。第三天白天。定序王子翻牌发动后重投。"),
        "诡术之境",
        _base((10, "定序王子"), rounds=(2,)),
    )
    assert [(e["number"], e["slot"], e["action"]) for e in result["events"]] == [
        (2, "sequential_prince_skill", "reveal"),
    ]
    assert any("没有第3轮" in issue for issue in result["issues"])
    assert any("逐人票型" in issue for issue in result["issues"])

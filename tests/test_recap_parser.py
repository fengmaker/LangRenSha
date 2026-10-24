"""Safety-focused tests for the local referee recap parser."""

from __future__ import annotations

from scripts.recap_parser import _number, extract_recap


def _segments(*parts: str) -> list[dict[str, object]]:
    return [
        {"start_ms": index * 1000, "end_ms": index * 1000 + 900, "text": part}
        for index, part in enumerate(parts)
    ]


def _event(rounds: list[dict[str, object]], number: int, phase: str, slot: str) -> list[dict[str, object]]:
    round_record = next(item for item in rounds if item["number"] == number)
    return [item for item in round_record[phase] if item["slot"] == slot]


def test_continuous_role_roster_survives_arbitrary_line_breaks_and_rounds() -> None:
    segments = _segments(
        "本局版型为机械狼通灵师。神职阵营通灵师",
        "一号女巫",
        "十号猎人七号守卫五号狼人阵营三号六号十二号",
        "机械狼八号本局游戏为机械双刀狼平民阵营二号四号九号十一号",
        "首夜守卫守护十二号，狼队击杀八号，形成平安夜。",
        "机械狼模仿十二号狼人；通灵师验证十二号玩家为狼人身份。",
        "第一天白天十二号狼人选择自爆。",
        "第二天白天警徽流失。入夜守卫自守，狼人击杀二号。",
    )

    parsed = extract_recap(segments, "机械狼通灵师")

    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}
    assert roles == {
        1: "通灵师", 2: "平民", 3: "狼人", 4: "平民", 5: "守卫", 6: "狼人",
        7: "猎人", 8: "机械狼", 9: "平民", 10: "女巫", 11: "平民", 12: "狼人",
    }
    mech = parsed["seats"][7]
    assert (mech["learning_target"], mech["learned_role"]) == (12, "机械双刀狼")
    assert [round_["number"] for round_ in parsed["rounds"]] == [1, 2, 3]
    assert _event(parsed["rounds"], 1, "night", "guard")[0]["targets"] == [12]
    assert len(_event(parsed["rounds"], 1, "night", "wolf_attack")) == 1
    assert _event(parsed["rounds"], 1, "day", "night_deaths")[0]["action"] == "peaceful"
    assert _event(parsed["rounds"], 1, "night", "seer_check")[0]["result"] == "狼人"
    assert _event(parsed["rounds"], 1, "day", "self_destruct")[0]["actor"] == 12
    # More than one record for a slot is preserved across later nights.
    assert _event(parsed["rounds"], 3, "night", "guard")[0]["targets"] == [5]
    assert _event(parsed["rounds"], 3, "night", "wolf_attack")[0]["targets"] == [2]


def test_conflicting_roster_seat_stays_unknown_and_player_claims_do_not_fill_it() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫十号狼人阵营一号三号机械狼八号平民阵营二号四号",
            "首夜狼队击杀二号。第一天白天二号玩家说我是女巫，三号说自己是平民。",
        ),
        "机械狼通灵师",
    )

    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}
    assert roles[1] is None
    assert roles[2] == "平民"
    assert roles[3] == "狼人"
    assert roles[5] is None
    assert any("身份冲突" in issue and "1号" in issue for issue in parsed["issues"])
    assert any("未按版型人数补齐" in issue for issue in parsed["issues"])


def test_poison_reflection_only_records_the_explicitly_reported_death() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号狼人阵营二号六号机械狼八号平民阵营四号五号",
            "首夜女巫毒杀四号，毒药被八号机械守卫的盾反弹，女巫死亡。",
        ),
        "机械狼通灵师",
    )

    poison = _event(parsed["rounds"], 1, "night", "witch_poison")[0]
    deaths = _event(parsed["rounds"], 1, "day", "night_deaths")[0]
    assert poison["targets"] == [4]
    assert poison["result"] == "毒药反弹"
    assert deaths["action"] == "die"
    assert deaths["targets"] == [3]
    assert 4 not in deaths["targets"]


def test_explicit_empty_poison_is_pass_and_action_targets_are_not_deaths() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号狼人阵营二号六号机械狼八号平民阵营四号五号",
            "首夜女巫毒药空过，狼队击杀四号。",
        ),
        "机械狼通灵师",
    )

    poison = _event(parsed["rounds"], 1, "night", "witch_poison")
    assert len(poison) == 1
    assert poison[0]["action"] == "pass"
    assert poison[0]["result"] == "明确记录本夜未使用毒药"
    assert _event(parsed["rounds"], 1, "day", "night_deaths") == []


def test_repeated_slot_actions_are_not_collapsed_and_parser_is_idempotent() -> None:
    segments = _segments(
        "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号狼人阵营二号六号机械狼八号平民阵营四号五号",
        "首夜狼队击杀四号，狼队击杀五号。",
    )

    first = extract_recap(segments, "机械狼通灵师")
    second = extract_recap(segments, "机械狼通灵师")

    attacks = _event(first["rounds"], 1, "night", "wolf_attack")
    assert [event["targets"] for event in attacks] == [[4], [5]]
    assert first == second


def test_winner_requires_an_explicit_terminal_result() -> None:
    explicit = extract_recap(
        _segments("本局版型为机械狼通灵师，首夜狼队击杀二号，游戏结束，好人阵营获胜。"),
        "机械狼通灵师",
    )
    hypothetical = extract_recap(
        _segments("本局版型为机械狼通灵师，首夜狼队击杀二号。如果狼人阵营获胜，应该还会继续追刀。"),
        "机械狼通灵师",
    )

    assert explicit["winning_faction"] == "good"
    assert hypothetical["winning_faction"] is None


def test_day_results_keep_text_order_and_capture_exile_sheriff_and_badge() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号猎人九号狼人阵营二号机械狼八号",
            "第一天白天九号猎人获得警徽，二号狼人被公投出局，警徽移交五号。",
        ),
        "机械狼通灵师",
    )

    events = parsed["rounds"][0]["day"]
    assert [(event["slot"], event["targets"]) for event in events] == [
        ("sheriff_result", [9]),
        ("exile_result", [2]),
        ("badge", [5]),
    ]


def test_continuous_seat_first_identity_roster_is_supported() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营一号通灵师三号女巫二号猎人四号守卫狼人阵营五号六号机械狼七号",
            "首夜狼队击杀八号。",
        ),
        "机械狼通灵师",
    )

    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}
    assert roles[1] == "通灵师"
    assert roles[2] == "猎人"
    assert roles[3] == "女巫"
    assert roles[4] == "守卫"
    assert roles[5] == "狼人"
    assert roles[6] == "狼人"
    assert roles[7] == "机械狼"


def test_learning_form_can_be_known_when_modeled_seat_is_not_reported() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号狼人阵营二号六号机械狼八号",
            "本局游戏为机械女巫形态。首夜机械狼学习成为机械女巫形态。",
        ),
        "机械狼通灵师",
    )

    mech = parsed["seats"][7]
    assert mech["learning_target"] is None
    assert mech["learned_role"] == "机械女巫"

    mechanical_seer = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号狼人阵营二号六号机械狼八号",
            "本局游戏为机械通灵师形态。首夜机械狼击杀二号。",
        ),
        "机械狼通灵师",
    )
    assert mechanical_seer["seats"][7]["learned_role"] == "机械通灵师"


def test_bv1ijvt6sel2_mixed_continuous_roster_and_wolf_genocide_win() -> None:
    parsed = extract_recap(
        _segments(
            "好第一局游戏结束了玉女猎白混血儿版型本就游戏预言家10号女巫2号猎人12号白神3号狼人一号4号七号9号平民6号八号11号本游戏的混血儿5号榜样是7号狼人本游戏是狼人混首夜狼人击杀2号女巫女巫毒杀一号狼人一二双死当夜冤家验证4号玩家为狼人身份上警环节一号悍跳狼获得警徽一号玩家出局之后将警徽移交至4号狼人同伴10号预言家被抗推出局入夜狼人击杀12号猎人猎人出局发动技能带走最后一张神职牌3号白神游戏结束狼人阵营屠神获胜"
        ),
        "预女猎白混",
    )

    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}
    assert roles == {
        1: "狼人", 2: "女巫", 3: "白神", 4: "狼人", 5: "混血儿", 6: "平民",
        7: "狼人", 8: "平民", 9: "狼人", 10: "预言家", 11: "平民", 12: "猎人",
    }
    assert parsed["winning_faction"] == "werewolf"
    # “1号出局” describes a death before badge transfer, not a vote result.
    assert [event["targets"] for event in _event(parsed["rounds"], 1, "day", "exile_result")] == [[10]]
    assert _event(parsed["rounds"], 1, "day", "sheriff_result")[0]["targets"] == [1]
    assert _event(parsed["rounds"], 1, "day", "badge")[0]["targets"] == [4]
    check = _event(parsed["rounds"], 1, "night", "seer_check")[0]
    assert (check["actor"], check["targets"], check["result"]) == (10, [4], "狼人")
    shot = _event(parsed["rounds"], 2, "day", "hunter_shot")[0]
    assert (shot["actor"], shot["targets"]) == (12, [3])


def test_bv1jjvt6sen4_continuous_faction_seats_stage_numbers_and_exile_boundaries() -> None:
    parsed = extract_recap(
        _segments(
            "本局游戏版型狼王守卫预言家7号女巫10号猎人2号守卫一号狼王8号狼人3号五号6号平民4号九号11号12号首页首位守护3号狼人狼人击杀11号平民女巫开药解救行程平安夜冤家验证9号玩家为好人身份上警环节7号预言家获得警徽第一天白天5号悍跳狼人被公投出局入夜首尾守护一号自首狼人击杀12号平民女巫毒杀2号猎人22双死冤家验证一号玩家为好人身份第二天八天3号狼人被公投出局狼人阵营决定拍刀刀数不够拍刀失败游戏结束好人阵营获胜"
        ),
        "狼王守卫预言家",
    )

    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}
    assert roles == {
        1: "守卫", 2: "猎人", 3: "狼人", 4: "平民", 5: "狼人", 6: "狼人",
        7: "预言家", 8: "狼王", 9: "平民", 10: "女巫", 11: "平民", 12: "平民",
    }
    assert [round_["number"] for round_ in parsed["rounds"]] == [1, 2]
    assert _event(parsed["rounds"], 1, "night", "guard")[0]["targets"] == [3]
    assert _event(parsed["rounds"], 2, "night", "guard")[0]["targets"] == [1]
    assert [event["targets"] for event in _event(parsed["rounds"], 1, "day", "exile_result")] == [[5]]
    assert [event["targets"] for event in _event(parsed["rounds"], 2, "day", "exile_result")] == [[3]]
    assert parsed["winning_faction"] == "good"


def test_first_night_asr_alias_needs_a_clear_night_action() -> None:
    clear = extract_recap(
        _segments("本局版型为机械狼通灵师，守夜狼人击杀二号。"),
        "机械狼通灵师",
    )
    vague = extract_recap(
        _segments("本局版型为机械狼通灵师，守夜后大家继续复盘。"),
        "机械狼通灵师",
    )

    assert [round_["number"] for round_ in clear["rounds"]] == [1]
    assert _event(clear["rounds"], 1, "night", "wolf_attack")[0]["targets"] == [2]
    assert vague["rounds"] == []


def test_generic_recap_anchor_requires_a_dense_roster_before_first_night() -> None:
    parsed = extract_recap(
        _segments(
            "假面舞会版型预言家5号女巫一号武者3号白神2号假面6号狼人8号九号10号平民4号7号11号12号"
            "首夜狼人击杀11号平民女巫开药解救行程平安夜。"
        ),
        "假面舞会",
    )
    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}
    assert roles == {
        1: "女巫", 2: "白神", 3: "舞者", 4: "平民", 5: "预言家", 6: "假面",
        7: "平民", 8: "狼人", 9: "狼人", 10: "狼人", 11: "平民", 12: "平民",
    }

    # Without the strong faction runs, a generic word such as “版型” is not
    # sufficient to make nearby player claims look like an identity roster.
    weak = extract_recap(
        _segments("假面舞会版型预言家5号女巫一号首夜狼人击杀11号，3号说我是狼人。"),
        "假面舞会",
    )
    assert all(seat["role"] is None for seat in weak["seats"])

    week_anchor = extract_recap(
        _segments(
            "本周游戏预女猎白混血儿版型预言家4号女巫7号猎人5号白神11号狼人一号3号六号"
            "12号平民2号八号十号本游戏的混血儿9号榜样是8号平民守夜狼人击杀8号平民女巫开药解救平安夜"
        ),
        "预女猎白混",
    )
    week_roles = {seat["seat"]: seat["role"] for seat in week_anchor["seats"]}
    assert [week_roles[seat] for seat in (1, 3, 6)] == ["狼人", "狼人", "狼人"]
    assert [week_roles[seat] for seat in (2, 8, 10)] == ["平民", "平民", "平民"]
    assert week_roles[9] == "混血儿"


def test_strong_roster_can_precede_late_intro_and_preserves_explicit_seat_runs() -> None:
    parsed = extract_recap(
        _segments(
            "做本球的复盘稍等我帮你弄深圳营预言家10号女巫3号猎人4号白神8号"
            "狼人阵营2号五号六号12号平民阵营一号9号11号混血儿7号本局游戏狼人混"
            "首页混圈儿选择5号狼人为榜样狼队击杀2号。"
        ),
        "预女猎白混",
    )
    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}
    assert roles == {
        1: "平民", 2: "狼人", 3: "女巫", 4: "猎人", 5: "狼人", 6: "狼人",
        7: "混血儿", 8: "白神", 9: "平民", 10: "预言家", 11: "平民", 12: "狼人",
    }

    # This preamble has no usable “本局版型” anchor before the roster.
    # The dense list and its faction runs, bounded by the first-night action,
    # are sufficient to read explicit seats without inferring missing ones.
    second = extract_recap(
        _segments(
            "做一下本节学的复盘本局版行为玉女猎白混血而神之预言家7号女巫3号猎人一号白神9号"
            "狼人阵营2号六号11号12号平民阵营4号五号8号混血儿10号本游戏为狼人混"
            "首页混圈选择6号狼人为榜样狼队击杀4号。"
        ),
        "预女猎白混",
    )
    second_roles = {seat["seat"]: seat["role"] for seat in second["seats"]}
    assert second_roles == {
        1: "猎人", 2: "狼人", 3: "女巫", 4: "平民", 5: "平民", 6: "狼人",
        7: "预言家", 8: "平民", 9: "白神", 10: "混血儿", 11: "狼人", 12: "狼人",
    }


def test_roster_punctuation_and_special_roles_stop_faction_runs() -> None:
    punctuation = extract_recap(
        _segments(
            "第二局游戏结束了。假面舞会短型预言家，八号女巫二号、舞者六号、白神三号"
            "假面七号、狼人五号、十号、十二号品名，一号、四号、九号十一号，"
            "首夜狼人击杀二号。"
        ),
        "假面舞会",
    )
    roles = {seat["seat"]: seat["role"] for seat in punctuation["seats"]}
    assert roles == {
        1: "平民", 2: "女巫", 3: "白神", 4: "平民", 5: "狼人", 6: "舞者",
        7: "假面", 8: "预言家", 9: "平民", 10: "狼人", 11: "平民", 12: "狼人",
    }

    ghost = extract_recap(
        _segments(
            "本剧版行为鬼畜之境神人阵营预言家9号女巫10号魔术师一号定序王子2号"
            "狼人阵营4号五号11号鬼术师8号平民阵营3号六号7号12号"
            "首页鬼术师交换一号魔术师。"
        ),
        "诡术之境",
    )
    ghost_roles = {seat["seat"]: seat["role"] for seat in ghost["seats"]}
    assert ghost_roles == {
        1: "魔术师", 2: "定序王子", 3: "平民", 4: "狼人", 5: "狼人", 6: "平民",
        7: "平民", 8: "诡术师", 9: "预言家", 10: "女巫", 11: "狼人", 12: "平民",
    }

    masquerade = extract_recap(
        _segments(
            "本举办行为假面舞会嘿深圳预言家8号女巫2号武者6号白神5号"
            "狼人阵营3号七号9号假面牌10号平民阵营一号4号11号12号"
            "首页狼队击杀2号。"
        ),
        "假面舞会",
    )
    masquerade_roles = {seat["seat"]: seat["role"] for seat in masquerade["seats"]}
    assert masquerade_roles == {
        1: "平民", 2: "女巫", 3: "狼人", 4: "平民", 5: "白神", 6: "舞者",
        7: "狼人", 8: "预言家", 9: "狼人", 10: "假面", 11: "平民", 12: "平民",
    }


def test_unclear_seat_number_stays_unknown_and_role_aliases_are_explicit() -> None:
    unclear = extract_recap(
        _segments(
            "本局版型为盗宝大师，预言家十二二号女巫3号猎人4号狼人阵营1号5号"
            "平民阵营6号7号首夜狼队击杀8号。"
        ),
        "盗宝大师",
    )
    assert unclear["seats"][11]["role"] is None
    assert unclear["seats"][0]["role"] == "狼人"
    assert unclear["seats"][4]["role"] == "狼人"

    aliases = extract_recap(
        _segments(
            "本局版型为盗宝大师，神职阵营摄梦人1号毒师2号蒙面人3号"
            "狼人阵营4号5号平民阵营6号7号，首夜狼队击杀8号。"
        ),
        "盗宝大师",
    )
    alias_roles = {seat["seat"]: seat["role"] for seat in aliases["seats"]}
    assert alias_roles[1] == "摄梦人"
    assert alias_roles[2] == "毒师"
    assert alias_roles[3] == "蒙面人"


def test_bv1jjvt6sen4_roster_and_rounds_remain_conservative() -> None:
    text = (
        "本局游戏版型狼王守卫预言家7号女巫10号猎人2号守卫一号狼王8号狼人3号五号6号平民4号九号11号12号"
        "首页首位守护3号狼人狼人击杀11号平民女巫开药解救行程平安夜冤家验证9号玩家为好人身份"
        "上警环节7号预言家获得警徽第一天白天5号悍跳狼人被公投出局入夜首尾守护一号"
        "自首狼人击杀12号平民女巫毒杀2号猎人22双死冤家验证一号玩家为好人身份"
        "第二天八天3号狼人被公投出局狼人阵营决定拍刀刀数不够拍刀失败游戏结束好人阵营获胜"
    )
    parsed = extract_recap(_segments(text), "狼王守卫预言家")
    roles = {seat["seat"]: seat["role"] for seat in parsed["seats"]}

    assert roles[5] == roles[6] == "狼人"
    assert roles[9] == roles[11] == roles[12] == "平民"
    assert [round_["number"] for round_ in parsed["rounds"]] == [1, 2]
    assert [(event["actor"], event["targets"], event["result"]) for event in _event(parsed["rounds"], 1, "night", "seer_check")] == [
        (7, [9], "好人")
    ]
    assert [(event["actor"], event["targets"], event["result"]) for event in _event(parsed["rounds"], 2, "night", "seer_check")] == [
        (7, [1], "好人")
    ]
    assert [event["targets"] for event in _event(parsed["rounds"], 1, "day", "exile_result")] == [[5]]
    assert [event["targets"] for event in _event(parsed["rounds"], 2, "day", "exile_result")] == [[3]]


def test_mechanical_form_maps_role_and_rejects_conflicts() -> None:
    learned = extract_recap(
        _segments(
            "机械狼通灵师版型本游戏通灵师8号女巫11号猎人4号守卫2号机械狼6号狼人一号3号5号平民7号九号十号12号"
            "守夜守卫守护11号女巫狼人击杀2号守卫女巫开药解救形成平安夜机械狼模仿4号猎人本酒席为机械猎人"
        ),
        "机械狼通灵师",
    )
    roles = {seat["seat"]: seat["role"] for seat in learned["seats"]}
    mech = learned["seats"][5]
    assert roles[6] == "机械狼"
    assert (mech["learning_target"], mech["learned_role"]) == (4, "机械猎人")

    conflict = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号猎人四号狼人阵营二号六号机械狼八号平民阵营五号"
            "本局游戏为机械守卫。首夜机械狼模仿四号猎人。"
        ),
        "机械狼通灵师",
    )
    assert conflict["seats"][7]["learning_target"] == 4
    assert conflict["seats"][7]["learned_role"] is None
    assert any("不一致" in issue for issue in conflict["issues"])

    conflicting_declaration = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号狼人阵营二号六号机械狼八号平民阵营四号五号"
            "本局游戏为机械守卫。首夜机械狼学习成为机械女巫形态。"
        ),
        "机械狼通灵师",
    )
    assert conflicting_declaration["seats"][7]["learned_role"] is None
    assert any("形态" in issue and "冲突" in issue for issue in conflicting_declaration["issues"])


def test_bv1pgvc6cebw_real_mechanical_hunter_form_and_shot() -> None:
    parsed = extract_recap(
        _segments(
            "机械狼通灵师版型本游戏通灵师8号女巫11号猎人4号守卫2号机械狼6号狼人一号3号"
            "5号平民7号九号十号12号守夜守卫守护11号女巫狼人击杀2号守卫女巫开药解救形成平安夜"
            "机械狼模仿4号猎人本酒席为机械猎人通灵师验证3号玩家为狼人身份"
            "第三天白天6号机械猎人被公投出局发动技能带走12号平民"
        ),
        "机械狼通灵师",
    )
    mech = parsed["seats"][5]
    assert (mech["learning_target"], mech["learned_role"]) == (4, "机械猎人")
    shot = _event(parsed["rounds"], 3, "day", "hunter_shot")[0]
    assert (shot["actor"], shot["targets"]) == (6, [12])


def test_mechanical_guard_without_named_actor_and_none_number_are_safe() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，神职阵营通灵师一号女巫三号狼人阵营二号六号机械狼八号平民阵营四号五号"
            "首夜机械狼守护五号。"
        ),
        "机械狼通灵师",
    )
    guard = _event(parsed["rounds"], 1, "night", "mechanical_action")[0]
    assert guard["action"] == "guard"
    assert guard["targets"] == [5]
    assert _number(None) is None


def test_explicit_exile_is_required_and_good_justice_is_a_terminal_win() -> None:
    parsed = extract_recap(
        _segments(
            "本局版型为机械狼通灵师，首夜狼队击杀二号，第一天白天一号出局之后转交警徽。"
            "游戏结束，好人正义获胜。"
        ),
        "机械狼通灵师",
    )
    assert _event(parsed["rounds"], 1, "day", "exile_result") == []
    assert parsed["winning_faction"] == "good"


"""Focused regressions from the 2026-11-02 board display review."""
import re

from scripts.game_timeline import build_game_timeline
from website.api.publisher import _public_endgame, _public_supplemental_events


def event(slot, action, *, actor=None, targets=(), result=None, **fields):
    return {"slot": slot, "action": action, "actor": actor,
            "targets": list(targets), "result": result, **fields}


def timeline_items(game, voting=None):
    return [item for phase in build_game_timeline(game, voting)["phases"]
            for item in phase["items"]]


def test_surrender_keeps_an_independently_added_exile_ballot_before_result():
    game = {
        "board": "neighbor_puppet",
        "seats": [{"seat": 1, "name": "甲", "role": "狼人"},
                  {"seat": 2, "name": "乙", "role": "平民"}],
        "rounds": [{"number": 2, "night": [], "day": [
            event("exile_result", "exile", targets=[2]),
            event("self_destruct", "surrender", actor=1),
        ]}],
    }
    voting = {"ballots": [{"id": "exile-round-3", "day": 2, "kind": "exile",
                           "number": 3, "stage": "initial",
                           "votes": [{"voter": 1, "target": 2, "state": "cast"}]}]}

    items = timeline_items(game, voting)
    ballot = next(i for i in items if i["kind"] == "ballot")
    result_index = next(i for i, item in enumerate(items) if item["slot"] == "exile_result")
    surrender_index = next(i for i, item in enumerate(items)
                           if item["slot"] == "werewolf_surrender")

    assert ballot["ballot"]["id"] == "exile-round-3"
    assert items.index(ballot) < result_index < surrender_index


def test_hunter_death_skill_follows_exile_while_night_shot_stays_with_night_death():
    game = {
        "board": "neighbor_puppet",
        "seats": [{"seat": 1, "name": "狼", "role": "狼人"},
                  {"seat": 2, "name": "夜猎", "role": "猎人"},
                  {"seat": 6, "name": "白天猎", "role": "猎人"}],
        "rounds": [{"number": 2, "night": [], "day": [
            event("night_deaths", "die", targets=[2]),
            event("hunter_shot", "shoot", actor=2, targets=[1]),
            event("hunter_shot", "unavailable", actor=6),
            event("exile_result", "exile", targets=[6]),
        ]}],
    }

    items = timeline_items(game)
    morning = next(i for i, item in enumerate(items) if item["slot"] == "night_deaths")
    night_shot = next(i for i, item in enumerate(items)
                      if item["slot"] == "hunter_shot" and item["events"][0]["actor"] == 2)
    exile = next(i for i, item in enumerate(items) if item["slot"] == "exile_result")
    exile_skill = next(i for i, item in enumerate(items)
                       if item["slot"] == "hunter_shot" and item["events"][0]["actor"] == 6)

    assert night_shot == morning + 1
    assert exile < exile_skill


def test_magic_duel_ballot_precedes_result_and_auto_election_follows_self_destruct():
    game = {
        "board": "magic_duel",
        "seats": [{"seat": 4, "name": "自爆狼", "role": "狼人"},
                  {"seat": 6, "name": "当选者", "role": "狼人"},
                  {"seat": 10, "name": "放逐者", "role": "平民"}],
        "rounds": [
            {"number": 1, "night": [], "day": [
                event("sheriff_result", "elected", targets=[6],
                      result="4号自爆后6号自动当选，无警徽投票。"),
                event("self_destruct", "self_destruct", actor=4),
            ]},
            {"number": 2, "night": [], "day": []},
            {"number": 3, "night": [], "day": [
                event("exile_result", "exile", targets=[10]),
                event("exile_vote", "vote", votes=[{"round": 1, "voter": 4, "target": 10}]),
            ]},
        ],
    }
    voting = {"ballots": [{"id": "day-3-exile", "day": 3, "kind": "exile",
                           "number": 1, "stage": "initial",
                           "votes": [{"voter": 4, "target": 10, "state": "cast"}]}]}

    phases = build_game_timeline(game, voting)["phases"]
    first_day = next(p for p in phases if p["number"] == 1 and p["phase"] == "day")["items"]
    third_day = next(p for p in phases if p["number"] == 3 and p["phase"] == "day")["items"]
    first_slots = [item["slot"] for item in first_day]
    third_result = next(i for i, item in enumerate(third_day) if item["slot"] == "exile_result")
    third_ballot = next(i for i, item in enumerate(third_day) if item["kind"] == "ballot")

    assert first_slots.index("self_destruct") < first_slots.index("sheriff_result")
    election = next(item for item in first_day if item["slot"] == "sheriff_result")
    assert "自动当选" in election["text"]
    assert third_ballot < third_result
    assert [item["ballot"]["kind"] for p in phases for item in p["items"]
            if item["kind"] == "ballot"] == ["exile"]


def test_implicit_unique_hunter_is_resolved_before_ordering_its_death_skill():
    game = {"board": "neighbor_puppet", "seats": [
        {"seat": 6, "name": "猎人", "role": "猎人"}], "rounds": [
        {"number": 4, "night": [], "day": [
            event("night_deaths", "die", targets=[2]),
            event("hunter_shot", "unavailable"),
            event("exile_result", "exile", targets=[6])]}]}
    items = timeline_items(game)
    assert [i['slot'] for i in items] == ['night_deaths', 'exile_result', 'hunter_shot']
    assert items[-1]['events'][0]['actor'] == 6


def test_qingqiu_actions_keep_targets_and_render_chinese_statuses():
    game = {
        "board": "qingqiu_night",
        "seats": [{"seat": 1, "name": "甲", "role": "平民"},
                  {"seat": 2, "name": "乙", "role": "平民"},
                  {"seat": 3, "name": "丙", "role": "平民"},
                  {"seat": 4, "name": "白泽", "role": "白泽"},
                  {"seat": 5, "name": "丁", "role": "平民"},
                  {"seat": 6, "name": "九尾", "role": "九尾狐"}],
        "rounds": [{"number": 1, "night": [
            event("whiteze_clear", "clear", actor=4, targets=[1], result="cleared"),
            event("whiteze_clear_mark", "clear_mark", actor=4, targets=[2], result="cleared"),
        ], "day": [
            event("nine_tail_hunt", "hunt", actor=6, targets=[3, 5], result="successful"),
            event("nine_tail_skill", "attempt", actor=6, targets=[1, 2],
                  result="技能未生效。"),
        ]}],
    }

    items = timeline_items(game)
    for slot, targets in (("whiteze_clear", (1,)), ("whiteze_clear_mark", (2,)),
                          ("nine_tail_hunt", (3, 5)), ("nine_tail_skill", (1, 2))):
        item = next(i for i in items if i["slot"] == slot)
        assert all(f"{seat}号" in item["text"] for seat in targets)
        assert not re.search(r"[A-Za-z_]", item["title"] + item["text"])


def test_all_in_trade_and_magic_exchange_have_chinese_labels_and_ordered_choices():
    all_in = {
        "board": "all_in",
        "seats": [{"seat": 1, "name": "典狱长", "role": "典狱长"},
                  {"seat": 4, "name": "先手", "role": "平民"},
                  {"seat": 8, "name": "后手", "role": "狼人"}],
        "rounds": [{"number": 2, "night": [
            event("warden_trade_targets", "select_pair", actor=1, targets=[4, 8]),
            event("trade_decisions", "trade_betray", targets=[4, 8]),
            event("trade_resolution", "betrayal_death", targets=[4, 8]),
        ], "day": []}],
    }
    magic = {
        "board": "magic_duel",
        "seats": [{"seat": 1, "name": "魔术师", "role": "魔术师"},
                  {"seat": 2, "name": "乙", "role": "平民"},
                  {"seat": 8, "name": "丙", "role": "狼人"}],
        "rounds": [{"number": 1, "night": [
            event("magician_exchange", "exchange", actor=1, targets=[2, 8]),
        ], "day": []}],
    }

    trade_items = [i for i in timeline_items(all_in)
                   if i["slot"] in {"warden_trade_targets", "trade_decisions", "trade_resolution"}]
    decisions = next(i for i in trade_items if i["slot"] == "trade_decisions")
    exchange = next(i for i in timeline_items(magic) if i["slot"] == "magician_exchange")

    assert len(trade_items) == 3
    assert all(not re.search(r"[A-Za-z_]", i["title"] + i["text"]) for i in trade_items + [exchange])
    assert decisions["text"].index("4号") < decisions["text"].index("8号")
    assert decisions["text"].index("交易") < decisions["text"].index("背叛")
    assert exchange["text"].index("2号") < exchange["text"].index("8号")


def test_magic_duel_poison_includes_confirmed_actual_hit_without_effect_rows():
    game = {
        "board": "magic_duel",
        "seats": [{"seat": 2, "name": "实际目标", "role": "狼人"},
                  {"seat": 5, "name": "女巫", "role": "女巫"}],
        "rounds": [{"number": 2, "night": [
            event("witch_poison", "poison", actor=5, targets=[5],
                  result="受魔术师交换影响，实际毒杀2号狼人。", effects=[]),
        ], "day": []}],
    }

    poison = next(i for i in timeline_items(game)
                  if any(e["slot"] == "witch_poison" for e in i["events"]))

    assert "5号" in poison["text"]
    assert "实际毒杀2号" in poison["text"]


def test_first_night_puppet_guard_failure_is_attached_to_the_guard_event():
    game = {
        "board": "neighbor_puppet",
        "seats": [{"seat": 1, "name": "狼", "role": "狼人"},
                  {"seat": 5, "name": "守卫", "role": "守卫"}],
        "rounds": [{"number": 1, "night": [
            event("puppet_select", "select", actor=1, targets=[5]),
            event("guard", "guard", actor=5, targets=[1]),
            event("puppet_skill_effect", "skill_disabled", actor=5, targets=[1],
                  result="5号傀儡守卫守护1号的技能失效。"),
        ], "day": []}],
    }

    items = timeline_items(game)
    guard = next(i for i in items if i["slot"] == "guard")

    assert "守护1号" in guard["text"]
    assert "技能失效" in guard["text"]
    assert [i["slot"] for i in items].count("puppet_skill_effect") == 0


def test_wolf_rush_endgame_phases_join_the_day_once_without_filling_unknowns():
    cases = [
        {"board": "magic_duel", "day": 2, "actor": None, "targets": [5, 3],
         "result": "werewolf_win", "source_shot": True},
        {"board": "neighbor_puppet", "day": 4, "actor": None, "targets": [3],
         "result": "werewolf_win", "source_shot": False},
        {"board": "neighbor_puppet", "day": 2, "actor": None, "targets": [9],
         "result": "unknown", "source_shot": False},
    ]

    for case in cases:
        day = case["day"]
        source = {
            "board": case["board"], "winner": "werewolf",
            "seats": [{"seat": n, "name": str(n), "role": "狼人" if n == 1 else "平民"}
                      for n in {*case["targets"], 1}],
            "rounds": [{"number": day, "night": [], "day": (
                [event("wolf_shot", "shoot", targets=case["targets"],
                       result="狼人拍刀，目标集合已记录。")]
                if case["source_shot"] else [])}],
            "endgame": {"phases": [{"kind": "wolf_rush", "day": day,
                                     "actor": case["actor"],
                                     "declared_targets": case["targets"],
                                     "result": case["result"]}]},
        }

        phase = next(p for p in build_game_timeline(source)["phases"]
                     if p["number"] == day and p["phase"] == "day")
        rushes = [item for item in phase["items"] if item["slot"] == "wolf_rush"]

        assert len(rushes) == 1
        rush = rushes[0]
        recorded_targets = set().union(*(set(e.get("targets", [])) for e in rush["events"]))
        assert recorded_targets == set(case["targets"])
        assert all(f"{seat}号" in rush["text"] for seat in case["targets"])
        assert all(item["slot"] != "wolf_shot" for item in phase["items"])
        if case["result"] == "unknown":
            assert not any(e.get("actor") is not None for e in rush["events"])
            assert "成功" not in rush["text"]
            assert any(e.get("result") == "unknown" for e in rush["events"])


def test_reviewed_supplemental_trade_is_readable_without_inventing_both_choices():
    supplemental = {"phase_reviewed": {"events": [{
        "event_id": "trade-1", "phase": "night", "round": 2,
        "action": "trade", "actor": 2, "targets": [3, 11],
        "state": "performed", "status": "text_explicit",
        "result": "典狱长选择3号与11号交易；双方认可；当夜交易池无事发生。",
    }]}}
    public_events = _public_supplemental_events(supplemental)
    game = {
        "board": "all_in",
        "seats": [{"seat": 2, "name": "典狱长", "role": "典狱长"},
                  {"seat": 3, "name": "甲", "role": "平民"},
                  {"seat": 11, "name": "乙", "role": "狼人"}],
        "rounds": [{"number": 2, "night": [], "day": []}],
        "_publication_context": {"supplemental_events": public_events},
    }

    items = [i for i in timeline_items(game) if i["kind"] == "event"]

    assert len(public_events) == 1
    assert len(items) == 1
    trade = items[0]
    assert not re.search(r"[A-Za-z_]", trade["title"] + trade["text"])
    assert "典狱长" in trade["text"] and "3号" in trade["text"] and "11号" in trade["text"]
    assert not {"trade_decisions", "trade_resolution"} & {i["slot"] for i in items}
    assert trade["events"][0].get("targets") == [3, 11]


def test_pending_endgame_and_legacy_public_status_do_not_become_confirmed_endings():
    from copy import deepcopy

    source = {
        "board": "qingqiu_night", "release_id": "old-release", "seats": [],
        "rounds": [{"number": 4, "night": [], "day": [
            event("night_deaths", "peaceful")]}],
        "endgame": {"phases": [{"kind": "wolf_rush", "day": 4, "actor": 4,
                                 "declared_targets": [12], "result": "werewolf_win"}]},
    }
    for endgame in (source["endgame"], _public_endgame({
            **source["endgame"], "review_status": "ai_candidate_awaiting_user"})):
        game = {**source, "endgame": endgame}
        before = deepcopy(game)
        phases = build_game_timeline(game)["phases"]
        assert not phases[-1]["terminal"]
        assert not any(i["slot"] == "wolf_rush" for p in phases for i in p["items"])
        assert game == before


def test_registration_and_retained_candidates_have_distinct_names_and_empty_list_text():
    game = {"board": "magic_duel", "seats": [], "rounds": [
        {"number": 1, "night": [], "day": [
            event("sheriff_candidates", "register", targets=[1, 4])]}]}
    voting = {"registrations": [{"day": 1, "on_police": [1, 2, 3, 4], "off_police": []}]}
    candidates = [i for i in timeline_items(game, voting) if i["slot"] == "sheriff_candidates"]
    assert [i["title"] for i in candidates] == ["首次上警", "退水后候选"]
    assert '警下：无人。' in candidates[0]['text']
    assert candidates[1]['text'].startswith('本轮候选：')


def test_surrender_excludes_later_occurrences_of_an_earlier_slot():
    game = {'board': 'neighbor_puppet', 'seats': [
        {'seat': 2, 'name': '甲', 'role': '猎人'},
        {'seat': 6, 'name': '乙', 'role': '猎人'}], 'rounds': [
        {'number': 2, 'night': [], 'day': [
            event('night_deaths', 'die', targets=[2]),
            event('hunter_shot', 'shoot', actor=2, targets=[1]),
            event('self_destruct', 'surrender', actor=4),
            event('hunter_shot', 'shoot', actor=6, targets=[3])]}]}
    shots = [i for i in timeline_items(game) if i['slot'] == 'hunter_shot']
    assert len(shots) == 1 and shots[0]['events'][0]['actor'] == 2


def test_distinct_endgame_records_with_same_targets_keep_each_settlement():
    game = {'board': 'neighbor_puppet', 'winner': 'werewolf', 'seats': [],
            'rounds': [{'number': 2, 'night': [], 'day': []}],
            'endgame': {'phases': [
                {'kind': 'wolf_rush', 'day': 2, 'declared_targets': [3], 'result': 'unknown'},
                {'kind': 'wolf_rush', 'day': 2, 'declared_targets': [3], 'result': 'werewolf_win'}]}}
    rushes = [i for i in timeline_items(game) if i['slot'] == 'wolf_rush']
    assert [i['events'][0]['result'] for i in rushes] == ['unknown', 'werewolf_win']

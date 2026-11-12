"""Synthetic settlement cases for the shared game-flow rules."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from game_flow import collect_death_announcements, replay


def event(slot, action, *, actor=None, targets=(), result=None):
    return {"slot": slot, "action": action, "actor": actor,
            "targets": list(targets), "result": result}


def game(rounds, *, roles=None, board="mixed_blood"):
    roles = roles or {}
    seats = [{"seat": seat, "name": str(seat),
              "role": roles.get(seat, "狼人" if seat == 1 else "平民")}
             for seat in range(1, 13)]
    return {"board": board, "seats": seats, "rounds": rounds}


def round_(number, *, night_deaths=(), day_events=()):
    night = [event("night_deaths", "die", targets=night_deaths)] if night_deaths else [
        event("night_deaths", "peaceful")]
    day = [*day_events]
    if not any(item["slot"] == "exile_result" for item in day):
        day.append(event("exile_result", "none"))
    return {"number": number, "night": night, "day": day}


def survivor_game():
    return game([
        round_(1, night_deaths=[6, 7], day_events=[event("exile_result", "exile", targets=[8])]),
        round_(2, night_deaths=[11]),
        round_(3, day_events=[event("exile_result", "exile", targets=[1, 10])]),
        round_(4, night_deaths=[12]),
    ])


def test_departures_set_the_living_roster_before_each_exile_vote():
    result = replay(survivor_game())
    living = {row["day"]: row["living_before_vote"] for row in result["rounds"]}
    assert living[3] == [1, 2, 3, 4, 5, 9, 10, 12]
    assert living[4] == [2, 3, 4, 5, 9]


def test_terminal_night_does_not_create_a_later_day():
    roles = {seat: ("平民" if seat == 2 else "狼人") for seat in range(1, 13)}
    rows = [round_(number) for number in range(1, 5)]
    rows.append(round_(5, night_deaths=[2]))
    facts = {"ballots": [], "interruptions": []}

    result = replay(game(rows, roles=roles), facts)

    assert [row["day"] for row in result["rounds"]] == [1, 2, 3, 4, 5]
    assert result["days"] == [1, 2, 3, 4]
    assert result["terminal"] == {
        "round": 5, "phase": "night", "after_day": 4,
        "winner": "werewolf", "eliminated_side": "civilian"}


def test_terminal_night_does_not_hide_a_conflicting_actual_ballot():
    roles = {seat: ("平民" if seat == 2 else "狼人") for seat in range(1, 13)}
    rows = [round_(number) for number in range(1, 5)]
    rows.append(round_(5, night_deaths=[2]))
    facts = {"ballots": [{"id": "contradiction", "day": 5, "kind": "exile"}],
             "interruptions": []}

    result = replay(game(rows, roles=roles), facts)

    assert result["terminal"] is None
    assert result["issues"][0]["code"] == "terminal_conflict"


def test_exiled_hunter_shoots_after_current_ballot():
    dossier = game([
        round_(1), round_(2),
        round_(3, day_events=[event("exile_result", "exile", targets=[3]),
                              event("hunter_shot", "shoot", actor=3, targets=[5])]),
        round_(4),
    ], roles={3: "猎人"})

    result = replay(dossier)
    living = {row["day"]: row["living_before_vote"] for row in result["rounds"]}

    assert 5 in living[3]
    assert 5 not in living[4]


def test_guarded_attack_without_a_recorded_settlement_stays_unknown():
    dossier = game([{
        "number": 1,
        "night": [event("wolf_attack", "attack", targets=[5]),
                  event("guard", "guard", actor=3, targets=[5])],
        "day": [event("exile_result", "none")],
    }], board="mechanical_wolf_seer")

    assert replay(dossier)["rounds"][0]["night_deaths"] is None


def test_judge_report_requires_a_unique_day_and_keeps_its_source():
    rows = [{"start_ms": 1000, "end_ms": 2000,
             "text": "昨夜8号玩家倒牌，没有遗言，是否发动技能"}]
    facts = {"ballots": [{"id": "b", "day": 3}], "interruptions": []}
    audit = {"source_path": "data/test.json", "evidence": {"b": [{"start_ms": 3000}]}}
    dossier = {"rounds": [{"number": 3,
                           "day": [event("night_deaths", "unknown")], "night": []}]}

    reports = collect_death_announcements(rows, dossier, facts, audit)

    assert [(row["day"], row["targets"]) for row in reports] == [(3, [8])]
    assert reports[0]["evidence"][0]["path"] == "data/test.json"
    facts["ballots"].append({"id": "c", "day": 4})
    audit["evidence"]["c"] = [{"start_ms": 4000}]
    assert collect_death_announcements(rows, dossier, facts, audit) == []


def test_both_good_sides_eliminated_on_the_same_night_settle_for_wolves():
    roles = {seat: "狼人" for seat in range(1, 13)}
    roles[2] = "平民"
    roles[3] = "预言家"
    dossier = game([round_(1), round_(2, night_deaths=[2, 3])], roles=roles)

    terminal = replay(dossier)["terminal"]

    assert terminal == {"round": 2, "phase": "night", "after_day": 1,
                        "winner": "werewolf", "eliminated_side": "civilian"}


def test_after_speech_death_is_a_daytime_terminal():
    roles = {seat: "狼人" for seat in range(1, 13)}
    roles[9] = "平民"
    rows = [round_(number) for number in range(1, 5)]
    rows.append(round_(5, day_events=[
        event("masked_delayed_death", "die_after_speech", actor=9, targets=[9])]))

    terminal = replay(game(rows, roles=roles))["terminal"]

    assert (terminal["round"], terminal["phase"], terminal["after_day"]) == (5, "day", 5)

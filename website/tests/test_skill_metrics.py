from __future__ import annotations

from scripts import game_inference
from website.api.skill_metrics import skill_metrics


def _faction(seat: dict) -> str | None:
    return seat.get("faction")


def _game(*, seats: list[dict], rounds: list[dict], presentation: dict | None = None) -> dict:
    game = {"id": "skill-game", "seats": seats, "rounds": rounds}
    if presentation is not None:
        game["presentation"] = presentation
    return game


def _seat(number: int, role: str, faction: str | None, **extra) -> dict:
    return {"seat": number, "role": role, "faction": faction, **extra}


def _event(slot: str, actor: int | None, action: str, *, targets: list[int] | None = None,
           **extra) -> dict:
    return {"slot": slot, "actor": actor, "action": action,
            "targets": targets or [], "effects": [], **extra}


def test_native_witch_metrics_separate_choices_targets_and_confirmed_kills():
    game = _game(
        seats=[_seat(1, "女巫", "good"), _seat(2, "狼人", "werewolf"),
               _seat(3, "守卫", "good")],
        rounds=[{"number": 1, "night": [
            _event("witch_poison", 1, "poison", targets=[2], effects=[{
                "kind": "poison_death", "intended_target": 2, "dead_seat": 2,
                "shield_actor": None,
            }]),
        ], "day": [{"slot": "night_deaths", "action": "die", "targets": [2]}]},
        {"number": 2, "night": [_event("witch_poison", 1, "pass")], "day": []}],
    )

    metric = skill_metrics(game, _faction)[1]

    assert metric["witch_poison_count"] == {
        "numerator": 1, "denominator": 2, "rate": 0.5, "excluded": 0,
        "game_ids": ["skill-game"],
        "samples": [{"game_id": "skill-game", "positive": 1, "negative": 1}],
    }
    assert metric["witch_poison_wolf_rate"]["numerator"] == 1
    assert metric["witch_poison_wolf_rate"]["denominator"] == 1
    assert metric["witch_poison_wolf_kills"]["numerator"] == 1
    assert metric["witch_poison_wolf_kills"]["denominator"] == 1


def test_target_rate_uses_chosen_target_while_kill_uses_resolved_target():
    source = _event("witch_poison", 1, "poison", targets=[2])
    projected = {**source, "resolved_targets": [3]}
    game = _game(
        seats=[_seat(1, "女巫", "good"), _seat(2, "平民", "good"),
               _seat(3, "狼人", "werewolf")],
        rounds=[{"number": 1, "night": [source],
                 "day": [{"slot": "night_deaths", "action": "die", "targets": [3]}]}],
        presentation={"rounds": [{"number": 1, "night": [projected], "day": []}]},
    )

    metric = skill_metrics(game, _faction)[1]

    assert metric["witch_poison_wolf_rate"]["numerator"] == 0
    assert metric["witch_poison_wolf_rate"]["denominator"] == 1
    assert metric["witch_poison_wolf_kills"]["numerator"] == 1
    assert metric["witch_poison_wolf_kills"]["denominator"] == 1


def test_unresolved_exchange_is_not_settled_from_the_intended_target(monkeypatch):
    monkeypatch.setattr(game_inference, "build_game_presentation", lambda game: game["presentation"])
    poison = _event("witch_poison", 1, "poison", targets=[2])
    game = _game(
        seats=[_seat(1, "女巫", "good"), _seat(2, "狼人", "werewolf"),
               _seat(3, "平民", "good")],
        rounds=[{"number": 1, "night": [
            poison,
            _event("magician_exchange", 3, "exchange", targets=[2, 3], result="交换2号与3号"),
        ], "day": [{"slot": "night_deaths", "action": "die", "targets": [2]}]}],
        presentation={"rounds": [{"number": 1, "night": [poison], "day": []}]},
    )

    metric = skill_metrics(game, _faction)[1]["witch_poison_wolf_kills"]

    assert metric["numerator"] == 0
    assert metric["denominator"] == 0
    assert metric["excluded"] == 1


def test_reflected_poison_is_not_counted_as_a_wolf_kill():
    game = _game(
        seats=[_seat(1, "女巫", "good"), _seat(2, "狼人", "werewolf"),
               _seat(3, "机械狼", "werewolf", learned_role="机械守卫")],
        rounds=[{"number": 1, "night": [_event("witch_poison", 1, "poison", targets=[2], effects=[{
            "kind": "poison_reflected", "intended_target": 2, "dead_seat": 1,
            "shield_actor": 3,
        }])], "day": [{"slot": "night_deaths", "action": "die", "targets": [1]}]}],
    )

    metric = skill_metrics(game, _faction)[1]

    assert metric["witch_poison_wolf_rate"]["numerator"] == 1
    assert metric["witch_poison_wolf_kills"]["numerator"] == 0
    assert metric["witch_poison_wolf_kills"]["denominator"] == 1


def test_mechanically_learned_skills_stay_out_of_native_role_metrics():
    game = _game(
        seats=[_seat(1, "机械狼", "werewolf", learned_role="机械女巫"),
               _seat(2, "狼人", "werewolf"),
               _seat(3, "机械狼", "werewolf", learned_role="机械猎人")],
        rounds=[{"number": 1, "night": [
            _event("mechanical_action", 1, "poison", targets=[2], effects=[{
                "kind": "poison_death", "intended_target": 2, "dead_seat": 2,
                "shield_actor": None,
            }]),
        ], "day": [
            _event("mechanical_day_skill", 3, "shoot", targets=[2]),
            {"slot": "night_deaths", "action": "die", "targets": [2]},
        ]}],
    )

    result = skill_metrics(game, _faction)

    assert set(result[1]) == {
        "mechanical_poison_count", "mechanical_poison_wolf_rate", "mechanical_poison_wolf_kills",
    }
    assert result[1]["mechanical_poison_count"]["numerator"] == 1
    assert result[1]["mechanical_poison_wolf_kills"]["numerator"] == 1
    assert set(result[3]) == {
        "mechanical_shot_count", "mechanical_shot_wolf_rate", "mechanical_shot_wolf_kills",
    }
    assert result[3]["mechanical_shot_wolf_kills"]["numerator"] == 1


def test_unknown_or_missing_skill_records_are_excluded_not_zero_uses():
    unknown = _game(
        seats=[_seat(1, "女巫", "good"), _seat(2, "狼人", "werewolf")],
        rounds=[{"number": 1, "night": [_event("witch_poison", 1, "unknown")], "day": []}],
    )
    empty = _game(seats=[_seat(1, "女巫", "good")], rounds=[])

    unknown_metric = skill_metrics(unknown, _faction)[1]["witch_poison_count"]
    empty_metric = skill_metrics(empty, _faction)[1]["witch_poison_count"]

    assert unknown_metric["denominator"] == 0
    assert unknown_metric["numerator"] == 0
    assert unknown_metric["excluded"] == 1
    assert empty_metric["denominator"] == 0
    assert empty_metric["excluded"] == 1


def test_actorless_choice_is_assigned_when_the_skill_holder_is_unique():
    game = _game(
        seats=[_seat(1, "女巫", "good")],
        rounds=[{"number": 1, "night": [_event("witch_poison", None, "pass")], "day": []}],
    )

    metric = skill_metrics(game, _faction)[1]["witch_poison_count"]

    assert metric["numerator"] == 0
    assert metric["denominator"] == 1
    assert metric["excluded"] == 0


def test_blocked_shot_counts_as_a_chosen_action_but_not_a_resolved_kill():
    game = _game(
        seats=[_seat(1, "猎人", "good"), _seat(2, "狼人", "werewolf")],
        rounds=[{"number": 1, "night": [], "day": [
            _event("hunter_shot", 1, "shoot", targets=[2], blocked_by_game_end=True),
        ]}],
    )

    metric = skill_metrics(game, _faction)[1]

    assert metric["hunter_shot_count"]["numerator"] == 1
    assert metric["hunter_shot_wolf_rate"]["numerator"] == 1
    assert metric["hunter_shot_wolf_kills"]["numerator"] == 0
    assert metric["hunter_shot_wolf_kills"]["denominator"] == 1
    assert metric["hunter_shot_wolf_kills"]["excluded"] == 0


def test_missing_record_is_excluded_per_hunter_and_invalidated_shot_is_no_kill():
    game = _game(
        seats=[_seat(1, "猎人", "good"), _seat(2, "猎人", "good"),
               _seat(3, "狼人", "werewolf")],
        rounds=[{"number": 1, "night": [], "day": [
            _event("hunter_shot", 1, "shoot", targets=[3], invalidated=True),
        ]}],
    )

    result = skill_metrics(game, _faction)

    assert result[1]["hunter_shot_wolf_kills"]["numerator"] == 0
    assert result[1]["hunter_shot_wolf_kills"]["denominator"] == 1
    assert result[1]["hunter_shot_wolf_kills"]["excluded"] == 0
    assert result[2]["hunter_shot_count"]["denominator"] == 0
    assert result[2]["hunter_shot_count"]["excluded"] == 1
    assert result[2]["hunter_shot_wolf_rate"]["excluded"] == 1

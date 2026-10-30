from __future__ import annotations

from website.api import publisher


def _terminal_seer_game(*, seer_action: str = "unavailable", seer_targets: list[int] | None = None) -> dict:
    roles = [
        ("守卫", "good"), ("猎人", "good"), ("平民", "good"),
        ("机械狼", "werewolf"), ("平民", "good"), ("狼人", "werewolf"),
        ("女巫", "good"), ("狼人", "werewolf"), ("通灵师", "good"),
        ("狼人", "werewolf"), ("平民", "good"), ("平民", "good"),
    ]
    names = [f"玩家{i}" for i in range(1, 13)]
    dossier = {
        "slug": "bili-BVterminal1234-p01",
        "season": "S21",
        "date": "2026-03-12",
        "phase": "regular",
        "board": "s21_mechanical_wolf_seer",
        "winner": "werewolf",
        "seats": [
            {"seat": seat, "name": names[seat - 1], "role": role, "faction": faction}
            for seat, (role, faction) in enumerate(roles, 1)
        ],
        "rounds": [
            {"number": 1, "night": [], "day": [
                {"slot": "night_deaths", "action": "die", "targets": [4, 7]},
            ]},
            {"number": 2, "night": [], "day": [
                {"slot": "night_deaths", "action": "die", "targets": [1, 2]},
                {"slot": "hunter_shot", "action": "shoot", "actor": 2, "targets": [1]},
            ]},
            {"number": 3, "night": [
                {"slot": "wolf_attack", "action": "attack", "targets": [9],
                 "result": "狼人击杀最后一张神职牌"},
                {"slot": "seer_check", "action": seer_action, "actor": 9,
                 "targets": seer_targets or [], "availability": "actor_departed"},
            ], "day": [
                {"slot": "night_deaths", "action": "die", "targets": [9],
                 "result": "9号通灵师死亡，游戏结束"},
                {"slot": "hunter_shot", "action": "unavailable", "actor": None,
                 "targets": [], "result": None},
            ]},
        ],
        "_publication_context": {"terminal_observation": {"round": 3, "phase": "night"}},
    }
    _, rules = publisher._logical_rules(publisher.PACKAGE_ROOT, "S21")
    board = rules["boards"][dossier["board"]]
    person_ids = {name: f"person-{seat}" for seat, name in enumerate(names, 1)}
    return publisher._public_game(dossier, {}, {}, None, board, person_ids)


def test_terminal_night_publication_omits_unplayed_seer_and_inherited_hunter_slot():
    doc = _terminal_seer_game()

    terminal = doc["presentation"]["terminal"]
    assert not any(event["slot"] == "seer_check" for round_ in doc["presentation"]["rounds"]
                   for event in round_["night"])


def test_terminal_night_publication_omits_inherited_unavailable_hunter_slot():
    doc = _terminal_seer_game()

    terminal = doc["presentation"]["terminal"]
    assert [event["slot"] for event in terminal["events"]] == ["night_deaths"]


def test_terminal_night_publication_preserves_an_explicit_seer_check():
    doc = _terminal_seer_game(seer_action="check", seer_targets=[3])

    assert any(event["slot"] == "seer_check" and event["action"] == "check"
               for round_ in doc["presentation"]["rounds"] for event in round_["night"])

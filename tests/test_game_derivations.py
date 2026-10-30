"""Shared preparation rules, tested before any website or database call."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from board_config import load_template
from game_derivations import derive_game, restore_source_records


def fixture(board="mixed_blood", rounds=3):
    template = load_template(board, ROOT)
    roles = ["猎人", "女巫", "预言家", "狼人", "狼人", "混血儿", "平民", "平民", "白神", "狼人", "平民", "狼人"]
    def event(slot):
        return dict(slot=slot, action="unknown", actor=None, targets=[], result=None, start_seat=None,
                    direction=None, votes=[], random_point=None, speech_scope=None, availability=None, effects=[])
    season = "S21" if board.startswith("s21_") else "S23" if board.startswith("s23_") else "S22"
    game = dict(slug="rule-fixture", season=season, board=board,
                seats=[dict(seat=i, role=role, faction=None, learned_role=None, learning_target=None) for i, role in enumerate(roles, 1)],
                rounds=[dict(number=n, **{p: [event(s["code"]) for s in template[p + "_slots"]]
                                          for p in ("night", "day")}) for n in range(1, rounds + 1)])
    for r in game["rounds"]:
        get(game, r["number"], "night_deaths").update(action="peaceful")
        get(game, r["number"], "exile_result").update(action="none")
    return game


def get(game, n, slot):
    r = game["rounds"][n - 1]
    return next(e for p in ("night", "day") for e in r[p] if e["slot"] == slot)


def test_first_night_saved_bottle_is_unavailable_upstream_in_every_season():
    for board in ("mixed_blood", "s21_seer_witch_hunter_white_mixed", "s23_mixed_blood"):
        game = fixture(board)
        get(game, 1, "witch_save").update(action="save", actor=2, targets=[1])
        original = deepcopy(game)
        result = derive_game(game)
        assert get(result["dossier"], 2, "witch_save")["action"] == "unavailable"
        # Spending antidote does not spend the independent poison bottle.
        assert get(result["dossier"], 2, "witch_poison")["action"] == "unknown"
        assert game == original
        assert any(x["slot"] == "witch_save" and x["round"] == 2 and x["status"] == "unavailable"
                   for x in result["derivations"]["slot_states"])
        assert not any(x["slot"] == "witch_save" and x["round"] == 2
                       for x in result["derivations"]["review_tasks"])


def test_usually_saving_on_first_night_never_becomes_a_fact():
    result = derive_game(fixture())
    assert get(result["dossier"], 1, "witch_save")["action"] == "unknown"
    assert get(result["dossier"], 2, "witch_save")["action"] == "unknown"


def test_new_boards_self_destruct_keep_a_valid_unheld_exile_action():
    for board in ("s23_magic_duel", "s23_qingqiu_night"):
        game = fixture(board, rounds=1)
        get(game, 1, "exile_result").update(action="unknown")
        get(game, 1, "self_destruct").update(action="self_destruct", actor=4)
        result = derive_game(game, voting([]))
        event = get(result["dossier"], 1, "exile_result")
        definition = next(s for s in load_template(board)["day_slots"]
                          if s["code"] == "exile_result")
        assert event["action"] == "none"
        assert event["action"] in definition["actions"]


def test_later_confirmed_antidote_use_proves_earlier_nonuse():
    game = fixture()
    get(game, 3, "witch_save").update(action="save", actor=2, targets=[1])
    result = derive_game(game)
    assert get(result["dossier"], 1, "witch_save")["action"] == "pass"
    assert get(result["dossier"], 2, "witch_save")["action"] == "pass"
    assert any(x["rule"] == "unique_later_bottle_use_proves_earlier_nonuse"
               for x in result["derivations"]["changes"])


def test_later_confirmed_learning_proves_earlier_mechanical_nonuse():
    game = fixture("s23_mechanical_wolf_seer")
    game["seats"][5]["role"] = "机械狼"
    get(game, 2, "mechanical_action").update(action="learn", actor=6, targets=[4])
    result = derive_game(game)
    assert get(result["dossier"], 1, "mechanical_action")["action"] == "pass"
    assert any(x["rule"] == "unique_later_learning_proves_earlier_nonuse" for x in result["derivations"]["changes"])
    get(game, 3, "mechanical_action").update(action="learn", actor=6, targets=[5])
    assert get(derive_game(game)["dossier"], 1, "mechanical_action")["action"] == "unknown"


def test_night_death_preserves_that_nights_check_but_removes_future_checks():
    game = fixture()
    get(game, 1, "seer_check").update(action="check", actor=3, targets=[4], result="wolf")
    get(game, 1, "night_deaths").update(action="die", targets=[3])
    result = derive_game(game)
    assert get(result["dossier"], 1, "seer_check")["action"] == "check"
    assert get(result["dossier"], 2, "seer_check")["action"] == "unavailable"
    assert result["derivations"]["rounds"][0]["living_before_vote"] == [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_recorded_action_after_death_is_reported_not_silently_erased():
    game = fixture()
    get(game, 1, "night_deaths").update(action="die", targets=[3])
    get(game, 2, "seer_check").update(action="check", actor=3, targets=[4], result="wolf")
    result = derive_game(game)
    assert get(result["dossier"], 2, "seer_check")["action"] == "check"
    assert any(x["code"] == "action_unavailable" and x["actor"] == 3 for x in result["derivations"]["issues"])


def ballot(day, kind="exile", eligible=None, votes=None, winner=None, stage="initial", candidates=None):
    return dict(id=f"b{day}-{kind}-{stage}", day=day, kind=kind, number=1, stage=stage, status="partial",
                candidates=candidates, eligible_voters=eligible, tied_candidates=[], winner=winner,
                unrecorded_voters=eligible, votes=votes or [])


def voting(ballots, registrations=None):
    return dict(schema_version=1, game_slug="rule-fixture", ballots=ballots, registrations=registrations or [],
                interruptions=[], days=[dict(day=n, sheriff="unknown", exile="unknown") for n in range(1, 4)])


def test_self_destruct_resolves_unheld_exile_before_later_mechanical_qualification():
    game = fixture("s21_mechanical_wolf_seer", rounds=2)
    game["seats"][5]["role"] = "机械狼"
    get(game, 1, "mechanical_action").update(action="learn", actor=6, targets=[4], result="mechanical_double_attack_werewolf")
    get(game, 1, "self_destruct").update(action="self_destruct", actor=4)
    get(game, 1, "exile_result").update(action="unknown")
    result = derive_game(game, voting([]))
    assert get(result["dossier"], 1, "exile_result")["action"] == "none"
    assert result["voting"]["days"][0]["exile"] == "interrupted_self_destruct"
    assert get(result["dossier"], 2, "mechanical_action")["action"] == "unavailable"
    # A completed exile ballot or absent voting archive cannot prove interruption.
    assert get(derive_game(game, voting([ballot(1)]))["dossier"], 1, "exile_result")["action"] == "unknown"
    assert get(derive_game(game)["dossier"], 1, "exile_result")["action"] == "unknown"


def test_shot_after_exile_does_not_remove_voters_from_the_prior_ballot():
    game = fixture()
    get(game, 1, "exile_result").update(action="exile", targets=[1])
    get(game, 1, "hunter_shot").update(action="shoot", actor=1, targets=[4])
    result = derive_game(game, voting([ballot(1), ballot(2)]))
    assert result["voting"]["ballots"][0]["eligible_voters"] == list(range(1, 13))
    assert result["voting"]["ballots"][1]["eligible_voters"] == [2, 3, 5, 6, 7, 8, 9, 10, 11, 12]


def test_shot_triggered_by_night_death_removes_target_before_exile_vote():
    game = fixture()
    get(game, 1, "night_deaths").update(action="die", targets=[1])
    get(game, 1, "hunter_shot").update(action="shoot", actor=1, targets=[4])
    eligible = [2, 3, 5, 6, 7, 8, 9, 10, 11, 12]
    choices = [dict(voter=seat, target=5, state="cast") for seat in eligible]
    result = derive_game(game, voting([ballot(1, eligible=eligible, votes=choices)]))
    current = result["voting"]["ballots"][0]
    assert current["eligible_voters"] == eligible
    assert current["unrecorded_voters"] == []
    assert current["status"] == "complete"


def test_pk_candidates_are_excluded_only_from_the_pk_ballot():
    result = derive_game(fixture(), voting([ballot(1), ballot(1, stage="pk", candidates=[4, 5])]))
    assert result["voting"]["ballots"][0]["eligible_voters"] == list(range(1, 13))
    assert result["voting"]["ballots"][1]["eligible_voters"] == [1, 2, 3, 6, 7, 8, 9, 10, 11, 12]


def test_missing_death_result_keeps_electorate_unknown():
    game = fixture()
    get(game, 1, "night_deaths").update(action="unknown", targets=[])
    result = derive_game(game, voting([ballot(1)]))
    assert result["voting"]["ballots"][0]["eligible_voters"] is None
    assert result["derivations"]["vote_review_tasks"][0]["slot"] == "vote_eligibility"


def test_only_off_sheriff_voter_can_be_uniquely_recovered():
    v = voting([ballot(1, "sheriff", eligible=[3], winner=7)],
               [dict(id="reg", day=1, on_police=[s for s in range(1, 13) if s != 3], off_police=[3])])
    result = derive_game(fixture(), v)
    b = result["voting"]["ballots"][0]
    assert b["votes"] == [dict(voter=3, target=7, state="cast")]
    assert b["status"] == "complete"
    assert any(x["rule"] == "unique_elector_and_elected_result" for x in result["derivations"]["changes"])


def test_judge_initial_list_fills_missing_registration_before_vote_eligibility():
    on = [s for s in range(1, 13) if s != 3]
    evidence = {"registration": {"day": 1, "on_police": on, "off_police": [3]}}
    source_votes = voting([ballot(1, "sheriff", winner=7)])
    result = derive_game(fixture(), source_votes, speech_evidence=evidence)
    assert result["voting"]["registrations"][0]["on_police"] == on
    assert result["voting"]["ballots"][0]["eligible_voters"] == [3]
    assert result["voting"]["ballots"][0]["votes"] == [dict(voter=3, target=7, state="cast")]
    assert result["derivations"]["sheriff_speech_evidence"] == evidence
    assert restore_source_records(result["dossier"], result["voting"], result["derivations"])["voting"] == source_votes


def test_incomplete_speech_chain_is_only_evidence_and_cannot_fill_complement():
    evidence = {"rounds": [{"day": 1, "speakers": [1, 2], "complete": False, "off_police": None}]}
    result = derive_game(fixture(), voting([ballot(1, "sheriff")]), speech_evidence=evidence)
    assert result["voting"]["registrations"] == []
    assert result["voting"]["ballots"][0]["eligible_voters"] is None
    assert result["derivations"]["sheriff_speech_evidence"] == evidence


def test_even_procedurally_complete_speeches_cannot_establish_unobserved_off_police_seats():
    evidence = {"rounds": [{"day": 1, "speakers": [1, 2], "complete": True, "off_police": list(range(3, 13))}]}
    result = derive_game(fixture(), voting([ballot(1, "sheriff")]), speech_evidence=evidence)
    assert result["voting"]["registrations"] == []
    assert result["voting"]["ballots"][0]["eligible_voters"] is None


def test_known_signup_list_skips_speech_round_inference_even_if_it_differs():
    registration = dict(id="judge-signup", day=1, on_police=[1, 2], off_police=list(range(3, 13)))
    evidence = {"rounds": [{"day": 1, "speakers": [3], "complete": True, "off_police": [s for s in range(1, 13) if s != 3]}]}
    result = derive_game(fixture(), voting([], [registration]), speech_evidence=evidence)
    assert result["voting"]["registrations"] == [registration]
    assert not any("sheriff_speech" in x["rule"] for x in result["derivations"]["changes"])
    assert not any("sheriff_speech" in x["code"] for x in result["derivations"]["issues"])


def test_judge_signup_evidence_has_priority_over_an_extra_speech_round():
    evidence = {"registration": {"day": 1, "on_police": [1, 2], "off_police": list(range(3, 13))},
                "rounds": [{"day": 1, "speakers": [3], "complete": True, "off_police": []}]}
    result = derive_game(fixture(), voting([]), speech_evidence=evidence)
    assert result["voting"]["registrations"][0]["on_police"] == [1, 2]
    assert any(x["rule"] == "judge_initial_sheriff_signup_list" for x in result["derivations"]["changes"])


def test_dependency_rebuild_reopens_the_bottle_after_source_use_is_removed():
    game = fixture()
    get(game, 1, "witch_save").update(action="save", actor=2, targets=[1])
    first = derive_game(game)
    restored = restore_source_records(first["dossier"], None, first["derivations"])
    assert restored["dossier"] == game
    get(restored["dossier"], 1, "witch_save").update(action="unknown", actor=None, targets=[])
    second = derive_game(restored["dossier"])
    assert get(second["dossier"], 2, "witch_save")["action"] == "unknown"


def test_explicit_dead_voter_is_a_conflict_and_the_record_is_preserved():
    game = fixture()
    get(game, 1, "night_deaths").update(action="die", targets=[3])
    v = voting([ballot(1, votes=[dict(voter=3, target=4, state="cast")])])
    result = derive_game(game, v)
    assert result["voting"]["ballots"][0]["votes"] == v["ballots"][0]["votes"]
    assert any(x["code"] == "ineligible_recorded_voter" for x in result["derivations"]["issues"])


def test_persisted_derivations_are_identical_across_python_hash_seeds():
    game = fixture(rounds=1)
    get(game, 1, "exile_result").update(action="unknown")
    v = voting([ballot(1, eligible=list(range(1, 13)), winner=4)])
    script = "import json,sys; sys.path.insert(0,'scripts'); from game_derivations import derive_game; print(json.dumps(derive_game(json.loads(sys.argv[1]),json.loads(sys.argv[2])),sort_keys=True))"
    results = [subprocess.check_output([sys.executable, "-c", script, json.dumps(game), json.dumps(v)],
               cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": seed}) for seed in ("1", "2")]
    assert results[0] == results[1]


def test_special_outcome_maps_round_trip_through_json_exactly():
    game = fixture("masquerade", rounds=2)
    game["seats"][2]["role"] = "舞者"
    game["seats"][3]["role"] = "假面"
    get(game, 2, "masquerade_mask").update(action="pass", actor=4)
    get(game, 2, "dancer_dance").update(action="dance", actor=3, targets=[3, 7, 8])
    result = derive_game(game)
    assert get(result["dossier"], 2, "dance_resolution")["action"] == "no_death"
    assert result["derivations"] == json.loads(json.dumps(result["derivations"]))


def test_supplemental_dq_updates_upstream_survival_and_future_hunter_qualification():
    game = fixture()
    get(game, 3, "hunter_state").update(action="can_shoot", actor=1)
    supplemental = {"events": [{"round": 2, "phase": "day", "event": {
        "slot": "disqualification", "action": "disqualify", "targets": [1], "actor": None}}]}
    result = derive_game(game, voting([ballot(2), ballot(3)]), supplemental=supplemental)
    assert 1 not in result["voting"]["ballots"][0]["eligible_voters"]
    assert get(result["dossier"], 2, "hunter_shot")["action"] == "unavailable"
    assert get(result["dossier"], 3, "hunter_state")["action"] == "unavailable"
    assert result["derivations"]["rounds"][1]["disqualified"] == [1]
    assert result["derivations"]["rounds"][1]["night_deaths"] == []


def test_prepare_refreshes_materialized_dependents_when_a_base_fact_changes(tmp_path, monkeypatch):
    import prepare_game_rules as command
    monkeypatch.setattr(command, "ROOT", tmp_path)
    folder = tmp_path / "data/games/S22/fixture"
    folder.mkdir(parents=True)
    game = fixture()
    get(game, 1, "witch_save").update(action="save", actor=2, targets=[1])
    (folder / "dossier.json").write_text(json.dumps(game), encoding="utf-8")
    (folder / "voting.json").write_text(json.dumps(voting([])), encoding="utf-8")
    command.prepare(["S22"], apply=True, materialize=True)
    stored = json.loads((folder / "dossier.json").read_text(encoding="utf-8"))
    assert get(stored, 2, "witch_save")["action"] == "unavailable"
    get(stored, 1, "witch_save").update(action="unknown", actor=None, targets=[])
    (folder / "dossier.json").write_text(json.dumps(stored), encoding="utf-8")
    command.prepare(["S22"], apply=True)
    updated = json.loads((folder / "dossier.json").read_text(encoding="utf-8"))
    assert get(updated, 2, "witch_save")["action"] == "unknown"

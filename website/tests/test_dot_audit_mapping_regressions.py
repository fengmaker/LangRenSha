from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from website.api import publisher
from website.api.game_presentation import build_game_presentation


ROOT = Path(__file__).resolve().parents[2]


def published_game(season: str, bvid: str) -> tuple[dict, dict]:
    entries, _, _ = publisher.load_release(ROOT, season)
    item = next(entry for entry in entries if entry["bvid"] == bvid)
    person_ids = {seat["name"]: seat["name"] for seat in item["dossier"]["seats"]}
    public = publisher._public_game(
        item["dossier"], item["voting"], item["endgame"], item["audit"], item["board"], person_ids
    )
    return item, public


def test_s23_default_abstention_basis_survives_the_public_projection():
    item, public = published_game("S23", "BV1gBhn6dE5c")
    source_vote = next(
        vote for ballot in item["voting"]["ballots"] if ballot["id"] == "ballot-2"
        for vote in ballot["votes"] if vote["voter"] == 12
    )
    public_vote = next(
        vote for ballot in public["voting"]["ballots"] if ballot["id"] == "ballot-2"
        for vote in ballot["votes"] if vote["voter"] == 12
    )
    assert "默认弃票" in source_vote["basis"]
    assert public_vote["basis"] == "rule_default"
    assert source_vote["basis"] not in json.dumps(public, ensure_ascii=False)


def test_s22_audited_night_terminal_cuts_the_unplayed_day_and_keeps_terminal_deaths():
    item, public = published_game("S22", "BV149TJ6WETs")
    terminal = item["audit"]["game_flow"]["terminal"]
    assert terminal["round"] == 4 and terminal["phase"] == "night"
    assert public["rounds"][-1]["number"] == 4
    assert public["rounds"][-1]["day"] == []
    assert all(row["day"] < 4 for row in public["voting"]["days"])
    presentation = build_game_presentation(public)
    assert [event["targets"] for event in presentation["terminal"]["events"]
            if event["slot"] == "night_deaths"] == [[9, 10]]


def test_explicit_s23_terminal_marker_cuts_unplayed_day_without_losing_final_death():
    _, public = published_game("S23", "BV1i6J163Ees")
    assert public["terminal_observation"] == {"round": 4, "phase": "night"}
    assert public["rounds"][-1]["day"] == []
    assert all(row["day"] < 4 for row in public["voting"]["days"])
    presentation = build_game_presentation(public)
    assert [event["targets"] for event in presentation["terminal"]["events"]
            if event["slot"] == "night_deaths"] == [[4]]


@pytest.mark.parametrize("bvid", ["BV1K3aQ6zEB9", "BV123aQ6BEu2"])
def test_s23_surrender_terminal_markers_keep_the_surrender_and_remove_the_unplayed_day(bvid: str):
    _, public = published_game("S23", bvid)
    assert public["terminal_observation"]["phase"] == "night"
    terminal_round = public["terminal_observation"]["round"]
    round_ = next(row for row in public["rounds"] if row["number"] == terminal_round)
    assert round_["day"] == []
    assert all(row["day"] < terminal_round for row in public["voting"]["days"])
    assert any(event["action"] == "surrender"
               for event in round_["night"])


def test_all_nine_s22_audited_night_terminals_hide_the_next_day():
    terminal_bvids = {
        "BV149TJ6WETs", "BV1suMG6PEYP", "BV1WEN86gERp", "BV1RGgx6xEP9",
        "BV1iMgq6ZEtz", "BV13g3z6FEdh", "BV1DFM26MEWR", "BV1kG8A6dEfF", "BV1kG8A6dEye",
    }
    entries, _, _ = publisher.load_release(ROOT, "S22")
    by_bvid = {entry["bvid"]: entry for entry in entries}
    assert terminal_bvids <= by_bvid.keys()
    for bvid in terminal_bvids:
        item = by_bvid[bvid]
        context = item["dossier"]["_publication_context"]
        assert item["audit"].get("dossier_sha256") == item["source_hashes"]["dossier"], bvid
        assert context["terminal_observation"]["phase"] == "night"
        public = publisher._public_game(
            item["dossier"], item["voting"], item["endgame"], item["audit"], item["board"],
            {seat["name"]: seat["name"] for seat in item["dossier"]["seats"]},
        )
        final_round = public["terminal_observation"]["round"]
        assert next(row for row in public["rounds"] if row["number"] == final_round)["day"] == []
        assert all(row["day"] < final_round for row in public["voting"]["days"])


def test_supplemental_disqualification_ends_later_hunter_actions():
    _, public = published_game("S23", "BV1BmpB6PE2C")
    dq = [event for round_ in public["rounds"] for phase in ("night", "day")
          for event in round_[phase] if event["slot"] == "disqualification"]
    assert len(dq) == 1 and dq[0]["targets"] == [8]
    assert "被DQ出局" in dq[0]["description"]

    presentation = build_game_presentation(public)
    later_hunter_actions = [event for round_ in presentation["rounds"] if round_["number"] > 2
                            for phase in ("night", "day") for event in round_[phase]
                            if event.get("actor") == 8 and event["slot"] in {"hunter_state", "hunter_shot"}]
    assert later_hunter_actions == []
    same_day_pending = [event for round_ in presentation["rounds"] if round_["number"] == 2
                        for event in round_["day"]
                        if event["slot"] == "hunter_shot" and event.get("inferred")]
    assert same_day_pending == []


def test_last_god_s23_hunter_has_no_pending_shot_after_game_end():
    _, public = published_game("S23", "BV1gBhn6dE5c")
    presentation = build_game_presentation(public)
    pending = [event for round_ in presentation["rounds"] for phase in ("night", "day")
               for event in round_[phase] if event["slot"] == "hunter_shot" and event.get("inferred")]
    assert pending == []


def test_s23_last_god_rule_combines_departures_from_multiple_rounds():
    source = {
        "season": "S23", "board": {"code": "mixed_blood"},
        "seats": [
            {"seat": 3, "role": "预言家"}, {"seat": 7, "role": "女巫"},
            {"seat": 11, "role": "猎人"}, {"seat": 12, "role": "白神"},
        ],
        "voting": {"days": [], "ballots": []},
        "rounds": [
            {"number": 1, "night": [], "day": [{
                "slot": "night_deaths", "action": "die", "targets": [7, 12],
            }]},
            {"number": 2, "night": [], "day": [{
                "slot": "night_deaths", "action": "die", "targets": [3],
            }]},
            {"number": 3, "night": [], "day": [
                {"slot": "exile_result", "action": "exile", "targets": [11]},
                {"slot": "hunter_shot", "action": "unknown", "actor": 11, "targets": []},
            ]},
        ],
    }
    presentation = build_game_presentation(source)
    shots = [event for event in presentation["rounds"][2]["day"]
             if event["slot"] == "hunter_shot"]
    assert shots == [] or all("inferred" not in shot for shot in shots)


def test_lost_badge_inference_does_not_claim_a_second_self_destruct():
    source = {
        "seats": [], "board": {"code": "mixed_blood"},
        "voting": {"days": [{"day": 1, "sheriff": "badge_lost"}], "ballots": []},
        "rounds": [{"number": 1, "night": [], "day": [{
            "slot": "badge", "action": "unknown", "actor": None, "targets": [],
            "votes": [], "effects": [], "availability": None,
        }]}],
    }
    badge = build_game_presentation(source)["rounds"][0]["day"][0]
    assert badge["action"] == "badge_lost"
    assert "自爆" not in badge["inference_note"]


def test_confirmed_puppet_hunter_does_not_get_a_pending_shot_question():
    _, public = published_game("S22", "BV12pNo6HEuV")
    presentation = build_game_presentation(public)
    pending = [event for round_ in presentation["rounds"] for phase in ("night", "day")
               for event in round_[phase]
               if event["slot"] == "hunter_shot" and event.get("inferred")]
    assert pending == []


def test_terminal_vote_clipping_preserves_unknown_day_and_rejects_recorded_after_terminal_data():
    unknown_day = {"day": None, "sheriff": "unknown", "exile": "unknown"}
    result = publisher._clip_voting({
        "days": [unknown_day, {"day": 4, "sheriff": "unknown", "exile": "unknown"}],
        "ballots": [], "registrations": [], "interruptions": [],
    }, 4, "night")
    assert unknown_day in result["days"]
    assert all(row.get("day") != 4 for row in result["days"])

    item, _ = published_game("S23", "BV1i6J163Ees")
    identities = {seat["name"]: seat["name"] for seat in item["dossier"]["seats"]}
    for collection, row in (
        ("ballots", {"day": 4, "id": "after-terminal", "votes": []}),
        ("registrations", {"day": 4, "id": "after-terminal", "on_police": [], "off_police": []}),
    ):
        voting = deepcopy(item["voting"])
        voting[collection].append(row)
        with pytest.raises(publisher.PublishError, match="终局边界之后"):
            publisher._public_game(
                item["dossier"], voting, item["endgame"], None, item["board"], identities
            )


def test_day_specific_absence_of_exile_is_not_a_terminal_boundary():
    dossier = {"rounds": [{"number": 4, "night": [], "day": [
        {"slot": "exile_result", "action": "none", "targets": [],
         "result": "未进入D4放逐；白天已经发生。"},
        {"slot": "exile_result", "action": "none", "targets": [],
         "result": "D4未开始放逐或投票。"},
    ]}]}
    assert publisher._terminal_from_dossier(dossier) is None


def test_s23_no_d4_day_wording_uses_the_explicit_terminal_boundary():
    _, public = published_game('S23', 'BV17QJh6qEid')
    assert public['terminal_observation'] == {'round': 4, 'phase': 'night'}
    assert public['rounds'][-1]['day'] == []
    assert all(row['day'] < 4 for row in public['voting']['days'])
    final_night = public['rounds'][-1]['night']
    assert next(e for e in final_night if e['slot'] == 'night_deaths')['targets'] == [3, 7]


def test_publication_format_changes_when_public_projection_contract_changes():
    assert publisher.PUBLICATION_FORMAT_VERSION >= 5


def test_night_terminal_preserves_its_explicit_ending_note_outside_the_unplayed_day():
    _, public = published_game("S22", "BV1iaE26kE1w")
    assert public["terminal_observation"] == {"round": 4, "phase": "night"}
    notes = [event for event in public["terminal_events"] if event["slot"] == "exile_result"]
    assert len(notes) == 1
    assert notes[0]["result"] == "第四夜毒杀最后一张狼人后游戏结束"
    presentation = build_game_presentation(public)
    assert any(event.get("result") == notes[0]["result"] and event.get("terminal")
               for event in presentation["terminal"]["events"])
    assert public["rounds"][-1]["day"] == []


def test_api_response_model_keeps_the_public_terminal_fields():
    from website.api.app import GameDetail, _resolved_snapshot
    _, public = published_game("S22", "BV1iaE26kE1w")
    public["release_id"] = "terminal-response-fixture"
    response = GameDetail.model_validate(_resolved_snapshot(public)).model_dump()
    assert response.get("terminal_observation") == public["terminal_observation"]
    assert response.get("terminal_events") == public["terminal_events"]

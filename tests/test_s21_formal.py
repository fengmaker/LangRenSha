import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_s21_formal as formal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("狼人交牌，好人阵营获胜", "good"),
        ("好人获胜", "good"),
        ("狼人阵营屠神获胜", "werewolf"),
        ("狼人阵营拍刀成功并获胜", "werewolf"),
        ("狼人未获胜", None),
        ("不是好人获胜", None),
        ("并非狼人阵营获胜", None),
        ("狼人阵营获胜，好人阵营获胜", None),
        ("狼人阵营拍刀成功，屠神获胜", None),
    ],
)
def test_winner_only_normalizes_explicit_unambiguous_result(text, expected):
    assert formal.normalize_winner(text) == expected


def _write_json(root: Path, relative: str, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _phase_event(event_id, phase, round_number, action, *, actor=None, targets=None,
                 result=None, details=None):
    return {
        "event_id": event_id, "phase": phase, "round": round_number, "action": action,
        "actor": actor, "actor_physical_role": None, "targets": targets or [],
        "actual_targets": None, "state": "performed", "status": "text_explicit",
        "result": result, "details": details or {}, "note": None, "evidence": [],
    }


def test_build_records_keeps_only_expressible_facts_and_separate_ballots(tmp_path):
    rules = formal.ROOT / "config/S21_formal_rules.json"
    (tmp_path / "config").mkdir()
    (tmp_path / "config/S21_formal_rules.json").write_bytes(rules.read_bytes())

    caption_path = _write_json(tmp_path, "data/fixture/captions.json", {"body": []})
    caption_hash = formal.digest(tmp_path, "data/fixture/captions.json")
    identity_path = _write_json(tmp_path, "data/fixture/identity.reviewed.json", {"fixture": "identity"})
    phase_path = _write_json(tmp_path, "data/fixture/phase.reviewed.json", {"fixture": "phase"})
    spec_path = _write_json(tmp_path, "data/fixture/phase-spec.json", {"fixture": "spec"})
    entry = {
        "bvid": "BVfixtureS21", "cid": 123456, "page": 1,
        "title": "20260303 正赛 第一期 Day-1 第一局-预女猎白混",
        "date_candidate": "2026-03-03", "phase_candidate": "regular",
        "selected_transcript_origin": "platform_original_chinese_subtitle",
        "selected_source_path": "data/fixture/captions.json",
        "related_sources": {"platform_raw_chinese_subtitle_path": "data/fixture/captions.json"},
        "source_hashes": {"selected_source_sha256": caption_hash},
    }
    identity = {
        "season": "S21", "bvid": entry["bvid"], "cid": entry["cid"], "page": entry["page"],
        "seats": [
            {"seat": n, "name": f"选手{n}",
             "role": "狼人" if n <= 4 else "平民" if n <= 8 else "猎人" if n == 9 else "女巫" if n == 10 else "预言家" if n == 11 else "白神"}
            for n in range(1, 13)
        ],
    }
    voters = [{"voter": n, "target": 3, "state": "cast", "evidence": []} for n in range(1, 13)]
    reviewed = {
        "schema_version": 1, "season": "S21", "bvid": entry["bvid"], "cid": entry["cid"], "page": 1,
        "source": {"selected_path": "data/fixture/captions.json", "selected_sha256": caption_hash,
                   "original_path": "data/fixture/captions.json", "original_sha256": caption_hash},
        "events": [
            _phase_event("n1", "night", 1, "wolf_attack", targets=[5]),
            _phase_event("d1", "night", 1, "night_deaths", targets=[5]),
            _phase_event("d1-announcement", "day", 1, "death_announcement", targets=[5]),
            _phase_event("signup", "day", 1, "sheriff_signup", targets=[1, 2],
                         details={"initial_signup_complete": True}),
            _phase_event("elected", "day", 1, "sheriff_elected", actor=1),
            _phase_event("exile", "day", 1, "exile", targets=[3]),
            _phase_event("end", "endgame", None, "game_end", result="好人阵营获胜"),
        ],
        "ballots": [{
            "ballot_id": "BVfixtureS21-ballot-01", "day": 1, "type": "exile", "stage": "initial",
            "eligible_voters": list(range(1, 13)), "candidate_seats": None, "votes": voters,
            "outcome": {"exiled": 3}, "completeness": "complete_for_proven_eligible_set",
            "evidence": [], "eligibility_evidence": [], "note": None,
        }],
        "coverage": {"gaps": []},
    }
    binding = {"identity": identity_path.relative_to(tmp_path).as_posix(),
               "phase": phase_path.relative_to(tmp_path).as_posix(),
               "spec": spec_path.relative_to(tmp_path).as_posix(), "approval": {"status": "fixture"}}

    item = formal.build_records(entry, identity, reviewed, binding, root=tmp_path)
    dossier = item["dossier"]
    assert dossier["board"] == "s21_seer_witch_hunter_white_mixed"
    assert dossier["game_number"] == 1
    assert dossier["winner"] == "good"
    assert all(seat["faction"] is None for seat in dossier["seats"])
    assert all(not event["votes"] for round_ in dossier["rounds"] for part in ("night", "day") for event in round_[part])
    day_deaths = next(event for event in dossier["rounds"][0]["day"] if event["slot"] == "night_deaths")
    assert day_deaths["action"] == "die" and day_deaths["targets"] == [5]
    assert any("same formal fact" in entry["reason"] for entry in item["supplemental"]["unmapped"])
    assert item["voting"]["ballots"][0]["status"] == "complete"
    assert len(item["voting"]["ballots"][0]["votes"]) == 12
    assert item["endgame"]["phases"] == []
    assert item["supplemental"]["phase_reviewed"] == reviewed


def test_unknown_shot_role_stays_in_supplemental():
    event = _phase_event("shoot-unknown", "day", 1, "shoot", actor=4, targets=[7])
    event["actor_physical_role"] = "盗宝大师"
    phase, number, mapped = formal.map_phase_event(event)
    assert phase is None and number is None
    assert "formal slot" in mapped


def test_night_death_peaceful_result_maps_without_inventing_targets():
    event = _phase_event("peaceful", "night", 1, "night_deaths", result="首夜平安，无夜死")
    phase, number, mapped = formal.map_phase_event(event)
    assert (phase, number) == ("day", 1)
    assert mapped["slot"] == "night_deaths"
    assert mapped["action"] == "peaceful"
    assert mapped["targets"] == []


def test_season_scope_rejects_excluded_bvid_without_reading_review_files(tmp_path):
    scope = json.loads((formal.ROOT / "config/S21_game_scope.json").read_text(encoding="utf-8"))
    excluded = scope["excluded_bvids"][0]
    _write_json(tmp_path, formal.INDEX.as_posix(), {"entries": [{"bvid": excluded}]})
    _write_json(tmp_path, formal.SCOPE.as_posix(), scope)
    with pytest.raises(formal.ReviewError, match="排除"):
        formal.selected_entries(root=tmp_path, bvids=[excluded])


def test_unknown_day_status_and_later_night_do_not_create_voting_days():
    lost = _phase_event("badge-unknown", "day", 1, "badge_lost")
    lost["state"] = "unknown"
    night = _phase_event("last-night", "night", 2, "wolf_attack", targets=[4])
    facts, _ = formal.voting_facts("fixture", {"events": [lost, night], "ballots": []})
    assert facts["days"] == []


def test_changed_spec_requires_a_current_primary_approval(tmp_path):
    entry = {"bvid": "BVfixtureS21", "cid": 123456, "page": 1}
    folder = formal.REVIEW_DIR / entry["bvid"]
    _write_json(tmp_path, (folder / "identity.reviewed.json").as_posix(), {
        "season": "S21", **entry, "review": {"status": "ai_visual_checked"},
        "seats": [{"seat": n} for n in range(1, 13)],
    })
    _write_json(tmp_path, (folder / "phase.reviewed.json").as_posix(), {})
    _write_json(tmp_path, (formal.PHASE_DIR / f"{entry['bvid']}.json").as_posix(), {"bvid": entry["bvid"]})
    with pytest.raises(formal.ReviewError, match="approval已过期"):
        formal.approved_identity_and_phase(entry, root=tmp_path,
                                          approvals={entry["bvid"]: {"spec_sha256": "0" * 64}})


def test_prepared_files_are_compared_before_database_import(tmp_path):
    item = {"entry": {"bvid": "BVfixtureS21"}, "folder": "data/games/S21/fixture",
            "dossier": {"winner": None}, "voting": {}, "endgame": {}, "supplemental": {}}
    formal.write_prepared([item], root=tmp_path)
    _write_json(tmp_path, item["folder"] + "/dossier.json", {"winner": "werewolf"})
    with pytest.raises(formal.ReviewError, match="当前approved输入不一致"):
        formal.load_prepared([item], root=tmp_path)

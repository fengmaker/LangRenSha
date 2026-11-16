from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import apply_incremental_review as apply
from incremental_common import entry_key, save_state, work_dir


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, monkeypatch):
    shutil.copytree(ROOT / "config/board_templates", root / "config/board_templates")
    people_path = root / "website/assets/people.json"
    people_path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "website/assets/people.json", people_path)

    bvid, cid, page = "BV1ABCDEF123", 456, 1
    entry = {"bvid": bvid, "cid": cid, "page": page, "labels": {"season": "S23"}}
    key = entry_key(entry)
    source = root / "data/source.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({"source": {"bvid": bvid, "cid": cid, "page": page}}), encoding="utf-8")
    folder = work_dir(root, "S23", entry)
    folder.mkdir(parents=True)
    (folder / "supplemental.json").write_text(json.dumps({
        "schema_version": 1, "game_slug": "bili-BV1ABCDEF123-p01-g01",
        "events": [{"round": 1, "phase": "day", "event": {
            "slot": "disqualification", "action": "disqualify", "actor": 3,
            "targets": [3],
        }}],
    }), encoding="utf-8")
    seats = [{"seat": number, "name": f"选手{number}",
              "role": "狼人" if number in {1, 2} else "平民",
              "faction": "werewolf" if number in {1, 2} else "good",
              "learning_target": None, "learned_role": None}
             for number in range(1, 13)]
    dossier = {
        "slug": "bili-BV1ABCDEF123-p01-g01", "season": "S23", "date": "2026-10-27",
        "phase": "regular", "game_number": 1, "board": "mixed_blood", "winner": None,
        "commentators": [], "referee": None, "seats": seats,
        "rounds": [{"number": 1, "night": [], "day": []}],
        "files": [{"role": "transcript", "platform": "bilibili",
                   "external_key": f"{bvid}:{cid}", "path": "data/source.json"}],
    }
    voting = {"schema_version": 1, "game_slug": dossier["slug"], "registrations": [],
              "ballots": [], "interruptions": [], "days": []}
    candidate = {"dossier": dossier, "voting": voting,
                 "endgame": {"schema_version": 1, "game_slug": dossier["slug"], "phases": []},
                 "evidence": [], "issues": []}
    candidate_path = folder / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    source_hash, candidate_hash = _digest(source), _digest(candidate_path)

    manifest_path = root / "data/raw/bilibili" / bvid / "p01/manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"bvid": bvid, "cid": cid, "page": page,
                                        "url": f"https://www.bilibili.com/video/{bvid}/?p=1"}),
                             encoding="utf-8")
    item = {"entry": entry, "analysis": "ready", "source_path": "data/source.json",
            "source_sha256": source_hash, "candidate_sha256": candidate_hash}
    state = {"schema_version": 1, "season": "S23", "items": {key: item}, "weibo": {}}
    save_state(root, "S23", state)
    review = root / "data/reports/S23/incremental/review.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"seat": number, "decision": "yes" if number == 1 else "", "success": ""}
            for number in range(1, 13)]
    game = {"review_id": key, "bvid": bvid, "cid": cid, "page": page,
            "candidate_sha256": candidate_hash, "source_sha256": source_hash,
            "reviewed": True, "note": "", "bluffs": rows}
    review.write_text(json.dumps({"format": apply.REVIEW_FORMAT_V2, "season": "S23", "games": [game]}),
                      encoding="utf-8")

    import analyze_incremental
    import endgame_records
    import game_derivations
    import game_records
    import media_ingest
    import voting_core

    monkeypatch.setattr(analyze_incremental, "validate_candidate", lambda value, *a, **k: value)
    monkeypatch.setattr(game_records, "validate", lambda *a, **k: None)
    monkeypatch.setattr(voting_core, "validate", lambda *a, **k: None)
    monkeypatch.setattr(endgame_records, "validate", lambda *a, **k: None)

    def derive(game_dossier, game_voting, **kwargs):
        return {"dossier": deepcopy(game_dossier), "voting": deepcopy(game_voting),
                "derivations": {"gaps": [], "issues": [], "terminal": {
                    "round": 1, "phase": "day"}, "input_hashes": {
                    "endgame": game_derivations.fingerprint(kwargs["endgame"])}}}

    monkeypatch.setattr(game_derivations, "derive_game", derive)
    monkeypatch.setattr(game_derivations, "apply_precomputed", lambda game_dossier, game_voting, _: {
        "dossier": deepcopy(game_dossier), "voting": deepcopy(game_voting)})
    monkeypatch.setattr(media_ingest, "validate_media", lambda path, bvid, page: {
        "manifest": json.loads(path.read_text(encoding="utf-8"))})
    return root, state, review, key


def test_apply_writes_only_final_game_and_same_result_is_idempotent(tmp_path, monkeypatch):
    root, state, review, key = _fixture(tmp_path, monkeypatch)
    report = apply.apply_review(review, season="S23", root=root, apply=True)
    state_path = root / "data/reports/S23/incremental/state.json"
    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    item = state_after["items"][key]
    destination = root / item["formal_dir"]
    game_path = destination / "game.json"

    assert report["state"] == "completed"
    assert game_path.is_file()
    assert [path.name for path in destination.iterdir()] == ["game.json"]
    game = json.loads(game_path.read_text(encoding="utf-8"))
    assert game["schema_version"] == 1
    assert game["bluff_review_available"] is True
    assert game["source"]["media"] == [{
        "bvid": "BV1ABCDEF123", "cid": 456, "page": 1,
        "url": "https://www.bilibili.com/video/BV1ABCDEF123/?p=1",
    }]
    assert game["board"] == {"code": "mixed_blood", "name": "预女猎白混"}
    assert "release_id" not in game and "presentation" not in game
    assert game["terminal_observation"] == {"round": 1, "phase": "day"}
    assert any(event["slot"] == "disqualification" for event in game["rounds"][0]["day"])
    assert item["phases"] == {"formal": "done"}
    assert item["applied"] is True
    original_bytes = game_path.read_bytes()

    again = apply.apply_review(review, season="S23", root=root, apply=True)

    assert again["state"] == "completed"
    assert game_path.read_bytes() == original_bytes
    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after["items"][key]["phases"] == {"formal": "done"}
    assert state_after["items"][key]["applied"] is True

    payload = json.loads(review.read_text(encoding="utf-8"))
    payload["games"][0]["note"] = "不同复核结论"
    review.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(apply.ReviewApplyError, match="已应用备注或悍跳结论不同"):
        apply.apply_review(review, season="S23", root=root, apply=True)


def test_formal_ownership_rejects_existing_game_with_same_source_elsewhere(tmp_path):
    bvid, cid, page = "BV1ABCDEF123", 456, 1
    destination = tmp_path / "data/games/S23/2026-10-27_g01_BV1ABCDEF123"
    other = tmp_path / "data/games/S23/other/game.json"
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps({"id": "different-game", "source": {"media": [
        {"bvid": bvid, "cid": cid, "page": page, "url": "https://example.test/video"},
    ]}}), encoding="utf-8")
    entry = {"bvid": bvid, "cid": cid, "page": page}
    final_game = {"id": "bili-BV1ABCDEF123-p01-g01", "source": {"media": [
        {"bvid": bvid, "cid": cid, "page": page, "url": "https://example.test/video"},
    ]}}

    with pytest.raises(apply.ReviewApplyError, match="已在其他正式目录出现"):
        apply._check_formal_ownership(tmp_path, "S23", {}, destination, entry, final_game)


def test_apply_preserves_reviewed_badge_loss_and_terminal_shot_window(tmp_path, monkeypatch):
    from scripts.game_timeline import build_game_timeline

    root, state, review, key = _fixture(tmp_path, monkeypatch)
    entry = state["items"][key]["entry"]
    folder = work_dir(root, "S23", entry)
    candidate_path = folder / "candidate.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["dossier"]["winner"] = "werewolf"
    candidate["dossier"]["seats"][4]["role"] = "猎人"
    candidate["dossier"]["seats"][3]["role"] = "女巫"
    candidate["dossier"]["rounds"][0]["day"] = [
        {"slot": "sheriff_result", "action": "none", "actor": None, "targets": []},
        {"slot": "exile_result", "action": "exile", "targets": [5]},
        {"slot": "hunter_shot", "action": "unavailable", "actor": 5, "targets": []},
    ]
    candidate["dossier"]["_publication_context"] = {"supplemental_events": [
        {"round": 1, "phase": "day", "event": {
            "slot": "sheriff_result", "action": "badge_lost", "actor": None,
            "targets": [], "result": "警长票两轮平票，警徽流失。"}},
        {"round": 1, "phase": "day", "event": {
            "slot": "hunter_shot", "action": "unavailable", "actor": 5,
            "targets": [], "blocked_by_game_end": True,
            "result": "放逐后直接宣胜，无后续猎枪窗口。"}},
    ]}
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    state["items"][key]["candidate_sha256"] = _digest(candidate_path)
    save_state(root, "S23", state)
    payload = json.loads(review.read_text(encoding="utf-8"))
    payload["games"][0]["candidate_sha256"] = _digest(candidate_path)
    review.write_text(json.dumps(payload), encoding="utf-8")

    apply.apply_review(review, season="S23", root=root, apply=True)

    updated = json.loads((root / "data/reports/S23/incremental/state.json").read_text(encoding="utf-8"))
    game = json.loads((root / updated["items"][key]["formal_dir"] / "game.json").read_text(encoding="utf-8"))
    day = game["rounds"][0]["day"]
    shots = [event for event in day if event["slot"] == "hunter_shot"]
    assert len(shots) == 1 and shots[0]["blocked_by_game_end"] is True
    assert [event["action"] for event in day if event["slot"] == "sheriff_result"] == ["badge_lost"]
    assert not any("最后一张神牌" in note for note in game["data_notes"])
    items = [item for phase in build_game_timeline(game)["phases"] for item in phase["items"]]
    assert any(item["slot"] == "sheriff_result" and "流失" in item["text"] for item in items)
    assert not any(item["slot"] == "hunter_shot" for item in items)


def test_unselected_manual_success_falls_back_to_rule_evaluation(monkeypatch):
    from website.api import bluffs

    monkeypatch.setattr(bluffs, "evaluate_success", lambda game, seat: {"value": True})
    seats = [
        {"seat": 1, "person_id": "person-1", "name": "狼甲", "role": "狼人", "faction": "werewolf"},
        {"seat": 2, "person_id": "person-2", "name": "狼乙", "role": "狼人", "faction": "werewolf"},
    ]
    rows = [{"seat": 1, "decision": "yes", "success": ""},
            {"seat": 2, "decision": "", "success": ""}]
    selection = apply._selected_bluffs({"bluffs": rows}, {"dossier": {"seats": seats}}, required=True)
    review = apply._combine_bluff_reviews({"reviewed": False, "no_bluff": False, "items": []}, selection)
    game = {"id": "game-1", "source": {"bvid": "BV1ABCDEF123"}, "seats": seats}

    projected = apply._public_bluffs(game, {"bluffs_review": review})

    assert [row["decision"] for row in projected] == ["yes", "no"]
    assert projected[0]["success"] is True
    assert projected[0]["success_source"] == "rules"
    assert projected[0]["manual_included"] is False


def test_selected_null_success_stays_pending_when_rules_can_judge(monkeypatch):
    from website.api import bluffs

    monkeypatch.setattr(bluffs, "evaluate_success", lambda game, seat: {"value": True})
    seats = [
        {"seat": 1, "person_id": "person-1", "name": "狼甲", "role": "狼人", "faction": "werewolf"},
        {"seat": 2, "person_id": "person-2", "name": "狼乙", "role": "狼人", "faction": "werewolf"},
    ]
    rows = [{"seat": 1, "decision": "yes", "success": "uncertain"},
            {"seat": 2, "decision": "", "success": ""}]
    selection = apply._selected_bluffs({"bluffs": rows}, {"dossier": {"seats": seats}}, required=True)
    review = apply._combine_bluff_reviews({"reviewed": False, "no_bluff": False, "items": []}, selection)
    game = {"id": "game-1", "source": {"bvid": "BV1ABCDEF123"}, "seats": seats}

    projected = apply._public_bluffs(game, {"bluffs_review": review})

    assert review["items"][0]["success_selected"] is True
    assert projected[0]["success"] is None
    assert projected[0]["success_source"] == "user"
    assert projected[0]["success_needs_review"] is True

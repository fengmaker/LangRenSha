"""Failure checks for the identity-only import boundary."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_s21_identities as identities
from database import ReviewError


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    monkeypatch.setattr(identities, "ROOT", tmp_path)
    bvid = "BVidentity"
    frame = Path(f"data/extractions/S21/frames/{bvid}/frame_00001.000.png")
    (tmp_path / frame).parent.mkdir(parents=True)
    (tmp_path / frame).write_bytes(b"immutable-source-frame")
    evidence = {"path": frame.as_posix(), "sha256": hashlib.sha256(b"immutable-source-frame").hexdigest(), "requested_time_ms": 1000}
    visual = {"status": "ai_visual_checked", "reviewer": "test", "bvid": bvid, "cid": 7, "page": 1,
              "actually_inspected_frames": [evidence], "seats": [
                  {"seat": n, "name": f"player{n}", "role": "平民", "evidence": evidence}
                  for n in range(1, 13)]}
    path = tmp_path / f"data/extractions/S21/game_reviews/{bvid}/visual_review.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(visual), encoding="utf-8")
    for other in (identities.CORRECTIONS, identities.NAMES, identities.PHOTOS):
        (tmp_path / other).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / other).write_text("{}", encoding="utf-8")
    return {"bvid": bvid, "cid": 7, "page": 1}, visual, path, tmp_path / frame


def update(path, visual):
    path.write_text(json.dumps(visual), encoding="utf-8")


def test_rejects_source_frame_changed_after_review(reviewed):
    entry, _, _, frame = reviewed
    frame.write_bytes(b"different-frame")
    with pytest.raises(ReviewError, match="SHA"):
        identities.prepare(entry, {}, [])


def test_rejects_uninspected_visual_proof(reviewed):
    entry, visual, path, _ = reviewed
    visual["actually_inspected_frames"] = []
    update(path, visual)
    with pytest.raises(ReviewError, match="实际查看"):
        identities.prepare(entry, {}, [])


def test_rejects_duplicate_canonical_people(reviewed):
    entry, _, _, _ = reviewed
    with pytest.raises(ReviewError, match="姓名.*重复"):
        identities.prepare(entry, {"player1": "same-person", "player2": "same-person"}, [])


def test_unknowns_stay_null_and_only_identity_fields_survive(reviewed):
    entry, visual, path, _ = reviewed
    visual["seats"][0]["name"] = None
    visual["seats"][0]["role"] = "未知"
    visual["winner"] = {"value": "werewolf"}
    visual["night"] = [{"fabricated": True}]
    update(path, visual)
    payload = identities.prepare(entry, {}, [])["payload"]
    assert payload["seats"][0]["name"] is None
    assert payload["seats"][0]["role"] is None
    assert not {"winner", "night", "day", "bluffs"}.intersection(payload)
    assert payload["field_scope"] == ["seat", "name", "role"]


def test_stale_primary_correction_rejected(reviewed):
    entry, visual, _, _ = reviewed
    correction = {"bvid": entry["bvid"], "seat": 1, "field": "name", "before": "old-name", "after": "new-name",
                  "evidence": copy.deepcopy(visual["seats"][0]["evidence"])}
    with pytest.raises(ReviewError, match="旧值不匹配"):
        identities.prepare(entry, {}, [correction])


def recap_correction(reviewed):
    entry, _, _, frame = reviewed
    root = frame.parents[5]
    source = root / "original.json"
    source.write_bytes(b"original-referee-recap")
    transcript = {"bvid": entry["bvid"], "source_path": "original.json",
                  "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "segments": [{"text": "终局复盘：1号女巫", "start_ms": 2000, "end_ms": 3000}]}
    path = Path(f"data/extractions/S21/media_evidence/{entry['bvid']}/transcript.selected.json")
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(json.dumps(transcript), encoding="utf-8")
    return {"bvid": entry["bvid"], "seat": 1, "field": "role", "before": "平民", "after": "女巫",
            "evidence": {"path": path.as_posix(), "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest(),
                         "kind": "literal_transcript", "source_segment_indices": [0],
                         "quote": "终局复盘：1号女巫", "start_ms": 2000, "end_ms": 3000}}


def test_referee_recap_can_correct_fantasy_role_without_changing_name(reviewed):
    correction = recap_correction(reviewed)
    payload = identities.prepare(reviewed[0], {}, [correction])["payload"]
    assert payload["seats"][0]["role"] == "女巫"
    assert payload["seats"][0]["name"] == "player1"
    assert payload["seats"][0]["role_basis"] == "terminal_referee_recap_overrides_fantasy_view"


def test_referee_correction_rejects_invented_quote(reviewed):
    correction = recap_correction(reviewed)
    correction["evidence"]["quote"] = "invented"
    with pytest.raises(ReviewError, match="原文"):
        identities.prepare(reviewed[0], {}, [correction])


def test_referee_correction_rejects_cross_media_source(reviewed):
    correction = recap_correction(reviewed)
    correction["evidence"]["path"] = correction["evidence"]["path"].replace("BVidentity", "BVother")
    with pytest.raises(ReviewError, match="来源"):
        identities.prepare(reviewed[0], {}, [correction])

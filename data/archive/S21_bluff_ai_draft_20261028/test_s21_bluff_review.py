import json
from pathlib import Path

import pytest

from scripts import build_s21_bluff_review as builder


def _bundle(tmp_path: Path) -> dict:
    segment = {"index": 3, "start_ms": 1000, "end_ms": 1800, "text": "我今天是预言家"}
    return {
        "root": tmp_path,
        "entry": {"bvid": "BV1abcdefghij", "cid": 77, "page": 1},
        "identity": {"seats": [{"seat": 4, "name": "测试玩家", "role": "狼人"}]},
        "transcript": {"segments": [segment]},
        "identity_sha256": "i" * 64,
        "phase_sha256": "p" * 64,
        "transcript_sha256": "t" * 64,
        "original_source_path": "data/raw/source.json",
        "original_source_sha256": "o" * 64,
    }


def _assessment(bundle: dict) -> dict:
    return {
        "schema_version": 1,
        "season": "S21",
        "bvid": bundle["entry"]["bvid"],
        "cid": bundle["entry"]["cid"],
        "page": bundle["entry"]["page"],
        "identity_reviewed_sha256": bundle["identity_sha256"],
        "phase_reviewed_sha256": bundle["phase_sha256"],
        "transcript_selected_sha256": bundle["transcript_sha256"],
        "original_source_path": bundle["original_source_path"],
        "original_source_sha256": bundle["original_source_sha256"],
        "assessments": [{
            "seat": 4,
            "name": "测试玩家",
            "physical_role": "狼人",
            "decision": "yes",
            "claimed_role": "预言家",
            "claim_day": 1,
            "decision_note": "本人明确自称信息神。",
            "evidence": [{
                "segment_indices": [3], "start_ms": 1000, "end_ms": 1800,
                "quote": "我今天是预言家",
            }],
            "faction": None,
            "faction_evidence": [],
            "reviewed_ranges": [{"start_ms": 0, "end_ms": 2200, "phase": "day1", "complete": True}],
            "explicit_gaps": [],
        }],
    }


def test_literal_evidence_requires_exact_selected_segment_text():
    transcript = {"segments": [{"index": 3, "start_ms": 1000, "end_ms": 1800, "text": "我今天是预言家"}]}
    evidence = {"segment_indices": [3], "start_ms": 1000, "end_ms": 1800, "quote": "我今天是预言家"}

    assert builder._literal_evidence(transcript, evidence, "test")["quote"] == "我今天是预言家"
    with pytest.raises(builder.BuildError, match="literal segments"):
        builder._literal_evidence(transcript, {**evidence, "quote": "我是预言家"}, "test")


def test_missing_assessment_file_is_not_automatically_no(tmp_path):
    rows, present = builder._load_assessments(tmp_path, _bundle(tmp_path))

    assert rows == {}
    assert present is False


def test_completion_requires_no_unresolved_review_items():
    counts = {"yes": 1, "no": 1, "uncertain": 0, "missing": 0}
    assert builder._completion_flags(counts, faction_unresolved=0, success_excluded=0) == (True, True)
    assert builder._completion_flags({**counts, "uncertain": 1}, 0, 0) == (False, True)
    assert builder._completion_flags(counts, 1, 0) == (False, True)
    assert builder._completion_flags(counts, 0, 1) == (False, True)
    assert builder._completion_flags({**counts, "missing": 1}, 0, 0) == (False, False)


def test_assessment_requires_current_source_binding_and_literal_evidence(tmp_path):
    bundle = _bundle(tmp_path)
    target = tmp_path / builder.ASSESSMENTS / f"{bundle['entry']['bvid']}.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(_assessment(bundle), ensure_ascii=False), encoding="utf-8")

    rows, present = builder._load_assessments(tmp_path, bundle)
    assert present is True
    assert rows[4]["decision"] == "yes"
    assert rows[4]["evidence"][0]["segment_indices"] == [3]

    bad = _assessment(bundle)
    bad["phase_reviewed_sha256"] = "x" * 64
    target.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(builder.BuildError, match="phase_reviewed_sha256"):
        builder._load_assessments(tmp_path, bundle)


def test_manual_wolf_faction_requires_source_evidence(tmp_path):
    bundle = _bundle(tmp_path)
    payload = _assessment(bundle)
    payload["assessments"][0]["faction"] = "werewolf"
    target = tmp_path / builder.ASSESSMENTS / f"{bundle['entry']['bvid']}.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(builder.BuildError, match="literal source evidence"):
        builder._load_assessments(tmp_path, bundle)


def test_assessment_rows_keep_success_contract_reasons_and_questions():
    bundle = _bundle(Path("."))
    assessment = {
        "seat": 4, "name": "测试玩家", "physical_role": "狼人", "decision": "yes",
        "claimed_role": "预言家", "claim_day": 1, "decision_note": "本人明确自称。",
        "evidence": [], "faction_evidence": [], "reviewed_ranges": [], "explicit_gaps": [],
        "faction_override": None,
    }
    game = {"id": "sample-game", "seats": [
        {"seat": 4, "name": "测试玩家", "role": "狼人", "faction": "werewolf"}
    ]}
    reasons = [{"kind": "first_day_good_exiled", "text": "首日最终放逐好人"}]
    questions = ["警徽结果待确认"]

    rows = builder._assessment_rows(
        bundle, {4: assessment}, game,
        [{"seat": 4, "success": None, "success_reasons": reasons, "review_questions": questions}],
    )

    assert rows[0]["success"] is None
    assert rows[0]["success_reasons"] == reasons
    assert rows[0]["success_questions"] == questions

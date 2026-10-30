from copy import deepcopy

import pytest

from scripts import build_manual_bluff_publication as builder
from website.api import bluffs


def fixture(*, badge_winner=2):
    bvid = "BV1234567890"
    seats = []
    for number in range(1, 13):
        role = "狼人" if number in (1, 2) else "平民"
        faction = "werewolf" if number in (1, 2) else "good"
        if number == 3:
            role, faction = "混血儿", "werewolf"
        seats.append({
            "seat": number, "person_id": f"player-{number}", "name": f"选手{number}",
            "role": role, "faction": faction,
        })
    game = {
        "id": "game-1", "season": "S23", "date": "2026-10-06", "game_number": 2,
        "source": {"bvid": bvid}, "seats": seats,
        "rounds": [{"number": 1, "day": [
            {"slot": "sheriff_result", "action": "elected", "targets": [badge_winner]},
            {"slot": "exile_result", "action": "exile", "targets": [4]},
        ]}],
        "voting": {"days": [{"day": 1, "sheriff": "recorded", "exile": "recorded"}], "ballots": []},
    }
    review_id = f"S23:{bvid}:p1"
    review_game = {
        "review_id": review_id, "bvid": bvid, "cid": 123, "page": 1,
        "date": game["date"], "game_number": game["game_number"],
        "title": "2026-10-06 第02局 · 测试",
        "seats": [{key: row[key] for key in ("seat", "name", "role")} for row in seats],
    }
    source = {
        "format": "masters-manual-bluff-review-v1", "season": "S23",
        "source_fingerprint": "a" * 64, "dates": [game["date"]], "games": [review_game],
    }
    manual = deepcopy(source)
    manual["games"][0]["reviews"] = [{
        "id": review_id, "reviewed": False, "no_bluff": False,
        "rows": [{"seat": 2, "success": "no", "note": "用户备注原文"}], "note": "局备注原文",
    }]
    old_assessments = [{
        "seat": number, "name": seats[number - 1]["name"], "physical_role": seats[number - 1]["role"],
        "decision": "yes" if number == 1 else "no",
        "claimed_role": "预言家" if number == 1 else None,
        "claim_day": 1 if number == 1 else None,
        "verification_status": "assistant_inferred", "evidence": [],
    } for number in (1, 2)]
    baseline = {
        "schema_version": 1, "season": "S23", "inference_version": "old-v1",
        "games": [{
            "game_id": game["id"], "bvid": bvid,
            "source_fingerprint": bluffs.source_fingerprint(game),
            "coverage": "first_day_video_and_transcript",
            "assessments": old_assessments,
        }],
        "summary": {"wolf_appearances": 2, "separate_identity_claims": 4},
    }
    return manual, source, [game], baseline


def test_rejects_user_metadata_that_does_not_match_generated_source():
    manual, source, games, baseline = fixture()
    manual["games"][0]["title"] = "改过的标题"

    with pytest.raises(builder.ManualReviewError, match="元数据与来源不一致"):
        builder.build_payload(manual, source, games, baseline, "b" * 64)


def test_rejects_a_published_game_with_a_different_schedule():
    manual, source, games, baseline = fixture()
    games[0]['date'] = '2026-10-07'
    with pytest.raises(builder.ManualReviewError, match='日期或局次'):
        builder.build_payload(manual, source, games, baseline, 'b' * 64)


def test_blank_game_keeps_its_baseline_record_without_becoming_no_bluff():
    manual, source, games, baseline = fixture()
    manual["games"][0]["reviews"] = [{
        "id": manual["games"][0]["review_id"], "reviewed": False,
        "no_bluff": False, "rows": [], "note": "",
    }]
    baseline["games"][0]["untouched_marker"] = {"value": 7}
    old_game = deepcopy(baseline["games"][0])

    payload, report = builder.build_payload(manual, source, games, baseline, "b" * 64)

    assert payload["games"][0] == old_game
    assert payload["games"][0]["assessments"][0]["decision"] == "yes"
    assert payload["summary"]["decisions"] == {"yes": 0, "no": 1, "uncertain": 1}
    assert payload["summary"]["manual_reviewed_games"] == 0
    assert report["blank_games_preserved"] == 1
    assert report["no_bluff_games"] == 0


def test_user_selection_includes_hybrid_and_preserves_explicit_unknown_and_notes():
    manual, source, games, baseline = fixture()
    manual["games"][0]["reviews"][0]["rows"] = [{
        "seat": 3, "success": "unknown", "note": "混血儿用户备注原文",
    }]

    payload, report = builder.build_payload(manual, source, games, baseline, "c" * 64)

    assessments = {row["seat"]: row for row in payload["games"][0]["assessments"]}
    hybrid = assessments[3]
    assert hybrid["decision"] == "yes"
    assert hybrid["manual_included"] is True
    assert hybrid["manual_success"] is None
    assert hybrid["manual_note"] == "混血儿用户备注原文"
    assert hybrid["manual_game_note"] == "局备注原文"
    assert hybrid["manual_source_sha256"] == "c" * 64
    assert hybrid["manual_review_id"] == manual["games"][0]["review_id"]
    item = next(row for row in bluffs.review_items(games, payload) if row["seat"] == 3)
    assert item["success"] is None and item["success_source"] == "user"
    assert payload["summary"]["wolf_appearances"] == 2
    assert payload["summary"]["manual_included_appearances"] == 1
    assert payload["manual_review"]["covered_games"] == 1
    assert report["unknown_successes"] == 1


def test_manual_success_overrides_automatic_success_and_user_remark_survives():
    manual, source, games, baseline = fixture(badge_winner=2)
    manual["games"][0]["reviews"][0]["rows"] = [{
        "seat": 2, "success": "no", "note": "人工判失败，原文保留",
    }]

    payload, _ = builder.build_payload(manual, source, games, baseline, "d" * 64)

    item = next(row for row in bluffs.review_items(games, payload) if row["seat"] == 2)
    assert item["success"] is False
    assert item["success_source"] == "user"
    assessment = next(row for row in payload["games"][0]["assessments"] if row["seat"] == 2)
    assert assessment["manual_note"] == "人工判失败，原文保留"
    assert assessment["claimed_role"] is None
    assert assessment["claim_day"] is None
    assert assessment["actual_claim_day"] is None
    assert assessment["first_day_claim"] is None


def test_rebuilding_legacy_manual_success_keeps_the_locked_human_result():
    manual, source, games, baseline = fixture()
    selected = manual["games"][0]["reviews"][0]["rows"][0]
    selected.update(seat=1, success="yes", note="原人工成功备注")
    old = baseline["games"][0]["assessments"][0]
    old.update(decision="yes", verification_status="user_confirmed", manual_success=True,
               manual_source_sha256="d" * 64, manual_review_id=manual["games"][0]["review_id"],
               decision_note="旧备注")

    payload, _ = builder.build_payload(manual, source, games, baseline, "d" * 64)

    assessment = next(row for row in payload["games"][0]["assessments"] if row["seat"] == 1)
    assert assessment["manual_success"] is True
    assert "success_fingerprint" not in assessment
    item = next(row for row in bluffs.review_items(games, payload) if row["seat"] == 1)
    assert item["decision"] == "yes" and item["success"] is True
    assert item["legacy_success_needs_review"] is False
    assert item["previous_success"] is True


def test_feedback_import_and_builder_apply_an_explicit_change_to_a_locked_success(monkeypatch):
    from scripts.import_bluff_feedback import validate_feedback

    manual, source, games, baseline = fixture()
    games[0]["bvid"] = games[0]["source"]["bvid"]
    baseline, _ = builder.build_payload(manual, source, games, baseline, "d" * 64)
    assessment = next(row for row in baseline["games"][0]["assessments"] if row["seat"] == 2)
    assessment.pop("success_fingerprint")
    item = next(row for row in bluffs.review_items(games, baseline) if row["seat"] == 2)
    assert item["success"] is False and item["legacy_success_needs_review"] is False
    record = {key: item.get(key) for key in (
        "review_id", "game_id", "bvid", "seat", "name", "physical_role", "source_fingerprint",
        "claim_fingerprint", "success_fingerprint", "claimed_role", "claim_day")}
    record.update(decision="", manual_success=True, notes="用户明确改为成功")
    value = {"kind": "s22_bluff_feedback", "schema_version": 1, "season": "S23", "records": [record]}
    monkeypatch.setattr("scripts.import_bluff_feedback.load_review", lambda _season: baseline)
    imported = validate_feedback(value, games, "S23")

    updated, report = builder.build_payload(manual, source, games, baseline, "d" * 64, imported)

    saved = next(row for row in updated["games"][0]["assessments"] if row["seat"] == 2)
    item = next(row for row in bluffs.review_items(games, updated) if row["seat"] == 2)
    assert saved["manual_success"] is True and saved["success_fingerprint"] == record["success_fingerprint"]
    assert item["success"] is True and item["success_source"] == "user"
    assert "用户备注原文" in item["decision_note"] and "用户明确改为成功" in item["decision_note"]
    assert report["success_feedback_games"] == 1


@pytest.mark.parametrize("mutation, message", [
    ("duplicate", "重复选择"),
    ("contradiction", "无人悍跳和选中座位"),
    ("invalid_success", "成功结果只能是"),
])
def test_rejects_duplicate_or_contradictory_user_choices(mutation, message):
    manual, source, games, baseline = fixture()
    review = manual["games"][0]["reviews"][0]
    if mutation == "duplicate":
        review["rows"].append(deepcopy(review["rows"][0]))
    elif mutation == "contradiction":
        review["no_bluff"] = True
    else:
        review["rows"][0]["success"] = "maybe"

    with pytest.raises(builder.ManualReviewError, match=message):
        builder.build_payload(manual, source, games, baseline, "e" * 64)

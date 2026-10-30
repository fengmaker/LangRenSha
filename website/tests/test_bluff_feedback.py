from copy import deepcopy

import pytest

from scripts.import_bluff_feedback import validate_feedback,source_games
from scripts.recover_bluff_feedback_text import recover_feedback
from scripts import build_manual_bluff_publication
from scripts import build_bluff_inference
from website.api.bluffs import claim_fingerprint, review_items, source_fingerprint
from website.tests.test_bluffs import review as signed_review, sample


def feedback():
    game = sample()
    game["bvid"] = "BV1kGVC6cEyg"
    value = {"kind": "s22_bluff_feedback", "schema_version": 1, "season": "S22", "records": [{
        "review_id": f"{game['bvid']}:1", "bvid": game["bvid"], "game_id": game["id"], "seat": 1,
        "name": "狼甲", "physical_role": "狼人", "source_fingerprint": source_fingerprint(game),
        "decision": "yes", "claimed_role": "通灵师", "claim_day": 1, "notes": "首日已自称。"}]}
    return value, game


def test_feedback_roundtrip_keeps_comments_separate_from_confirmation():
    value, game = feedback()
    result = validate_feedback(value, [game])
    assert next(iter(result.values()))["decision"] == "yes"
    assert 'manual_success' not in next(iter(result.values()))
    value["records"][0]["decision"] = ""
    assert next(iter(validate_feedback(value, [game]).values()))["decision"] == "comment"
    value["records"][0]["notes"] = "  "
    assert validate_feedback(value, [game]) == {}


def test_signed_feedback_survives_unrelated_game_change(monkeypatch):
    value, game = feedback()
    game["source"] = {"bvid": game["bvid"]}
    payload = signed_review(game)
    item = next(row for row in review_items([game], payload) if row["seat"] == 1)
    value["records"][0]["claim_fingerprint"] = item["claim_fingerprint"]
    monkeypatch.setattr("scripts.import_bluff_feedback.load_review", lambda _season: payload)

    changed = deepcopy(game)
    changed["voting"]["ballots"].append({"kind": "exile", "day": 2, "winner": 4})
    assert source_fingerprint(changed) != payload["games"][0]["source_fingerprint"]
    assert next(iter(validate_feedback(value, [changed]).values()))["claim_fingerprint"] == item["claim_fingerprint"]


def test_success_feedback_roundtrip_updates_only_selected_legacy_manual_result(monkeypatch):
    game = sample()
    game["source"] = {"bvid": "BV1kGVC6cEyg"}
    game["bvid"] = game["source"]["bvid"]
    baseline = signed_review(game)
    reviewed_game = baseline["games"][0]
    row = reviewed_game["assessments"][0]
    row.update(verification_status="user_confirmed", manual_success=True,
               manual_source_sha256="f" * 64, manual_review_id="manual-review",
               decision_note="既有人工备注保留")
    row["claim_fingerprint"] = claim_fingerprint(game, row)
    row.pop("success_fingerprint")  # Existing manual outcome has no dependency baseline.
    current_item = next(item for item in review_items([game], baseline) if item["seat"] == 1)
    assert current_item["legacy_success_needs_review"] is False
    assert current_item['success'] is True

    value = {"kind": "s22_bluff_feedback", "schema_version": 1, "season": "S22", "records": [{
        "review_id": current_item["review_id"], "game_id": game["id"], "bvid": game["source"]["bvid"],
        "seat": 1, "name": current_item["name"], "physical_role": current_item["physical_role"],
        "source_fingerprint": current_item["source_fingerprint"],
        "claim_fingerprint": current_item["claim_fingerprint"],
        "success_fingerprint": current_item["success_fingerprint"],
        "decision": "", "claimed_role": current_item["claimed_role"],
        "claim_day": current_item["claim_day"], "manual_success": False,
        "notes": "重新核对后确认失败。",
    }]}
    monkeypatch.setattr("scripts.import_bluff_feedback.load_review", lambda _season: baseline)
    imported = validate_feedback(value, [game])
    assert len(imported) == 1

    assert build_manual_bluff_publication._apply_success_feedback(game, reviewed_game, imported) is True
    updated = next(item for item in review_items([game], baseline) if item["seat"] == 1)
    untouched = next(item for item in review_items([game], baseline) if item["seat"] == 4)
    assert updated["success"] is False and updated["success_source"] == "user"
    assert updated["decision_note"].startswith("既有人工备注保留")
    assert "重新核对后确认失败" in updated["decision_note"]
    assert untouched["decision"] == "no" and not reviewed_game["assessments"][1].get("manual_success")


def test_feedback_can_confirm_only_a_currently_manual_included_seat(monkeypatch):
    game = sample()
    game["bvid"] = "BV1kGVC6cEyg"
    game["source"] = {"bvid": game["bvid"]}
    payload = signed_review(game)
    mixed = game["seats"][1]
    mixed["role"] = "混血儿"
    mixed["faction"] = "good"
    row = {"seat": mixed["seat"], "name": mixed["name"], "physical_role": mixed["role"],
           "decision": "yes", "claimed_role": "通灵师", "claim_day": 1,
           "verification_status": "user_confirmed", "manual_included": True,
           "evidence": [{"kind": "recap", "text": "2号悍跳狼人",
                         "source_ref": "e" * 64, "source_sha256": "a" * 64}]}
    row["claim_fingerprint"] = claim_fingerprint(game, row)
    from website.api.bluffs import success_fingerprint
    row["success_fingerprint"] = success_fingerprint(game, 2, 1)
    payload["games"][0]["assessments"].append(row)
    monkeypatch.setattr("scripts.import_bluff_feedback.load_review", lambda _season: payload)
    item = next(item for item in review_items([game], payload) if item["seat"] == 2)
    record = {key: item.get(key) for key in (
        "review_id", "game_id", "bvid", "seat", "name", "physical_role", "source_fingerprint",
        "claim_fingerprint", "success_fingerprint", "claimed_role", "claim_day")}
    record.update(decision="", manual_success=True, notes="已确认")
    value = {"kind": "s22_bluff_feedback", "schema_version": 1, "season": "S22", "records": [record]}

    imported = validate_feedback(value, [game])
    assert imported[record["review_id"]]["manual_success"] is True

    # The same non-wolf seat is rejected when there is no current manual-inclusion proof.
    payload["games"][0]["assessments"].pop()
    with pytest.raises(ValueError, match="选手或狼人底牌不匹配"):
        validate_feedback(value, [game])


def test_inference_builder_applies_only_current_success_feedback():
    game = sample()
    payload = signed_review(game)
    assessment = deepcopy(payload["games"][0]["assessments"][0])
    item = next(row for row in review_items([game], payload) if row["seat"] == 1)
    feedback = {
        "decision": "comment", "claim_day": item["claim_day"],
        "claimed_role": item["claimed_role"], "claim_fingerprint": item["claim_fingerprint"],
        "success_fingerprint": item["success_fingerprint"], "manual_success": False,
        "notes": "人工复核后确认失败",
    }

    assert build_bluff_inference._apply_success_feedback(game, assessment, feedback) is True
    assert assessment["manual_success"] is False
    assert assessment["verification_status"] == "user_confirmed"
    assert "人工复核后确认失败" in assessment["decision_note"]

    stale = deepcopy(assessment)
    changed = deepcopy(game)
    changed["seats"][1]["faction"] = "werewolf"
    with pytest.raises(ValueError, match="dependency changed"):
        build_bluff_inference._apply_success_feedback(changed, stale, feedback)


def test_s23_feedback_is_season_bound_and_preserves_unknown_fields():
    value,game=feedback()
    value['season']='S23'
    value['records'][0].update(claim_day=None,claimed_role=None)
    with pytest.raises(ValueError):validate_feedback(value,[game])
    row=next(iter(validate_feedback(value,[game],'S23').values()))
    assert row['claim_day'] is None and row['claimed_role'] is None
    assert row['decision']=='yes'


def test_s23_feedback_uses_the_same_terminal_boundary_as_the_published_game():
    games=source_games('S23')
    assert len(games)==75
    terminal=next(g for g in games if g['bvid']=='BV17xpA6aE7N')
    assert next(r for r in terminal['rounds'] if r['number']==4)['day']==[]


@pytest.mark.parametrize("change", [
    {"source_fingerprint": "0" * 64}, {"name": "另一人"}, {"physical_role": "通灵师"},
    {"claim_day": True}, {"claimed_role": "女巫"}, {"decision": "unsupported"},
    {"normalization_notes": ["有效说明", 2]},
])
def test_feedback_rejects_stale_or_misidentified_records(change):
    value, game = feedback()
    value["records"][0].update(change)
    with pytest.raises(ValueError):
        validate_feedback(value, [game])


def test_good_card_cannot_be_confirmed_as_wolf_bluff_and_duplicates_are_rejected():
    value, game = feedback()
    value["records"].append(deepcopy(value["records"][0]))
    with pytest.raises(ValueError):
        validate_feedback(value, [game])
    value["records"].pop()
    game["seats"][0]["role"] = "预言家"
    value["records"][0].update(physical_role="预言家", source_fingerprint=source_fingerprint(game))
    with pytest.raises(ValueError):
        validate_feedback(value, [game])


def test_explicit_confirmation_survives_missing_auxiliary_fields():
    value, game = feedback()
    value["records"][0].update(claim_day=None, claimed_role=None)
    result = next(iter(validate_feedback(value, [game]).values()))
    assert result["decision"] == "yes"
    assert result["claim_day"] is None and result["claimed_role"] is None


def test_copied_form_recovery_preserves_selection_and_comment_without_placeholder():
    value, game = feedback()
    row = value["records"][0]
    text = f'''本页已填写 1 / 586 条
2026-06-01 第1局 · 1号 狼甲 · 悍跳归属待复核
反馈编号：{row['review_id']}
填写本条复核意见
复核结论
确认是悍跳
发生天数
尚未确定
所跳身份
待定／不适用
其他意见
可填写正确座位、首日时间点、所跳身份或不同意见。
本条草稿已保存
'''
    result = recover_feedback(text, [row])
    record = result["records"][0]
    assert record["decision"] == "yes" and record["claim_day"] is None
    assert record["notes"] == "" and record["input_values"]["claimed_role"] == "待定／不适用"
    assert validate_feedback(result, [game])
    with pytest.raises(ValueError):
        recover_feedback(text.replace("已填写 1", "已填写 2"), [row])

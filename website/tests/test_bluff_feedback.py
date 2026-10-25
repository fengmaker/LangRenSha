from copy import deepcopy

import pytest

from scripts.import_bluff_feedback import validate_feedback
from scripts.recover_bluff_feedback_text import recover_feedback
from website.api.bluffs import source_fingerprint
from website.tests.test_bluffs import sample


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
    value["records"][0]["decision"] = ""
    assert next(iter(validate_feedback(value, [game]).values()))["decision"] == "comment"
    value["records"][0]["notes"] = "  "
    assert validate_feedback(value, [game]) == {}


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

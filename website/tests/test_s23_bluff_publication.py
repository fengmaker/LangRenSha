import json

import pytest

from scripts import build_s23_bluff_publication as builder
from website.api import bluffs
from scripts.build_s23_bluff_publication import (
    _assessment,
    _claim_day,
    _evidence,
    _indexed_bluffs,
    _separate_identity_claims,
)


def wolf_seat(seat=6, role="狼人"):
    return {"seat": seat, "person_id": f"player-{seat}", "name": f"狼{seat}",
            "role": role, "faction": "werewolf"}


def test_new_s23_roles_count_only_when_their_published_faction_is_werewolf():
    game = {"seats": [wolf_seat(role="九尾狐"), wolf_seat(seat=7, role="狼术师"),
                      {**wolf_seat(seat=8, role="九尾狐"), "faction": "good"}]}

    assert [row["seat"] for row in game["seats"] if bluffs.physical_wolf(game, row)] == [6, 7]


def test_attempted_values_are_explicit_and_absence_stays_uncertain():
    seat = wolf_seat()
    evidence = [{"kind": "speech", "quote": "我验了3号"}]
    assert _assessment(seat, {"attempted": True, "claimed_role": "预言家", "evidence": evidence}, [])["decision"] == "yes"
    assert _assessment(seat, {"attempted": False}, [])["decision"] == "no"
    assert _assessment(seat, {"attempted": None}, [])["decision"] == "uncertain"
    missing = _assessment(seat, None, [])
    assert missing["decision"] == "uncertain"
    assert "未按未尝试计入" in missing["review_questions"][0]


def test_daily_user_confirmed_override_replaces_the_ai_record():
    review = {
        "bluffs": [{"seat": 6, "attempted": False}],
        "daily_bluff_changes": [{"before": None, "after": {
            "seat": 6, "day": 1, "claimed_role": "通灵师", "attempted": True,
            "confirmation_status": "user_confirmed", "evidence": [],
        }}],
    }

    row = _indexed_bluffs(review)[6]
    assessment = _assessment(wolf_seat(), row, [])
    assert assessment["decision"] == "yes"
    assert assessment["verification_status"] == "user_confirmed"
    assert assessment["claimed_role"] == "通灵师"


def test_ambiguous_claim_role_stays_uncertain_without_guessing():
    assessment = _assessment(wolf_seat(12), {
        "attempted": True, "claimed_role": "预言家/通灵师",
        "evidence": [{"quote": "我跳信息神"}],
    }, [])

    assert assessment["decision"] == "uncertain"
    assert assessment["claimed_role"] is None
    assert "预言家/通灵师" in assessment["decision_note"]


def test_claim_after_day_two_is_stored_as_later_with_original_day_note():
    assert _claim_day(4) == "later"
    assessment = _assessment(wolf_seat(), {
        "attempted": True, "day": 4, "claimed_role": "通灵师",
        "evidence": [{"quote": "我跳通灵师"}],
    }, [])

    assert assessment["decision"] == "yes"
    assert assessment["claim_day"] == "later"
    assert "第4天" in assessment["decision_note"]


def test_eulogy_identity_claim_stays_separate_and_uncertain_without_source_paths():
    seat = wolf_seat(10)
    claim = {
        "seat": 10, "day": 1, "claimed_role": "通灵师", "attempted": None,
        "category_label": "遗言自称", "counting_note": "统计口径待用户决定，暂不计常规悍跳",
        "count_in_physical_wolf_bluffs": False,
        "evidence": [{
            "source_path": "data/seasons/S23/private.json", "source_sha256": "secret",
            "start_ms": 2047320, "quote": "我是通灵师啊",
        }],
    }
    separate = _separate_identity_claims({"separate_identity_claims": [claim]})
    assessment = _assessment(seat, None, separate)
    rendered = str({"assessment": assessment, "separate": separate})

    assert assessment["decision"] == "uncertain"
    assert "遗言阶段" in assessment["decision_note"]
    assert separate[0]["decision"] == "uncertain"
    assert separate[0]["count_in_physical_wolf_bluffs"] is False
    assert "source_path" not in rendered and "source_sha256" not in rendered and "private.json" not in rendered
    assert separate[0]["evidence"][0]["text"] == "我是通灵师啊"
    assert separate[0]["evidence"][0]["start_ms"] == 2047320


def test_public_evidence_is_limited_to_quotes_and_timestamps():
    evidence = _evidence([{
        "source_path": "data/extractions/S23/image.png", "source_sha256": "secret",
        "kind": "video_frame", "frame_time_ms": 3749100, "quote": "画面显示悍跳信息",
    }])

    assert evidence == [{"kind": "video_frame", "text": "画面显示悍跳信息", "start_ms": 3749100}]


@pytest.mark.parametrize("independent,incomplete_legacy", [(True, True), (False, False), (False, True)])
def test_builder_uses_reviewed_assessments_and_preserves_separate_claims(
    tmp_path, monkeypatch, independent, incomplete_legacy,
):
    from website.tests.test_bluffs import sample

    game = sample()
    game.update(season="S23", source={"bvid": "BV1234567890"})
    legacy = {"bvid": game["source"]["bvid"],
              "bluffs": [{"seat": 1, "attempted": incomplete_legacy, "claimed_role": "通灵师"}],
              "separate_identity_claims": [{"seat": 4, "day": 1, "claimed_role": "通灵师",
                  "category_label": "遗言自称", "attempted": None,
                  "count_in_physical_wolf_bluffs": False,
                  "evidence": [{"quote": "我是通灵师", "start_ms": 1000}]}]}
    (tmp_path / "ai_review.json").write_text(json.dumps(legacy), encoding="utf-8")
    entry = {"folder": tmp_path, "bvid": game["source"]["bvid"], "dossier": {"seats": game["seats"]}}
    assessments = [{"seat": seat["seat"], "name": seat["name"], "physical_role": seat["role"],
                    "decision": "yes" if seat["seat"] == 1 else "no",
                    "claimed_role": "通灵师" if seat["seat"] == 1 else None,
                    "claim_day": 1, "first_day_claim": True, "decision_note": "已核本人话轮",
                    "verification_status": "assistant_inferred", "review_questions": [],
                    "evidence": [{"kind": "transcript", "text": "本人话轮", "start_ms": 1000}]}
                   for seat in game["seats"] if bluffs.physical_wolf(game, seat)]
    monkeypatch.setattr(builder, "EXPECTED_GAMES", 1)
    monkeypatch.setattr(builder.publisher, "load_publication", lambda *_: ([entry], "", ""))
    monkeypatch.setattr(builder, "_public_game", lambda *_: game)
    monkeypatch.setattr(builder, "load_audits", lambda *_, **__: {
        game["id"]: {"assessments": assessments}
    } if independent else {})

    if incomplete_legacy and not independent:
        with pytest.raises(builder.BuildError, match="缺少可公开的定位证据"):
            builder.build_payload(tmp_path)
        return

    payload, items, _ = builder.build_payload(tmp_path)
    record = payload["games"][0]
    assert record["assessments"][0]["decision"] == ("yes" if independent else "no")
    assert record["assessments"][0]["review_stage"] == ("reviewed" if independent else "assistant_pending")
    assert record["source_fingerprint"] == bluffs.source_fingerprint(game)
    assert record["separate_identity_claims"][0]["decision"] == "uncertain"
    assert next(item for item in items if item["seat"] == 4)["decision"] == "uncertain"

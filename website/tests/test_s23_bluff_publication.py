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

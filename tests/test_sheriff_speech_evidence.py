import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.sheriff_speech_evidence import (
    analyze_sheriff_speeches,
    load_bound_sheriff_speeches,
)


def segments(*texts):
    result = []
    for position, text in enumerate(texts):
        result.append(
            {
                "index": position,
                "start_ms": position * 1000,
                "end_ms": position * 1000 + 900,
                "text": text,
            }
        )
    return result


class SheriffSpeechEvidenceTests(unittest.TestCase):
    def test_procedural_round_is_supporting_and_never_establishes_complement(self):
        result = analyze_sheriff_speeches(
            {
                "segments": segments(
                    "想上警的玩家请亮红灯",
                    "随机点数四由十一号玩家开始顺序发言",
                    "十一号玩家请发言",
                    "十二号玩家请做发言准备",
                    "十二号玩家请",
                    "发表竞选发言",
                    "1号玩家请发言",
                    "警上所有玩家发言结束",
                    "2号玩家请发言",
                    "请发表遗言",
                    "复盘时，3号玩家说起警上发言",
                )
            }
        )

        round_result = result["rounds"][0]
        self.assertEqual(round_result["day"], 1)
        self.assertEqual(round_result["on_police"], [11, 12, 1])
        self.assertEqual(round_result["count"], 3)
        self.assertTrue(round_result["procedural_complete"])
        self.assertFalse(round_result["complete"])
        self.assertIsNone(round_result["off_police"])
        self.assertEqual(
            [item["strength"] for item in result["evidence"] if item["claim"] == "on_police"],
            ["supporting", "supporting", "supporting"],
        )
        self.assertFalse(any(item["claim"] in {"on_police_roster_complete", "off_police"} for item in result["evidence"]))
        self.assertTrue(all("segment_refs" in item for item in result["evidence"]))

    def test_self_destruct_interrupt_keeps_support_but_withholds_complement(self):
        result = analyze_sheriff_speeches(
            segments(
                "上警玩家请亮红灯",
                "随机点数二由5号玩家开始逆序发言",
                "5号玩家请发言",
                "自曝2号自爆",
                "退水自爆环节",
            )
        )
        round_result = result["rounds"][0]
        self.assertEqual(round_result["on_police"], [5])
        self.assertEqual(round_result["off_police"], None)
        self.assertFalse(round_result["complete"])
        self.assertTrue(any(gap["code"] == "signup_interrupted" for gap in result["gaps"]))
        self.assertFalse(any(item["claim"] == "off_police" for item in result["evidence"]))

    def test_pk_interrupt_blocks_completeness_but_pk_after_closure_is_outside_round(self):
        interrupted = analyze_sheriff_speeches(
            segments(
                "上警玩家请亮红灯",
                "随机点数二由5号玩家开始逆序发言",
                "5号玩家请发言",
                "开始PK发言环节",
                "退水自爆环节",
            )
        )
        self.assertFalse(interrupted["rounds"][0]["complete"])
        self.assertEqual(interrupted["rounds"][0]["on_police"], [5])

        after_close = analyze_sheriff_speeches(
            segments(
                "上警玩家请亮红灯",
                "随机点数二由5号玩家开始逆序发言",
                "5号玩家请发言",
                "警上所有玩家发言结束",
                "开始PK发言环节",
                "4号玩家请发表竞选发言",
            )
        )
        self.assertTrue(after_close["rounds"][0]["procedural_complete"])
        self.assertFalse(after_close["rounds"][0]["complete"])
        self.assertEqual(after_close["rounds"][0]["on_police"], [5])

    def test_regular_day_speeches_and_recap_mentions_do_not_create_signup(self):
        result = analyze_sheriff_speeches(
            segments(
                "随机点数三由1号玩家开始顺序发言",
                "1号玩家请发言",
                "2号玩家请发言",
                "复盘时上警玩家请亮红灯，12号玩家请发言",
            )
        )
        self.assertEqual(result["rounds"], [])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["gaps"][0]["code"], "initial_registration_not_found")

    def test_duplicate_calls_and_timestamp_clip_keep_only_lower_bound(self):
        duplicated = analyze_sheriff_speeches(
            segments(
                "上警玩家请亮红灯",
                "随机点数二由5号玩家开始逆序发言",
                "5号玩家请发言",
                "5号玩家请发表竞选发言",
                "退水自爆环节",
            )
        )
        self.assertFalse(duplicated["rounds"][0]["complete"])
        self.assertEqual(duplicated["rounds"][0]["count"], 1)
        self.assertTrue(any(gap["code"] == "duplicate_speaker_call" for gap in duplicated["gaps"]))

        clipped = segments(
            "上警玩家请亮红灯",
            "随机点数二由5号玩家开始逆序发言",
            "5号玩家请发言",
            "退水自爆环节",
        )
        clipped[-1]["start_ms"] += 60000
        clipped[-1]["end_ms"] += 60000
        clipped_result = analyze_sheriff_speeches(clipped)
        self.assertFalse(clipped_result["rounds"][0]["complete"])
        self.assertTrue(any(gap["code"] == "possible_clip_gap" for gap in clipped_result["gaps"]))

    def test_explicit_exclusion_list_conflicting_with_a_call_blocks_complement(self):
        result = analyze_sheriff_speeches(
            segments(
                "本局游戏除1号2号外其他玩家上警，上警玩家请亮红灯",
                "随机点数一由1号玩家开始顺序发言",
                "1号玩家请发言",
                "警上所有玩家发言结束",
            )
        )
        self.assertFalse(result["rounds"][0]["complete"])
        self.assertEqual(result["rounds"][0]["on_police"], [1])
        self.assertIsNone(result["rounds"][0]["off_police"])
        self.assertTrue(any(gap["code"] == "speaker_number_conflict" for gap in result["gaps"]))

    def test_helper_requires_and_verifies_bound_transcript(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(load_bound_sheriff_speeches({}, root=root))

            transcript_path = root / "selected.json"
            payload = json.dumps({"segments": segments("上警玩家请亮红灯")}, ensure_ascii=False).encode("utf-8")
            transcript_path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            supplemental = {
                "source_binding": {
                    "selected_transcript_path": "selected.json",
                    "selected_transcript_sha256": digest,
                }
            }
            result = load_bound_sheriff_speeches(supplemental, root=root)
            self.assertEqual(result["source_binding"], {"path": "selected.json", "sha256": digest})
            with self.assertRaisesRegex(ValueError, "SHA256 changed"):
                load_bound_sheriff_speeches(
                    {"source_binding": {**supplemental["source_binding"], "selected_transcript_sha256": "0" * 64}},
                    root=root,
                )


def test_existing_judge_registration_skips_loading_and_speech_analysis(tmp_path, monkeypatch):
    import sheriff_speech_evidence as module
    monkeypatch.setattr(module, "analyze_sheriff_speeches", lambda *_: (_ for _ in ()).throw(AssertionError("fallback ran")))
    known = {"registrations": [{"day": 1, "on_police": [1], "off_police": list(range(2, 13))}]}
    # An unreadable transcript is irrelevant once the explicit list is known.
    assert module.load_bound_sheriff_speeches({"source_binding": {}}, root=tmp_path, voting=known) is None


def test_judge_direct_signup_list_skips_speech_fallback(tmp_path, monkeypatch):
    import sheriff_speech_evidence as module
    monkeypatch.setattr(module, "analyze_sheriff_speeches", lambda *_: (_ for _ in ()).throw(AssertionError("fallback ran")))
    payload = json.dumps({"segments": segments("本局游戏除3号玩家外，其他玩家上警", "3号玩家请发言")}, ensure_ascii=False).encode("utf-8")
    (tmp_path / "selected.json").write_bytes(payload)
    binding = {"source_binding": {"selected_transcript_path": "selected.json", "selected_transcript_sha256": hashlib.sha256(payload).hexdigest()}}
    result = module.load_bound_sheriff_speeches(binding, root=tmp_path, voting={"registrations": []})
    assert result["method"] == "judge_signup_list"
    assert result["registration"]["off_police"] == [3]
    assert result["rounds"] == []
    assert result["evidence"][0]["strength"] == "direct"


if __name__ == "__main__":
    unittest.main()

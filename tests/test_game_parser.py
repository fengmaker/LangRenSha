import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from game_parser import parse_transcript


def transcript(rows, duration=100_000, **extra):
    segments = []
    for index, row in enumerate(rows):
        start, end, text, speaker = row
        segments.append(
            {
                "id": f"s{index}",
                "start_ms": start,
                "end_ms": end,
                "text": text,
                "speaker": speaker,
            }
        )
    return {
        "source": "synthetic-test",
        "status": "machine_generated_unverified",
        "audio_duration_ms": duration,
        "segments": segments,
        **extra,
    }


class GameParserTests(unittest.TestCase):
    def test_judge_continuation_is_not_assigned_to_the_named_player(self):
        data = transcript([(0, 300, "请三号玩家发言", "judge"),
                           (400, 600, "发言限时两分钟", "judge"),
                           (700, 900, "我先说一下", "player_cluster")])
        result = parse_transcript(data)
        self.assertIsNone(result["segments"][1]["player_number"])
        self.assertEqual(result["segments"][1]["status"], "unknown")
        self.assertEqual(result["segments"][2]["player_number"], 3)

    def test_explicit_self_explosion_night_does_not_become_pending_players_speech(self):
        data = transcript([(0, 300, "六号玩家请发言，", "judge"),
                           (400, 800, "二号玩家选择自爆天黑请闭眼。", "judge"),
                           (900, 1500, "现在继续流程", "judge")])
        result = parse_transcript(data)
        self.assertEqual(result["segments"][1]["stage"], "night")
        self.assertTrue(all(s["player_number"] is None for s in result["segments"]))

    def test_ordinal_game_end_prevents_recap_day_cue_reopening_play(self):
        data = transcript([(0, 300, "第三局游戏结束了。", "host"),
                           (400, 800, "第二天白天", "host")])
        result = parse_transcript(data)
        self.assertEqual([s["stage"] for s in result["segments"]], ["ended", "ended"])
        self.assertTrue(all(s["player_number"] is None for s in result["segments"]))

    def test_short_explicit_player_commands_support_chinese_and_arabic_numbers(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 500, "天亮了", "chunk_0001:speaker_0"),
                    (600, 900, "请十二号玩家发言", "chunk_0001:speaker_0"),
                    (1000, 1500, "我先说一下", "chunk_0001:speaker_3"),
                    (1600, 1900, "3号玩家请发言。", "chunk_0001:speaker_0"),
                    (2000, 2400, "我觉得先看票型", "chunk_0001:speaker_2"),
                ]
            )
        )
        prompts = [s for s in result["segments"] if s["speech_type"] == "judge_instruction_candidate"]
        speeches = [s for s in result["segments"] if s["speech_type"] == "player_speech_candidate"]
        self.assertEqual([p["evidence"][0]["target_player_number"] for p in prompts], [12, 3])
        self.assertEqual([s["player_number"] for s in speeches], [12, 3])
        self.assertEqual(speeches[0]["stage"], "daytime")
        self.assertFalse(result["verified"])
        self.assertFalse(result["judge_speaker_verified"])

    def test_player_command_variants_allow_optional_player_word_and_leading_politeness(self):
        cases = [
            ("请三号发言", 3, "speak"),
            ("有请十二号玩家发言", 12, "speak"),
            ("7号玩家开始发言", 7, "speak"),
            ("请4号玩家发表遗言", 4, "last_words"),
        ]
        for text, expected_number, expected_kind in cases:
            with self.subTest(text=text):
                result = parse_transcript(transcript([(0, 300, text, "judge_cluster")]))
                command = result["segments"][0]
                event = next(e for e in command["evidence"] if e["kind"] == "player_instruction_match")
                self.assertEqual(event["target_player_number"], expected_number)
                self.assertEqual(event["instruction_kind"], expected_kind)

    def test_multiple_short_commands_in_one_asr_segment_keep_clause_evidence(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 500, "天亮了，请3号发言。", "chunk_1:speaker_0"),
                    (600, 900, "我说两句", "chunk_1:speaker_3"),
                    (1000, 1400, "3号玩家发言结束，请4号玩家发言", "chunk_1:speaker_0"),
                    (1500, 1900, "我先过一下", "chunk_1:speaker_4"),
                ]
            )
        )
        composites = [s for s in result["segments"] if s["speech_type"] == "compound_instruction_candidate"]
        self.assertEqual(len(composites), 2)
        first_events = composites[0]["evidence"][:-1]
        self.assertEqual([e["kind"] for e in first_events], ["stage_cue_match", "player_instruction_match"])
        self.assertEqual(first_events[1]["matched_text"], "请3号发言")
        second_events = composites[1]["evidence"][:-1]
        self.assertEqual([e["kind"] for e in second_events], ["player_turn_end_match", "player_instruction_match"])
        self.assertEqual(second_events[0]["target_player_number"], 3)
        self.assertEqual(second_events[1]["target_player_number"], 4)
        speeches = [s for s in result["segments"] if s["speech_type"] == "player_speech_candidate"]
        self.assertEqual([s["player_number"] for s in speeches], [3, 4])
        self.assertEqual(speeches[0]["player_speaker_candidate"], "chunk_1:speaker_3")

    def test_partial_commands_inside_analysis_do_not_trigger_compound_matching(self):
        result = parse_transcript(
            transcript(
                [(0, 700, "我觉得天亮了，请3号玩家发言，是因为昨天他的票型不对", "speaker_2")]
            )
        )
        candidate = result["segments"][0]
        self.assertEqual(candidate["speech_type"], "unassigned_speech")
        self.assertEqual(candidate["status"], "unknown")
        self.assertIsNone(candidate["player_number"])

    def test_quotes_and_long_analysis_that_mentions_cues_do_not_switch_state(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 1000, "我昨天天黑请闭眼以后就听到有人说请3号玩家发言", "chunk_1:speaker_2"),
                    (1100, 1600, "“请三号玩家发言”", "chunk_1:speaker_2"),
                    (1700, 2100, "我觉得应该先投票再讨论", "chunk_1:speaker_2"),
                ]
            )
        )
        self.assertEqual(len(result["segments"]), 1)
        candidate = result["segments"][0]
        self.assertIsNone(candidate["player_number"])
        self.assertEqual(candidate["status"], "unknown")
        self.assertEqual(candidate["source_segment_ids"], ["s0", "s1", "s2"])

    def test_speaker_cluster_ids_never_become_seat_numbers_and_mismatch_is_evidence(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 300, "请7号玩家发言", "chunk_0001:speaker_0"),
                    (400, 800, "我听一下前置位", "chunk_0001:speaker_7"),
                    (900, 1200, "我补充一句", "chunk_0002:speaker_7"),
                ]
            )
        )
        speech = [s for s in result["segments"] if s["speech_type"] == "player_speech_candidate"]
        self.assertEqual(speech[0]["player_number"], 7)
        self.assertEqual(speech[0]["speaker_cluster_id"], "chunk_0001:speaker_7")
        self.assertIn("instruction_speaker_cluster_differs", speech[0]["review_reasons"])
        self.assertEqual(speech[0]["evidence"][0]["speaker_cluster_relation"], "different")
        self.assertEqual(speech[1]["player_number"], 7)
        self.assertEqual(speech[1]["speaker_cluster_id"], "chunk_0002:speaker_7")
        self.assertEqual(speech[1]["evidence"][0]["speaker_cluster_relation"], "unknown_chunk_boundary")
        self.assertEqual(speech[1]["review_reasons"].count("speaker_chunk_boundary"), 1)

        unprompted = parse_transcript(
            transcript([(0, 200, "没有点名", "speaker_4")])
        )["segments"][0]
        self.assertIsNone(unprompted["player_number"])

    def test_same_chunk_speaker_change_blocks_seat_attribution_until_next_prompt(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 250, "请5号发言", "chunk_1:speaker_0"),
                    (300, 550, "我开始说", "chunk_1:speaker_5"),
                    (600, 850, "我补充一下", "chunk_1:speaker_8"),
                    (900, 1100, "再补一句", "chunk_1:speaker_5"),
                    (1200, 1450, "请6号发言", "chunk_1:speaker_0"),
                    (1500, 1750, "我继续", "chunk_1:speaker_8"),
                ]
            )
        )
        speech = [s for s in result["segments"] if s["speech_type"] == "player_speech_candidate"]
        self.assertEqual(speech[0]["player_number"], 5)
        self.assertEqual(speech[0]["player_speaker_candidate"], "chunk_1:speaker_5")
        blocked = [s for s in result["segments"] if "speaker_changed_without_instruction" in s["review_reasons"]]
        self.assertEqual(len(blocked), 2)
        self.assertTrue(all(s["player_number"] is None and s["status"] == "unknown" for s in blocked))
        self.assertEqual(speech[-1]["player_number"], 6)

    def test_explicit_game_end_clears_last_player_before_award_or_recap(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 300, "请二号玩家发言", "judge"),
                    (400, 800, "我过了", "player_cluster"),
                    (900, 1200, "本局游戏结束，谢谢大家", "judge"),
                    (1300, 1800, "现在开始颁奖", "host"),
                ]
            )
        )
        ending = next(s for s in result["segments"] if s["stage"] == "ended")
        post_game = next(s for s in result["segments"] if s["text"] == "现在开始颁奖")
        self.assertIsNone(ending["player_number"])
        self.assertEqual(ending["speech_type"], "game_end_candidate")
        self.assertIsNone(post_game["player_number"])
        self.assertEqual(post_game["status"], "unknown")
        self.assertIn("post_game_content_unassigned", post_game["review_reasons"])

    def test_post_game_player_instruction_cannot_restart_assignment_without_game_start(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 200, "请2号发言", "judge"),
                    (250, 500, "我说完了", "player"),
                    (600, 800, "本局游戏结束", "judge"),
                    (900, 1100, "请3号玩家发言", "host"),
                    (1200, 1500, "现在请大家领奖", "host"),
                    (1600, 1800, "游戏开始", "judge"),
                    (1900, 2100, "请4号发言", "judge"),
                    (2200, 2500, "我先发言", "player_4"),
                ]
            )
        )
        postgame_prompt = next(
            s for s in result["segments"] if s["text"] == "请3号玩家发言"
        )
        postgame_speech = next(s for s in result["segments"] if s["text"] == "现在请大家领奖")
        resumed_speech = next(s for s in result["segments"] if s["text"] == "我先发言")
        ignored = next(e for e in postgame_prompt["evidence"] if e["kind"] == "post_game_player_instruction_ignored")
        self.assertFalse(ignored["applied"])
        self.assertEqual(postgame_prompt["stage"], "ended")
        self.assertIsNone(postgame_speech["player_number"])
        self.assertEqual(resumed_speech["stage"], "opening")
        self.assertEqual(resumed_speech["player_number"], 4)

    def test_adjacent_instructions_remain_separate_and_judge_labels_do_not_verify(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 200, "请1号玩家发言", "chunk_1:speaker_0"),
                    (250, 450, "请2号玩家发言", "chunk_1:speaker_0"),
                    (500, 900, "我开始了", "chunk_1:speaker_2"),
                ],
                judge_speakers=["chunk_1:speaker_0"],
            )
        )
        commands = [s for s in result["segments"] if s["speech_type"] == "judge_instruction_candidate"]
        self.assertEqual([s["text"] for s in commands], ["请1号玩家发言", "请2号玩家发言"])
        speech = next(s for s in result["segments"] if s["speech_type"] == "player_speech_candidate")
        self.assertEqual(speech["player_number"], 2)
        self.assertEqual(result["judge_speakers_candidate"], ["chunk_1:speaker_0"])
        self.assertFalse(result["judge_speaker_verified"])
        self.assertFalse(result["verified"])

    def test_day_number_is_only_set_by_an_explicit_day_cue(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 250, "天亮了", None),
                    (300, 600, "进入投票环节", None),
                    (700, 900, "第十二天白天", None),
                ]
            )
        )
        self.assertIsNone(result["segments"][0]["day_number"])
        self.assertIsNone(result["segments"][1]["day_number"])
        self.assertEqual(result["segments"][2]["day_number"], 12)

    def test_explicit_day_number_survives_voting_and_last_words_then_night_clears_it(self):
        result = parse_transcript(
            transcript(
                [
                    (0, 250, "第3天白天", None),
                    (300, 550, "进入投票环节", None),
                    (600, 850, "发表遗言", None),
                    (900, 1150, "天黑请闭眼", None),
                ]
            )
        )
        self.assertEqual([s["day_number"] for s in result["segments"]], [3, 3, 3, None])

    def test_merged_source_ids_cover_every_input_and_times_stay_legal(self):
        data = transcript(
            [
                (0, 250, "请5号玩家发言", None),
                (300, 500, "我认为", "chunk_1:speaker_5"),
                (500, 750, "应该再听一下", "chunk_1:speaker_5"),
                (800, 1000, "开始投票", None),
            ],
            duration=1000,
        )
        result = parse_transcript(data)
        seen = [segment_id for item in result["segments"] for segment_id in item["source_segment_ids"]]
        self.assertCountEqual(seen, [segment["id"] for segment in data["segments"]])
        merged_speech = next(s for s in result["segments"] if s["speech_type"] == "player_speech_candidate")
        self.assertEqual(merged_speech["source_segment_ids"], ["s1", "s2"])
        self.assertEqual((merged_speech["start_ms"], merged_speech["end_ms"]), (300, 750))
        self.assertTrue(all(0 <= s["start_ms"] <= s["end_ms"] <= 1000 for s in result["segments"]))
        self.assertEqual(merged_speech["text"], "我认为应该再听一下")
        self.assertTrue(all(item["evidence"] for item in result["segments"]))

    def test_invalid_timestamps_and_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "timestamps"):
            parse_transcript(
                {"audio_duration_ms": 100, "segments": [{"id": 1, "start_ms": 10, "end_ms": 101, "text": "x"}]}
            )
        duplicate = transcript([(0, 10, "a", None), (10, 20, "b", None)])
        duplicate["segments"][1]["id"] = duplicate["segments"][0]["id"]
        with self.assertRaisesRegex(ValueError, "duplicate segment"):
            parse_transcript(duplicate)


if __name__ == "__main__":
    unittest.main()

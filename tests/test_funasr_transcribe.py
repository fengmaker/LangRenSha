import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from transcribe_funasr import chunk_plan, normalize, validate_plan


class FunASRExportTests(unittest.TestCase):
    def test_chunks_cover_full_recording_without_cutting_vad_speech(self):
        vad = [[100, 590_000], [590_500, 610_000], [611_000, 1_250_000]]
        chunks = chunk_plan(vad, 1_260_000, 600_000)
        self.assertEqual(chunks, [[0, 610_500], [610_500, 1_260_000]])
        self.assertTrue(all(not a < chunks[0][1] < b for a, b in vad))

    def test_continuous_voice_does_not_get_cut_at_arbitrary_time(self):
        self.assertEqual(chunk_plan([[0, 1_000_000]], 1_000_000, 600_000), [[0, 1_000_000]])

    def test_resume_plan_rejects_wrong_audio_missing_tail_gaps_and_overlaps(self):
        plan = {"audio_sha256": "same", "audio_duration_ms": 1000, "chunks": [[0, 500], [500, 1000]]}
        validate_plan(plan, "same", 1000)
        with self.assertRaisesRegex(ValueError, "different audio"):
            validate_plan(plan, "changed", 1000)
        for chunks in ([[0, 500]], [[0, 500], [501, 1000]], [[0, 500], [499, 1000]], []):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                validate_plan({**plan, "chunks": chunks}, "same", 1000)

    def test_offsets_and_speaker_namespaces_are_preserved(self):
        raw = [{"text": "三号玩家发言。", "sentence_info": [
            {"start": 200, "end": 1200, "sentence": "三号玩家发言。", "spk": 3}]}]
        sentence = normalize(raw, 2, 600_000, 700_000)[0]
        self.assertEqual((sentence["start_ms"], sentence["end_ms"]), (600_200, 601_200))
        self.assertEqual(sentence["speaker"], "chunk_0002:speaker_3")
        self.assertNotIn("player_number", sentence)

    def test_missing_or_invalid_alignment_is_not_silently_exported(self):
        with self.assertRaises(RuntimeError):
            normalize([{"text": "存在文字但无时间"}], 1, 0, 1000)
        with self.assertRaises(ValueError):
            normalize([{"sentence_info": [{"text": "x", "start": -10, "end": 100}]}], 1, 0, 1000)

    def test_model_vad_join_does_not_fragment_cue_or_shift_word_timeline(self):
        # Real FunASR failure pattern: Chinese VAD joins compact adjacent words,
        # but raw_text retains the original one-token/one-timestamp alignment.
        raw = [{"text": "天亮了。十号玩家请发言。", "raw_text": "天 亮 了 十 号 玩 家 请 发 言",
                "timestamp": [[1000 + i * 100, 1100 + i * 100] for i in range(10)],
                "sentence_info": [
                    {"text": "天亮了十号玩，", "start": 1000, "end": 1300, "spk": 0},
                    {"text": "家请发言。", "start": 1300, "end": 1700, "spk": 0}]}]
        sentences = normalize(raw, 2, 600_000, 603_000)
        self.assertEqual([s["text"] for s in sentences], ["天亮了。", "十号玩家请发言。"])
        self.assertEqual((sentences[1]["start_ms"], sentences[1]["end_ms"]), (601_300, 602_000))

    def test_surface_alignment_keeps_english_and_refuses_semantic_edits(self):
        raw = [{"text": "DGY是好人。", "raw_text": "dgy 是 好 人",
                "timestamp": [[0, 100], [100, 200], [200, 300], [300, 400]], "sentence_info": []}]
        self.assertEqual(normalize(raw, 1, 0, 1000)[0]["text"], "DGY是好人。")
        raw[0]["text"] = "DGY不是好人。"
        with self.assertRaisesRegex(ValueError, "changed ASR text"):
            normalize(raw, 1, 0, 1000)


if __name__ == "__main__":
    unittest.main()

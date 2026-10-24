import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_transcript_review import build_review_html


class TranscriptReviewTests(unittest.TestCase):
    def test_recap_clip_keeps_original_clock_but_seeks_inside_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            clip = base / "recap.wav"
            clip.write_bytes(b"fixture")
            segment = {"id": "r1", "start_ms": 2_037_480, "end_ms": 2_039_240,
                       "text": "先做本局复盘", "speaker": None}
            transcript = {"source": {"audio_file": "original.m4a"}, "audio_duration_ms": 2_228_416,
                          "playback_audio": {"file": str(clip), "origin_ms": 2_034_000,
                                             "duration_ms": 52_000}, "segments": [segment]}
            structure = {"segments": [{**segment, "source_segment_ids": ["r1"], "stage": "ended",
                                       "speech_type": "referee_recap_candidate", "status": "needs_review"}]}
            page = build_review_html(transcript, structure, base / "transcript.json", base / "review.html")
            self.assertIn('src="recap.wav"', page)
            self.assertIn('data-time="3.480"', page)
            self.assertIn("00:33:57.480", page)
            self.assertIn("法官（复盘语境候选）", page)
            self.assertIn("列表显示原音频时间", page)

    def test_transcript_and_candidate_text_are_html_escaped(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            audio = base / "audio.m4a"
            audio.write_bytes(b"fixture")
            transcript_path = base / "transcript.json"
            output_path = base / "review.html"
            transcript = {
                "source": {"audio_file": str(audio), "title": '</title><script>alert("title")</script>'},
                "audio_duration_ms": 2500,
                "engine": "FunASR",
                "status": "machine_generated_unverified",
                "segments": [
                    {"id": "x", "start_ms": 0, "end_ms": 1000, "text": '</script><script>alert("raw")</script>', "speaker": None}
                ],
            }
            structure = {
                "status": "needs_review",
                "segments": [
                    {
                        "source_segment_ids": ["x"],
                        "start_ms": 0,
                        "end_ms": 1000,
                        "text": '<img src=x onerror="alert(1)">',
                        "player_number": None,
                        "stage": "daytime",
                        "speech_type": "unassigned_speech",
                        "status": "unknown",
                        "review_reasons": ["</script>", "<b>unsafe</b>"],
                        "evidence": [{"value": "</script><script>alert('evidence')</script>"}],
                    }
                ],
            }
            page = build_review_html(transcript, structure, transcript_path, output_path)

        self.assertIn("&lt;/script&gt;&lt;script&gt;alert(&quot;raw&quot;)&lt;/script&gt;", page)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", page)
        self.assertIn("&lt;/script&gt;&lt;script&gt;alert(&#x27;evidence&#x27;)&lt;/script&gt;", page)
        self.assertNotIn('</script><script>alert("raw")</script>', page)
        self.assertNotIn('</title><script>alert("title")</script>', page)
        self.assertIn("未归属", page)
        self.assertIn("白天候选", page)
        self.assertIn("候选 · 未人工校对", page)

    def test_audio_link_is_relative_url_encoded_and_audio_is_not_copied(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            transcript_dir = base / "inputs"
            report_dir = base / "reports"
            audio_dir = base / "audio files"
            transcript_dir.mkdir()
            report_dir.mkdir()
            audio_dir.mkdir()
            audio = audio_dir / "原声 clip.m4a"
            audio.write_bytes(b"original audio")
            transcript_path = transcript_dir / "transcript.json"
            output_path = report_dir / "review.html"
            transcript = {
                "source": {"audio_file": "../audio files/原声 clip.m4a"},
                "audio_duration_ms": 10_000,
                "segments": [{"id": 1, "start_ms": 0, "end_ms": 500, "text": "测试", "speaker": None}],
            }
            structure = {
                "segments": [
                    {
                        "source_segment_ids": [1],
                        "start_ms": 0,
                        "end_ms": 500,
                        "text": "测试",
                        "player_number": 4,
                        "stage": "daytime",
                        "speech_type": "player_speech_candidate",
                        "status": "needs_review",
                        "review_reasons": [],
                        "evidence": [],
                    }
                ]
            }
            page = build_review_html(transcript, structure, transcript_path, output_path)

            self.assertIn('src="../audio%20files/%E5%8E%9F%E5%A3%B0%20clip.m4a"', page)
            self.assertIn("4号（候选）", page)
            self.assertIn('data-time="0.000"', page)
            self.assertIn("句级原始转写", page)
            self.assertIn("合并发言候选", page)
            self.assertTrue(audio.exists())
            self.assertFalse((report_dir / audio.name).exists())


if __name__ == "__main__":
    unittest.main()

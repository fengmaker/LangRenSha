import csv
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import transcribe_review_queue as queue


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bvid = "BVTEST123456"
        self.cid = "123456789"
        self.audio = self.root / "data/seasons/S22/sample.音频.m4a"
        self.audio.parent.mkdir(parents=True)
        self.audio.write_bytes(b"a small deterministic audio fixture")
        self.digest = hashlib.sha256(self.audio.read_bytes()).hexdigest()
        self.manifest = self.root / f"data/raw/bilibili/{self.bvid}/p01/manifest.json"
        write_json(self.manifest, {
            "bvid": self.bvid, "cid": int(self.cid), "page": 1,
            "duration_seconds": 1,
            "audio": {"file": "audio.m4a", "sha256": self.digest},
        })
        self.entry = {
            "row_number": 15, "bvid": self.bvid, "cid": self.cid,
            "quality": "no_zh_subtitle", "reason": "没有可用的中文字幕轨道",
            "audio_file": queue.relative(self.audio, self.root),
            "manifest_file": queue.relative(self.manifest, self.root),
            "manifest_audio_sha256": self.digest,
            "output_dir": f"data/transcripts/S22/{self.bvid}_p01_funasr_full",
            "exports": {
                "json": "data/seasons/S22/sample.本地全文转写_funasr.json",
                "srt": "data/seasons/S22/sample.本地全文转写_funasr.srt",
                "reading": "data/seasons/S22/sample.本地全文转写_funasr.阅读.txt",
            },
        }

    def write_valid_output(self, *, duration=1000, range_end=1000, full=True):
        output = self.root / self.entry["output_dir"]
        output.mkdir(parents=True, exist_ok=True)
        (output / "raw").mkdir(exist_ok=True)
        source = {"audio_file": str(self.audio), "audio_sha256": self.digest,
                  "bvid": self.bvid, "cid": int(self.cid), "page": 1,
                  "manifest": str(self.manifest)}
        transcript = {
            "full_audio_processed": full,
            "audio_duration_ms": duration,
            "source": source,
            "chunks": [{"index": 1, "start_ms": 0, "end_ms": range_end}],
            "segments": [{"id": "c0001_s0001", "text": "测试完整转写。",
                          "start_ms": 100, "end_ms": min(900, range_end), "chunk_index": 1}],
        }
        write_json(output / "transcript.json", transcript)
        write_json(output / "vad_plan.json", {
            "audio_sha256": self.digest, "audio_duration_ms": duration,
            "chunks": [[0, range_end]],
        })
        write_json(output / "raw/chunk_0001.json", {
            "index": 1, "start_ms": 0, "end_ms": range_end, "result": []
        })
        (output / "transcript.srt").write_text(
            "1\n00:00:00,100 --> 00:00:00,900\n测试完整转写。\n", encoding="utf-8")
        (output / "transcript.阅读.txt").write_text("测试完整转写。\n", encoding="utf-8")
        return output

    def test_selection_uses_quality_field_even_after_new_local_columns_exist(self):
        qualities = ["needs_review", "no_short_caption_signal", "no_zh_subtitle",
                     "needs_review", "accepted", "no_zh_subtitle", "no_short_caption_signal"]
        rows = [{"BVID": f"BV{index}", "质量筛查": quality,
                 "本地转写状态": "complete" if index == 2 else "pending"}
                for index, quality in enumerate(qualities)]
        chosen = queue.selected_rows(rows)
        self.assertEqual([row["BVID"] for row in chosen], ["BV0", "BV2", "BV3", "BV5"])

    def test_full_transcript_and_checkpoint_ranges_validate(self):
        self.write_valid_output()
        details = queue.validate_output(self.entry, self.root)
        self.assertEqual(details["duration_ms"], 1000)
        self.assertEqual(details["sentence_count"], 1)

    def test_truncated_result_is_rejected_even_if_it_claims_full_audio(self):
        self.write_valid_output(duration=1000, range_end=900)
        with self.assertRaisesRegex(queue.QueueError, "end at audio duration"):
            queue.validate_output(self.entry, self.root)

    def test_checkpoint_range_mismatch_is_rejected(self):
        output = self.write_valid_output()
        checkpoint_path = output / "raw/chunk_0001.json"
        checkpoint = queue.load_json(checkpoint_path)
        checkpoint["end_ms"] = 999
        write_json(checkpoint_path, checkpoint)
        with self.assertRaisesRegex(queue.QueueError, "raw checkpoint range differs"):
            queue.validate_output(self.entry, self.root)

    def test_audio_hash_mismatch_against_manifest_is_rejected(self):
        self.write_valid_output()
        self.audio.write_bytes(b"changed source audio")
        with self.assertRaisesRegex(queue.QueueError, "SHA-256 mismatch against manifest"):
            queue.validate_output(self.entry, self.root)

    def test_invalid_segment_timestamps_are_rejected(self):
        output = self.write_valid_output()
        transcript_path = output / "transcript.json"
        transcript = queue.load_json(transcript_path)
        transcript["segments"][0]["end_ms"] = 1001
        write_json(transcript_path, transcript)
        with self.assertRaisesRegex(queue.QueueError, "invalid time range"):
            queue.validate_output(self.entry, self.root)

    def test_run_resumes_existing_checkpoint_and_copies_verified_exports(self):
        output = self.root / self.entry["output_dir"]
        (output / "raw").mkdir(parents=True)
        write_json(output / "raw/chunk_0001.json", {
            "index": 1, "start_ms": 0, "end_ms": 1000, "result": []
        })
        write_json(output / "transcript.json", {"full_audio_processed": False})
        state = {"items": {self.bvid: {"status": "pending"}}}
        calls = []

        def mocked_asr(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[0], sys.executable)
            self.assertIn("--no-speakers", command)
            self.assertIn("--manifest", command)
            self.assertTrue((output / "raw/chunk_0001.json").is_file())
            self.write_valid_output()
            return SimpleNamespace(returncode=0)

        ok, details = queue.run_one(self.entry, self.root, state, runner=mocked_asr)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(state["items"][self.bvid]["status"], "complete")
        self.assertEqual(details["duration_ms"], 1000)
        for relative_path in self.entry["exports"].values():
            self.assertTrue((self.root / relative_path).is_file())

    def test_verified_existing_output_is_reused_without_starting_asr(self):
        self.write_valid_output()
        state = {"items": {self.bvid: {"status": "pending"}}}

        def forbidden_runner(*args, **kwargs):
            self.fail("verified full output should be reused")

        ok, details = queue.run_one(self.entry, self.root, state, runner=forbidden_runner)
        self.assertTrue(ok)
        self.assertEqual(details["sentence_count"], 1)
        self.assertEqual(state["items"][self.bvid]["status"], "complete")

    def test_failed_entry_is_recorded_and_run_one_does_not_mark_it_complete(self):
        state = {"items": {self.bvid: {"status": "pending"}}}

        def failed_runner(command, **kwargs):
            self.write_valid_output(full=False)
            return SimpleNamespace(returncode=1)

        ok, details = queue.run_one(self.entry, self.root, state, runner=failed_runner)
        self.assertFalse(ok)
        self.assertIsNone(details)
        self.assertEqual(state["items"][self.bvid]["status"], "failed")
        self.assertIn("full_audio_processed", state["items"][self.bvid]["error"])

    def test_plan_is_offline_and_writes_only_plan_and_summary(self):
        rows = []
        qualities = ["no_zh_subtitle", "needs_review", "no_short_caption_signal",
                     "needs_review", "no_zh_subtitle", "accepted", "no_short_caption_signal"]
        for index, quality in enumerate(qualities):
            bvid = f"BV{index:010d}"
            audio = self.root / f"data/seasons/S22/{bvid}.m4a"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(b"a")
            digest = hashlib.sha256(b"a").hexdigest()
            manifest = self.root / f"data/raw/bilibili/{bvid}/p01/manifest.json"
            write_json(manifest, {"bvid": bvid, "cid": index + 1, "page": 1,
                                  "duration_seconds": 1,
                                  "audio": {"sha256": digest}})
            rows.append({"目录序号": str(index + 1), "BVID": bvid, "CID": str(index + 1),
                         "质量筛查": quality,
                         "音频文件": queue.relative(audio, self.root), "字幕待核事项": ""})
        csv_path = self.root / "data/seasons/S22/S22_中文优先复核目录.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result = queue.do_plan(csv_path, self.root)
        self.assertEqual(result["entry_count"], 4)
        self.assertEqual(result["counts"], {"no_zh_subtitle": 2, "needs_review": 2})
        plan = queue.load_json(self.root / "data/reports/S22_全文补转写计划.json")
        self.assertEqual([entry["bvid"] for entry in plan["entries"]],
                         [row["BVID"] for row in rows if row["质量筛查"] in queue.SELECTED_QUALITIES])
        summary = self.root / "data/seasons/S22/S22_全文补转写目录.csv"
        with summary.open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 4)


if __name__ == "__main__":
    unittest.main()

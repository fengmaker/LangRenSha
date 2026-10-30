"""Incremental text routing, provenance checks and read-only AI execution."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_incremental as analysis
import game_records
import incremental_ai


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "config", self.root / "config")
        self.entry = {"bvid": "BV17QJh6qEur", "cid": 123456, "page": 1,
                      "duration_seconds": 20, "title": "测试正赛", "labels": {
                          "season": "S23", "phase_candidate": "regular",
                          "event_date_candidate": "2026-10-27", "game_number_candidate": 1,
                          "board_candidate": "预女猎白混", "issue_candidate": 7}}
        self.source = self.root / "data/raw/bilibili/BV17QJh6qEur/p01/subtitle.01.raw.json"
        self.source.parent.mkdir(parents=True)
        self.source.write_text(json.dumps({"body": [{"from": 1, "to": 3, "content": "本局身份开始复盘"}]}), encoding="utf-8")
        self.patcher = patch.object(game_records, "ROOT", self.root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def candidate(self):
        value = analysis.skeleton(self.entry, self.source, root=self.root)
        value["evidence"] = [{"field": "dossier.rounds", "kind": "text",
                              "source_path": self.source.relative_to(self.root).as_posix(),
                              "start_ms": 1000, "end_ms": 3000, "quote": "本局身份开始复盘"}]
        return value

    def test_platform_chinese_never_starts_asr(self):
        checked = {"manifest": {"cid": self.entry["cid"]}, "subtitles": [(self.source, {"language": "ai-zh"})],
                   "audio_path": None}
        with patch.object(analysis, "validate_media", return_value=checked), patch.object(analysis.subprocess, "run") as run:
            self.assertEqual(analysis.prepare_text(self.entry, "S23", root=self.root), self.source)
            run.assert_not_called()

    def test_weibo_context_includes_local_roster_images_only_in_target_window(self):
        folder = self.root / "data/raw/weibo/2026-10-21_2026-10-29_test"
        folder.mkdir(parents=True)
        (folder / "post.json").write_text("{}")
        (folder / "roster.png").write_bytes(b"fixture")
        (folder / "manifest.json").write_text(json.dumps({"request": {"uid": "7525583841"},
            "posts": [{"post_id": "123", "published_date": "2026-10-26", "raw_file": "post.json",
                       "images": [{"status": "downloaded", "file": "roster.png"}]},
                      {"post_id": "old", "published_date": "2026-09-01", "raw_file": "post.json"}]}))
        context = analysis.weibo_sources(self.root, "2026-10-27")
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0]["post_id"], "123")
        self.assertTrue(context[0]["images"][0].endswith("roster.png"))

    def test_matching_completed_asr_is_reused(self):
        out = self.root / "data/transcripts/S23/BV17QJh6qEur_p01_funasr/transcript.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({"full_audio_processed": True, "source": {
            "bvid": self.entry["bvid"], "cid": self.entry["cid"], "page": 1, "audio_sha256": "abc"}}))
        checked = {"manifest": {"cid": self.entry["cid"], "audio": {"sha256": "abc"}},
                   "subtitles": [], "audio_path": self.source.parent / "audio.m4a"}
        with patch.object(analysis, "validate_media", return_value=checked), patch.object(analysis.subprocess, "run") as run:
            self.assertEqual(analysis.prepare_text(self.entry, "S23", root=self.root), out)
            run.assert_not_called()

    def test_partial_asr_requires_completion(self):
        out = self.root / "data/transcripts/S23/BV17QJh6qEur_p01_cid123456_funasr/transcript.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({"full_audio_processed": False, "source": {"audio_sha256": "abc"}}))
        checked = {"manifest": {"cid": self.entry["cid"], "audio": {"sha256": "abc"}},
                   "subtitles": [], "audio_path": self.source.parent / "audio.m4a"}
        with patch.object(analysis, "validate_media", return_value=checked), patch.object(analysis.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "尚未完整"):
                analysis.prepare_text(self.entry, "S23", root=self.root)
            run.assert_called_once()
            self.assertIn("--no-speakers", run.call_args.args[0])

    def test_valid_candidate_has_evidence_hash_and_no_formal_write(self):
        value = analysis.validate_candidate(self.candidate(), self.entry, self.source, root=self.root)
        self.assertEqual(value["evidence"][0]["sha256"], analysis.sha256(self.source))
        self.assertFalse((self.root / "data/games").exists())

    def test_wrong_source_and_fabricated_quote_rejected(self):
        value = self.candidate()
        value["dossier"]["files"][0]["external_key"] = "another:999"
        with self.assertRaisesRegex(ValueError, "来源"):
            analysis.validate_candidate(value, self.entry, self.source, root=self.root)
        value = self.candidate()
        value["evidence"][0]["quote"] = "根本不存在的原话"
        with self.assertRaisesRegex(ValueError, "原话"):
            analysis.validate_candidate(value, self.entry, self.source, root=self.root)

    def test_invalid_votes_not_hidden_as_abstention(self):
        value = self.candidate()
        value["voting"]["ballots"] = [{"id": "one", "day": 1, "kind": "exile", "number": 1,
              "stage": "initial", "status": "complete", "candidates": None,
              "eligible_voters": [1], "votes": [{"voter": 1, "target": None, "state": "cast"}],
              "tied_candidates": [], "winner": None, "unrecorded_voters": []}]
        with self.assertRaisesRegex(ValueError, "弃票"):
            analysis.validate_candidate(value, self.entry, self.source, root=self.root)

    def test_changed_candidate_is_not_overwritten_on_repeated_runs(self):
        folder = analysis.work_dir(self.root, "S23", self.entry)
        folder.mkdir(parents=True)
        candidate_path = folder / "candidate.json"
        candidate_path.write_text("{}")
        item = {"entry": self.entry, "analysis": "failed", "source_sha256": analysis.sha256(self.source),
                "candidate_sha256": "old"}
        with patch.object(analysis, "prepare_text", return_value=self.source), patch.object(analysis, "run_json") as ai:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "版本已变化"):
                    analysis.analyze_one(item, "S23", root=self.root)
            self.assertEqual(candidate_path.read_text(), "{}")
            ai.assert_not_called()

    def test_runner_uses_read_only_luna_and_rejects_failed_stale_output(self):
        target = self.root / "data/test/result.json"

        def invoke(command, **kwargs):
            response = Path(command[command.index("--output-last-message") + 1])
            response.write_text(json.dumps({"result_json": json.dumps({"ok": True})}))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(incremental_ai.shutil, "which", return_value="codex.exe"), \
                patch.object(incremental_ai.subprocess, "run", side_effect=invoke) as runner:
            self.assertEqual(incremental_ai.run_json("限定任务", target, root=self.root), {"ok": True})
            command = runner.call_args.args[0]
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertEqual(command[command.index("--model") + 1], "gpt-6-luna")
            self.assertNotIn("--worktree", command)
        with patch.object(incremental_ai.shutil, "which", return_value="codex.exe"), \
                patch.object(incremental_ai.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, "调用失败"):
                incremental_ai.run_json("限定任务", target, root=self.root)
        self.assertEqual(json.loads(target.read_text()), {"ok": True})


if __name__ == "__main__":
    unittest.main()

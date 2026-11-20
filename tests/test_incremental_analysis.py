"""Incremental text routing and candidate provenance checks."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_incremental as analysis
import game_records
from raw_media_fixture import make_subtitle_media


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

    def test_alternate_subtitle_keeps_official_game_and_uses_its_own_media_time(self):
        bvid, cid, page = "BV1tj8p6REqy", 321, 2
        folder = self.root / f"data/raw/bilibili/{bvid}/p{page:02d}"
        manifest_path = make_subtitle_media(folder)
        manifest = analysis.read_json(manifest_path)
        manifest.update(cid=cid, page=page, owner={"mid": 999}, duration_seconds=3)
        analysis.write_json(manifest_path, manifest)
        analysis.write_json(folder / "metadata.raw.json", {"data": {
            "bvid": bvid, "owner": manifest["owner"],
            "pages": [{"page": page, "cid": cid, "duration": 3}],
        }})
        source = folder / "subtitle.01.raw.json"
        analysis.write_json(source, {"body": [{"from": 2, "to": 3, "content": "合成中文测试字幕"}]})
        official = self.source.parent / "manifest.json"
        official.write_text("{}", encoding="utf-8")
        self.entry["duration_seconds"] = 1
        selection = analysis.work_dir(self.root, "S23", self.entry) / "review_subtitle.json"
        analysis.write_json(selection, {"bvid": bvid, "cid": cid, "page": page})
        item = {"entry": self.entry}
        with patch.object(analysis.subprocess, "run") as run:
            result = analysis.analyze_one(item, "S23", root=self.root)
            run.assert_not_called()
        prepared = analysis.read_json(Path(result["input"]))
        value = prepared["skeleton"]
        subtitle, primary = value["dossier"]["files"]
        self.assertEqual((subtitle["external_key"], subtitle["page"]), (f"{bvid}:{cid}", page))
        self.assertEqual(primary["external_key"], f"{self.entry['bvid']}:{self.entry['cid']}")
        self.assertIn(self.entry["bvid"], value["dossier"]["slug"])
        value["evidence"] = [{"field": "dossier.rounds", "kind": "text",
                              "source_path": prepared["source_path"], "start_ms": 2000, "end_ms": 3000,
                              "quote": "合成中文测试字幕"}]
        self.assertEqual(analysis.validate_candidate(value, self.entry, source, root=self.root)
                         ["evidence"][0]["sha256"], analysis.sha256(source))
        analysis.write_json(selection, {"bvid": bvid, "cid": cid + 1, "page": page})
        with self.assertRaisesRegex(ValueError, "CID 不匹配"):
            analysis.prepare_text(self.entry, "S23", root=self.root)

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

    def test_s22_known_template_does_not_require_a_season_code_mapping(self):
        entry = {**self.entry, "labels": {**self.entry["labels"], "board_candidate": "预女猎白混"}}

        self.assertEqual(analysis.board_for(entry, "S22", self.root), "mixed_blood")

    def test_configured_entertainment_board_is_rejected_during_candidate_preparation(self):
        entry = {**self.entry, "labels": {**self.entry["labels"], "board_candidate": "狼王守卫"}}

        with self.assertRaisesRegex(ValueError, "娱乐版型"):
            analysis.board_for(entry, "S22", self.root)

    def test_valid_candidate_has_evidence_hash_and_no_formal_write(self):
        value = analysis.validate_candidate(self.candidate(), self.entry, self.source, root=self.root)
        self.assertEqual(value["evidence"][0]["sha256"], analysis.sha256(self.source))
        self.assertFalse((self.root / "data/games").exists())

    def test_evidence_hash_is_cached_per_path_but_each_row_is_checked(self):
        value = self.candidate()
        value["evidence"].append({**value["evidence"][0], "field": "dossier.rounds.1"})
        with patch.object(analysis, "sha256", wraps=analysis.sha256) as hash_file:
            checked = analysis.validate_candidate(value, self.entry, self.source, root=self.root)
        self.assertEqual(hash_file.call_count, 1)
        self.assertEqual(checked["evidence"][0]["sha256"], checked["evidence"][1]["sha256"])

        invalid_rows = [
            ({"sha256": "0" * 64}, "证据SHA"),
            ({"start_ms": -1}, "合法时间窗口"),
            ({"quote": "不是字幕里的原话"}, "原话"),
        ]
        for change, message in invalid_rows:
            with self.subTest(change=change):
                invalid = self.candidate()
                invalid["evidence"].append({**invalid["evidence"][0], "field": "dossier.rounds.1", **change})
                with patch.object(analysis, "sha256", wraps=analysis.sha256) as hash_file:
                    with self.assertRaisesRegex(ValueError, message):
                        analysis.validate_candidate(invalid, self.entry, self.source, root=self.root)
                self.assertEqual(hash_file.call_count, 1)

    def test_evidence_source_ownership_is_checked_for_each_row(self):
        other = self.root / "data/raw/bilibili/another-game.json"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text(json.dumps({"body": [{"from": 1, "to": 3, "content": "合法文字"}]}), encoding="utf-8")
        value = self.candidate()
        value["evidence"].append({**value["evidence"][0],
                                  "field": "dossier.seats", "source_path": other.relative_to(self.root).as_posix()})
        with self.assertRaisesRegex(ValueError, "另一对局"):
            analysis.validate_candidate(value, self.entry, self.source, root=self.root)

    def test_analyze_one_prepares_local_candidate_input_by_default(self):
        item = {"entry": self.entry}
        with patch.object(analysis, "prepare_text", return_value=self.source):
            result = analysis.analyze_one(item, "S23", root=self.root)
        self.assertTrue(result["prepared"])
        self.assertEqual(json.loads(Path(result["input"]).read_text(encoding="utf-8"))["source_path"],
                         self.source.relative_to(self.root).as_posix())

    def test_cli_validate_candidates_switches_from_preparation_to_candidate_validation(self):
        report = {"failures": [], "waiting_acquisition": [], "analyzed": 0, "prepared": 0}
        with patch.object(analysis, "run", return_value=report) as run:
            self.assertEqual(analysis.main([]), 0)
            self.assertTrue(run.call_args.kwargs["prepare_only"])
            self.assertEqual(analysis.main(["--validate-candidates"]), 0)
            self.assertFalse(run.call_args.kwargs["prepare_only"])

    def test_independent_endgame_is_preserved_and_validated_at_candidate_boundary(self):
        value = self.candidate()
        value["endgame"] = {"schema_version": 1, "game_slug": value["dossier"]["slug"], "phases": [
            {"kind": "wolf_rush", "day": 1, "actor": None,
             "declared_targets": [9], "result": "werewolf_win"}]}
        checked = analysis.validate_candidate(value, self.entry, self.source, root=self.root)
        self.assertEqual(checked["endgame"], value["endgame"])
        value["endgame"]["game_slug"] = "another-game"
        with self.assertRaisesRegex(ValueError, "终局与对局slug"):
            analysis.validate_candidate(value, self.entry, self.source, root=self.root)
        value["endgame"]["game_slug"] = value["dossier"]["slug"]
        value["endgame"]["phases"][0]["declared_targets"] = [13]
        from game_records import ReviewError
        with self.assertRaisesRegex(ReviewError, "拍刀目标座位"):
            analysis.validate_candidate(value, self.entry, self.source, root=self.root)

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
        with patch.object(analysis, "prepare_text", return_value=self.source):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "版本已变化"):
                    analysis.analyze_one(item, "S23", root=self.root)
            self.assertEqual(candidate_path.read_text(), "{}")


if __name__ == "__main__":
    unittest.main()

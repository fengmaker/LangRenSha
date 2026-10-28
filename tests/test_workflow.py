"""Exercise workflow contracts using registered seasons outside the real data set."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workflow


class WorkflowTests(unittest.TestCase):
    def registry(self, root):
        (root / "config").mkdir()
        (root / "config/seasons.json").write_text(json.dumps({"seasons": {
            code: {"name": code, "scope_file": f"config/{code}_game_scope.json",
                   "formal_rules_file": f"config/{code}_formal_rules.json",
                   "bluff_entry": "scripts/build_bluff_inference.py"}
            for code in ("S01", "S02")
        }}), encoding="utf-8")

    def test_new_registered_season_collects_without_borrowing_another_seasons_review(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            jobs = workflow.stage_commands("collect", "S01", root=root)
            self.assertEqual(len(jobs), 2)
            self.assertEqual([job[1] for job in jobs], ["scripts/collect_season.py"] * 2)
            self.assertEqual([job[2] for job in jobs], ["plan", "run"])
            self.assertTrue(all("S22" not in part and "S23" not in part for job in jobs for part in job))
            self.assertFalse(any("audit_season" in part or "reconcile_season_subtitles" in part
                                 for job in jobs for part in job))
            with self.assertRaisesRegex(ValueError, "尚无复核适配"):
                workflow.stage_commands("review", "S01", root=root, full_season=True)
            self.assertFalse((root / "data").exists(), "Preview must not create data files")

    def test_collect_uses_existing_plan_and_runs_only_acquisition(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            plan = root / "data/indexes/S01_采集计划.json"
            plan.parent.mkdir(parents=True)
            plan.write_text("{}", encoding="utf-8")
            jobs = workflow.stage_commands("collect", "S01", root=root)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0][1:3], ["scripts/collect_season.py", "run"])

    def test_transcription_does_not_implicitly_register_sources_in_database(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            jobs = workflow.stage_commands("transcribe", "S01", root=root)
            self.assertEqual(len(jobs), 1)
            self.assertIn("scripts/transcribe_review_queue.py", jobs[0])
            self.assertEqual(jobs[0][0], str(workflow.ASR_PYTHON))

    def test_publication_retains_all_formal_seasons(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            for code in ("S01", "S02"):
                folder = root / "data/games" / code / "example"
                folder.mkdir(parents=True)
                (folder / "dossier.json").write_text("{}", encoding="utf-8")
            jobs = workflow.stage_commands("publish", "S02", root=root)
            publication = next(job for job in jobs if "website.api.publish" in job)
            self.assertEqual(publication[publication.index("--seasons") + 1:][:2], ["S01", "S02"])

    def test_s23_import_prepares_then_uses_the_validated_transaction_entry(self):
        jobs = workflow.stage_commands("import", "S23")
        self.assertEqual([job[1:] for job in jobs], [
            ["scripts/backup_database.py"],
            ["scripts/import_s23_formal.py", "--prepare"],
            ["scripts/import_s23_formal.py", "--import-db", "--verify-idempotency"],
        ])

    def test_s22_import_requires_a_specific_game_and_does_not_publish(self):
        with self.assertRaisesRegex(ValueError, "请指定--bvid"):
            workflow.stage_commands("import", "S22")
        jobs = workflow.stage_commands("import", "S22", bvid="BV1234567890")
        self.assertEqual([job[1:] for job in jobs], [
            ["scripts/backup_database.py"],
            ["scripts/batch_s22.py", "import-edits", "--bvid", "BV1234567890"],
        ])

    def test_s21_import_uses_its_own_adapter_and_preserves_selected_media(self):
        jobs = workflow.stage_commands("import", "S21", bvid="BV1234567890")
        self.assertEqual([job[1:] for job in jobs], [
            ["scripts/backup_database.py"],
            ["scripts/import_s21_formal.py", "--prepare", "--bvid", "BV1234567890"],
            ["scripts/import_s21_formal.py", "--import-db", "--bvid", "BV1234567890"],
        ])

    def test_local_review_does_not_schedule_a_full_season_pipeline(self):
        for season in ("S21", "S22", "S23"):
            with self.subTest(season=season):
                with self.assertRaisesRegex(ValueError, "局部复核"):
                    workflow.stage_commands("review", season, bvid="BV1234567890")

    def test_explicit_full_season_review_keeps_existing_checks(self):
        s22 = workflow.stage_commands("review", "S22", full_season=True)
        self.assertEqual([job[1:] for job in s22], [
            ["scripts/audit_s22_batch.py"], ["scripts/formal_entry.py", "audit"],
        ])
        s23 = workflow.stage_commands("review", "S23", full_season=True)
        self.assertEqual(s23[0][1:], ["scripts/audit_s23_review.py"])
        self.assertIn(["scripts/build_s23_review.py", "--require-complete"], [job[1:] for job in s23])

    def test_a_game_filter_cannot_silently_run_the_full_season(self):
        with self.assertRaisesRegex(ValueError, "不能用--bvid限制"):
            workflow.stage_commands("review", "S23", bvid="BV1234567890", full_season=True)

    def test_local_review_run_stops_before_starting_any_subprocess(self):
        with patch.object(sys, "argv", ["workflow.py", "run", "--season", "S23", "--stage", "review"]), \
                patch.object(workflow.subprocess, "run") as execute:
            with self.assertRaisesRegex(ValueError, "局部复核"):
                workflow.main()
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Generic incremental workflow commands stay season scoped."""
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
        path = root / "config/seasons.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 2, "seasons": {
            code: {"name": code, "scope_file": "config/seasons.json",
                   "formal_rules_file": "config/game_rules.json"}
            for code in ("S01", "S02")
        }}), encoding="utf-8")

    def test_collect_process_and_review_use_the_current_incremental_entry_points(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            self.assertEqual(workflow.stage_commands("collect", "S01", root=root), [[
                str(root / ".venv/Scripts/python.exe"), "scripts/update_incremental.py", "--season", "S01"]])
            self.assertEqual(workflow.stage_commands("process", "S01", root=root, bvid="BVfixture"), [[
                str(root / ".venv/Scripts/python.exe"), "scripts/analyze_incremental.py", "--season", "S01",
                "--bvid", "BVfixture"]])
            self.assertEqual(workflow.stage_commands("review", "S01", root=root, bvid="BVfixture"), [[
                str(root / ".venv/Scripts/python.exe"), "scripts/analyze_incremental.py", "--season", "S01",
                "--validate-candidates", "--bvid", "BVfixture"]])

    def test_finalize_requires_a_review_export_and_applies_it_with_optional_revisions(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            with self.assertRaisesRegex(ValueError, "finalize需要--review-export"):
                workflow.stage_commands("finalize", "S01", root=root)
            self.assertEqual(workflow.stage_commands(
                "finalize", "S01", root=root, review_export="review.json", note_revisions="notes.json"), [[
                    str(root / ".venv/Scripts/python.exe"), "scripts/apply_incremental_review.py",
                    "review.json", "--season", "S01", "--apply", "--note-revisions", "notes.json"]])

    def test_export_and_verify_use_the_local_static_exporter(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            python = str(root / ".venv/Scripts/python.exe")
            self.assertEqual(workflow.stage_commands("export", "S01", root=root), [[
                python, "website/static_publish/export_static.py"]])
            self.assertEqual(workflow.stage_commands("verify", "S01", root=root), [[
                python, "website/static_publish/export_static.py", "--check"]])

    def test_status_reads_incremental_state_and_counts_final_game_json(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            games = root / "data/games/S01"
            games.mkdir(parents=True)
            (games / "one").mkdir()
            (games / "one/game.json").write_text("{}", encoding="utf-8")
            state = root / "data/reports/S01/incremental/state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"items": {
                "a": {"analysis": "ready", "applied": False},
                "b": {"analysis": "failed", "applied": False},
                "c": {"analysis": "ready", "formal_dossier": True},
            }}), encoding="utf-8")

            result = workflow.status("S01", root=root)

            self.assertEqual(result["formal_games"], 1)
            self.assertEqual(result["pending"], 2)
            self.assertEqual(result["analysis"], {"ready": 1, "failed": 1})

    def test_unknown_seasons_are_rejected_without_creating_data(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.registry(root)
            with self.assertRaisesRegex(ValueError, "Unknown season"):
                workflow.stage_commands("collect", "S99", root=root)
            self.assertFalse((root / "data").exists())

    def test_run_executes_the_requested_stage_only(self):
        argv = ["workflow.py", "run", "--season", "S23", "--stage", "process", "--bvid", "BVfixture"]
        with patch.object(sys, "argv", argv), patch.object(workflow.subprocess, "run") as execute:
            self.assertEqual(workflow.main(), 0)
        command = execute.call_args.args[0]
        self.assertEqual(command[1:3], ["scripts/analyze_incremental.py", "--season"])
        self.assertIn("BVfixture", command)
        execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()

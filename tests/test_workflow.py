"""Exercise workflow contracts using registered seasons outside the real data set."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

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
            self.assertTrue(all("S22" not in part and "S23" not in part for job in jobs for part in job))
            with self.assertRaisesRegex(ValueError, "尚无复核适配"):
                workflow.stage_commands("review", "S01", root=root)
            self.assertFalse((root / "data").exists(), "Preview must not create data files")

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


if __name__ == "__main__":
    unittest.main()

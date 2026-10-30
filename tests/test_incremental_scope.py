"""Publication count extensions require the actual human export and formal bytes."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from incremental_scope import approved_incremental_count


class IncrementalScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def fixture(self, reviewed=True):
        row = {"review_id": "BVnew1234567:123:p01", "bvid": "BVnew1234567", "cid": 123,
               "page": 1, "reviewed": reviewed, "note": "", "candidate_sha256": "a" * 64,
               "source_sha256": "b" * 64}
        manual = "data/reports/S23/incremental/manual.json"
        marker = {"format": "masters-incremental-confirmed-v1", "reviewed": True,
                  **{k: row[k] for k in ("review_id", "bvid", "cid", "page")},
                  "manual_source_path": manual}
        self.save("data/reports/S23/S23_逐局复核计划.json", {"entries": [{"bvid": "BVold1234567", "phase": "regular"}]})
        marker["manual_sha256"] = self.save(manual, {"format": "masters-incremental-review-v1", "season": "S23", "games": [row]})
        marker["dossier_sha256"] = self.save("data/games/S23/new/dossier.json", {
            "season": "S23", "files": [{"external_key": "BVnew1234567:123"}]})
        marker["voting_sha256"] = self.save("data/games/S23/new/voting.json", {})
        self.save("data/games/S23/new/incremental_review.json", marker)
        return marker

    def test_legacy_scope_unchanged_without_new_approvals(self):
        self.assertEqual(approved_incremental_count(self.root, "S23"), 0)
        self.assertEqual(approved_incremental_count(self.root, "S22"), 0)

    def test_confirmed_new_game_extends_count(self):
        self.fixture()
        self.assertEqual(approved_incremental_count(self.root, "S23"), 1)

    def test_unchecked_or_edited_formal_record_cannot_extend_scope(self):
        self.fixture(reviewed=False)
        with self.assertRaisesRegex(ValueError, "勾选"):
            approved_incremental_count(self.root, "S23")
        self.fixture()
        self.save("data/games/S23/new/voting.json", {"tampered": True})
        with self.assertRaisesRegex(ValueError, "版本不一致"):
            approved_incremental_count(self.root, "S23")

    def test_existing_baseline_game_cannot_be_counted_again(self):
        self.fixture()
        self.save("data/reports/S23/S23_逐局复核计划.json", {"entries": [{"bvid": "BVnew1234567", "phase": "regular"}]})
        with self.assertRaisesRegex(ValueError, "原75局"):
            approved_incremental_count(self.root, "S23")


if __name__ == "__main__":
    unittest.main()

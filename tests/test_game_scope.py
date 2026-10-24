"""User-excluded games cannot re-enter through batch or direct imports."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch_s22 as batch
import game_scope
import game_records


class GameScopeTests(unittest.TestCase):
    def test_phase_date_and_bvid_apply_only_to_s22(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / game_scope.POLICY_REL
            path.parent.mkdir()
            path.write_text(json.dumps({"season": "S22", "excluded_phases": ["showmatch"],
                "excluded_dates": ["2026-07-03"], "excluded_bvids": ["BVexcluded"]}), encoding="utf-8")
            for entry in [{"phase": "showmatch"}, {"date": "2026-07-03"}, {"bvid": "BVexcluded"},
                          {"slug": "bili-BVexcluded-p01-g01"}]:
                self.assertTrue(game_scope.exclusion_reason(entry, root=root))
            self.assertIsNone(game_scope.exclusion_reason({"season": "S23", "phase": "showmatch"}, root=root))
            self.assertIsNone(game_scope.exclusion_reason({"phase": "finals_week", "date": "2026-08-21"}, root=root))

    def test_current_catalog_does_not_restore_removed_games(self):
        full = batch.entries_from_catalog(include_excluded=True)
        active = batch.entries_from_catalog()
        self.assertEqual(len(full), 163)
        self.assertEqual(len(active), 149)
        self.assertEqual(len(full) - len(active), 14)
        self.assertFalse(any(game_scope.exclusion_reason(entry) for entry in active))
        self.assertIn("BV1yt7v6QE3Q", {entry["bvid"] for entry in active})

    def test_loaded_old_progress_filters_excluded_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / game_scope.POLICY_REL
            policy.parent.mkdir()
            policy.write_text(json.dumps({"season": "S22", "excluded_bvids": ["BVexcluded"]}), encoding="utf-8")
            state_path = root / "state.json"
            state_path.write_text(json.dumps({"season": "S22", "items": {
                "BVexcluded": {"phase": "regular"}, "BVkeep": {"phase": "regular"}}}), encoding="utf-8")
            with patch.object(batch, "ROOT", root), patch.object(batch, "STATE_FILE", state_path):
                self.assertEqual(set(batch.load_state()["items"]), {"BVkeep"})

    def test_direct_import_blocks_before_validation_or_database_write(self):
        with patch.object(game_records, "connect") as connect, patch.object(game_records, "validate") as validate:
            with self.assertRaisesRegex(game_records.ReviewError, "禁止重新入库"):
                game_records.import_game({"season": "S22", "phase": "showmatch"})
            connect.assert_not_called()
            validate.assert_not_called()

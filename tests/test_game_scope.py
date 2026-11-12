"""Pure user-confirmed exclusions for the active S22 scope."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import game_scope


class GameScopeTests(unittest.TestCase):
    def test_phase_date_and_bvid_exclusions_apply_only_to_the_configured_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / game_scope.POLICY_REL
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"seasons": {"S22": {"scope": {
                "excluded_phases": ["showmatch"],
                "excluded_dates": ["2026-07-03"],
                "excluded_bvids": ["BVexcluded"]}}}}), encoding="utf-8")
            entries = [
                {"season": "S22", "phase": "showmatch"},
                {"season": "S22", "date": "2026-07-03"},
                {"season": "S22", "bvid": "BVexcluded"},
                {"season": "S22", "slug": "bili-BVexcluded-p01-g01"},
            ]
            self.assertTrue(all(game_scope.exclusion_reason(row, root=root) for row in entries))
            self.assertIsNone(game_scope.exclusion_reason(
                {"season": "S23", "phase": "showmatch"}, root=root))
            self.assertIsNone(game_scope.exclusion_reason(
                {"season": "S22", "phase": "finals_week", "date": "2026-08-21"}, root=root))

    def test_entertainment_board_classification_does_not_depend_on_bvid_or_frequency(self):
        self.assertTrue(game_scope.exclusion_reason(
            {"season": "S22", "phase": "finals_week", "board": "ghost_bride", "bvid": "BVnew"}))
        self.assertTrue(game_scope.exclusion_reason(
            {"season": "S22", "board_name": "狼王守卫", "bvid": "BVanother"}))
        self.assertIsNone(game_scope.exclusion_reason(
            {"season": "S22", "board": "all_in", "phase": "finals_week"}))

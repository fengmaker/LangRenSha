import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from season_config import ROOT, load_season, season_codes


class SeasonConfigTests(unittest.TestCase):
    def test_registry_root_can_be_overridden_and_unknown_season_is_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config/seasons.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"seasons": {"S01": {"name": "测试", "status": "planned"}}}),
                              encoding="utf-8")
            self.assertEqual(season_codes(root), ["S01"])
            self.assertEqual(load_season("S01", root)["name"], "测试")
            with self.assertRaisesRegex(ValueError, "Unknown season"):
                load_season("S02", root)


if __name__ == "__main__":
    unittest.main()

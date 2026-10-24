import copy
from contextlib import nullcontext
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import batch_s22 as batch
from game_records import empty_event, template, ROLE_FACTIONS
import s22_review_server as server
from s22_text_review import merge_review, make_round


class TextReviewTests(unittest.TestCase):
    def setUp(self):
        roles = ["狼人", "女巫", "白神", "狼人", "混血儿", "平民", "狼人", "平民", "狼人", "预言家", "平民", "猎人"]
        seats = [{"seat": n, "name": f"测试玩家{n}", "role": role,
                  "faction": None if role == "混血儿" else ROLE_FACTIONS[role],
                  "learning_target": None, "learned_role": None} for n, role in enumerate(roles, 1)]
        self.value = {"slug": "s22-text-review-test", "season": "S22", "date": "2026-06-02",
                      "phase": "regular", "episode": 1, "day_in_episode": 1, "game_number": 1,
                      "board": "mixed_blood", "winner": None, "roster": [s["name"] for s in seats],
                      "commentators": [], "referee": None, "seats": seats,
                      "rounds": [make_round(template("mixed_blood"), n, seats) for n in [1, 2]], "files": []}

    def test_transcript_fills_double_death_and_explicit_wolf_mixed_blood(self):
        value = copy.deepcopy(self.value)
        value["seats"][4]["faction"] = None
        day = value["rounds"][0]["day"]
        day[next(i for i, e in enumerate(day) if e["slot"] == "night_deaths")] = empty_event("night_deaths")
        reviewed, changes, questions = merge_review(value, {"seats": [{"seat": 5, "faction": "werewolf"}], "events": [
            {"number": 1, "phase": "day", "slot": "night_deaths", "action": "die", "actor": None,
             "targets": [1, 2], "result": "一二双死"}], "round_count": 2})
        self.assertEqual(reviewed["seats"][4]["faction"], "werewolf")
        death = next(e for e in reviewed["rounds"][0]["day"] if e["slot"] == "night_deaths")
        self.assertEqual(death["targets"], [1, 2])
        self.assertFalse(questions)
        self.assertEqual(len(changes), 2)

    def test_uncertain_or_conflicting_candidates_do_not_erase_known_identity(self):
        reviewed, _, questions = merge_review(self.value, {"seats": [
            {"seat": 10, "role": None}, {"seat": 10, "role": "女巫"}], "events": []})
        self.assertEqual(reviewed["seats"][9]["role"], "预言家")
        self.assertTrue(any(q["candidate"] == "女巫" for q in questions if "candidate" in q))

    def test_learning_metadata_cannot_move_to_another_original_card(self):
        reviewed, _, questions = merge_review(self.value, {"seats": [{"seat": 10, "learned_role": "机械猎人"}], "events": []})
        self.assertIsNone(reviewed["seats"][9]["learned_role"])
        self.assertTrue(any("机械狼" in q["reason"] for q in questions))

    def test_stale_browser_save_is_rejected_before_any_import(self):
        with patch.object(server.batch, "batch_lock", return_value=nullcontext()), \
             patch.object(server, "item_data", return_value={"sha256": "current"}), \
             patch.object(server, "import_game") as importer:
            with self.assertRaisesRegex(ValueError, "已被更新"):
                server.save_item("BVtest", {"expected_sha256": "old"})
            importer.assert_not_called()

    def test_failed_import_restores_the_previous_dossier_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "data/game"
            folder.mkdir(parents=True)
            batch.atomic_json(folder / "dossier.json", self.value)
            incoming = copy.deepcopy(self.value)
            incoming["winner"] = "good"
            old = {"sha256": "expected", "dossier": self.value, "entry": {"output_dir": "data/game"}}
            with patch.object(batch, "ROOT", root), patch.object(batch, "batch_lock", return_value=nullcontext()), \
                 patch.object(batch, "load_state", return_value={"items": {"BVtest": old["entry"]}}), \
                 patch.object(server, "item_data", return_value=old), patch.object(server, "validate"), \
                 patch.object(server, "import_game", side_effect=RuntimeError("rollback")):
                with self.assertRaisesRegex(RuntimeError, "rollback"):
                    server.save_item("BVtest", {"expected_sha256": "expected", "dossier": incoming})
            self.assertEqual(batch.read_json(folder / "dossier.json"), self.value)

    def test_local_service_supports_ranges_and_blocks_private_paths_and_origins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            (root / "data/test.bin").write_bytes(b"0123456789")
            with patch.object(batch, "ROOT", root), patch.object(server.Handler, "log_message", lambda *args: None):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = "http://127.0.0.1:" + str(httpd.server_port)
                try:
                    req = urllib.request.Request(base + "/data/test.bin", headers={"Range": "bytes=2-4"})
                    with urllib.request.urlopen(req) as response:
                        self.assertEqual((response.status, response.read()), (206, b"234"))
                    with self.assertRaises(urllib.error.HTTPError) as private:
                        urllib.request.urlopen(base + "/data/%2e%2e/.secrets/not-readable")
                    self.assertEqual(private.exception.code, 403)
                    req = urllib.request.Request(base + "/api/game/BVtest", data=b"{}",
                        headers={"Content-Type": "application/json", "Origin": "https://unrelated.example"})
                    with self.assertRaises(urllib.error.HTTPError) as origin:
                        urllib.request.urlopen(req)
                    self.assertEqual(origin.exception.code, 403)
                finally:
                    httpd.shutdown()
                    httpd.server_close()


if __name__ == "__main__":
    unittest.main()

"""S22 endgame sidecars keep wolf-rush evidence separate and source-bound."""
from pathlib import Path
import copy
import hashlib
import os
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import batch_s22
import endgame_records
import database


class EndgameRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = endgame_records.build(write=False)
        cls.phases = {p["bvid"]: p for p in cls.report["phases"]}

    def test_june_second_game_three_is_a_separate_wolf_rush_phase(self):
        phase = self.phases["BV1pGVC6cEbW"]
        self.assertEqual(phase["kind"], "wolf_rush")
        self.assertEqual((phase["day"], phase["actor"]), (4, 1))
        self.assertEqual(phase["declared_targets"], [9])
        self.assertEqual(phase["result"], "werewolf_win")
        self.assertEqual(len(phase["evidence"]), 1)
        self.assertIn("最后一名9号", phase["evidence"][0]["quote"])

    def test_targets_are_unordered_and_only_named_targets_are_written(self):
        phase = self.phases["BV1suMG6PEYP"]
        self.assertEqual(phase["declared_targets"], [11, 12])
        self.assertIn("小刀击杀12号", phase["note"])
        self.assertIn("大刀击杀11号", phase["note"])
        self.assertEqual(self.phases["BV1W6jG6HEeT"]["declared_targets"], [])

    def test_speculative_postgame_discussion_stays_a_candidate(self):
        bvid = "BV1KkL96MEuH"
        self.assertNotIn(bvid, self.phases)
        self.assertEqual([c["bvid"] for c in self.report["candidates"]], [bvid])

    def test_sidecar_contract_and_sha256_match_source(self):
        state = batch_s22.load_state()
        entry = state["items"]["BV1pGVC6cEbW"]
        source_hash = hashlib.sha256(
            (ROOT / entry["source_path"]).read_bytes()).hexdigest()
        item = next(g for g in self.report["games"]
                    if g["bvid"] == "BV1pGVC6cEbW")
        self.assertEqual(item["source_sha256"], source_hash)
        self.assertEqual(endgame_records.SCHEMA_VERSION, 1)
        self.assertEqual(set(self.phases["BV1pGVC6cEbW"]["evidence"][0]),
                         {"path", "start_ms", "end_ms", "quote"})


@unittest.skipUnless((ROOT / ".secrets/database.json").is_file() or os.environ.get("DATABASE_URL"), "需要本地 PostgreSQL 配置")
class EndgameDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "jcms_endgame_test_" + uuid.uuid4().hex
        database.migrate(cls.schema)

    @classmethod
    def tearDownClass(cls):
        from psycopg import sql
        assert cls.schema.startswith("jcms_endgame_test_")
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def test_reimport_preserves_unknowns_and_invalid_replacement_preserves_existing_phases(self):
        sidecar = {"schema_version": 1, "game_slug": "rush-" + uuid.uuid4().hex, "phases": [
            {"kind": "wolf_rush", "day": None, "actor": None, "declared_targets": [], "result": "unknown"},
            {"kind": "wolf_rush", "day": 4, "actor": 1, "declared_targets": [9], "result": "werewolf_win"},
        ]}
        with patch.dict(os.environ, {"DATABASE_SCHEMA": self.schema}):
            with database.connect() as conn:
                conn.execute("INSERT INTO games(slug) VALUES(%s)", (sidecar["game_slug"],))
            endgame_records.import_endgame(sidecar)
            endgame_records.import_endgame(sidecar)
            broken = copy.deepcopy(sidecar)
            broken["phases"][1]["declared_targets"] = [13]
            with self.assertRaises(database.ReviewError):
                endgame_records.import_endgame(broken)
            with database.connect() as conn:
                phases = conn.execute("SELECT day_number,actor_seat,declared_targets,result FROM game_endgame_phases ORDER BY phase_number").fetchall()
                self.assertEqual(phases, [
                    {"day_number": None, "actor_seat": None, "declared_targets": [], "result": "unknown"},
                    {"day_number": 4, "actor_seat": 1, "declared_targets": [9], "result": "werewolf_win"},
                ])
                conn.execute("DELETE FROM games WHERE slug=%s", (sidecar["game_slug"],))
                self.assertEqual(conn.execute("SELECT count(*) n FROM game_endgame_phases").fetchone()["n"], 0)

    def test_endgame_replacement_leaves_existing_ballots_untouched(self):
        sidecar = {"schema_version": 1, "game_slug": "rush-" + uuid.uuid4().hex, "phases": [
            {"kind": "wolf_rush", "day": 4, "actor": 1, "declared_targets": [9], "result": "werewolf_win"}]}
        with patch.dict(os.environ, {"DATABASE_SCHEMA": self.schema}):
            with database.connect() as conn:
                game = conn.execute("INSERT INTO games(slug) VALUES(%s) RETURNING id", (sidecar["game_slug"],)).fetchone()
                ballot = conn.execute("""INSERT INTO game_ballots(game_id,ballot_key,day_number,kind,ballot_number,stage,status)
                    VALUES(%s,'ballot-1',4,'exile',1,'initial','partial') RETURNING id""", (game["id"],)).fetchone()
            endgame_records.import_endgame(sidecar)
            endgame_records.import_endgame({**sidecar, "phases": []})
            with database.connect() as conn:
                self.assertEqual(conn.execute("SELECT id FROM game_ballots WHERE game_id=%s", (game["id"],)).fetchone()["id"], ballot["id"])
                self.assertEqual(conn.execute("SELECT count(*) n FROM game_endgame_phases WHERE game_id=%s", (game["id"],)).fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()

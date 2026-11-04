"""S22 endgame sidecars keep wolf-rush evidence separate and source-bound."""
from pathlib import Path
import copy
import hashlib
import os
import tempfile
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

    def test_bv1oxmb6feq4_rush_is_the_day_after_the_night_kill(self):
        phase = self.phases["BV1oXMB6fEQ4"]
        self.assertEqual(phase["day"], 4)
        self.assertIn("第四天12号", phase["note"])

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

    def test_supplied_connection_keeps_endgame_in_the_outer_transaction(self):
        sidecar = {"schema_version": 1, "game_slug": "rush-" + uuid.uuid4().hex, "phases": [
            {"kind": "wolf_rush", "day": 2, "actor": None, "declared_targets": [3], "result": "unknown"}]}
        with patch.dict(os.environ, {"DATABASE_SCHEMA": self.schema}):
            with self.assertRaisesRegex(RuntimeError, "later import failed"):
                with database.connect() as conn:
                    conn.execute("INSERT INTO games(slug) VALUES(%s)", (sidecar["game_slug"],))
                    endgame_records.import_endgame(sidecar, conn=conn)
                    raise RuntimeError("later import failed")
            with database.connect() as conn:
                self.assertEqual(conn.execute("SELECT count(*) n FROM games WHERE slug=%s", (sidecar["game_slug"],)).fetchone()["n"], 0)

    def test_incremental_import_preserves_rush_and_empty_endgames_and_rolls_back_on_failure(self):
        import apply_incremental_review as apply
        import game_records
        import voting_records

        def import_game(dossier, *, conn, **kwargs):
            row = conn.execute("INSERT INTO games(slug) VALUES(%s) RETURNING id", (dossier["slug"],)).fetchone()
            return {"id": row["id"]}

        def import_voting(voting, *, conn):
            game = conn.execute("SELECT id FROM games WHERE slug=%s", (voting["game_slug"],)).fetchone()
            conn.execute("""INSERT INTO game_ballots(game_id,ballot_key,day_number,kind,ballot_number,stage,status)
                VALUES(%s,'incremental-ballot',1,'exile',1,'initial','partial')""", (game["id"],))
            return {"ballots": 1}

        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp, \
                patch.dict(os.environ, {"DATABASE_SCHEMA": self.schema}), \
                patch.object(database, "import_media", return_value={}), \
                patch.object(game_records, "import_game", side_effect=import_game), \
                patch.object(voting_records, "import_voting", side_effect=import_voting), \
                patch.object(apply, "save_state"):
            root = Path(temp)
            candidate_path, source_path = root / "candidate.json", root / "source.json"
            candidate_path.write_text("{}")
            source_path.write_text("{}")
            for has_rush in (True, False):
                with self.subTest(has_rush=has_rush):
                    slug = "incremental-" + uuid.uuid4().hex
                    sidecar = {"schema_version": 1, "game_slug": slug, "phases": [
                        {"kind": "wolf_rush", "day": 2, "actor": None,
                         "declared_targets": [9], "result": "werewolf_win"}] if has_rush else []}
                    plan = {"item": {}, "game": {"review_id": slug, "bvid": "BVtest", "page": 1,
                            "candidate_sha256": apply.sha256_file(candidate_path),
                            "source_sha256": apply.sha256_file(source_path)},
                            "candidate_path": candidate_path, "source_path": source_path,
                            "manifest": root / "manifest.json", "prepared_formal": {
                                "dossier": {"slug": slug}, "voting": {"game_slug": slug},
                                "endgame": sidecar, "derivations": {}}}
                    receipt = apply._import_database(plan, {}, "S23", root)
                    self.assertEqual(receipt["endgame"], {"phases": int(has_rush)})
                    with database.connect() as conn:
                        rows = conn.execute("""SELECT p.day_number,p.actor_seat,p.declared_targets,p.result
                            FROM game_endgame_phases p JOIN games g ON g.id=p.game_id
                            WHERE g.slug=%s""", (slug,)).fetchall()
                        self.assertEqual(rows, [{"day_number": 2, "actor_seat": None,
                                               "declared_targets": [9], "result": "werewolf_win"}]
                                         if has_rush else [])
                        self.assertEqual(conn.execute("""SELECT count(*) n FROM game_ballots b
                            JOIN games g ON g.id=b.game_id WHERE g.slug=%s""", (slug,)).fetchone()["n"], 1)
                        conn.execute("DELETE FROM games WHERE slug=%s", (slug,))

            # A failure after inserting the terminal phases rolls back the
            # dossier and ballots as well, and never marks the state applied.
            slug = "incremental-rollback-" + uuid.uuid4().hex
            plan["item"] = {}
            plan["prepared_formal"]["dossier"]["slug"] = slug
            plan["prepared_formal"]["voting"]["game_slug"] = slug
            plan["prepared_formal"]["endgame"] = {"schema_version": 1, "game_slug": slug, "phases": [
                {"kind": "wolf_rush", "day": 2, "actor": None,
                 "declared_targets": [9], "result": "werewolf_win"}]}
            real_import = endgame_records.import_endgame

            def fail_after_endgame(value, *, conn):
                real_import(value, conn=conn)
                raise RuntimeError("endgame import failed")

            with patch.object(endgame_records, "import_endgame", side_effect=fail_after_endgame):
                with self.assertRaisesRegex(RuntimeError, "endgame import failed"):
                    apply._import_database(plan, {}, "S23", root)
            self.assertEqual(plan["item"]["phases"], {})
            with database.connect() as conn:
                self.assertEqual(conn.execute("SELECT count(*) n FROM games WHERE slug=%s", (slug,)).fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()

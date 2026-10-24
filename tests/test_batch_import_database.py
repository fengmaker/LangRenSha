"""Batch dossier writes are exercised only inside a disposable PostgreSQL schema."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
HAS_DRIVER = importlib.util.find_spec("psycopg") is not None
HAS_DATABASE_CONFIG = (ROOT / ".secrets/database.json").is_file() or bool(os.environ.get("DATABASE_URL"))
if HAS_DRIVER:
    from psycopg import sql
    import database
    import game_records
    from game_records import ReviewError, import_game, validate


@unittest.skipUnless(HAS_DRIVER and HAS_DATABASE_CONFIG, "需要本地 PostgreSQL 配置和 psycopg 驱动")
class BatchGameImportDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "jcms_batch_test_" + uuid.uuid4().hex
        assert cls.schema.startswith("jcms_batch_test_")
        database.migrate(cls.schema)
        cls.sample = json.loads(
            (ROOT / "data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json").read_text(encoding="utf-8")
        )
        cls.audio = copy.deepcopy(next(file for file in cls.sample["files"] if file["role"] == "audio"))
        cls.audio_path = ROOT / cls.audio["path"]
        if not cls.audio_path.is_file():
            raise RuntimeError(f"样例音频必须是真实文件：{cls.audio_path}")
        with database.connect(cls.schema) as conn:
            conn.execute("INSERT INTO seasons(code,name) VALUES('S22','isolated batch integration test')")
            conn.execute(
                "INSERT INTO sources(platform,external_key,title) VALUES(%s,%s,%s)",
                (cls.audio["platform"], cls.audio["external_key"], "isolated test source from existing sample"),
            )

    @classmethod
    def tearDownClass(cls):
        assert cls.schema.startswith("jcms_batch_test_")
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        self.environment = patch.dict(os.environ, {"DATABASE_SCHEMA": self.schema})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def record(self):
        value = copy.deepcopy(self.sample)
        value["slug"] = "batch-test-" + uuid.uuid4().hex
        # Keep database artifact ingestion read-only on the filesystem. The
        # existing audio file is registered; text artifacts are unnecessary.
        value["files"] = [copy.deepcopy(self.audio)]
        return value

    def incomplete_record(self):
        value = self.record()
        value.update(roster=[], commentators=[], referee=None, rounds=[], game_number=None, winner=None)
        for seat in value["seats"]:
            seat.update(name=None, role=None, faction=None, learning_target=None, learned_role=None)
        return value

    def counts_for_game(self, slug):
        with database.connect(self.schema) as conn:
            game = conn.execute("SELECT id FROM games WHERE slug=%s", (slug,)).fetchone()
            self.assertIsNotNone(game)
            game_id = game["id"]
            result = {"games": conn.execute("SELECT count(*) AS n FROM games WHERE id=%s", (game_id,)).fetchone()["n"]}
            for table in ("game_details", "game_seats", "game_staff", "game_files", "game_rounds",
                          "game_event_records", "game_event_targets", "game_event_votes", "game_event_effects"):
                result[table] = conn.execute(
                    sql.SQL("SELECT count(*) AS n FROM {} WHERE game_id=%s").format(sql.Identifier(table)),
                    (game_id,),
                ).fetchone()["n"]
            result["game_id"] = str(game_id)
            return result

    def game_snapshot(self, slug):
        with database.connect(self.schema) as conn:
            game_id = conn.execute("SELECT id FROM games WHERE slug=%s", (slug,)).fetchone()["id"]
            details = dict(conn.execute(
                "SELECT board_code,event_date,phase,episode,day_in_episode,game_number,winning_faction "
                "FROM game_details WHERE game_id=%s", (game_id,)
            ).fetchone())
            seats = [dict(row) for row in conn.execute("""SELECT s.seat_number,p.name,s.role,s.faction,
                    s.learning_target_seat,s.learned_role FROM game_seats s LEFT JOIN people p ON p.id=s.person_id
                    WHERE s.game_id=%s ORDER BY s.seat_number""", (game_id,)).fetchall()]
            events = [dict(row) for row in conn.execute("""SELECT id,round_number,phase,slot_code,action,actor_seat
                    FROM game_event_records WHERE game_id=%s ORDER BY round_number,phase,slot_code""", (game_id,)).fetchall()]
            targets = [dict(row) for row in conn.execute("""SELECT t.event_id,t.position,t.seat_number
                    FROM game_event_targets t WHERE t.game_id=%s ORDER BY t.event_id,t.position""", (game_id,)).fetchall()]
            files = [dict(row) for row in conn.execute(
                "SELECT game_id,file_role,artifact_id FROM game_files WHERE game_id=%s ORDER BY file_role", (game_id,)
            ).fetchall()]
            return {"details": details, "seats": seats, "events": events, "targets": targets, "files": files}

    def test_all_unknown_batch_facts_insert_as_nulls_without_placeholder_round(self):
        value = self.incomplete_record()
        receipt = import_game(value, allow_incomplete=True)

        with database.connect(self.schema) as conn:
            details = conn.execute("SELECT game_number,winning_faction FROM game_details WHERE game_id=%s",
                                  (receipt["game_id"],)).fetchone()
            seats = conn.execute("SELECT seat_number,person_id,role,faction FROM game_seats WHERE game_id=%s ORDER BY seat_number",
                                 (receipt["game_id"],)).fetchall()
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM game_staff WHERE game_id=%s",
                                          (receipt["game_id"],)).fetchone()["n"], 0)
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM game_rounds WHERE game_id=%s",
                                          (receipt["game_id"],)).fetchone()["n"], 0)
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM game_files WHERE game_id=%s AND file_role='audio'",
                                          (receipt["game_id"],)).fetchone()["n"], 1)

        self.assertIsNone(details["game_number"])
        self.assertIsNone(details["winning_faction"])
        self.assertEqual(len(seats), 12)
        self.assertTrue(all(row["person_id"] is None and row["role"] is None and row["faction"] is None for row in seats))
        self.assertEqual(receipt["rounds"], 0)

    def test_ghost_bride_and_third_party_winner_are_stored(self):
        value = self.incomplete_record()
        value["slug"] = "batch-test-ghost-" + uuid.uuid4().hex
        value["board"] = "ghost_bride"
        value["winner"] = "third_party"
        roles = [
            ("鬼魂新娘", "third_party"), ("预言家", "good"), ("女巫", "good"), ("猎人", "good"),
            ("守卫", "good"), ("平民", "good"), ("平民", "good"), ("平民", "good"), ("平民", "good"),
            ("狼人", "werewolf"), ("狼人", "werewolf"), ("狼人", "werewolf"),
        ]
        for seat, (role, faction) in zip(value["seats"], roles):
            seat.update(role=role, faction=faction)

        receipt = import_game(value, allow_incomplete=True)
        with database.connect(self.schema) as conn:
            details = conn.execute("SELECT board_code,winning_faction FROM game_details WHERE game_id=%s",
                                   (receipt["game_id"],)).fetchone()
            bride = conn.execute("SELECT role,faction FROM game_seats WHERE game_id=%s AND seat_number=1",
                                 (receipt["game_id"],)).fetchone()

        self.assertEqual(dict(details), {"board_code": "ghost_bride", "winning_faction": "third_party"})
        self.assertEqual(dict(bride), {"role": "鬼魂新娘", "faction": "third_party"})

    def test_repeat_import_keeps_game_and_events_counts_and_unknown_actor_target(self):
        value = self.record()
        value["rounds"] = [copy.deepcopy(self.sample["rounds"][0])]
        guard = next(event for event in value["rounds"][0]["night"] if event["slot"] == "guard")
        guard.update(actor=None, targets=[12])

        first = import_game(copy.deepcopy(value), allow_incomplete=True)
        before = self.counts_for_game(value["slug"])
        second = import_game(copy.deepcopy(value), allow_incomplete=True)
        after = self.counts_for_game(value["slug"])

        self.assertEqual(first["game_id"], second["game_id"])
        self.assertEqual(before, after)
        with database.connect(self.schema) as conn:
            event = conn.execute("""SELECT e.actor_seat,t.seat_number FROM game_event_records e
                JOIN game_event_targets t ON t.event_id=e.id WHERE e.game_id=%s AND e.phase='night'
                AND e.slot_code='guard'""", (first["game_id"],)).fetchone()
        self.assertEqual(dict(event), {"actor_seat": None, "seat_number": 12})

    def test_failure_after_delete_rolls_back_the_old_game_record(self):
        value = self.record()
        value["rounds"] = [copy.deepcopy(self.sample["rounds"][0])]
        original = import_game(copy.deepcopy(value), allow_incomplete=True)
        before = self.game_snapshot(value["slug"])

        replacement = copy.deepcopy(value)
        replacement["winner"] = "werewolf"
        real_ensure_person = game_records.ensure_person
        calls = 0

        def fail_after_delete(conn, name):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("simulated write failure after current rows were deleted")
            return real_ensure_person(conn, name)

        with patch.object(game_records, "ensure_person", side_effect=fail_after_delete):
            with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
                import_game(replacement, allow_incomplete=True)

        self.assertGreaterEqual(calls, 3)
        self.assertEqual(self.game_snapshot(value["slug"]), before)
        self.assertEqual(self.counts_for_game(value["slug"])["game_id"], original["game_id"])

    def test_confirmed_sample_still_passes_the_default_strict_path(self):
        board = validate(copy.deepcopy(self.sample), check_files=True)
        self.assertEqual(board["code"], self.sample["board"])
        with self.assertRaises(ReviewError):
            validate(self.incomplete_record(), check_files=False)


if __name__ == "__main__":
    unittest.main()

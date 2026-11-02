"""Batch dossier writes are exercised only inside a disposable PostgreSQL schema."""
import copy
import importlib.util
import json
import os
from contextlib import ExitStack
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
        with database.connect(cls.schema) as conn:
            conn.execute("INSERT INTO seasons(code,name) VALUES('S22','isolated batch integration test')")
            conn.execute("INSERT INTO seasons(code,name) VALUES('S21','isolated archived-board test')")
            source = conn.execute(
                "INSERT INTO sources(platform,external_key,title) VALUES(%s,%s,%s) RETURNING id",
                (cls.audio["platform"], cls.audio["external_key"], "isolated test source from existing sample"),
            ).fetchone()
            if not cls.audio_path.is_file():
                conn.execute("INSERT INTO artifacts(source_id,kind,relative_path,sha256,byte_size,metadata) "
                             "VALUES(%s,'audio',%s,%s,0,jsonb_build_object('ingested_from',%s::text))",
                             (source["id"], cls.audio["path"], "f" * 64, cls.audio["path"]))

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

    def record_with_unique_audio_source(self):
        value = self.record()
        external_key = "batch-test-audio-" + uuid.uuid4().hex
        value["files"][0]["external_key"] = external_key
        with database.connect(self.schema) as conn:
            conn.execute("INSERT INTO sources(platform,external_key,title) VALUES(%s,%s,%s)",
                         (value["files"][0]["platform"], external_key, "isolated missing audio test source"))
        return value

    def register_audio_artifact(self, value, digest=None, path=None):
        file = next(file for file in value["files"] if file["role"] == "audio")
        digest = digest or "f" * 64
        path = path or file["path"]
        with database.connect(self.schema) as conn:
            source = conn.execute("SELECT id FROM sources WHERE platform=%s AND external_key=%s",
                                  (file["platform"], file["external_key"])).fetchone()
            self.assertIsNotNone(source)
            row = conn.execute("INSERT INTO artifacts(source_id,kind,relative_path,sha256,byte_size,metadata) "
                               "VALUES(%s,'audio',%s,%s,0,jsonb_build_object('ingested_from',%s::text)) "
                               "ON CONFLICT(source_id,kind,sha256) DO NOTHING RETURNING id",
                               (source["id"], path, digest, path)).fetchone()
            if row is None:
                row = conn.execute("SELECT id FROM artifacts WHERE source_id=%s AND kind='audio' AND sha256=%s",
                                   (source["id"], digest)).fetchone()
            return str(row["id"])

    def with_missing_paths(self, paths):
        real_is_file = Path.is_file
        real_exists = Path.exists
        missing = {Path(path).resolve() for path in paths}

        def is_file(path):
            if path.resolve() in missing:
                return False
            return real_is_file(path)

        def exists(path):
            if path.resolve() in missing:
                return False
            return real_exists(path)

        stack = ExitStack()
        stack.enter_context(patch.object(Path, "is_file", is_file))
        stack.enter_context(patch.object(Path, "exists", exists))
        return stack

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
        # S22 entertainment is excluded by user policy; generic historical-board
        # storage remains supported for another season in this disposable schema.
        value["season"] = "S21"
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

    def test_text_only_source_is_stable_when_same_video_audio_is_added(self):
        for role in ("subtitle", "transcript"):
            with self.subTest(role=role):
                value = self.incomplete_record()
                value["files"] = [copy.deepcopy(next(f for f in self.sample["files"] if f["role"] == role))]
                first = import_game(copy.deepcopy(value), allow_incomplete=True)
                again = import_game(copy.deepcopy(value), allow_incomplete=True)
                self.assertEqual(first["game_id"], again["game_id"])
                with database.connect(self.schema) as conn:
                    files = conn.execute("SELECT file_role FROM game_files WHERE game_id=%s", (first["game_id"],)).fetchall()
                    before = conn.execute("SELECT primary_source_id FROM games WHERE id=%s", (first["game_id"],)).fetchone()
                self.assertEqual([row["file_role"] for row in files], [role])
                value["files"].append(copy.deepcopy(self.audio))
                self.register_audio_artifact(value)
                with_audio = import_game(value, allow_incomplete=True)
                self.assertEqual(first["game_id"], with_audio["game_id"])
                with database.connect(self.schema) as conn:
                    after = conn.execute("SELECT primary_source_id FROM games WHERE id=%s", (first["game_id"],)).fetchone()
                self.assertEqual(before, after)

    def test_other_video_cannot_replace_a_text_only_primary_source(self):
        value = self.incomplete_record()
        value["files"] = [copy.deepcopy(next(f for f in self.sample["files"] if f["role"] == "subtitle"))]
        import_game(copy.deepcopy(value), allow_incomplete=True)
        before = self.game_snapshot(value["slug"])
        value["files"][0]["external_key"] = "synthetic-other-video-" + uuid.uuid4().hex
        with database.connect(self.schema) as conn:
            conn.execute("INSERT INTO sources(platform,external_key,title) VALUES('bilibili',%s,'synthetic only')",
                         (value["files"][0]["external_key"],))
        with self.assertRaisesRegex(ReviewError, "其他赛季或源文件"):
            import_game(value, allow_incomplete=True)
        self.assertEqual(self.game_snapshot(value["slug"]), before)

    def test_missing_audio_reuses_only_the_registered_source_artifact(self):
        for matched_by in ("relative_path", "ingested_from"):
            with self.subTest(matched_by=matched_by):
                value = self.record_with_unique_audio_source()
                expected_artifact_id = self.register_audio_artifact(value)
                with database.connect(self.schema) as conn:
                    if matched_by == "relative_path":
                        conn.execute("UPDATE artifacts SET metadata='{}'::jsonb WHERE id=%s",
                                     (expected_artifact_id,))
                    else:
                        conn.execute("UPDATE artifacts SET relative_path='data/archive/other-audio.m4a' WHERE id=%s",
                                     (expected_artifact_id,))

                with self.with_missing_paths([self.audio_path]):
                    first = import_game(copy.deepcopy(value), allow_incomplete=True)
                before = self.game_snapshot(value["slug"])
                artifact_id = before["files"][0]["artifact_id"]

                with database.connect(self.schema) as conn, self.with_missing_paths([self.audio_path]):
                    with patch.object(game_records, "connect", side_effect=AssertionError("conn must be reused")):
                        replacement = import_game(copy.deepcopy(value), allow_incomplete=True, conn=conn)
                after = self.game_snapshot(value["slug"])

                self.assertEqual(first["game_id"], replacement["game_id"])
                self.assertEqual(len(after["files"]), 1)
                self.assertEqual(after["files"][0]["file_role"], "audio")
                self.assertEqual(after["files"][0]["artifact_id"], artifact_id)
                self.assertEqual(str(artifact_id), expected_artifact_id)

    def test_missing_audio_without_registered_artifact_is_rejected(self):
        value = self.record_with_unique_audio_source()

        with self.with_missing_paths([self.audio_path]):
            with self.assertRaisesRegex(ReviewError, "缺失.*audio.*artifact"):
                import_game(value, allow_incomplete=True)

        with database.connect(self.schema) as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM artifacts a JOIN sources s ON s.id=a.source_id "
                                          "WHERE s.external_key=%s AND a.kind='audio'",
                                          (value["files"][0]["external_key"],)).fetchone()["n"], 0)
            self.assertIsNone(conn.execute("SELECT id FROM games WHERE slug=%s", (value["slug"],)).fetchone())

    def test_missing_audio_with_ambiguous_registered_artifacts_is_rejected(self):
        value = self.record_with_unique_audio_source()
        self.register_audio_artifact(value, "a" * 64)
        with self.with_missing_paths([self.audio_path]):
            import_game(copy.deepcopy(value), allow_incomplete=True)
        before = self.game_snapshot(value["slug"])
        with database.connect(self.schema) as conn:
            source = conn.execute("SELECT id FROM sources WHERE platform=%s AND external_key=%s",
                                  (value["files"][0]["platform"], value["files"][0]["external_key"])).fetchone()
            conn.execute("INSERT INTO artifacts(source_id,kind,relative_path,sha256,byte_size) "
                         "VALUES(%s,'audio',%s,%s,0)",
                         (source["id"], value["files"][0]["path"], "b" * 64))

        with self.with_missing_paths([self.audio_path]):
            with self.assertRaisesRegex(ReviewError, "ambiguous|歧义|多个"):
                import_game(copy.deepcopy(value), allow_incomplete=True)

        self.assertEqual(self.game_snapshot(value["slug"]), before)

    def test_missing_non_audio_source_remains_strict_with_registered_audio(self):
        value = self.record_with_unique_audio_source()
        self.register_audio_artifact(value)
        with self.with_missing_paths([self.audio_path]):
            import_game(copy.deepcopy(value), allow_incomplete=True)
        before = self.game_snapshot(value["slug"])
        transcript = copy.deepcopy(next(f for f in self.sample["files"] if f["role"] == "transcript"))
        transcript["external_key"] = value["files"][0]["external_key"]
        value["files"].append(transcript)
        transcript_path = ROOT / transcript["path"]

        with self.with_missing_paths([self.audio_path, transcript_path]):
            with self.assertRaisesRegex(ReviewError, "源文件必须位于data目录"):
                import_game(copy.deepcopy(value), allow_incomplete=True)

        self.assertEqual(self.game_snapshot(value["slug"]), before)

    def test_validate_keeps_default_strict_file_check_for_missing_audio(self):
        value = self.record()

        with self.with_missing_paths([self.audio_path]):
            with self.assertRaisesRegex(ReviewError, "源文件必须位于data目录"):
                validate(copy.deepcopy(value), check_files=True)

    def test_puppet_skill_effect_actions_keep_their_single_target(self):
        value = json.loads(
            (ROOT / "data/games/S22/2026-07-08_g02_BV1KuMG6NEez/dossier.json").read_text(encoding="utf-8")
        )
        for action, target in (("reverse_check", 8), ("skill_disabled", 6)):
            with self.subTest(action=action):
                candidate = copy.deepcopy(value)
                puppet_select = next(event for round_ in candidate["rounds"] for event in round_["night"]
                                     if round_["number"] == 1 and event["slot"] == "puppet_select")
                if action == "skill_disabled":
                    puppet_select["targets"] = [target]
                    candidate["seats"][target - 1]["faction"] = "werewolf"
                    candidate["seats"][7]["faction"] = "good"
                else:
                    candidate["seats"][target - 1]["faction"] = "werewolf"
                event = next(event for round_ in candidate["rounds"] for event in round_["night"]
                             if round_["number"] == 2 and event["slot"] == "puppet_skill_effect")
                event.update(action=action, targets=[target])
                game_records.validate_batch(candidate, check_files=False, check_rules=False)

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
        value = copy.deepcopy(self.sample)
        value["files"] = [copy.deepcopy(next(f for f in self.sample["files"] if f["role"] == "transcript"))]
        board = validate(value, check_files=True)
        self.assertEqual(board["code"], self.sample["board"])
        with self.assertRaises(ReviewError):
            validate(self.incomplete_record(), check_files=False)


if __name__ == "__main__":
    unittest.main()

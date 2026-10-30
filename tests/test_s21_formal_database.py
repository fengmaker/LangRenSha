"""Exercise a reviewed S21 game's complete import in an isolated database schema."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from board_config import template_path
from psycopg import sql
import database
import endgame_records
import game_records
import import_s21_formal as formal


@unittest.skipUnless((ROOT / ".secrets/database.json").is_file() or os.environ.get("DATABASE_URL"),
                     "需要本机 PostgreSQL 配置")
class S21FormalDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "jcms_s21_formal_test_" + uuid.uuid4().hex
        database.migrate(cls.schema)
        cls.item = formal.build_selected(bvids=["BV1juPwzfEj5"])[0]

    @classmethod
    def tearDownClass(cls):
        assert cls.schema.startswith("jcms_s21_formal_test_")
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def snapshot(self):
        with database.connect(self.schema) as conn:
            game = conn.execute("SELECT id FROM games WHERE slug=%s", (self.item["slug"],)).fetchone()
            return {
                "game": conn.execute("SELECT * FROM game_details WHERE game_id=%s", (game["id"],)).fetchone(),
                "events": conn.execute("SELECT * FROM game_event_records WHERE game_id=%s ORDER BY id", (game["id"],)).fetchall(),
                "votes": conn.execute("SELECT c.* FROM game_ballot_choices c JOIN game_ballots b ON b.id=c.ballot_id WHERE b.game_id=%s ORDER BY c.ballot_id,c.voter_seat", (game["id"],)).fetchall(),
            }

    def test_reviewed_game_votes_and_endgame_import_atomically_without_audio(self):
        item = copy.deepcopy(self.item)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            root = Path(folder)
            for file in item["dossier"]["files"]:
                destination = root / file["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / file["path"], destination)
            templates = root / "config/board_templates"
            templates.mkdir(parents=True)
            board = item["dossier"]["board"]
            source_template = template_path(board, ROOT)
            shutil.copyfile(source_template, templates / source_template.name)
            shutil.copyfile(ROOT / "config/game_rules.json", root / "config/game_rules.json")

            def run(payload):
                conn = database.connect(self.schema)
                with patch.object(database, "ROOT", root), patch.object(game_records, "ROOT", root), \
                        patch.object(database, "connect", return_value=conn):
                    return formal.import_batch([payload])

            first = run(item)
            self.assertEqual(first["games"], 1)
            with database.connect(self.schema) as conn:
                before_counts = {name: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(name))).fetchone()["n"]
                                 for name in ("games", "game_seats", "game_event_records", "game_ballots", "game_ballot_choices", "game_formal_annotations")}
                self.assertEqual(conn.execute("SELECT count(*) AS n FROM game_files WHERE file_role='audio'").fetchone()["n"], 0)
                derived = conn.execute("SELECT payload FROM game_formal_annotations WHERE annotation_key='shared-rule-derivations'").fetchone()
                self.assertIsNotNone(derived)
                self.assertEqual(derived["payload"], item["rule_derivations"])
            run(copy.deepcopy(item))
            with database.connect(self.schema) as conn:
                after_counts = {name: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(name))).fetchone()["n"]
                                for name in before_counts}
                self.assertEqual(before_counts, after_counts)
                self.assertEqual(conn.execute("SELECT count(*) AS n FROM seasons WHERE code='S21'").fetchone()["n"], 1)
            before = self.snapshot()
            replacement = copy.deepcopy(item)
            replacement["dossier"]["winner"] = "werewolf" if item["dossier"]["winner"] != "werewolf" else "good"
            with patch.object(endgame_records, "import_endgame", side_effect=RuntimeError("endgame import failed")):
                with self.assertRaisesRegex(RuntimeError, "endgame import failed"):
                    run(replacement)
            self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()

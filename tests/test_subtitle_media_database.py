"""Register and import subtitle-only media inside a disposable schema and folder."""
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
from psycopg import sql
import database
import game_records
import media_ingest
from raw_media_fixture import make_subtitle_media


@unittest.skipUnless((ROOT / ".secrets/database.json").is_file() or os.environ.get("DATABASE_URL"),
                     "需要本机 PostgreSQL 配置")
class SubtitleMediaDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "jcms_subtitle_test_" + uuid.uuid4().hex
        database.migrate(cls.schema)
        with database.connect(cls.schema) as conn:
            conn.execute("INSERT INTO seasons(code,name) VALUES('S22','synthetic subtitle test')")

    @classmethod
    def tearDownClass(cls):
        assert cls.schema.startswith("jcms_subtitle_test_")
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def test_subtitle_registration_and_formal_import_need_no_audio(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            root = Path(folder)
            manifest_path = make_subtitle_media(root / "data/raw/bilibili/BV1tj8p6REqy/p01")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            conn = database.connect(self.schema)
            with patch.object(database, "ROOT", root), patch.object(media_ingest, "ROOT", root), \
                    patch.object(database, "connect", return_value=conn):
                registered = database.import_media(manifest_path)

            sample = json.loads((ROOT / "data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json").read_text(encoding="utf-8"))
            value = copy.deepcopy(sample)
            value.update(slug="subtitle-only-" + uuid.uuid4().hex, rounds=[], roster=[],
                         commentators=[], referee=None, winner=None, game_number=None)
            for seat in value["seats"]:
                seat.update(name=None, role=None, faction=None, learning_target=None, learned_role=None)
            subtitle = manifest_path.parent / manifest["subtitles"]["tracks"][0]["file"]
            value["files"] = [{"role": "subtitle", "kind": "subtitle", "platform": "bilibili",
                               "external_key": f"{manifest['bvid']}:{manifest['cid']}",
                               "path": subtitle.relative_to(root).as_posix()}]
            templates = root / "config/board_templates"
            templates.mkdir(parents=True)
            shutil.copyfile(ROOT / f"config/board_templates/{value['board']}.json", templates / f"{value['board']}.json")
            shutil.copyfile(ROOT / "config/game_rules.json", root / "config/game_rules.json")

            with database.connect(self.schema) as conn:
                kinds = {row["kind"] for row in conn.execute("SELECT kind FROM artifacts").fetchall()}
                self.assertEqual(kinds, {"manifest", "metadata", "subtitle"})
                with patch.object(database, "ROOT", root), patch.object(game_records, "ROOT", root):
                    first = game_records.import_game(copy.deepcopy(value), allow_incomplete=True, conn=conn)
                    again = game_records.import_game(copy.deepcopy(value), allow_incomplete=True, conn=conn)
                self.assertEqual(first["game_id"], again["game_id"])
                actual = conn.execute("SELECT primary_source_id FROM games WHERE id=%s", (first["game_id"],)).fetchone()
                self.assertEqual(str(actual["primary_source_id"]), registered["source_id"])
                files = conn.execute("SELECT file_role FROM game_files WHERE game_id=%s", (first["game_id"],)).fetchall()
                self.assertEqual([row["file_role"] for row in files], ["subtitle"])
            self.assertFalse((manifest_path.parent / "audio.m4a").exists())


if __name__ == "__main__":
    unittest.main()

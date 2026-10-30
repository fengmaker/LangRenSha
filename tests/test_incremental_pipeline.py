"""Exercise real new-game contracts across analysis, manual export and formalization."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_incremental as analyze
import apply_incremental_review as application
import capture_bilibili_frame
import database
import game_records
import media_ingest
import voting_records
from incremental_common import entry_key, load_state, save_state, write_json
from incremental_scope import approved_incremental_count
from raw_media_fixture import make_subtitle_media


class IncrementalPipelineTests(unittest.TestCase):
    def test_subtitle_to_ai_to_notes_acceptance_preserves_formal_database_contract(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "config", root / "config")
            manifest = make_subtitle_media(root / "data/raw/bilibili/BV1tj8p6REqy/p01")
            source = manifest.parent / "subtitle.01.raw.json"
            entry = {"bvid": "BV1tj8p6REqy", "cid": 123456, "page": 1,
                     "duration_seconds": 1, "title": "合成对局，不是真实比赛", "labels": {
                         "season": "S23", "event_date_candidate": "2026-10-27",
                         "phase_candidate": "regular", "game_number_candidate": 1,
                         "issue_candidate": 7, "board_candidate": "预女猎白混"}}
            state = load_state(root, "S23")
            state["items"][entry_key(entry)] = {"entry": entry, "scope": "in_scope",
                    "acquisition": "ready", "analysis": "pending", "applied": False}
            save_state(root, "S23", state)
            write_json(root / "data/reports/S23/S23_逐局复核计划.json", {"entries": []})

            def ai_result(prompt, output, **kwargs):
                if output.name.startswith("frame_plan"):
                    return {"frame_times_seconds": [0], "notes": ["合成截图"]}
                value = analyze.skeleton(entry, source, root=root)
                value["evidence"] = [{"kind": "text", "field": "dossier.rounds",
                    "source_path": source.relative_to(root).as_posix(),
                    "start_ms": 0, "end_ms": 1000, "quote": "合成中文测试字幕"}]
                return value

            def capture(bvid, cid, seconds, folder, *args):
                folder.mkdir(parents=True, exist_ok=True)
                for second in seconds:
                    # AI invocation is mocked; the fixture is never treated as a real image.
                    (folder / f"{bvid}_{second:09.3f}.png").write_bytes(b"synthetic frame")

            with patch.object(media_ingest, "ROOT", root), patch.object(game_records, "ROOT", root), \
                    patch.object(analyze, "run_json", side_effect=ai_result) as ai, \
                    patch.object(capture_bilibili_frame, "capture", side_effect=capture), \
                    patch.object(analyze.subprocess, "run", side_effect=AssertionError("中文字幕不能跑ASR")):
                result = analyze.run(root=root)
                self.assertEqual(result["analyzed"], 1)
                self.assertFalse(result["failures"])
                self.assertTrue(Path(result["review_page"]).is_file())
                self.assertEqual(ai.call_count, 2)
                again = analyze.run(root=root)
                self.assertEqual(again["analyzed"], 1)
                self.assertEqual(ai.call_count, 2, "已分析候选不可重复调用AI")

            state = load_state(root, "S23")
            item = state["items"][entry_key(entry)]
            review = root / "data/reports/S23/incremental/manual.json"
            write_json(review, {"format": application.REVIEW_FORMAT, "season": "S23", "games": [{
                "review_id": entry_key(entry), "bvid": entry["bvid"], "cid": entry["cid"], "page": 1,
                "candidate_sha256": item["candidate_sha256"], "source_sha256": item["source_sha256"],
                "reviewed": True, "note": ""}]})
            connection = object()
            with patch.object(media_ingest, "ROOT", root), patch.object(game_records, "ROOT", root), \
                    patch.object(database, "import_media", return_value={"registered": True}), \
                    patch.object(database, "connect", return_value=nullcontext(connection)), \
                    patch.object(game_records, "import_game", return_value={"game": "fixture"}) as game_import, \
                    patch.object(voting_records, "import_voting", return_value={"votes": 0}) as vote_import:
                prepared = application.apply_review(review, root=root, run_ai=False)
                self.assertEqual(prepared["reviewed_games"], 1)
                self.assertFalse((root / "data/games").exists())
                applied = application.apply_review(review, root=root, apply=True, backup=False, run_ai=False)
                self.assertEqual(applied["state"], "completed")
                folders = list((root / "data/games/S23").glob("*/dossier.json"))
                self.assertEqual(len(folders), 1)
                dossier = json.loads(folders[0].read_text(encoding="utf-8"))
                voting = json.loads((folders[0].parent / "voting.json").read_text(encoding="utf-8"))
                self.assertEqual(game_import.call_args.args[0], dossier)
                self.assertEqual(vote_import.call_args.args[0], voting)
                self.assertIs(game_import.call_args.kwargs["conn"], connection)
                self.assertIs(vote_import.call_args.kwargs["conn"], connection)
                self.assertEqual(approved_incremental_count(root, "S23"), 1)
                # A synthetic zero-game historical baseline plus this approved
                # addition must pass the real publication loader's count guard.
                registry_path = root / "config/seasons.json"
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
                registry["seasons"]["S23"]["formal_import"]["scope"]["scored_total"] = 0
                registry["seasons"]["S23"]["scope"]["expected_games"] = 0
                write_json(registry_path, registry)
                from website.api import publisher
                entries, _, _ = publisher.load_publication(root, "S23")
                self.assertEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()

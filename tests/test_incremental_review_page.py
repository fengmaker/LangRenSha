from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from incremental_review_page import render_review_page


def game(*, bvid="BV-test", cid="cid-1", page=2, title="测试局", candidate_hash="candidate-v1", source_hash="source-v1"):
    return {
        "entry": {
            "bvid": bvid, "cid": cid, "page": page, "title": title,
            "source_sha256": source_hash,
            "labels": {"event_date_candidate": "2026-10-30", "game_number_candidate": 3},
        },
        "candidate_sha256": candidate_hash,
        "source_sha256": source_hash,
        "candidate": {
            "dossier": {
                "board": "mixed_blood", "winner": "good",
                "seats": [
                    {"seat": 1, "name": '小明 <img src=x onerror="alert(1)">', "role": "平民", "faction": "good"},
                    {"seat": 2, "name": None, "role": None, "faction": None},
                ],
                "rounds": [{
                    "number": 1,
                    "night": [{"slot": "wolf_attack", "action": "attack", "actor": 1, "targets": [2],
                               "result": None, "votes": [{"voter": 1, "target": 2}], "start_seat": None,
                               "direction": "clockwise", "random_point": None, "speech_scope": None,
                               "availability": None, "effects": []}],
                    "day": [{"slot": "exile_result", "action": "unknown", "actor": None, "targets": [],
                             "result": "未知", "effects": ["保留候选记录"]}],
                }],
            },
            "voting": {
                "schema_version": 1,
                "registrations": [{"day": 1, "on_police": [1], "off_police": [2]}],
                "ballots": [{"id": "b1", "day": 1, "kind": "exile", "number": 1, "stage": "initial",
                             "status": "complete", "candidates": None, "eligible_voters": [1, 2],
                             "votes": [{"voter": 1, "target": 2, "state": "cast"},
                                       {"voter": 2, "target": None, "state": "abstained"}],
                             "tied_candidates": [], "winner": 2, "unrecorded_voters": []}],
                "interruptions": [], "days": [{"day": 1, "sheriff": "recorded", "exile": "unknown"}],
            },
            "evidence": [
                {"kind": "video_frame", "source_path": "assets/frame & one.png", "start_ms": 13500,
                 "end_ms": 16000, "quote": '证据文字 <script>alert("x")</script>', "note": "画面座位", "sha256": "abc"},
                {"kind": "subtitle", "source_path": "assets/line.txt", "start_ms": 2010,
                 "quote": "这句字幕", "note": "本地文字来源"},
                {"kind": "untrusted", "source_path": "../outside.txt", "quote": "路径越界"},
                {"kind": "external", "source_path": "https://example.com/evidence?x=1&y=2", "quote": "安全链接"},
                {"kind": "unsafe", "source_path": "javascript:alert(1)", "quote": "协议不安全"},
            ],
            "issues": ["候选问题文本"],
        },
    }


class IncrementalReviewPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        (self.root / "assets").mkdir()
        (self.root / "assets" / "frame & one.png").write_bytes(b"fake image")
        (self.root / "assets" / "line.txt").write_text("本地字幕证据", encoding="utf-8")
        (self.root.parent / "outside.txt").write_text("outside root", encoding="utf-8")

    def tearDown(self):
        (self.root.parent / "outside.txt").unlink(missing_ok=True)
        self.temp.cleanup()

    def render(self, games):
        output = self.root / "offline" / "review.html"
        result = render_review_page(games, output, season="S23", root=self.root)
        return output.read_text(encoding="utf-8"), result

    def test_renders_read_only_candidate_actions_votes_and_unknown_values(self):
        page, result = self.render([game()])
        self.assertEqual(result["review_ids"], ["BV-test:cid-1:p02"])
        self.assertIn("AI 候选座位与物理身份", page)
        self.assertIn("物理身份", page)
        self.assertIn("狼人袭击", page)
        self.assertNotIn("wolf_attack", page)
        self.assertNotIn("effects", page)
        self.assertIn("保留候选记录", page)
        self.assertIn("第一天白天", page)
        self.assertIn("1号位（小明", page)
        self.assertIn("2号位（未知）", page)
        self.assertIn("未知", page)
        self.assertIn("弃票", page)
        self.assertIn("没有更改任何本机复核记录", page)
        self.assertNotIn("snapshot_id", page)
        self.assertIn('data-reviewed', page)
        self.assertIn('data-note', page)
        # The page has one note and one reviewed checkbox per game, with only global import/export controls.
        self.assertEqual(page.count("<textarea "), 1)
        self.assertEqual(page.count('type="checkbox"'), 1)
        self.assertIn('id="export"', page)
        self.assertIn('id="import-file"', page)

    def test_escapes_text_json_and_urls_and_keeps_local_evidence_under_root(self):
        hostile = game(title='标题 </script><script>alert("title")</script> &')
        hostile["candidate_sha256"] = 'v1</script><script>alert("hash")</script>'
        page, _ = self.render([hostile])
        self.assertIn("&lt;script&gt;alert(&quot;title&quot;)&lt;/script&gt;", page)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", page)
        self.assertIn("证据文字 &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", page)
        self.assertNotIn('</script><script>alert("hash")', page)
        self.assertIn("\\u003c/script\\u003e", page)
        self.assertIn("../assets/frame%20%26%20one.png", page)
        self.assertIn("../assets/line.txt", page)
        self.assertNotIn("outside.txt", page)
        self.assertNotIn("javascript:alert(1)", page)
        self.assertIn("https://example.com/evidence?x=1&amp;y=2", page)
        self.assertIn("video/BV-test?p=2&amp;t=13", page)
        self.assertIn("来源与证据编号", page)

    def test_evidence_images_are_inline_and_timestamp_uses_actual_page(self):
        page, _ = self.render([game()])
        self.assertIn('<img loading=lazy src="../assets/frame%20%26%20one.png"', page)
        self.assertIn('href="https://www.bilibili.com/video/BV-test?p=2&amp;t=13"', page)
        self.assertIn("本地文字来源", page)

    def test_all_vote_rows_and_unknown_ballot_fields_render(self):
        page, _ = self.render([game()])
        self.assertEqual(page.count("已投票"), 1)
        self.assertEqual(page.count("弃票"), 1)
        self.assertIn("可投票位", page)
        self.assertIn("AI 候选未提供", page)  # e.g. empty interruptions stay visible as absent records

    def test_drafts_are_keyed_per_identity_and_both_versions_across_new_batches(self):
        first = game()
        page_a, result_a = self.render([first])
        page_b, result_b = self.render([first, game(bvid="BV-new", cid="cid-2", candidate_hash="candidate-v2")])
        self.assertEqual(result_a["review_ids"][0], result_b["review_ids"][0])
        key_expression = "encodeURIComponent(game.review_id)}:${game.candidate_sha256}:${game.source_sha256}"
        self.assertIn(key_expression, page_a)
        self.assertIn(key_expression, page_b)
        self.assertIn("localStorage.setItem(keyFor(game)", page_a)
        self.assertIn("localStorage.getItem(keyFor(game)", page_a)
        self.assertIn("masters-incremental-review-v1:${encodeURIComponent(data.season)}", page_a)
        self.assertNotIn("batch_hash", page_b)

    def test_export_import_contract_allows_subset_and_rejects_all_errors_without_partial_apply(self):
        page, _ = self.render([game(), game(bvid="BV-2", cid="cid-2")])
        expected_export_fields = ["review_id", "bvid", "cid", "page", "candidate_sha256", "source_sha256", "reviewed", "note"]
        for field in expected_export_fields:
            self.assertIn(f'"{field}"', page)
        self.assertIn('const format = "masters-incremental-review-v1"', page)
        self.assertIn("payload.season !== data.season", page)
        self.assertIn("包含未知游戏", page)
        self.assertIn("重复", page)
        self.assertIn("游戏身份不匹配", page)
        self.assertIn("候选或来源版本已变化", page)
        self.assertIn("if (errors.length)", page)
        self.assertIn("accepted.forEach(({ item, expected }) => localStorage.setItem", page)
        self.assertIn("未列出的游戏保持原样", page)

    def test_actual_page_script_autosaves_exports_and_validates_import_atomically(self):
        node = shutil.which("node")
        if not node:
            bundled = ROOT / ".tools" / "node"
            node_candidates = list(bundled.glob("node-*/node.exe")) if bundled.exists() else []
            node = str(node_candidates[0]) if node_candidates else None
        if not node:
            self.skipTest("Node.js executable is unavailable")
        solo = self.root / "offline" / "solo.html"
        expanded = self.root / "offline" / "expanded.html"
        render_review_page([game()], solo, season="S23", root=self.root)
        render_review_page([game(), game(bvid="BV-2", cid="cid-2", candidate_hash="candidate-v2")],
                           expanded, season="S23", root=self.root)
        checker = ROOT / "tests" / "check_incremental_review_page.mjs"
        result = subprocess.run([node, str(checker), str(solo), str(expanded)],
                                capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"autosave_survives_new_batch":true', result.stdout)
        self.assertIn('"subset_import":true', result.stdout)

    def test_duplicate_stable_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "review.html"
            with self.assertRaisesRegex(ValueError, "duplicate game identity"):
                render_review_page([game(), game()], out, root=self.root)

    def test_version_hashes_are_required_for_version_bound_drafts(self):
        item = game()
        item.pop("candidate_sha256")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "candidate_sha256 is required"):
                render_review_page([item], Path(temp) / "review.html", root=self.root)


if __name__ == "__main__":
    unittest.main()

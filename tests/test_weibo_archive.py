import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import collect_weibo_archive as archive
from collect_weibo import CollectionError, WeiboCollector, new_manifest, normalize_post, save_json
from weibo_naming import artifact_paths


def post(post_id, day, *, long=False, text="第22季 第一期阵容公布"):
    return {"idstr": str(post_id), "created_at": f"2026-{day}T15:33:00+08:00",
            "user": {"idstr": "7525583841", "screen_name": "京城大师赛"},
            "text": text, "isLongText": long}


def page(posts, cursor, more=True):
    return {"cards": [{"card_type": 9, "mblog": item} for item in posts],
            "cardlistInfo": {"since_id": cursor}, "has_more": more}


class FakeCollector:
    request_interval = 1.5

    def __init__(self, pages):
        self.pages = iter(pages)
        self.cursors = []
        self.long_calls = []
        self.saved = []

    def get_timeline_page(self, uid, cursor):
        self.cursors.append(cursor)
        value = next(self.pages)
        if isinstance(value, Exception):
            raise value
        return value

    def save_post(self, raw, normalized, root, download_images):
        self.saved.append(normalized["post_id"])
        save_json(root / normalized["raw_file"], raw)
        return normalized

    def get_long_text(self, post_id):
        self.long_calls.append(post_id)
        return {"ok": 1, "data": {"longTextContent": "完整阵容<br>法官：甲"}}


class WeiboArchiveTests(unittest.TestCase):
    def test_image_list_expansion_preserves_downloaded_prefix_and_saves_detail(self):
        raw = post("12345678", "09-22")
        raw.update(pic_num=2, pics=[{"large": {"url": "https://wx1.sinaimg.cn/mw2000/a.jpg"}}])
        normalized = normalize_post(raw)
        normalized["images"][0].update(status="downloaded", file="images/existing_a.jpg")
        detail = {**raw, "pic_ids": ["a", "b"], "pic_infos": {
            "a": {"original": {"url": "https://wx1.sinaimg.cn/large/a.jpg"}},
            "b": {"original": {"url": "https://wx1.sinaimg.cn/large/b.jpg"}},
        }}
        class DetailCollector:
            calls = 0
            def get_post_data(self, post_id):
                self.calls += 1
                return detail
        collector = DetailCollector()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive.complete_image_list(raw, normalized, root, collector)
            self.assertEqual(len(normalized["images"]), 2)
            self.assertEqual(normalized["images"][0]["file"], "images/existing_a.jpg")
            self.assertEqual(normalized["images"][0]["status"], "downloaded")
            self.assertEqual(normalized["images"][1]["status"], "not_downloaded")
            self.assertTrue((root / normalized["detail_file"]).is_file())
            archive.complete_image_list(raw, normalized, root, collector)
            self.assertEqual(collector.calls, 1)

    def test_rename_preserves_bytes_hashes_and_all_manifest_references(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = post("12345678", "09-22", long=True)
            normalized = normalize_post(raw)
            normalized.update(full_text_file="long_text/12345678.json", full_text_status="expanded")
            normalized["images"] = [{"status": "downloaded", "file": "images/12345678_1.jpg"}]
            save_json(root / normalized["raw_file"], raw)
            save_json(root / normalized["full_text_file"], {"ok": 1, "data": {"longTextContent": "全文"}})
            (root / "images").mkdir()
            (root / "images/12345678_1.jpg").write_bytes(b"image bytes")
            before = {key: archive.file_hash(root / normalized[key]) for key in ("raw_file", "full_text_file")}
            manifest = new_manifest("author", {})
            manifest["posts"] = [normalized]
            path = root / "manifest.json"
            save_json(path, manifest)
            result = archive.rename_manifest(path)
            self.assertEqual(result["renamed_files"], 3)
            updated = json.loads(path.read_text(encoding="utf-8"))["posts"][0]
            self.assertTrue(updated["raw_file"].startswith("posts/2026-09/2026-09-22_15-33-00_"))
            self.assertTrue(updated["images"][0]["file"].endswith("_图01.jpg"))
            self.assertEqual((root / updated["images"][0]["file"]).read_bytes(), b"image bytes")
            for key, digest in before.items():
                self.assertEqual(archive.file_hash(root / updated[key]), digest)
            self.assertEqual(archive.rename_manifest(path)["renamed_files"], 0)

    def test_seed_post_is_not_downloaded_again_and_long_text_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            seed_root, output = Path(folder) / "seed", Path(folder) / "archive"
            raw = post("12345678", "09-22", long=True)
            names = artifact_paths(raw)
            normalized = normalize_post(raw)
            normalized.update(raw_file=names["raw_file"], full_text_file=names["full_text_file"],
                              full_text_status="expanded", text="已有完整正文")
            save_json(seed_root / normalized["raw_file"], raw)
            save_json(seed_root / normalized["full_text_file"], {"ok": 1, "data": {"longTextContent": "已有完整正文"}})
            seed = new_manifest("author", {})
            seed["posts"] = [normalized]
            seed_path = seed_root / "manifest.json"
            save_json(seed_path, seed)
            collector = FakeCollector([page([raw], "next", more=False)])
            result = archive.collect_archive(collector, output, "7525583841", archive.date(2026, 5, 26),
                                             archive.date(2026, 10, 20), seed_path=seed_path)
            self.assertEqual(collector.saved, [])
            self.assertEqual(collector.long_calls, [])
            self.assertEqual(result["counts"]["seed_posts_reused"], 1)
            self.assertTrue((output / normalized["raw_file"]).is_file())

    def test_resume_uses_checkpoint_cursor_and_preserves_full_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = post("12345678", "06-01", long=True)
            first = FakeCollector([page([raw], "after-first"), CollectionError("网络失败", reason="network_error")])
            result = archive.collect_archive(first, root, "7525583841", archive.date(2026, 5, 26),
                                             archive.date(2026, 10, 20))
            self.assertEqual(result["counts"]["posts_saved"], 1)
            self.assertEqual(result["posts"][0]["full_text_status"], "expanded")
            second = FakeCollector([page([post("12345679", "05-26")], "end", more=False)])
            resumed = archive.collect_archive(second, root, "7525583841", archive.date(2026, 5, 26),
                                              archive.date(2026, 10, 20))
            self.assertEqual(second.cursors, ["after-first"])
            self.assertEqual(resumed["counts"]["posts_saved"], 2)
            self.assertEqual(resumed["window_scan_status"], "completed")
            self.assertEqual(second.long_calls, [])

    def test_old_pinned_page_is_confirmed_again_after_recent_page_resets_streak(self):
        old = lambda offset: [post(str(12000000 + offset + i), "05-20") for i in range(5)]
        pages = [page(old(0), "one"), page([post("13000000", "05-26")], "two"),
                 page(old(10), "three"), page(old(20), "four"), page(old(30), "five")]
        with tempfile.TemporaryDirectory() as folder:
            result = archive.collect_archive(FakeCollector(pages), Path(folder), "7525583841",
                                             archive.date(2026, 5, 26), archive.date(2026, 10, 20))
            self.assertEqual(result["counts"]["pages_fetched"], 5)
            self.assertEqual(result["counts"]["posts_saved"], 1)
            self.assertEqual(result["termination_reason"], "date_window_passed_3_pages")
            self.assertEqual(result["window_scan_status"], "completed")
            self.assertTrue((Path(folder) / result["pages"][-1]["raw_file"]).is_file())


if __name__ == "__main__":
    unittest.main()

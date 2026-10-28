import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collect_weibo", ROOT / "scripts" / "collect_weibo.py")
weibo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(weibo)


class FakeResponse:
    def __init__(self, payload=None, status=200, text=None, url="https://m.weibo.cn/api?token=DO_NOT_LOG",
                 chunks=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {}, ensure_ascii=False)
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        self.content = self.text.encode("utf-8")
        self.chunks = chunks
        self.chunks_read = 0
        self.closed = False

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def iter_content(self, chunk_size=64 * 1024):
        chunks = self.chunks if self.chunks is not None else [self.content]
        for chunk in chunks:
            self.chunks_read += 1
            yield chunk

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, pages=None, exact=None, image=None, long_text=None, post_data=None):
        self.headers = {}
        self.pages = pages or {}
        self.exact = exact
        self.image = image
        self.long_text = long_text
        self.post_data = post_data
        self.calls = []

    def get(self, url, params=None, timeout=None, allow_redirects=None, stream=False):
        self.calls.append((url, params, stream))
        if "/detail/" in url:
            return self.exact
        if "/statuses/extend" in url:
            return self.long_text
        if "/ajax/statuses/show" in url:
            return self.post_data
        if ".sinaimg.cn/" in url:
            return self.image
        page = len([call for call in self.calls if "/api/container/getIndex" in call[0]])
        item = self.pages[page]
        if isinstance(item, Exception):
            raise item
        return item


def mblog(post_id, uid="7525583841", created="Thu Sep 25 15:33:00 +0800 2025", text="阵容公告", repost=None):
    value = {
        "idstr": str(post_id),
        "created_at": created,
        "text": text,
        "user": {"idstr": str(uid), "screen_name": "京城大师赛"},
    }
    if repost is not None:
        value["retweeted_status"] = {
            "idstr": "991111", "user": {"idstr": str(repost), "screen_name": "原作者"},
            "text": "转发来源正文",
        }
    return value


def page(statuses, has_more, next_cursor=None):
    cards = [{"card_type": 9, "mblog": item} for item in statuses]
    data = {"cards": cards, "has_more": has_more}
    if next_cursor is not None:
        data["cardlistInfo"] = {"since_id": next_cursor}
    return FakeResponse({"ok": 1, "data": data})


class WeiboParsingTests(unittest.TestCase):
    def test_known_weibo_id_and_supported_urls_are_parsed(self):
        self.assertEqual(weibo.parse_post_id("Q6cG6kgmH"), "Q6cG6kgmH")
        self.assertEqual(weibo.parse_post_id("https://www.weibo.com/7525583841/Q6cG6kgmH"), "Q6cG6kgmH")
        self.assertEqual(weibo.parse_post_id("https://weibo.com/2/detail/5334011972420022"), "5334011972420022")
        with self.assertRaises(weibo.CollectionError):
            weibo.parse_post_id("https://example.invalid/12345678")

    def test_detail_renderer_extracts_post_without_touching_network(self):
        source = '<script>var $render_data = [{"status":{"idstr":"Q6cG6kgmH","text":"阵容"}}][0]</script>'
        self.assertEqual(weibo.parse_detail_html(source)["idstr"], "Q6cG6kgmH")
        self.assertIsNone(weibo.parse_detail_html("登录后可见"))

    def test_date_parser_handles_weibo_time_format(self):
        self.assertEqual(weibo.post_date("Thu Sep 25 15:33:00 +0800 2025"), date(2025, 9, 25))
        self.assertEqual(weibo.post_date("2026-05-25T16:30:00Z"), date(2026, 5, 26))
        self.assertEqual(weibo.post_date("2026-06-01T00:30:00+14:00"), date(2026, 5, 31))
        self.assertIsNone(weibo.post_date("刚刚"))


class WeiboLongTextTests(unittest.TestCase):
    def test_full_image_detail_uses_explicit_picture_order(self):
        payload = {"idstr": "12345678", "pic_ids": ["a", "b"], "pic_infos": {
            "b": {"original": {"url": "https://wx1.sinaimg.cn/large/b.jpg"}},
            "a": {"original": {"url": "https://wx1.sinaimg.cn/large/a.jpg"}},
        }}
        collector = weibo.WeiboCollector(session=FakeSession(post_data=FakeResponse(payload)))
        result = collector.get_post_data("12345678")
        self.assertEqual(weibo.image_urls(result), ["https://wx1.sinaimg.cn/large/a.jpg", "https://wx1.sinaimg.cn/large/b.jpg"])

    def test_existing_valid_images_are_not_requested_again_when_supplementing(self):
        import hashlib
        raw = mblog("12345678")
        detail = {**raw, "pic_ids": ["a", "b"], "pic_infos": {
            "a": {"original": {"url": "https://wx1.sinaimg.cn/large/a.jpg"}},
            "b": {"original": {"url": "https://wx1.sinaimg.cn/large/b.jpg"}},
        }}
        normalized = weibo.normalize_post(detail)
        image_response = FakeResponse({}, chunks=[b"newimage"])
        image_response.headers["Content-Type"] = "image/jpeg"
        session = FakeSession(image=image_response)
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "images").mkdir()
            (root / "images/existing.jpg").write_bytes(b"existing")
            normalized["images"][0].update(status="downloaded", file="images/existing.jpg", size_bytes=8,
                                           sha256=hashlib.sha256(b"existing").hexdigest())
            collector.save_post(raw, normalized, root, True, image_source=detail)
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(session.calls[0][0].endswith("/b.jpg"))
            self.assertEqual((root / "images/existing.jpg").read_bytes(), b"existing")
            self.assertEqual(normalized["images"][1]["status"], "downloaded")

    def test_extend_response_is_preserved_and_login_wall_stops(self):
        payload = {"ok": 1, "data": {"longTextContent": "完整排班<br>法官：甲"}}
        session = FakeSession(long_text=FakeResponse(payload))
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        self.assertEqual(collector.get_long_text("12345678"), payload)
        self.assertEqual(session.calls[0][1], {"id": "12345678"})
        session.long_text = FakeResponse({"ok": 0, "msg": "请先登录"})
        with self.assertRaises(weibo.CollectionError) as caught:
            collector.get_long_text("12345678")
        self.assertEqual(caught.exception.state, "login_required")
        self.assertNotIn("DO_NOT_LOG", str(caught.exception))

    def make_manifest(self, folder, ids):
        run = Path(folder)
        posts = []
        for post_id in ids:
            raw = mblog(post_id, text="阵容 ... 全文")
            raw["isLongText"] = True
            normalized = weibo.normalize_post(raw)
            weibo.save_json(run / normalized["raw_file"], raw)
            posts.append(normalized)
        manifest = weibo.new_manifest("author", {"keywords": ["法官"]})
        manifest["posts"] = posts
        path = run / "manifest.json"
        weibo.save_json(path, manifest)
        return path

    def test_expansion_keeps_list_source_and_reuses_full_text_response(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_manifest(folder, ["12345678"])
            collector = mock.Mock()
            payload = {"ok": 1, "data": {"longTextContent": "完整阵容<br>法官：甲"}}
            collector.get_long_text.return_value = payload
            first = weibo.expand_manifest(path, collector)
            self.assertEqual(first["posts"][0]["text"], "完整阵容 \n 法官：甲")
            self.assertEqual(first["posts"][0]["matched_keywords"], ["法官"])
            raw = json.loads((path.parent / "posts/12345678.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["text"], "阵容 ... 全文")
            collector.get_long_text.reset_mock()
            second = weibo.expand_manifest(path, collector)
            collector.get_long_text.assert_not_called()
            self.assertEqual(second["long_text_expansion"]["cached_responses"], 1)
            self.assertEqual(second["posts"][0]["full_text_status"], "expanded")

    def test_expansion_without_keyword_request_does_not_add_keyword_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_manifest(folder, ["12345678"])
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["request"].pop("keywords")
            weibo.save_json(path, manifest)
            collector = mock.Mock()
            collector.get_long_text.return_value = {
                "ok": 1, "data": {"longTextContent": "完整正文"}}

            result = weibo.expand_manifest(path, collector)

        self.assertNotIn("matched_keywords", result["posts"][0])
        self.assertNotIn("keyword_candidate", result["posts"][0])

    def test_verification_failure_preserves_progress_and_stops_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_manifest(folder, ["12345678", "12345679", "12345680"])
            collector = mock.Mock()
            collector.get_long_text.side_effect = [
                {"ok": 1, "data": {"longTextContent": "完整正文"}},
                weibo.CollectionError("微博返回验证页面", "blocked", "rate_or_verification_wall"),
            ]
            result = weibo.expand_manifest(path, collector)
            self.assertEqual(collector.get_long_text.call_count, 2)
            self.assertEqual(result["long_text_expansion"]["expanded_posts"], 1)
            self.assertEqual(result["long_text_expansion"]["status"], "partial")
            self.assertEqual(result["posts"][0]["full_text_status"], "expanded")
            self.assertEqual(result["posts"][2]["full_text_status"], "pending")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["long_text_expansion"], result["long_text_expansion"])


class WeiboHistoryBoundaryTests(unittest.TestCase):
    def test_old_pinned_or_out_of_order_post_does_not_end_date_scan_early(self):
        pages = {
            1: page([
                mblog("11111111", created="Mon Jan 01 12:00:00 +0800 2024", text="置顶旧帖"),
                mblog("22222222", created="Thu Sep 25 15:33:00 +0800 2025", text="第19季阵容"),
            ], True, "cursor-page-2"),
            2: page([mblog("33333333", created="Sat Sep 20 10:00:00 +0800 2025", text="积分说明")], False),
        }
        session = FakeSession(pages)
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            result = collector.collect_author("7525583841", date(2025, 9, 1), date(2025, 9, 30),
                                              ["阵容", "积分"], 4, Path(folder))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["termination_reason"], "api_end_marker")
        self.assertEqual(result["counts"]["pages_fetched"], 2)
        self.assertEqual([item["post_id"] for item in result["posts"]], ["22222222", "33333333"])
        self.assertEqual(result["counts"]["keyword_candidates_saved"], 2)
        self.assertEqual(session.calls[1][1]["since_id"], "cursor-page-2")

    def test_non_target_posts_are_skipped_but_target_repost_keeps_target_author(self):
        target_repost = mblog("44444444", text="转发：阵容规则", repost="9999999999")
        other_author = mblog("55555555", uid="1111111111", text="无关活动")
        non_post_card = {"card_type": 8, "mblog": mblog("66666666")}
        session = FakeSession({1: FakeResponse({"ok": 1, "data": {
            "cards": [{"card_type": 9, "mblog": target_repost},
                      {"card_type": 9, "mblog": other_author}, non_post_card],
            "has_more": False,
        }})})
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            result = collector.collect_author("7525583841", date(2025, 9, 1), date(2025, 9, 30),
                                              ["阵容"], 3, Path(folder))
        self.assertEqual([item["post_id"] for item in result["posts"]], ["44444444"])
        self.assertTrue(result["posts"][0]["is_repost"])
        self.assertEqual(result["posts"][0]["author_uid"], "7525583841")
        self.assertEqual(result["posts"][0]["reposted_author_uid"], "9999999999")
        self.assertEqual(result["counts"]["non_target_posts_skipped"], 1)

    def test_login_response_is_login_required_and_does_not_echo_token_url(self):
        response = FakeResponse({"ok": 0, "msg": "请先登录"})
        session = FakeSession({1: response})
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with self.assertRaises(weibo.CollectionError) as caught:
            collector.get_timeline_page("7525583841", 1)
        self.assertEqual(caught.exception.state, "login_required")
        self.assertNotIn("DO_NOT_LOG", str(caught.exception))

    def test_page_cap_is_explicit_partial_boundary_even_with_more_pages(self):
        session = FakeSession({1: page([mblog("77777777")], True, "cursor-page-2")})
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            result = collector.collect_author("7525583841", date(2025, 9, 1), date(2025, 9, 30),
                                              [], 1, Path(folder))
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["termination_reason"], "max_pages_reached")
            self.assertEqual(result["counts"]["pages_fetched"], 1)
            self.assertTrue((Path(folder) / "posts" / "77777777.json").exists())
            self.assertTrue((Path(folder) / "manifest.json").exists())

    def test_empty_success_page_is_not_reported_as_no_history(self):
        session = FakeSession({1: page([], None)})
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            result = collector.collect_author("7525583841", date(2025, 9, 1), date(2025, 9, 30),
                                              [], 3, Path(folder))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["termination_reason"], "empty_page_without_end_marker")
        self.assertIn("均可能造成遗漏", result["coverage_note"])

    def test_exact_post_login_wall_is_reported_without_secret_url(self):
        response = FakeResponse(None, status=302, text="", url="https://m.weibo.cn/detail/Q6cG6kgmH")
        response.headers["Location"] = "https://passport.weibo.com/login?token=DO_NOT_LOG"
        collector = weibo.WeiboCollector(session=FakeSession(exact=response), sleep=lambda _: None)
        with self.assertRaises(weibo.CollectionError) as caught:
            collector.get_post("Q6cG6kgmH")
        self.assertEqual(caught.exception.state, "login_required")
        self.assertNotIn("DO_NOT_LOG", str(caught.exception))

    def test_optional_image_save_records_redacted_url_and_hash(self):
        source = {
            "idstr": "Q6cG6kgmH", "created_at": "Thu Sep 25 15:33:00 +0800 2025",
            "text": "阵容", "user": {"idstr": "7525583841", "screen_name": "京城大师赛"},
            "pics": [{"large": {"url": "https://wx1.sinaimg.cn/large/sample.jpg?token=IMAGE_TOKEN"}}],
        }
        body = '<script>var $render_data = [' + json.dumps({"status": source}, ensure_ascii=False) + '][0]</script>'
        detail = FakeResponse(None, text=body)
        image = FakeResponse({}, text="")
        image.content = b"sample-image-bytes"
        image.headers["Content-Type"] = "image/jpeg"
        session = FakeSession(exact=detail, image=image)
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            result = collector.collect_exact("Q6cG6kgmH", Path(folder), download_images=True)
            item = result["posts"][0]["images"][0]
            self.assertEqual(item["status"], "downloaded")
            self.assertEqual(item["sha256"], "14a815d7d433118e805214e0ae972c88b9a23288a0c4564e222fe5fe7ffcf608")
            self.assertNotIn("IMAGE_TOKEN", json.dumps(item))
            self.assertTrue((Path(folder) / item["file"]).exists())
            self.assertTrue(session.calls[-1][2])
            self.assertTrue(image.closed)

    def test_oversized_stream_without_content_length_stops_and_does_not_save(self):
        response = FakeResponse({}, text="", chunks=[b"a" * 24, b"b" * 9, b"must-not-be-read"])
        response.headers["Content-Type"] = "image/jpeg"
        session = FakeSession(image=response)
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(weibo, "MAX_IMAGE_BYTES", 32):
            collector.output_dir = Path(folder)
            target = Path(folder) / "images" / "oversized.jpg"
            result = collector.download_image("https://wx1.sinaimg.cn/large/oversized.jpg", target)
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "size_limit")
            self.assertEqual(response.chunks_read, 2)
            self.assertTrue(response.closed)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix(".jpg.part").exists())

    def test_content_length_over_limit_is_rejected_before_reading(self):
        response = FakeResponse({}, text="", chunks=[b"should-not-be-read"])
        response.headers["Content-Type"] = "image/jpeg"
        response.headers["Content-Length"] = "33"
        session = FakeSession(image=response)
        collector = weibo.WeiboCollector(session=session, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(weibo, "MAX_IMAGE_BYTES", 32):
            collector.output_dir = Path(folder)
            target = Path(folder) / "images" / "large.jpg"
            result = collector.download_image("https://wx1.sinaimg.cn/large/large.jpg", target)
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["declared_bytes"], 33)
            self.assertEqual(response.chunks_read, 0)
            self.assertTrue(response.closed)
            self.assertFalse(target.exists())

    def test_html_response_is_not_saved_as_an_image(self):
        response = FakeResponse({}, text="<html>please sign in</html>", chunks=[b"fake image bytes"])
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        collector = weibo.WeiboCollector(session=FakeSession(image=response), sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            collector.output_dir = Path(folder)
            target = Path(folder) / "images" / "fake.jpg"
            result = collector.download_image("https://wx1.sinaimg.cn/large/fake.jpg", target)
            self.assertEqual(result, {"status": "download_failed", "reason": "not_an_image"})
            self.assertEqual(response.chunks_read, 0)
            self.assertTrue(response.closed)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

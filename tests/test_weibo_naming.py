from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from weibo_naming import artifact_paths, post_stem


class WeiboNamingTests(unittest.TestCase):
    def test_weibo_timezone_is_normalized_to_beijing_across_day_boundary(self):
        stem = post_stem({
            "idstr": "5334011972420022",
            "created_at": "Wed May 27 00:10:11 +0800 2026",
            "text": "#京城大师赛# S22 第一期 积分说明",
        })
        self.assertTrue(stem.startswith("2026-05-27_00-10-11_S22_第01期_积分说明"))

        utc_stem = post_stem({
            "idstr": "5334011972420023",
            "created_at": "2026-05-26T16:10:11Z",
            "text": "积分说明",
        })
        self.assertTrue(utc_stem.startswith("2026-05-27_00-10-11_"))

    def test_issue_is_kept_without_guessing_a_season(self):
        stem = post_stem({
            "idstr": "5334011972420024",
            "created_at": "2026-05-26T11:00:00+08:00",
            "text": "#京城大师赛# 第二期 阵容公告",
        })
        self.assertIn("_赛季待核_第02期_", stem)
        self.assertNotIn("S22", stem)

    def test_longmen_category_is_not_mislabeled_as_masters(self):
        stem = post_stem({
            "idstr": "5334011972420025",
            "created_at": "2026-06-01T09:00:00+08:00",
            "text": "#京城大师赛##S22# 龙门赛报名公告",
        })
        self.assertIn("_龙门赛公告__WB", stem)
        self.assertNotIn("大师赛公告", stem)

    def test_specific_suspension_notice_outranks_a_longmen_mention(self):
        stem = post_stem({
            "idstr": "5334011972420033",
            "created_at": "2026-10-19T09:00:00+08:00",
            "text": "#京城大师赛#停播整顿公告：京城龙门赛相关安排另行通知。",
        })
        self.assertIn("停播整顿公告_涉及龙门赛", stem)
        self.assertNotIn("_龙门赛__", stem)

    def test_longmen_posts_keep_roster_result_and_notice_categories_distinct(self):
        common = {
            "created_at": "2026-10-19T10:00:00+08:00",
        }
        roster = post_stem({**common, "idstr": "5334011972420034", "text": "京城龙门赛选手阵容公布"})
        result = post_stem({**common, "idstr": "5334011972420035", "text": "京城龙门赛今日赛果"})
        notice = post_stem({**common, "idstr": "5334011972420036", "text": "京城龙门赛报名公告"})
        self.assertIn("_龙门赛阵容__WB", roster)
        self.assertIn("_龙门赛赛果__WB", result)
        self.assertIn("_龙门赛公告__WB", notice)

    def test_selection_commerce_posts_use_short_labels_instead_of_promo_copy(self):
        stem = post_stem({
            "idstr": "5334011972420037",
            "created_at": "2026-10-19T11:00:00+08:00",
            "text": "#京师甄选#🎉🎉 明晚直播带货安排：" + "限时优惠超值好物立即下单！" * 20,
        })
        self.assertIn("_京师甄选_带货安排__WB", stem)
        self.assertLessEqual(len(stem), 100)
        self.assertNotIn("🎉", stem)
        self.assertNotIn("限时优惠", stem)

    def test_same_second_and_title_are_disambiguated_by_numeric_id(self):
        base = {
            "created_at": "2026-06-01T09:00:00+08:00",
            "text": "#京城大师赛# 今日公告",
        }
        first = post_stem({**base, "idstr": "5334011972420026"})
        second = post_stem({**base, "idstr": "5334011972420027"})
        self.assertNotEqual(first, second)
        self.assertTrue(first.endswith("__WB5334011972420026"))

    def test_regular_image_announcement_gets_a_readable_image_base(self):
        paths = artifact_paths({
            "idstr": "5334011972420028",
            "created_at": "2026-06-02T10:30:00+08:00",
            "text": "#京城大师赛# 图片公告：本周活动安排",
            "pics": [{"large": {"url": "https://example.invalid/image.jpg"}}],
        })
        self.assertEqual(paths["raw_file"].split("/")[0], "posts")
        self.assertTrue(paths["raw_file"].startswith("posts/2026-06/"))
        self.assertTrue(paths["full_text_file"].startswith("long_text/2026-06/"))
        self.assertTrue(paths["full_text_file"].endswith(".长文原始.json"))
        self.assertTrue(paths["image_base"].startswith("images/2026-06/"))
        self.assertFalse(paths["image_base"].endswith((".jpg", "_图01")))
        self.assertEqual(paths["published_at_utc8"], "2026-06-02T10:30:00+08:00")
        self.assertIn("图片公告", paths["stem"])

    def test_long_title_is_html_cleaned_and_truncated(self):
        stem = post_stem({
            "idstr": "5334011972420029",
            "created_at": "2026-06-02T10:30:00+08:00",
            "text": "#京城大师赛# <p>这是一个非常长的长文标题" + "甲乙丙丁戊己庚辛壬癸" * 20 + "</p>",
        })
        self.assertLessEqual(len(stem), 100)
        self.assertNotIn("<p>", stem)
        self.assertNotIn("</p>", stem)
        self.assertLess(len(stem.rsplit("__WB", 1)[0]), 90)

    def test_dangerous_filename_characters_and_traversal_are_removed(self):
        stem = post_stem({
            "idstr": "5334011972420030",
            "created_at": "2026-06-02T10:30:00+08:00",
            "text": "#京城大师赛# ../../CON:<公告>?* ",
        })
        self.assertFalse(any(char in stem for char in '<>:"/\\|?*'))
        self.assertNotIn("..", stem)
        self.assertFalse(stem.endswith((" ", ".")))
        self.assertNotEqual(stem, "CON")

    def test_missing_or_invalid_time_is_explicit_and_uses_unknown_partition(self):
        paths = artifact_paths({"idstr": "5334011972420031", "text": "停播通知"})
        self.assertTrue(paths["stem"].startswith("未知时间_未知时间_"))
        self.assertIn("/未知时间/", paths["raw_file"])
        self.assertIn("/未知时间/", paths["full_text_file"])
        self.assertIn("/未知时间/", paths["image_base"])
        self.assertIsNone(paths["published_at_utc8"])

        invalid = post_stem({
            "idstr": "5334011972420032",
            "created_at": "刚刚",
            "text": "请假",
        })
        self.assertTrue(invalid.startswith("未知时间_未知时间_"))


if __name__ == "__main__":
    unittest.main()

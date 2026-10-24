import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "export_weibo_schedule", ROOT / "scripts" / "export_weibo_schedule.py"
)
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)


def post(post_id, text, *, published="2026-10-10", uid="7525583841", repost=False, images=None):
    return {
        "post_id": str(post_id), "post_url": f"https://m.weibo.cn/detail/{post_id}",
        "author_uid": str(uid), "author_name": "京城大师赛", "published_date": published,
        "text": text, "is_repost": repost, "reposted_author_uid": "9999999999" if repost else None,
        "raw_file": f"posts/{post_id}.json", "images": images or [],
    }


class WeiboScheduleParsingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("C:/offline-weibo")

    def analyze(self, value):
        return schedule.analyze_post(value, self.root, self.root / "export", "C:/offline-weibo/manifest.json")

    def test_master_schedule_is_preserved_when_broadcast_account_is_longmen(self):
        names = " ".join(f"@选手{i}" for i in range(1, 13))
        item = self.analyze(post("broadcast", f"第22季《京城大师赛》之曙光航纪 第一期阵容公布："
                                 f"周三（6月3日): {names} 解说: @甲 @乙 法官: @丙 "
                                 "板子:预女猎白混、假面舞会、机械狼通灵师 请锁定京城龙门赛，今晚19点"))
        self.assertEqual(item["candidate_category"], "排班候选")
        self.assertEqual(item["season"], 22)
        self.assertEqual(len(item["players"]), 12)
        self.assertEqual(item["episode"], 1)

    def test_collaboration_showmatch_is_separate_from_master_season_schedule(self):
        item = self.analyze(post("collab", "京城大师赛×天天狼人独家联动直播！京师天狼·网杀季·整活表演赛，今天下午14点。"))
        self.assertFalse(item["schedule_candidate"])
        self.assertEqual(item["players"], [])
        self.assertIsNone(item["season"])

    def test_extracts_roster_and_keeps_commentators_and_judge_out_of_players(self):
        names = " ".join(f"@选手{i}" for i in range(1, 12)) + " ... 苏打"
        item = self.analyze(post(
            "p1", f"第23季《京城大师赛》之昆仑归墟 第六期阵容公布：周二（10月14日): {names} "
            "解说: @解说甲 @解说乙 法官: @法官甲 板子:预女猎白混、诡术之境、机械狼通灵师"
            "[打call]看顶尖玩家如何博弈\n更多精彩内容敬请期待 今晚19点"
        ))
        self.assertEqual(item["season"], 23)
        self.assertEqual(item["episode"], 6)
        self.assertEqual(item["game_dates"], ["2026-10-14"])
        self.assertEqual(len(item["players"]), 12)
        self.assertEqual(item["players"][-1], "苏打")
        self.assertNotIn("解说甲", item["players"])
        self.assertNotIn("法官甲", item["players"])
        self.assertEqual(item["commentators"], ["解说甲", "解说乙"])
        self.assertEqual(item["judges"], ["法官甲"])
        self.assertEqual(item["board"], "预女猎白混、诡术之境、机械狼通灵师")
        self.assertEqual(item["start_time"], "今晚19点")
        self.assertEqual(item["schedule_match_keys"], ["S23-E6-2026-10-14"])

    def test_expands_multiple_days_in_one_announcement(self):
        item = self.analyze(post(
            "p2", "第23季第六期阵容公布：10月14日、15日 @甲 @乙 解说: @丙 法官: @丁 "
            "板子:预女猎白混 今晚19点"
        ))
        self.assertEqual(item["game_dates"], ["2026-10-14", "2026-10-15"])
        self.assertEqual(item["schedule_match_keys"], [])
        self.assertIn("多个日期", item["role_date_association"])
        self.assertTrue(any("日期关联未核" in flag for flag in item["review_flags"]))

    def test_expands_day_range_and_keeps_it_unmatched_for_review(self):
        item = self.analyze(post(
            "p2b", "第23季第六期阵容公布：10月14日至16日 @甲 @乙 解说: @丙 法官: @丁 "
            "板子:预女猎白混 今晚19点"
        ))
        self.assertEqual(item["game_dates"], ["2026-10-14", "2026-10-15", "2026-10-16"])
        self.assertEqual(item["schedule_match_keys"], [])

    def test_uses_nearest_calendar_year_for_cross_year_date(self):
        item = self.analyze(post(
            "p3", "第23季第六期阵容公布：1月2日 @甲 @乙 解说: @丙 法官: @丁 "
            "板子:预女猎白混 今晚19点", published="2025-12-30"
        ))
        self.assertEqual(item["game_dates"], ["2026-01-02"])

    def test_repost_does_not_infer_fields_and_non_target_or_other_event_is_excluded(self):
        repost = self.analyze(post("p4", "转发微博", repost=True))
        self.assertTrue(repost["schedule_candidate"])
        self.assertTrue(repost["is_repost"])
        self.assertIsNone(repost["season"])
        self.assertEqual(repost["players"], [])
        self.assertIn("转载外层只作待核", repost["review_flags"][0])

        other_author = self.analyze(post("p5", "第23季第六期阵容公布：10月14日", uid="111"))
        self.assertFalse(other_author["schedule_candidate"])
        self.assertIsNone(other_author["season"])

        other_event = self.analyze(post("p6", "京城龙门赛第六期阵容公布，今晚19点"))
        self.assertFalse(other_event["schedule_candidate"])
        self.assertIn("排除", other_event["candidate_reason"])
        supertopic_prefix = self.analyze(post("p6b", "京城大师赛 #京城龙门赛# 第六期阵容公布，今晚19点"))
        self.assertFalse(supertopic_prefix["schedule_candidate"])
        referral = self.analyze(post("p6c", "京城大师赛 #京城龙门赛·歌剧魅影季# 通往【京城大师赛】的席位珍稀难求，10月16日13:00开演。"))
        self.assertFalse(referral["schedule_candidate"])

        mixed_notice = self.analyze(post(
            "p6b", "京城大师赛以及京城龙门赛决定自即日起停播整顿一周"
        ))
        self.assertTrue(mixed_notice["schedule_candidate"])
        self.assertEqual(mixed_notice["candidate_category"], "赛事公告待核")
        self.assertIsNone(mixed_notice["season"])

        mixed_schedule = self.analyze(post(
            "p6d", "第23季京城大师赛以及京城龙门赛第六期阵容公布：10月14日"
        ))
        self.assertTrue(mixed_schedule["schedule_candidate"])
        self.assertEqual(mixed_schedule["candidate_category"], "赛事公告待核")
        self.assertIsNone(mixed_schedule["season"])

        commercial = self.analyze(post("p6c", "京师甄选 带货安排：今晚直播间见"))
        self.assertFalse(commercial["schedule_candidate"])
        self.assertEqual(commercial["candidate_category"], "商业内容排除")

    def test_anomalous_roster_remains_a_candidate_with_review_flag(self):
        item = self.analyze(post(
            "p7", "第23季第六期阵容公布：10月14日 @甲 解说: @乙 法官: @丙 "
            "板子:预女猎白混 今晚19点"
        ))
        self.assertTrue(item["schedule_candidate"])
        self.assertEqual(item["players"], ["甲"])
        self.assertTrue(any("不是常见12人排班" in flag for flag in item["review_flags"]))

        for count in (11, 13):
            names = " ".join(f"@P{i}" for i in range(count))
            roster = self.analyze(post(
                f"p{count}", f"第23季第六期阵容公布：10月14日 {names} 解说: @C 法官: @J "
                "板子:预女猎白混 今晚19点"
            ))
            self.assertTrue(any("不是常见12人排班" in flag for flag in roster["review_flags"]))

    def test_six_city_league_and_qualifier_rosters_are_not_master_schedule_rows(self):
        text = (
            "京城大师赛 #六城联赛#\n京城大师赛·六城联赛正式开启\n"
            "【8月25日】阵容公布：\n京城小师赛：佩玖 阿狮 大道寺\n"
            "沪上小师赛：恐龙 六六\n公开赛：森森\n"
            "板型：预女猎白、狼王守卫、石像鬼守墓人\n法官：云歌\n今晚19:00"
        )
        item = self.analyze(post("p-qualifier", text, published="2026-08-25"))
        self.assertFalse(item["schedule_candidate"])
        self.assertEqual(item["candidate_category"], "其他活动/资格赛待核")
        self.assertEqual(item["phase"], "其他活动/资格赛待核")
        self.assertEqual(item["players"], [])
        self.assertEqual(item["board"], "")
        self.assertIn("京城小师赛：佩玖 阿狮 大道寺", item["text"])
        self.assertIn("保留原帖与证据", item["candidate_reason"])

    def test_showmatch_and_finals_stage_allow_missing_episode_and_parse_board_type(self):
        showmatch = self.analyze(post(
            "p-showmatch",
            "第23季《京城大师赛》表演赛阵容公布：9月1日 @甲 @乙 "
            "解说: @解说甲 法官: @法官甲 板型:预女猎白混、机械狼通灵师 今晚19点",
            published="2026-09-01",
        ))
        self.assertTrue(showmatch["schedule_candidate"])
        self.assertEqual(showmatch["season"], 23)
        self.assertIsNone(showmatch["episode"])
        self.assertEqual(showmatch["phase"], "表演赛")
        self.assertFalse(any("未识别到期数" in flag for flag in showmatch["review_flags"]))
        self.assertEqual(showmatch["players"], ["甲", "乙"])
        self.assertNotIn("预女猎白混", showmatch["players"])
        self.assertEqual(showmatch["board"], "预女猎白混、机械狼通灵师")
        self.assertEqual(showmatch["schedule_match_keys"], [])

        finals = self.analyze(post(
            "p-finals",
            "第22季《京城大师赛》决赛阵容公布：8月20日 @甲 @乙 "
            "解说: @解说甲 法官: @法官甲 板子:预女猎白混 今晚19点",
            published="2026-08-20",
        ))
        self.assertEqual(finals["phase"], "决赛周")
        self.assertIsNone(finals["episode"])
        self.assertFalse(any("未识别到期数" in flag for flag in finals["review_flags"]))

    def test_s23_showmatch_rows_are_exported_with_phase_without_inventing_episode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            collection = root / "raw"
            output = root / "整理结果"
            collection.mkdir()
            manifest_path = collection / "manifest.json"
            showmatch = post(
                "p-showmatch-export",
                "第23季《京城大师赛》表演赛阵容公布：9月1日 @甲 @乙 "
                "解说: @解说甲 法官: @法官甲 板子:预女猎白混 今晚19点",
                published="2026-09-01",
            )
            manifest_path.write_text(json.dumps({"posts": [showmatch]}, ensure_ascii=False), encoding="utf-8")
            schedule.export(manifest_path, output)
            with (output / "比赛排班.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["阶段"], "表演赛")
            self.assertEqual(rows[0]["赛季"], "S23")
            self.assertEqual(rows[0]["期数"], "")

    def test_image_only_post_is_kept_as_a_candidate_with_relative_image_reference(self):
        item = self.analyze(post(
            "p8", "", images=[{"status": "downloaded", "file": "images/p8_1.jpg"}]
        ))
        self.assertTrue(item["schedule_candidate"])
        self.assertIn("images/p8_1.jpg", item["image_refs"][0])
        self.assertIn("仅有配图", item["review_flags"][-1])


class WeiboScheduleExportTests(unittest.TestCase):
    def test_writes_bom_csv_json_and_markdown_with_source_traceability(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            collection = root / "raw"
            output = root / "整理结果"
            collection.mkdir()
            manifest_path = collection / "manifest.json"
            roster = post(
                "p9", "第23季第六期阵容公布：10月14日、15日 @甲 @乙 解说: @丙 法官: @丁 "
                "板子:预女猎白混 今晚19点",
                images=[{"status": "downloaded", "file": "images/p9_1.jpg"}],
            )
            roster["full_text_file"] = "long_text/p9.json"
            roster["full_text_status"] = "expanded"
            manifest = {
                "status": "partial", "termination_reason": "max_pages_reached",
                "coverage_note": "仅代表本次可见分页样本。", "posts": [roster],
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            result = schedule.export(manifest_path, output)

            self.assertEqual(result["candidate_count"], 1)
            all_csv = output / "全部微博.csv"
            self.assertTrue(all_csv.read_bytes().startswith(b"\xef\xbb\xbf"))
            with all_csv.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["post_url"], "https://m.weibo.cn/detail/p9")
            self.assertIn("images/p9_1.jpg", rows[0]["image_refs"])
            self.assertIn("10月14日、15日", rows[0]["text"])
            self.assertIn("long_text/p9.json", rows[0]["full_text_file_ref"])
            with (output / "比赛排班.csv").open(encoding="utf-8-sig", newline="") as stream:
                schedules = list(csv.DictReader(stream))
            self.assertEqual(schedules[0]["比赛日期"], "2026-10-14；2026-10-15")
            self.assertEqual(schedules[0]["阶段"], "正赛")
            self.assertEqual(schedules[0]["原帖链接"], "https://m.weibo.cn/detail/p9")

            data = json.loads((output / "排班候选.json").read_text(encoding="utf-8"))
            self.assertEqual(data["candidates"][0]["game_dates"], ["2026-10-14", "2026-10-15"])
            self.assertEqual(data["candidates"][0]["post_url"], "https://m.weibo.cn/detail/p9")
            self.assertEqual(data["candidates"][0]["phase"], "正赛")
            self.assertTrue(data["candidates"][0]["raw_file_ref"].endswith("posts/p9.json"))

            markdown = (output / "微博整理.md").read_text(encoding="utf-8")
            self.assertIn("max_pages_reached", markdown)
            self.assertIn("仅代表本次可见分页样本", markdown)
            self.assertIn("https://m.weibo.cn/detail/p9", markdown)
            self.assertIn("images/p9_1.jpg", markdown)

    def test_other_activity_remains_in_all_posts_with_evidence_refs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            collection = root / "raw"
            output = root / "整理结果"
            collection.mkdir()
            manifest_path = collection / "manifest.json"
            activity = post(
                "p-qualifier-export",
                "京城大师赛 #六城联赛# 【8月25日】阵容公布：京城小师赛：甲 乙 "
                "公开赛：丙 板型：预女猎白 法官：丁",
                published="2026-08-25",
            )
            activity["raw_file"] = "posts/qualifier.json"
            activity["full_text_file"] = "long_text/qualifier.json"
            activity["full_text_status"] = "expanded"
            regular = post(
                "p-regular-export",
                "第23季第六期阵容公布：10月14日 @甲 解说: @乙 法官: @丙 "
                "板子:预女猎白混 今晚19点",
                published="2026-10-14",
            )
            manifest_path.write_text(
                json.dumps({"posts": [activity, regular]}, ensure_ascii=False), encoding="utf-8"
            )
            schedule.export(manifest_path, output)

            with (output / "全部微博.csv").open(encoding="utf-8-sig", newline="") as stream:
                all_rows = list(csv.DictReader(stream))
            self.assertEqual(len(all_rows), 2)
            activity_row = next(row for row in all_rows if row["post_id"] == "p-qualifier-export")
            self.assertIn("京城小师赛", activity_row["text"])
            self.assertIn("posts/qualifier.json", activity_row["raw_file_ref"])
            self.assertIn("long_text/qualifier.json", activity_row["full_text_file_ref"])
            self.assertEqual(activity_row["candidate_category"], "其他活动/资格赛待核")

            with (output / "排班候选.csv").open(encoding="utf-8-sig", newline="") as stream:
                candidates = list(csv.DictReader(stream))
            self.assertEqual([row["post_id"] for row in candidates], ["p-regular-export"])


if __name__ == "__main__":
    unittest.main()

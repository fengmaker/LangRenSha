"""Batch person enrichment must use verified names and reliable seat evidence."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from batch_people import enrich_people


class BatchPeopleTests(unittest.TestCase):
    def make_value(self, count=12):
        return {
            "slug": "synthetic",
            "roster": [],
            "commentators": [],
            "referee": None,
            "seats": [{"seat": n, "name": None, "role": None, "faction": None}
                      for n in range(1, count + 1)],
            "rounds": [],
            "files": [],
        }

    def setup_root(self, root, schedule_rows, aliases=()):
        schedule = root / "data/weibo/2026-05-26_2026-10-20/比赛排班.csv"
        schedule.parent.mkdir(parents=True, exist_ok=True)
        columns = ["阶段", "比赛日期", "赛季", "期数", "选手", "解说", "法官"]
        with schedule.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(schedule_rows)

        names = root / "data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv"
        names.parent.mkdir(parents=True, exist_ok=True)
        columns = ["照片编号", "原图名字", "复核行名字", "去重后姓名", "原人工确认状态",
                   "归并依据", "赛季", "图片SHA256", "纳入参赛名单", "排除原因"]
        with names.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for i, (raw, canonical) in enumerate(aliases, 1):
                writer.writerow({"照片编号": f"P{i:04d}", "原图名字": raw,
                                 "复核行名字": raw, "去重后姓名": canonical,
                                 "赛季": "S22", "纳入参赛名单": "是"})
        return root

    def schedule_row(self, date, *, season="S22", roster="", commentators="", referee=""):
        return {"阶段": "正赛", "比赛日期": date, "赛季": season, "期数": "4",
                "选手": roster, "解说": commentators, "法官": referee}

    def test_non_s22_same_day_announcement_does_not_contaminate_s22_people(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [
                self.schedule_row("2026-06-26", season="S23", roster="错误选手", commentators="错误解说", referee="错误法官"),
                self.schedule_row("2026-06-26", roster="张小凡、牛肉干", commentators="徐言雨", referee="豆儿啵"),
            ], [(name, name) for name in ("张小凡", "牛肉干", "徐言雨")])
            value, issues, context = enrich_people(self.make_value(), {"date": "2026-06-26", "season": "S22"}, root)

        self.assertEqual(value["roster"], ["张小凡", "牛肉干"])
        self.assertEqual(value["commentators"], ["徐言雨"])
        self.assertEqual(value["referee"], "豆儿啵")
        self.assertNotIn("错误选手", value["roster"])
        self.assertEqual(context["schedule_row"], 3)

    def test_ambiguous_reviewed_name_is_not_written_as_a_person(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [self.schedule_row("2026-06-26", roster="阿明")],
                            [("阿明", "阿明甲"), ("阿明", "阿明乙")])
            value, issues, _ = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertEqual(value["roster"], [])
        self.assertTrue(any("无法唯一映射" in issue for issue in issues))
        self.assertTrue(all(seat["name"] is None for seat in value["seats"]))

    def test_confirmed_schedule_aliases_resolve_to_canonical_people(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = self.schedule_row(
                "2026-06-26", roster="JY戴士",
                commentators="陸慧霖_陆元箐小桃子、其人的心事、萧亚辉",
                referee="pointy豆儿啵",
            )
            self.setup_root(root, [row])
            value, _, _ = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertEqual(value["roster"], ["JY"])
        self.assertEqual(value["commentators"], ["桃子", "其人", "辉少"])
        self.assertEqual(value["referee"], "豆儿啵")

    def test_photo_mapping_row_order_never_becomes_seat_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = [f"玩家{i}" for i in range(1, 13)]
            self.setup_root(root, [self.schedule_row("2026-06-26", roster="、".join(names))],
                            [(name, name) for name in reversed(names)])
            value, _, context = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertEqual(set(value["roster"]), set(names))
        self.assertEqual([seat["name"] for seat in value["seats"]], [None] * 12)
        self.assertIsNone(context["seat_source"])

    def test_jy_is_seat_seven_only_when_the_official_roster_confirms_participation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [self.schedule_row("2026-06-26", roster="JY戴士、张小凡")],
                            [("张小凡", "张小凡")])
            value, _, context = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertEqual(value["seats"][6]["name"], "JY")
        self.assertEqual(sum(seat["name"] == "JY" for seat in value["seats"]), 1)
        self.assertEqual(context["seat_source"], "confirmed_jy_seat_rule")

    def test_first_game_self_intro_can_assign_a_seat_but_chat_mentions_cannot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [self.schedule_row("2026-06-26", roster="张小凡")], [("张小凡", "张小凡")])
            transcript = root / "data/seasons/S22/2026-06-26/2026-06-26_第01局_阅读.txt"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                "[00:00:01.000 → 00:00:02.000] 有请1号玩家\n"
                "[00:00:02.000 → 00:00:03.000] 大家好我是张小凡\n"
                "[00:00:04.000 → 00:00:05.000] 刚才JY也提到这件事\n",
                encoding="utf-8",
            )
            value, _, context = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertEqual(value["seats"][0]["name"], "张小凡")
        self.assertTrue(all(seat["name"] != "JY" for seat in value["seats"]))
        self.assertEqual(context["seat_source"], "first_game_self_introduction")
        self.assertEqual(context["intro_candidates"][0]["self_intro_line"], 2)

    def test_unique_local_full_transcript_precedes_platform_reading_and_companion_formats(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [self.schedule_row("2026-06-26", roster="张小凡、牛肉干")],
                            [(name, name) for name in ("张小凡", "牛肉干")])
            transcript_dir = root / "data/seasons/S22/2026-06-26"
            transcript_dir.mkdir(parents=True, exist_ok=True)
            local_base = "2026-06-26_第01局_机械狼_本地全文转写_funasr"
            local_reading = transcript_dir / f"{local_base}.阅读.txt"
            local_srt = transcript_dir / f"{local_base}.srt"
            platform_reading = transcript_dir / "2026-06-26_第01局_机械狼_平台AI字幕.阅读.txt"
            local_text = (
                "[00:00:01.000 → 00:00:02.000] 有请1号玩家\n"
                "[00:00:02.000 → 00:00:03.000] 大家好我是张小凡\n"
            )
            local_reading.write_text(local_text, encoding="utf-8")
            local_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n本地全文\n", encoding="utf-8")
            platform_reading.write_text(
                "[00:00:01.000 → 00:00:02.000] 有请1号玩家\n"
                "[00:00:02.000 → 00:00:03.000] 大家好我是牛肉干\n",
                encoding="utf-8",
            )
            value, issues, context = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertEqual(context["intro_source_path"], local_reading.relative_to(root).as_posix())
        self.assertEqual(value["seats"][0]["name"], "张小凡")
        self.assertIsNone(value["seats"][1]["name"])
        self.assertFalse(any("多个候选" in issue for issue in issues))

    def test_different_local_full_sources_at_same_priority_remain_ambiguous(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [self.schedule_row("2026-06-26", roster="张小凡、牛肉干")],
                            [(name, name) for name in ("张小凡", "牛肉干")])
            transcript_dir = root / "data/seasons/S22/2026-06-26"
            transcript_dir.mkdir(parents=True, exist_ok=True)
            for engine, name in (("funasr", "张小凡"), ("whisper", "牛肉干")):
                (transcript_dir / f"2026-06-26_第01局_本地全文转写_{engine}.阅读.txt").write_text(
                    "[00:00:01.000 → 00:00:02.000] 有请1号玩家\n"
                    f"[00:00:02.000 → 00:00:03.000] 大家好我是{name}\n",
                    encoding="utf-8",
                )
            (transcript_dir / "2026-06-26_第01局_平台AI字幕.阅读.txt").write_text(
                "[00:00:01.000 → 00:00:02.000] 有请1号玩家\n"
                "[00:00:02.000 → 00:00:03.000] 大家好我是张小凡\n",
                encoding="utf-8",
            )
            value, issues, context = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertIsNone(context["intro_source_path"])
        self.assertTrue(all(seat["name"] is None for seat in value["seats"]))
        self.assertTrue(any("多个候选" in issue for issue in issues))

    def test_speech_about_a_name_is_not_mistaken_for_self_identification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [self.schedule_row("2026-06-26", roster="张小凡")], [("张小凡", "张小凡")])
            transcript = root / "data/seasons/S22/2026-06-26/2026-06-26_第01局_阅读.txt"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                "[00:00:01.000 → 00:00:02.000] 有请1号玩家\n"
                "[00:00:02.000 → 00:00:03.000] 我是觉得张小凡可能是好人\n",
                encoding="utf-8",
            )
            value, _, _ = enrich_people(self.make_value(), {"date": "2026-06-26"}, root)

        self.assertIsNone(value["seats"][0]["name"])

    def test_missing_sources_preserve_unknowns_and_do_not_add_review_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.setup_root(root, [self.schedule_row("2026-06-26")])
            value = self.make_value()
            original = {key: value[key] for key in ("roster", "commentators", "referee", "seats", "files")}
            value, issues, context = enrich_people(value, {"date": "2026-06-26"}, root)

        self.assertEqual({key: value[key] for key in original}, original)
        self.assertFalse({"evidence", "review", "version"} & value.keys())
        self.assertIn("schedule_path", context)
        self.assertIsNone(context["intro_source_path"])
        self.assertTrue(issues)
        self.assertTrue(any("没有找到当日首局转写" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()

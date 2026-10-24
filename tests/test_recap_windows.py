import unittest

from scripts.plan_recap_windows import analyze_subtitle, _segments


def seg(t, text, end=None):
    return {"from": t, "to": end if end is not None else t + 1, "content": text}


def roster(t):
    return [seg(t, "1号预言家"), seg(t + 1, "2号女巫"), seg(t + 2, "3号猎人"),
            seg(t + 3, "4号守卫"), seg(t + 4, "5号平民"), seg(t + 5, "6号狼人"),
            seg(t + 6, "7号白痴"), seg(t + 7, "8号机械狼")]


class RecapWindowTests(unittest.TestCase):
    def test_future_recap_mention_is_not_detected(self):
        rows = [seg(20, "游戏结束以后我们再复盘本局"), seg(30, "等会儿给大家复盘")]
        status, windows = analyze_subtitle(_segments(rows), 600_000)
        self.assertEqual(status, "needs_localization")
        self.assertEqual(windows, [])

    def test_recap_in_middle_of_long_audio_is_localized(self):
        rows = [seg(4_680, "现在给大家复盘一下本局")] + roster(4_686) + [
                seg(4_700, "首夜行动"), seg(4_704, "狼队这一刀刀在了5号"), seg(4_740, "好人阵营胜利"),
                seg(4_746, "下面看鲜花席"), seg(8_300, "片尾")]
        status, windows = analyze_subtitle(_segments(rows), 8_600_000)
        self.assertEqual(status, "candidate")
        self.assertEqual(len(windows), 1)
        self.assertGreater(windows[0]["start_ms"], 4_000_000)
        self.assertLess(windows[0]["end_ms"], 5_000_000)
        self.assertFalse(windows[0]["exact_boundary_verified"])

    def test_missing_subtitle_returns_tail_probe_not_detection(self):
        status, windows = analyze_subtitle([], 2_000_000, subtitle_present=False)
        self.assertEqual(status, "tail_probe")
        self.assertEqual(windows[0]["start_ms"], 1_700_000)

    def test_truncated_subtitle_uses_tail_probe_even_with_future_mention(self):
        rows = [seg(20, "等会儿给大家复盘本局")]
        status, windows = analyze_subtitle(_segments(rows), 600_000, subtitle_truncated=True)
        self.assertEqual(status, "tail_probe")
        self.assertEqual(windows[0]["start_ms"], 300_000)

    def test_split_roster_captions_are_joined_into_role_lines(self):
        rows = [seg(100, "现在给大家复盘本局"), seg(105, "1号"), seg(106, "预言家"),
                seg(108, "2号女"), seg(109, "巫"), seg(111, "3号猎人"), seg(112, "4号守卫"),
                seg(113, "5号平民"), seg(114, "6号狼人"), seg(116, "首夜行动"),
                seg(120, "狼队刀了6号"), seg(145, "下一局准备开始")]
        status, windows = analyze_subtitle(_segments(rows), 600_000)
        self.assertEqual(status, "candidate")
        self.assertGreaterEqual(windows[0]["role_line_count"], 2)

    def test_no_intro_uses_distinct_seat_role_density_and_night_cues(self):
        rows = [seg(300, "本局版型通灵师一号、女巫十号、猎人七号、守卫五号；狼人三/六/十二、机械狼八；平民二/四/九/十一"),
                seg(320, "首夜守卫守护5号"), seg(328, "狼队击杀了9号"), seg(365, "下一局")]
        status, windows = analyze_subtitle(_segments(rows), 900_000)
        self.assertEqual(status, "candidate")
        self.assertEqual(len(windows), 1)
        self.assertGreaterEqual(windows[0]["role_line_count"], 10)
        self.assertTrue(any("一号" in item["text"] for item in windows[0]["evidence"]))

    def test_transition_marks_end_boundary(self):
        rows = [seg(200, "给大家复盘本局")] + roster(205) + [
                seg(218, "首夜行动"), seg(220, "狼队刀了4号"), seg(252, "下面看解说席")]
        status, windows = analyze_subtitle(_segments(rows), 600_000, after_ms=2_000)
        self.assertEqual(status, "candidate")
        self.assertEqual(windows[0]["end_ms"], 255_000)
        self.assertTrue(any(x.startswith("post_recap_transition") for x in windows[0]["basis"]))

    def test_long_midstream_recap_ignores_previous_game_result(self):
        rows = [seg(4_699.81, "上一局游戏结束"),
                seg(4_701.13, "本局游戏机械狼通灵师版型")] + roster(4_703.15) + [
                seg(4_715.82, "首夜守卫守护5号"),
                seg(4_718.96, "首夜通灵师验证2号"),
                seg(4_764.50, "游戏结束"),
                seg(4_765.32, "狼人阵营胜利", 4_766.76)]
        status, windows = analyze_subtitle(_segments(rows), 8_580_000)
        self.assertEqual(status, "candidate")
        self.assertEqual(len(windows), 1)
        self.assertLessEqual(windows[0]["start_ms"], 4_701_130)
        self.assertGreaterEqual(windows[0]["end_ms"], 4_766_760)

    def test_consecutive_game_roster_and_night_recap_stay_one_window(self):
        rows = [seg(3_171.30, "上一局狼人阵营胜利"),
                seg(3_172.40, "第二局游戏开始预言家版型")] + roster(3_174.08) + [
                seg(3_184.41, "首夜狼队击杀10号，女巫用药救人"),
                seg(3_198.39, "通灵师验证4号"),
                seg(3_250.60, "游戏结束"),
                seg(3_251.58, "狼人阵营胜利", 3_253.23)]
        status, windows = analyze_subtitle(_segments(rows), 5_000_000)
        self.assertEqual(status, "candidate")
        self.assertEqual(len(windows), 1)
        self.assertLessEqual(windows[0]["start_ms"], 3_172_400)
        self.assertGreaterEqual(windows[0]["end_ms"], 3_253_230)

    def test_overlapping_candidates_are_deduplicated(self):
        rows = [seg(100, "给大家复盘本局"), seg(103, "本局复盘一下")] + roster(107) + [
                seg(118, "首夜行动"), seg(120, "狼队刀了5号"), seg(147, "下一局")]
        status, windows = analyze_subtitle(_segments(rows), 600_000)
        self.assertEqual(status, "candidate")
        self.assertEqual(len(windows), 1)

    def test_distinct_overlapping_candidates_stay_separate_and_capped(self):
        rows = []
        for start in (100, 240):
            rows += [seg(start, "给大家复盘本局")] + roster(start + 4)
            rows += [seg(start + 17, "首夜行动"), seg(start + 20, "狼队刀了5号")]
        status, windows = analyze_subtitle(_segments(rows), 900_000)
        self.assertEqual(status, "review")
        self.assertEqual(len(windows), 2)
        self.assertTrue(all(w["end_ms"] - w["start_ms"] <= 180_000 for w in windows))


if __name__ == "__main__":
    unittest.main()

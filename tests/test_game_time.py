import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from game_time import chinese, display_time_text, phase_label


def test_phase_labels_and_chinese_round_numbers():
    assert phase_label(1, "night") == "首夜"
    assert phase_label(2, "night") == "第一天夜晚"
    assert phase_label(4, "night") == "第三天夜晚"
    assert phase_label(4, "day") == "第四天白天"
    assert chinese(11) == "十一"


def test_display_time_text_normalizes_only_legacy_time_phrases():
    assert display_time_text("在第4夜结束，未进入第4天白天") == "在第三天夜晚结束，未进入第四天白天"
    assert display_time_text("第4天夜晚开始后，再到首夜") == "第四天夜晚开始后，再到首夜"
    assert display_time_text("开局夜晚与第一夜") == "首夜与首夜"

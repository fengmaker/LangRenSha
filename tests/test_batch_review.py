import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from batch_review import _display_phase_label


def test_display_phase_label_replaces_stored_flow_labels():
    assert _display_phase_label({"round": 1, "phase": "night", "label": "开局夜晚"}) == "首夜"
    assert _display_phase_label({"round": 2, "phase": "night", "label": "第2夜"}) == "第一天夜晚"


def test_display_phase_label_keeps_night_skill_settlement_suffix():
    stage = {"round": 4, "phase": "day", "label": "第3天夜晚 · 死亡技能结算",
             "event_slots": ["night_deaths", "hunter_shot"]}
    assert _display_phase_label(stage) == "第三天夜晚 · 死亡技能结算"

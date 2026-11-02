"""Old storage codes retain their exact archival structure after consolidation."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from board_config import load_template, template_path

HISTORY = ROOT / "data/extractions/shared/config_history/2026-10-29"


@pytest.mark.parametrize("path", sorted((HISTORY / "board_templates").glob("*.json")), ids=lambda p: p.stem)
def test_old_template_shapes_are_preserved(path):
    previous = json.loads(path.read_text(encoding="utf-8"))
    code = previous["code"]
    if code in {"s21_mechanical_wolf_seer", "s23_mechanical_wolf_seer"}:
        previous["mechanical_forms"] = load_template("mechanical_wolf_seer")["mechanical_forms"]
    # Reviewed terminal phases now distinguish an unavailable knife or an
    # unheld exile. Everything else in the archival shape remains exact.
    additions = {
        "s21_seer_witch_hunter_white_mixed": ("night_slots", "wolf_attack", "unavailable"),
        "s21_masquerade": ("night_slots", "wolf_attack", "unavailable"),
        "s23_magic_duel": ("day_slots", "exile_result", "none"),
        "s23_qingqiu_night": ("day_slots", "exile_result", "none"),
    }
    if code in additions:
        phase, slot, action = additions[code]
        actions = next(s["actions"] for s in previous[phase] if s["code"] == slot)
        actions.insert(actions.index("unknown") if action == "unavailable" else len(actions), action)
    if code == "s23_qingqiu_night":
        # 九尾狐接刀后的普通狼刀不可用，已在现有模板中保留这一终局状态。
        next(s["actions"] for s in previous["night_slots"] if s["code"] == "wolf_attack").append("unavailable")
    if code == "s21_treasure_master":
        actions = next(s["actions"] for s in previous["night_slots"] if s["code"] == "wolf_attack")
        actions[1:1] = ["forbidden", "unavailable"]
    if code in {"treasure_master", "s23_treasure_master"}:
        next(s for s in previous["night_slots"] if s["code"] == "treasure_choice")["label"] = (
            "盗宝大师选择身份（平民或本局另一牌）")
    if code == "treasure_master":
        previous["wake_order_note"] = (
            "完整睁眼顺序未核；槽位排列仅用于事件归档，不表示已确认夜序。15 张候选牌中发出 12 张、"
            "余 3 张；物理余牌与可切换身份分开，盗宝大师只能在平民与本局另一张身份间切换；首夜狼队禁刀。")
    assert load_template(code) == previous
    assert not template_path(code).stem.startswith(("s21_", "s23_"))


def test_archived_config_hashes_remain_exact():
    manifest = json.loads((HISTORY / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        assert hashlib.sha256((ROOT / item["archive_path"]).read_bytes()).hexdigest() == item["sha256"]


@pytest.mark.parametrize("code, storage", [
    ("wolf_girl", "s23_wolf_girl"),
    ("troublemaker", "s23_troublemaker"),
])
def test_new_s23_templates_keep_unconfirmed_wake_order_and_storage_code(code, storage):
    canonical = load_template(code)
    stored = load_template(storage)
    assert canonical["wake_order"] == []
    assert stored["code"] == storage
    assert {slot["code"] for slot in canonical["night_slots"]} <= {
        slot["code"] for slot in stored["night_slots"]
    }

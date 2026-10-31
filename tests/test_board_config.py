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
    assert load_template(code) == previous
    assert not template_path(code).stem.startswith(("s21_", "s23_"))


def test_archived_config_hashes_remain_exact():
    manifest = json.loads((HISTORY / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        assert hashlib.sha256((ROOT / item["archive_path"]).read_bytes()).hexdigest() == item["sha256"]

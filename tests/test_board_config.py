"""Current board templates retain confirmed night-order constraints."""
import sys

import pytest

sys.path.insert(0, "scripts")
from board_config import load_template


@pytest.mark.parametrize("code", ["masquerade", "s23_masquerade"])
def test_masquerade_keeps_the_confirmed_dancer_then_mask_sequence(code):
    board = load_template(code)
    slots = [slot["code"] for slot in board["night_slots"]]

    assert slots == [
        "dancer_dance", "masquerade_verify", "masquerade_mask", "wolf_attack",
        "witch_save", "witch_poison", "seer_check", "dance_resolution",
    ]
    assert board["wake_order"] == []
    assert "其余角色的完整睁眼顺序未核" in board["wake_order_note"]


@pytest.mark.parametrize("code", ["wolf_girl", "troublemaker"])
def test_special_board_templates_leave_unconfirmed_wake_order_unknown(code):
    board = load_template(code)

    assert board["wake_order"] == []
    assert board["night_slots"]

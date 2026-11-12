"""Current rules keep shared semantics and season scope separate."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rule_config import load_formal_rules, load_rules, load_scope
from season_config import load_season


@pytest.mark.parametrize("season", ["S21", "S22", "S23"])
def test_season_adapters_use_shared_rules_and_registered_scope(season):
    registry = load_season(season)

    assert load_scope(season) == {"season": season, **registry["scope"]}
    assert load_formal_rules(season)["shared_rules"] == load_rules()["shared_rules"]


def test_wolf_king_rules_include_the_user_confirmed_departure_and_terminal_boundaries():
    rule = load_rules()["shared_rules"]["wolf_king"]
    assert rule["qualification_display_requires_current_departure"] is True
    assert rule["ordinary_shot_triggers"] == ["exile", "wolf_attack_death"]
    assert all(rule[key] is True for key in (
        "poison_death_blocks_shot", "dream_link_death_blocks_shot",
        "repeat_dream_death_blocks_shot", "last_wolf_exiled_game_end_prevents_shot",
    ))
    assert rule["status"] == "user_confirmed"
    assert rule["source"]["confirmed_on"] == "2026-10-30"


def test_nine_tail_takeover_rule_keeps_the_user_confirmed_gate():
    rule = load_rules()['shared_rules']['nine_tail']
    assert rule['knife_requires_all_ordinary_wolves_departed'] is True
    assert rule['takeover_kill_replaces_wolf_attack_display'] is True
    assert rule['status'] == 'user_confirmed'
    assert rule['source']['confirmed_on'] == '2026-10-30'

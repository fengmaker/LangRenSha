"""Consolidated rules keep shared semantics and season scope separate."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rule_config import load_formal_rules, load_rules, load_scope

HISTORY = ROOT / "data/extractions/shared/config_history/2026-10-29"


def original(name):
    return json.loads((HISTORY / name).read_text(encoding="utf-8"))


def test_s22_shared_rules_and_board_semantics_survive_consolidation():
    previous = original("S22_formal_rules.json")
    previous["rotation"]["source"]["scope_policy"] = "config/seasons.json"
    current = load_formal_rules("S22")
    assert {key: value for key, value in current["shared_rules"].items()
            if key not in {"wolf_king", "nine_tail"}} == previous["shared_rules"]
    assert current["field_definitions"] == previous["field_definitions"]
    assert current["rotation"] == previous["rotation"]
    assert set(current["boards"]) == set(previous["boards"])
    for code, board in previous["boards"].items():
        for field in ("board_rules", "role_composition", "role_pool", "scored_count", "wake_order"):
            assert current["boards"][code].get(field) == board.get(field)


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


@pytest.mark.parametrize("season", ["S21", "S22", "S23"])
def test_scope_and_common_rules_are_available_without_season_rule_files(season):
    current = load_scope(season)
    previous = original(f"{season}_game_scope.json")
    for field in ("excluded_bvids", "excluded_phases", "expected_games", "authoritative_snapshot_id"):
        assert current.get(field) == previous.get(field)
    assert load_formal_rules(season)["shared_rules"] == load_rules()["shared_rules"]
    assert not (ROOT / f"config/{season}_formal_rules.json").exists()


def test_cases_keep_evidence_status_and_single_game_scope():
    previous = original("S23_review_rules.json")
    assert load_rules()["review_rules"]["rules"] == previous["rules"]
    current = load_formal_rules("S23")
    old = original("S23_formal_rules.json")
    for field in ("board_code_map", "role_profiles", "confirmed_rule_handling", "separate_review_context"):
        assert current[field] == old[field]


def test_scoring_keeps_points_and_user_reported_provenance():
    previous = original("scoring_rules.user_reported.v1.json")
    scoring = load_rules()["scoring"]
    for field in ("config_id", "scoring_rules", "phase_rules", "source", "official_verified"):
        assert scoring[field] == previous[field]

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
    assert current["shared_rules"] == previous["shared_rules"]
    assert current["field_definitions"] == previous["field_definitions"]
    assert current["rotation"] == previous["rotation"]
    assert set(current["boards"]) == set(previous["boards"])
    for code, board in previous["boards"].items():
        for field in ("board_rules", "role_composition", "role_pool", "scored_count", "wake_order"):
            assert current["boards"][code].get(field) == board.get(field)


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

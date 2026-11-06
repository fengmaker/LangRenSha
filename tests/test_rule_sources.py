"""Scoped dependency changes, legacy reports, and publication-local reuse."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import game_derivations as rules
from test_game_derivations import fixture, voting


@pytest.fixture
def rule_root(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    target = tmp_path / "scripts"
    target.mkdir()
    for path in (ROOT / "scripts").glob("*.py"):
        shutil.copyfile(path, target / path.name)
    monkeypatch.setattr(rules, "ROOT", tmp_path)
    return tmp_path


def test_scoped_sources_ignore_unused_boards_and_other_seasons(rule_root):
    game = {"season": "S22", "board": "mixed_blood"}
    before = rules.rule_sources(game)
    templates = rule_root / "config/board_templates"
    (templates / "unused_new.json").write_text('{"code": "unused_new"}', encoding="utf-8")
    (templates / "masquerade.json").write_text('{}', encoding="utf-8")
    registry_path = rule_root / "config/seasons.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["seasons"]["S23"]["name"] = "other season changed"
    registry["seasons"]["S99"] = {"name": "new season"}
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    assert rules.rule_sources(game) == before
    assert "config/board_templates/mixed_blood.json" in before
    assert "config/seasons.json#S22" in before
    assert "config/seasons.json" not in before


@pytest.mark.parametrize("dependency", ["season", "template", "shared"])
def test_scoped_sources_detect_actual_dependencies(rule_root, dependency):
    game = {"season": "S22", "board": "mixed_blood"}
    before = rules.rule_sources(game)
    if dependency == "season":
        path = rule_root / "config/seasons.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["seasons"]["S22"]["name"] = "changed"
        path.write_text(json.dumps(value), encoding="utf-8")
    elif dependency == "template":
        path = rule_root / "config/board_templates/mixed_blood.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    else:
        path = rule_root / "scripts/voting_core.py"
        path.write_text("# changed shared rules\n", encoding="utf-8")
    assert rules.rule_sources(game) != before


def test_scoped_sources_resolve_season_mapping_and_storage_variants(rule_root):
    for season, board in [("S21", "s21_mechanical_wolf_seer"), ("S23", "mechanical_wolf_seer")]:
        sources = rules.rule_sources({"season": season, "board": board})
        assert [key for key in sources if key.startswith("config/board_templates/")] == [
            "config/board_templates/mechanical_wolf_seer.json"
        ]


def test_rule_hashes_are_reused_only_in_the_supplied_scope(rule_root, monkeypatch):
    reads = Counter()
    original = Path.read_bytes

    def counted(path):
        reads[path] += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    cache = {}
    games = [{"season": "S22", "board": "mixed_blood"},
             {"season": "S23", "board": "mixed_blood"}]
    for game in games * 3:
        rules.rule_sources(game, cache=cache)
    assert reads and set(reads.values()) == {1}
    path = rule_root / "scripts/role_constraints.py"
    before = rules.rule_sources(games[0], cache=cache)
    path.write_text("# shared rules changed\n", encoding="utf-8")
    assert rules.rule_sources(games[0]) != before


@pytest.mark.parametrize("version", [1, 2])
def test_saved_versions_keep_rule_and_fact_validation(version):
    game, votes = fixture(rounds=1), voting([])
    result = rules.derive_game(game, votes)
    report = deepcopy(result["derivations"])
    report["version"] = version
    report["rule_sources"] = rules.rule_sources(None if version == 1 else game)
    expected = {key: result[key] for key in ("dossier", "voting")}
    assert rules.apply_precomputed(game, votes, report) == expected
    assert rules.apply_precomputed(result["dossier"], result["voting"], report) == expected
    changed = deepcopy(game)
    changed["winner"] = "changed source fact"
    with pytest.raises(ValueError, match="基础事实已变化"):
        rules.apply_precomputed(changed, votes, report)
    report["rule_sources"]["scripts/role_constraints.py"] = "stale"
    with pytest.raises(ValueError, match="通用规则已变化"):
        rules.apply_precomputed(game, votes, report)


def test_unknown_report_version_is_rejected():
    game, votes = fixture(rounds=1), voting([])
    report = rules.derive_game(game, votes)["derivations"]
    report["version"] = 999
    with pytest.raises(ValueError, match="规则推导版本"):
        rules.apply_precomputed(game, votes, report)


def test_prepare_migrates_legacy_report_without_changing_source_facts(tmp_path, monkeypatch):
    import prepare_game_rules as command

    game, votes = fixture(rounds=1), voting([])
    report = rules.derive_game(game, votes)["derivations"]
    report.update(version=1, rule_sources=rules.rule_sources())
    # Even stale legacy rules need an explicit refresh, never a validation bypass.
    report["rule_sources"]["scripts/role_constraints.py"] = "old code"
    folder = tmp_path / "data/games/S22/fixture"
    folder.mkdir(parents=True)
    for name, value in [("dossier", game), ("voting", votes), ("rule_derivations", report)]:
        (folder / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    originals = [(folder / f"{name}.json").read_bytes() for name in ("dossier", "voting")]
    monkeypatch.setattr(command, "ROOT", tmp_path)
    command.prepare(["S22"], apply=True)
    updated = json.loads((folder / "rule_derivations.json").read_text(encoding="utf-8"))
    assert updated["version"] == 2
    assert updated["rule_sources"] == rules.rule_sources(game)
    assert rules.apply_precomputed(game, votes, updated)
    assert [(folder / f"{name}.json").read_bytes() for name in ("dossier", "voting")] == originals

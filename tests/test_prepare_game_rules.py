"""Preserve reviewed voting conclusions while refreshing shared rules."""
import hashlib
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_game_rules as command
from test_game_derivations import fixture, voting


@pytest.mark.parametrize("voting_changed", [False, True])
def test_refresh_keeps_reviewed_terminal_before_exile(tmp_path, monkeypatch, voting_changed):
    monkeypatch.setattr(command, "ROOT", tmp_path)
    folder = tmp_path / "data/games/S22/fixture_BV1xYEo6QEGV"
    folder.mkdir(parents=True)
    game, votes = fixture(), voting([])
    votes["days"] = [{"day": 1, "sheriff": "unknown", "exile": "unknown"}]
    source = tmp_path / "data/source.txt"
    source.write_text("游戏结束，未进入放逐", encoding="utf-8")
    reviewed = {"day": 1, "outcome": "ended_before_exile", "exile_note": "终局已确认，无放逐。"}
    audit = {
        "source_path": "data/source.txt",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "facts": {**votes, "days": []} if voting_changed else votes,
        "evidence": {},
        "causal_review": {"day_outcomes": [reviewed]},
        "day_outcomes": [{**reviewed, "evidence": []}],
    }
    audit_path = tmp_path / "data/extractions/S22/voting/BV1xYEo6QEGV.json"
    audit_path.parent.mkdir(parents=True)
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    (folder / "dossier.json").write_text(json.dumps(game), encoding="utf-8")
    (folder / "voting.json").write_text(json.dumps(votes), encoding="utf-8")

    command.prepare(["S22"], apply=True)

    saved = json.loads(audit_path.read_text(encoding="utf-8"))
    assert saved["day_outcomes"] == [{**reviewed, "evidence": []}]
    assert saved["causal_review"] == audit["causal_review"]

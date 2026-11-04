from __future__ import annotations

import hashlib
from copy import deepcopy
import json
from pathlib import Path
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from website.api import bluff_store, bluffs, publisher
import build_bluff_inference
import build_s23_bluff_publication


BASELINES = {
    "S22": {
        "game_count": 148, "assessment_count": 586, "wolf_count": 586,
        "yes_count": 121, "success_count": 46, "user_confirmed_count": 586,
        "projection_sha256": "b32655882b592c6858ae10c367e2582ae1098582d6ed53dcc296c7500b216b81",
        "aggregate_sha256": "ccfb2b56cadc8c661f643151c51f99138308115cb6f97e6425a0cf985a349109",
    },
    "S23": {
        "game_count": 90, "assessment_count": 362, "wolf_count": 360,
        "yes_count": 81, "success_count": 13, "user_confirmed_count": 362,
        "manual_included_count": 2,
        "projection_sha256": "5e96ee81581510398c8a7d6543588b15b45a1b3c0874e3a38938db7248c7cd88",
        "aggregate_sha256": "e7111bf68ed828d97cf3364c0744a5bfa0fdab4b7030ffabb7877a5cda1a2f91",
    },
}
S23_BASELINE_CUTOFF = "2026-11-03"


def _public_games(season: str) -> list[dict]:
    entries, _, _ = publisher.load_release(ROOT, season)
    names = {seat.get("name") for entry in entries for seat in entry["dossier"].get("seats", [])}
    person_ids = {
        name: str(uuid.uuid5(publisher.PERSON_NAMESPACE, name.strip().casefold()))
        for name in names if isinstance(name, str)
    }
    return [
        publisher._public_game(
            entry["dossier"], entry["voting"], entry["endgame"], entry.get("audit"),
            entry["board"], person_ids, source_voting=entry.get("source_voting"),
            derivations=entry.get("derivations"),
        )
        for entry in entries
    ]


def _sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _baseline_scope(season: str, games: list[dict], payload: dict) -> tuple[list[dict], dict]:
    if season == "S22":
        baseline_games = games
    else:
        baseline_games = [game for game in games
                          if isinstance(game.get("date"), str)
                          and game["date"] <= S23_BASELINE_CUTOFF]
    game_ids = {game.get("id", game.get("slug")) for game in baseline_games}
    baseline_payload = deepcopy(payload)
    baseline_payload["games"] = [row for row in payload["games"] if row.get("game_id") in game_ids]
    return baseline_games, baseline_payload


@pytest.mark.parametrize("season", ["S22", "S23"])
def test_confirmed_bluff_baseline_matches_the_official_release(season: str):
    expected = BASELINES[season]
    payload_path = ROOT / "website" / "assets" / "bluffs" / f"{season}.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    games, payload = _baseline_scope(season, _public_games(season), payload)
    items, validation = bluff_store._validate_review(
        games, payload, season, expected_game_count=len(games))
    aggregate = bluffs.aggregate_bluffs(games, payload)

    expected_validation = {
        "game_count": expected["game_count"], "wolf_count": expected["wolf_count"],
        "yes_count": expected["yes_count"], "success_count": expected["success_count"],
        "pending_count": 0, "user_confirmed_count": expected["user_confirmed_count"],
    }
    if "manual_included_count" in expected:
        expected_validation["manual_included_count"] = expected["manual_included_count"]
    assert validation == expected_validation
    assert payload["confirmed_baseline"] == {
        "confirmed_at": "2026-11-04",
        "game_count": expected["game_count"],
        "assessment_count": expected["assessment_count"],
        "confirmation": "用户确认：S22、S23人工全部已确认，以当前结果为准。",
    }

    assessments = [row for game in payload["games"] for row in game["assessments"]]
    assert len(assessments) == expected["assessment_count"]
    assert all(row["verification_status"] == "user_confirmed" for row in assessments)
    by_key = {(game["game_id"], row["seat"]): row
              for game in payload["games"] for row in game["assessments"]}
    for item in items:
        record = by_key[(item["game_id"], item["seat"])]
        if item["decision"] == "yes":
            assert "manual_success" in record
            assert record["manual_success"] == item["success"]
            assert record["manual_success"] is None or type(record["manual_success"]) is bool

    projection = [
        {key: item[key] for key in ("game_id", "seat", "decision", "success", "claimed_role", "claim_day")}
        for item in sorted(items, key=lambda row: (row["game_id"], row["seat"]))
    ]
    assert _sha256(projection) == expected["projection_sha256"]
    assert _sha256(aggregate) == expected["aggregate_sha256"]
    assert sum(row["bluff_count"] for row in aggregate.values()) == expected["yes_count"]

    if season == "S23":
        assert payload["manual_review"]["reviewed_games"] == 84


def test_s23_baseline_scope_excludes_games_after_the_confirmed_cutoff():
    games = [
        {"id": "confirmed-game", "date": "2026-11-03"},
        {"id": "future-game", "date": "2026-11-04"},
    ]
    payload = {"games": [
        {"game_id": "confirmed-game"}, {"game_id": "future-game"},
    ]}

    baseline_games, baseline_payload = _baseline_scope("S23", games, payload)

    assert [game["id"] for game in baseline_games] == ["confirmed-game"]
    assert [game["game_id"] for game in baseline_payload["games"]] == ["confirmed-game"]


def test_confirmed_baseline_blocks_legacy_rebuilders_without_changing_assets(monkeypatch):
    s22_path = ROOT / "website" / "assets" / "bluffs" / "S22.json"
    s23_path = ROOT / "website" / "assets" / "bluffs" / "S23.json"
    before = {path: path.read_bytes() for path in (s22_path, s23_path)}

    monkeypatch.setattr(build_bluff_inference, "build",
                        lambda **kwargs: pytest.fail("S22 推断重建不应运行"))
    monkeypatch.setattr(sys, "argv", ["build_bluff_inference.py"])
    with pytest.raises(SystemExit) as s22_error:
        build_bluff_inference.main()
    assert s22_error.value.code == 2

    monkeypatch.setattr(build_s23_bluff_publication, "build_payload",
                        lambda *args, **kwargs: pytest.fail("S23 推断重建不应运行"))
    assert build_s23_bluff_publication.main(["--output", str(s23_path)]) == 2
    assert s22_path.read_bytes() == before[s22_path]
    assert s23_path.read_bytes() == before[s23_path]

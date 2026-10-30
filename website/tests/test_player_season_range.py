from __future__ import annotations

from importlib import import_module

import pytest
from fastapi.testclient import TestClient


api = import_module("website.api.app")


def _snapshot(game_id: str, season: str, date: str, person_id: str | None) -> dict:
    seats = ([{"seat": 1, "person_id": person_id, "name": "Player", "role": "平民", "faction": "good"}]
             if person_id else [])
    players = ([{"id": person_id, "name": "Player", "seat": 1, "role": "平民", "faction": "good"}]
               if person_id else [])
    return {
        "id": game_id, "season": season, "date": date, "phase": "regular", "game_number": 1,
        "board": {"code": "test", "name": "测试版型"}, "winner": "good", "seats": seats,
        "players": players, "ballot_count": 0, "round_count": 0, "data_notes": [],
    }


@pytest.fixture
def client(monkeypatch):
    snapshots = {
        "S22": [
            _snapshot("s22-player", "S22", "2026-06-01", "p"),
            _snapshot("s22-other", "S22", "2026-06-02", None),
        ],
        "S23": [
            _snapshot("s23-player", "S23", "2026-07-01", "p"),
            _snapshot("s23-other", "S23", "2026-07-02", None),
        ],
    }
    monkeypatch.setattr(api, "_release", lambda conn: {"id": "release"})
    monkeypatch.setattr(api, "_available_seasons", lambda conn, release_id: ["S22", "S23"])
    monkeypatch.setattr(api, "_scope_snapshots", lambda conn, release_id, season, phase="all": snapshots[season])
    monkeypatch.setattr(api, "read_review", lambda conn, release_id, season: {
        "season": season, "inference_version": f"review-{season}",
    })

    def fake_aggregate_bluffs(games, payload):
        assert all(game["season"] == payload["season"] for game in games)
        if not any(seat.get("person_id") == "p" for game in games for seat in game["seats"]):
            return {}
        denominator = 1 if payload["season"] == "S22" else 2
        numerator = 1 if payload["season"] == "S22" else 0
        return {"p": {
            "bluff_count": 1, "bluff_count_complete": True, "bluff_pending_games": 0,
            "bluff_review_count": 0, "bluff_success_rate": {
                "numerator": numerator, "denominator": denominator,
                "rate": numerator / denominator, "excluded": 0,
                "game_ids": [f"{payload['season']}-bluff"],
            },
        }}

    monkeypatch.setattr(api, "aggregate_bluffs", fake_aggregate_bluffs)
    monkeypatch.setattr(api, "photo_for", lambda name, season: {"season": season})

    class Cursor:
        def fetchone(self):
            return {"id": "p", "name": "Player"}

    class Connection:
        def execute(self, query, params=None):
            return Cursor()

    api.app.dependency_overrides[api.connection_dependency] = lambda: Connection()
    try:
        with TestClient(api.app) as test_client:
            yield test_client
    finally:
        api.app.dependency_overrides.pop(api.connection_dependency, None)


def test_player_games_are_newest_first_with_unknown_game_numbers_last(client, monkeypatch):
    snapshots = [
        {**_snapshot("first", "S23", "2026-07-02", "p"), "game_number": 1},
        {**_snapshot("unknown", "S23", "2026-07-02", "p"), "game_number": None},
        {**_snapshot("fourth", "S23", "2026-07-02", "p"), "game_number": 4},
        {**_snapshot("third", "S23", "2026-07-02", "p"), "game_number": 3},
        {**_snapshot("older", "S23", "2026-07-01", "p"), "game_number": 4},
    ]
    monkeypatch.setattr(api, "_scope_snapshots", lambda *args, **kwargs: snapshots)
    response = client.get("/api/v1/players/p?season=S23")
    assert response.status_code == 200
    assert [game["id"] for game in response.json()["games"]] == [
        "fourth", "third", "first", "unknown", "older",
    ]


def test_player_range_resolves_latest_and_aggregates_season_local_bluff_metrics(client):
    response = client.get("/api/v1/players/p?season_start=S22&season_end=latest")

    assert response.status_code == 200
    detail = response.json()
    assert detail["scope"]["season_start"] == "S22"
    assert detail["scope"]["season_end"] == "S23"
    assert detail["scope"]["seasons"] == ["S22", "S23"]
    assert detail["scope"]["games"] == 4
    assert detail["stats"]["attendance"]["numerator"] == 2
    assert detail["stats"]["attendance"]["denominator"] == 4
    assert detail["boards"] == [{"code": "test", "name": "测试版型", "count": 2}]
    assert detail["stats"]["boards"] == [{
        "code": "test", "name": "测试版型", "appearances": 2,
        "wins": 2, "losses": 0, "pending_games": 0, "win_rate": 1.0,
        "metric": {
            "numerator": 2, "denominator": 2, "rate": 1.0, "excluded": 0,
            "game_ids": ["s22-player", "s23-player"],
            "samples": [
                {"game_id": "s22-player", "positive": 1, "negative": 0},
                {"game_id": "s23-player", "positive": 1, "negative": 0},
            ],
        },
        "ranking": {"rank": 1, "total": 1, "tied": False},
        "ranking_board": [{
            "id": "p", "name": "Player", "rank": 1, "tied": False,
            "value": 1.0, "sample_count": 2, "appearances": 2,
        }],
    }]
    assert [row["season"] for row in detail["stats"]["ledger"]] == ["S22", "S23"]
    assert detail["stats"]["rankings"]["total_win_rate"] == {"rank": 1, "total": 1, "tied": False}
    assert set(detail["stats"]["ranking_boards"]) == set(detail["stats"]["rankings"])
    assert detail["stats"]["ranking_boards"]["total_win_rate"] == [{
        "id": "p", "name": "Player", "rank": 1, "tied": False,
        "value": 1.0, "sample_count": 2, "appearances": 2,
    }]
    assert detail["stats"]["roles"][0]["ranking"] == {"rank": 1, "total": 1, "tied": False}
    assert detail["stats"]["roles"][0]["ranking_board"] == [{
        "id": "p", "name": "Player", "rank": 1, "tied": False,
        "value": 1.0, "sample_count": 2, "appearances": 2,
    }]
    assert detail["stats"]["roles"][0]["metric"]["samples"] == [
        {"game_id": "s22-player", "positive": 1, "negative": 0},
        {"game_id": "s23-player", "positive": 1, "negative": 0},
    ]
    metric = detail["stats"]["bluff_success_rate"]
    assert metric["numerator"] == 1 and metric["denominator"] == 3
    assert metric["rate"] == 1 / 3
    assert detail["bluff_inference_version"] == "S22: review-S22, S23: review-S23"
    assert detail["photo"]["season"] == "S23"


def test_player_default_season_stays_compatible_and_invalid_ranges_are_rejected(client):
    default = client.get("/api/v1/players/p")
    assert default.status_code == 200
    assert default.json()["scope"]["season"] == "S22"
    assert default.json()["scope"]["seasons"] == ["S22"]

    assert client.get("/api/v1/players/p?season_start=S24&season_end=latest").status_code == 422
    assert client.get("/api/v1/players/p?season_start=S23&season_end=S22").status_code == 422


def test_stats_share_player_season_range_and_keep_single_season_compatibility(client):
    all_seasons = client.get("/api/v1/stats")
    assert all_seasons.status_code == 200
    all_stats = all_seasons.json()
    assert all_stats["scope"] == {
        "season": "S23", "season_start": "S22", "season_end": "S23",
        "seasons": ["S22", "S23"], "phase": "all", "games": 4,
    }
    assert all_stats["available_seasons"] == ["S22", "S23"]
    assert all_stats["game_count"] == 4
    assert all_stats["roles"] == [{"role": "平民", "count": 2}]
    assert all_stats["boards"] == [{
        "code": "test", "name": "测试版型", "games": 4,
        "good_wins": 4, "werewolf_wins": 0, "unknown": 0,
    }]
    assert all_stats["players"] == [{
        "id": "p", "name": "Player", "appearances": 2,
        "roles": [{"role": "平民", "count": 2}], "stats": None, "photo": None,
    }]

    latest_only = client.get("/api/v1/stats?season_start=S23&season_end=latest").json()
    assert latest_only["scope"]["seasons"] == ["S23"]
    assert latest_only["game_count"] == 2
    assert latest_only["roles"] == [{"role": "平民", "count": 1}]
    assert latest_only["boards"][0]["games"] == 2
    assert latest_only["players"][0]["appearances"] == 1

    legacy = client.get("/api/v1/stats?season=S22").json()
    assert legacy["scope"]["seasons"] == ["S22"]
    assert legacy["game_count"] == 2
    assert legacy["boards"][0]["games"] == 2
    assert client.get("/api/v1/stats?season_start=S24&season_end=latest").status_code == 422
    assert client.get("/api/v1/stats?season_start=S23&season_end=S22").status_code == 422

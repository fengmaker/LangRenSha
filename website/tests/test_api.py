from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from website.api.app import app
from website.api.publisher import _connect


@pytest.fixture(scope="module")
def client():
    try:
        conn = _connect("masters_web")
        has_release = conn.execute("SELECT EXISTS(SELECT 1 FROM active_release)").fetchone()["exists"]
        conn.close()
    except Exception as exc:  # pragma: no cover - depends on local PostgreSQL availability
        pytest.skip(f"masters_web integration database is unavailable: {type(exc).__name__}")
    if not has_release:
        pytest.skip("Publish a sample release before running the API integration tests")
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("path,collection", [
    ("/api/v1/games?page_size=100", "items"),
    ("/api/v1/games?season=S21&page_size=100", "items"),
    ("/api/v1/overview", "recent_games"),
])
def test_game_lists_order_newest_date_and_highest_game_number_first(client, path, collection):
    response = client.get(path)
    assert response.status_code == 200
    items = response.json()[collection]
    keys = [(item["date"], item["game_number"] if item["game_number"] is not None else -1)
            for item in items]
    assert keys == sorted(keys, reverse=True)


def test_read_only_contract_filtering_pagination_and_details(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    overview_response = client.get("/api/v1/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    release_id = overview["release"]["id"]
    assert overview["totals"]["games"] == overview["release"]["game_count"]
    assert overview["totals"]["days"] == len({
        game["date"] for page in range(1, (overview["totals"]["games"] + 99) // 100 + 1)
        for game in client.get(f"/api/v1/games?page={page}&page_size=100").json()["items"]
    })

    first_page = client.get("/api/v1/games?page=1&page_size=1").json()
    assert first_page["release_id"] == release_id
    assert first_page["page"] == 1 and first_page["page_size"] == 1
    assert len(first_page["items"]) == 1
    sample = first_page["items"][0]
    second_page = client.get("/api/v1/games?page=2&page_size=1").json()
    assert second_page["total"] == first_page["total"]
    assert second_page["page"] == 2 and len(second_page["items"]) <= 1

    board_filtered = client.get(f"/api/v1/games?season={sample['season']}&board={sample['board']['code']}").json()
    assert board_filtered["total"] >= 1
    assert all(item["board"]["code"] == sample["board"]["code"] for item in board_filtered["items"])
    player = sample["players"][0]
    player_filtered = client.get(f"/api/v1/games?player={player['id']}").json()
    assert player_filtered["total"] >= 1
    assert all(any(row["id"] == player["id"] for row in game["players"])
               for game in player_filtered["items"])

    detail_response = client.get(f"/api/v1/games/{sample['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["release_id"] == release_id
    assert detail["source"]["bvid"]
    assert all("slot_label" in event and "description" in event
               for round_ in detail["rounds"] for phase in ("night", "day") for event in round_[phase])

    players = client.get("/api/v1/players?page_size=1").json()
    assert len(players["items"]) == 1
    person = players["items"][0]
    player_detail = client.get(f"/api/v1/players/{person['id']}")
    assert player_detail.status_code == 200
    assert player_detail.json()["release_id"] == release_id
    assert player_detail.json()["appearances"] == person["appearances"]

    stats = client.get(f"/api/v1/stats?season={sample['season']}")
    assert stats.status_code == 200
    assert stats.json()["game_count"] >= 1
    assert any("个人胜率" in note for note in stats.json()["methodology"])
    releases = client.get("/api/v1/releases").json()["items"]
    assert any(item["id"] == release_id and item["active"] for item in releases)


def test_invalid_inputs_and_missing_ids_use_http_errors(client):
    assert client.get("/api/v1/games?page=0").status_code == 422
    assert client.get("/api/v1/games?page_size=101").status_code == 422
    assert client.get("/api/v1/games/not-a-published-game").status_code == 404
    assert client.get("/api/v1/players/not-a-published-person").status_code == 404


def test_bluff_review_and_season_metrics_are_consistent_and_do_not_export_local_paths(client):
    board = client.get("/api/v1/leaderboard").json()
    finals = client.get("/api/v1/leaderboard?phase=finals_week").json()
    by_id = {row["id"]: row for row in board["items"]}
    fields = ("bluff_count", "bluff_count_complete", "bluff_pending_games",
              "bluff_review_count", "bluff_success_rate")
    for row in finals["items"]:
        for key in fields:
            assert row[key] == by_id[row["id"]][key]
    if board["items"]:
        row = board["items"][0]
        detail = client.get(f"/api/v1/players/{row['id']}").json()
        for key in fields:
            assert detail["stats"][key] == row[key]
    review = client.get("/api/v1/bluff-review?status=all").json()
    assert review["summary"]["games"] == board["game_count"]
    assert review["analytics_version"] >= 3
    import json
    body = json.dumps(review, ensure_ascii=False)
    assert '"source_path"' not in body
    assert "D:\\\\" not in body and ".secrets" not in body
    assert client.get("/api/v1/bluff-review?status=invalid").status_code == 422


def test_published_bluff_data_does_not_depend_on_local_review_files(client, monkeypatch, tmp_path):
    from website.api import bluffs

    before = client.get("/api/v1/bluff-review?status=all").json()
    if not before.get("inference_version"):
        pytest.skip("Publish bluff review data before checking the database-backed API")
    monkeypatch.setattr(bluffs, "ASSET_ROOT", tmp_path)
    bluffs.load_review.cache_clear()
    assert bluffs.load_review("S22") == {"games": []}
    after = client.get("/api/v1/bluff-review?status=all").json()
    assert after == before
    assert after["bluff_data_source"] == "database"
    board = client.get("/api/v1/leaderboard").json()
    assert board["bluff_data_source"] == "database"
    assert board["bluff_inference_version"] == after["inference_version"]
    assert sum(row["bluff_count"] for row in board["items"]) == after["summary"]["identified_bluffs"]
    if board["items"]:
        detail = client.get(f"/api/v1/players/{board['items'][0]['id']}").json()
        assert detail["bluff_data_source"] == "database"
        assert detail["bluff_inference_version"] == after["inference_version"]
    bluffs.load_review.cache_clear()

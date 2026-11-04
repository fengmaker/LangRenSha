import builtins
import copy
import json

import pytest

from website.static_publish import check_static as checker
from website.tests.test_incremental_acceptance import _api_fixture
from website.tests.test_static_acceptance import _snapshot, _write_json


def _scope_fixture(tmp_path):
    out = _snapshot(tmp_path)
    snapshot = checker._load_snapshot(out, "/example-site")
    docs = checker._read_documents(snapshot)
    snapshot["seasons"] = ["S20", "S21"]
    games = [{**docs["games_index"]["items"][0], "id": f"game-{index}",
              "season": "S20" if index < 50 else "S21"} for index in range(100)]
    players = [{"id": f"player-{index}", "name": f"选手{index}"} for index in range(100)]
    docs["games_index"]["items"] = games
    docs["players_index"]["items"] = players
    for season in snapshot["seasons"]:
        _write_json(snapshot["data"] / "players/by-season" / f"{season}.json", {"items": players})
        _write_json(snapshot["data"] / "bluff-review" / f"{season}.json", {"items": []})
    files = {}
    for game in games:
        files[f"games/{game['id']}.json"] = {"input_hash": game["id"], "sha256": "old"}
    for player in players:
        for season in snapshot["seasons"]:
            files[f"players/{player['id']}/{season}--{season}.json"] = {
                "input_hash": player["id"] + season, "sha256": "old"}
    index = {"metadata": {"release_id": "old-release", "content_fingerprints": {
        "implementation": "same", "games": {game["id"]: game["id"] for game in games},
        "seasons": {season: season for season in snapshot["seasons"]},
    }}, "files": files}
    return snapshot, docs, index


def test_default_browser_scope_stays_small_without_previous_baseline(tmp_path):
    snapshot, docs, index = _scope_fixture(tmp_path)

    routes, mobile = checker._browser_routes(snapshot, docs, index)

    assert len(routes) <= 11
    assert routes == mobile
    assert {"/", "/games", "/players", "/stats", "/leaderboard", "/leaderboard/bluff-review"} <= set(routes)
    assert [route for route in routes if route.startswith("/games/")] == ["/games/game-0"]
    assert len([route for route in routes if route.startswith("/players/")]) == 1
    assert "/seasons/S20" not in routes


def test_release_rebinding_does_not_expand_browser_routes_to_all_players(tmp_path):
    snapshot, docs, previous = _scope_fixture(tmp_path)
    current = copy.deepcopy(previous)
    current["metadata"]["release_id"] = "new-release"
    for entry in current["files"].values():
        entry["sha256"] = "new-release-bound-content"

    routes, mobile = checker._browser_routes(snapshot, docs, current, previous)

    assert checker._affected_browser_scope(current, previous) == {
        "games": set(), "seasons": set(), "players": set()}
    assert len(routes) <= 11
    assert routes == mobile


def test_smoke_covers_special_season_page_without_data_changes(tmp_path):
    snapshot, docs, index = _scope_fixture(tmp_path)
    snapshot["seasons"].append("S23")
    _write_json(snapshot["data"] / "bluff-review/S23.json", {"items": []})
    _write_json(snapshot["data"] / "players/by-season/S23.json", {"items": []})

    routes, mobile = checker._browser_routes(snapshot, docs, index, index)

    assert "/seasons/S23/bluff-review" in routes
    assert "/seasons/S23/bluff-review" in mobile
    assert len(routes) <= 12


def test_implementation_change_keeps_game_checks_representative(tmp_path):
    snapshot, docs, previous = _scope_fixture(tmp_path)
    current = copy.deepcopy(previous)
    current["metadata"]["content_fingerprints"]["implementation"] = "new-implementation"
    for entry in current["files"].values():
        entry["input_hash"] += "new-implementation"

    routes, _ = checker._browser_routes(snapshot, docs, current, previous)

    assert [route for route in routes if route.startswith("/games/")] == ["/games/game-0"]
    assert len([route for route in routes if route.startswith("/players/")]) == 1


def test_update_visits_each_changed_game_and_representative_affected_pages(tmp_path):
    snapshot, docs, previous = _scope_fixture(tmp_path)
    current = copy.deepcopy(previous)
    for game_id in ["game-5", "game-6"]:
        current["metadata"]["content_fingerprints"]["games"][game_id] = "changed"
        current["files"][f"games/{game_id}.json"]["input_hash"] = "changed"
    current["metadata"]["content_fingerprints"]["seasons"]["S20"] = "changed"
    for path, entry in current["files"].items():
        if path.startswith("players/") and path.endswith("S20--S20.json"):
            entry["input_hash"] += "changed"

    routes, mobile = checker._browser_routes(snapshot, docs, current, previous)

    assert {"/games/game-5", "/games/game-6", "/seasons/S20", "/players?season=S20",
            "/stats?season_start=S20&season_end=S20", "/leaderboard?season=S20",
            "/leaderboard/bluff-review?season=S20&status=all"} <= set(routes)
    assert len([route for route in routes if route.startswith("/players/")]) == 2
    assert "/games/game-5" not in mobile
    assert "/games/game-7" not in routes
    assert not any("season=S21" in route for route in routes)


def test_new_game_and_player_are_selected_but_removed_game_has_no_route(tmp_path):
    snapshot, docs, previous = _scope_fixture(tmp_path)
    current = copy.deepcopy(previous)
    previous["metadata"]["content_fingerprints"]["games"].pop("game-99")
    previous["files"].pop("games/game-99.json")
    previous["metadata"]["content_fingerprints"]["games"]["removed"] = "old"
    current["files"]["players/player-99/S21--S21.json"]["input_hash"] = "new-player"

    routes, _ = checker._browser_routes(snapshot, docs, current, previous)

    assert "/games/game-99" in routes
    assert any(route.startswith("/players/player-99?") for route in routes)
    assert "/games/removed" not in routes


def test_bluff_publication_rebind_selects_its_season_when_content_fingerprints_are_unchanged(tmp_path):
    snapshot, docs, previous = _scope_fixture(tmp_path)
    previous["metadata"]["bluff_publications"] = [
        {"season": "S20", "publication_id": "old", "payload_hash": "payload"}]
    current = copy.deepcopy(previous)
    current["metadata"]["bluff_publications"][0]["publication_id"] = "new"

    routes, _ = checker._browser_routes(snapshot, docs, current, previous)

    assert {"/seasons/S20", "/leaderboard?season=S20",
            "/leaderboard/bluff-review?season=S20&status=all"} <= set(routes)
    assert any(route.startswith("/players/") and "season_start=S20&season_end=S20" in route for route in routes)
    assert [route for route in routes if route.startswith("/games/")] == ["/games/game-0"]


@pytest.mark.parametrize("kind", ["player-photos", "bluff-frames"])
def test_media_only_change_selects_its_season_without_all_games(tmp_path, kind):
    snapshot, docs, previous = _scope_fixture(tmp_path)
    previous["metadata"]["media_assets"] = [{"url": f"/media/{kind}/S20/old.png", "sha256": "old"}]
    current = copy.deepcopy(previous)
    current["metadata"]["media_assets"] = [{"url": f"/media/{kind}/S20/new.png", "sha256": "new"}]

    routes, _ = checker._browser_routes(snapshot, docs, current, previous)

    assert "/seasons/S20" in routes
    assert "/players?season=S20" in routes
    assert "/leaderboard/bluff-review?season=S20&status=all" in routes
    assert [route for route in routes if route.startswith("/games/")] == ["/games/game-0"]


def test_smoke_selects_visible_photo_and_evidence_samples_outside_the_latest_season(tmp_path):
    snapshot, docs, index = _scope_fixture(tmp_path)
    _write_json(snapshot["data"] / "players/by-season/S20.json", {
        "items": [{"id": "player-0", "photo": {"url": "/media/player-photos/S20/photo.png"}}]})
    _write_json(snapshot["data"] / "bluff-review/S20.json", {
        "items": [{"frame": "/media/bluff-frames/S20/frame.png"}]})

    routes, mobile = checker._browser_routes(snapshot, docs, index)

    assert "/players?season=S20" in routes
    assert "/leaderboard/bluff-review?season=S20&status=all" in routes
    assert routes == mobile
    assert len(routes) <= 12


def test_skip_browser_still_checks_structure_api_bindings_and_versions(monkeypatch, tmp_path):
    out = _snapshot(tmp_path)
    _snapshot_state, _docs, _binding, index, api_calls, get_json = _api_fixture(out)
    monkeypatch.setattr(checker, "_get_json", get_json)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert not name.startswith("playwright"), "skip must not import Playwright"
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(checker, "_browser_check", lambda *_: pytest.fail("skip must not launch a browser"))
    report_path = tmp_path / "acceptance.json"

    report = checker.check(out, "/example-site", "http://api.test", export_index=index,
                           skip_browser_check=True, output=report_path)

    assert report["state"] == "passed"
    assert report["complete"] is True
    assert report["layers"]["structure"]["routes_checked"] == 9
    assert report["layers"]["api"]["export_manifest"]["bindings_checked"] is True
    assert report["layers"]["browser"]["state"] == "skipped"
    assert report["layers"]["browser"]["routes_checked"] == 0
    assert any(path == "/api/v1/export-manifest" for path, _query in api_calls)
    assert json.loads(report_path.read_text(encoding="utf-8"))["layers"]["browser"]["state"] == "skipped"


@pytest.mark.parametrize("relative", ["games/game-1.json", "players/player-1/S21--S21.json",
                                      "stats/S21--S21.json", "players/by-season/S21.json"])
def test_skip_browser_still_rejects_missing_required_data(monkeypatch, tmp_path, relative):
    out = _snapshot(tmp_path)
    (out / "data/releases/snapshot-1" / relative).unlink()
    monkeypatch.setattr(checker, "_browser_check", lambda *_: pytest.fail("skip must not launch a browser"))

    with pytest.raises(checker.StaticAcceptanceError):
        checker.check(out, "/example-site", "http://api.test", skip_browser_check=True)


def test_skip_browser_still_rejects_api_version_mismatch(monkeypatch, tmp_path):
    out = _snapshot(tmp_path)
    _snapshot_state, _docs, binding, _index, _calls, get_json = _api_fixture(out)
    binding["analytics_version"] += 1
    monkeypatch.setattr(checker, "_get_json", get_json)

    with pytest.raises(checker.StaticAcceptanceError, match="source or analytics version"):
        checker.check(out, "/example-site", "http://api.test", skip_browser_check=True)


def test_cli_forwards_explicit_browser_skip(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(checker, "check", lambda *args, **kwargs: calls.append(kwargs) or {
        "state": "passed", "mode": "full", "complete": True, "snapshot_id": "snapshot",
        "duration_seconds": 0, "layers": {"browser": {"routes_checked": 0}},
    })

    assert checker.main(["--out", str(tmp_path), "--base-path", "/example-site",
                         "--api-url", "http://api.test", "--skip-browser-check"]) == 0
    assert calls[0]["skip_browser_check"] is True

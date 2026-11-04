import hashlib
import json
from types import SimpleNamespace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

import website.check_static as checker
from website.check_static import (
    StaticAcceptanceError,
    _check_player_rankings,
    _check_site_size,
    _load_snapshot,
    _exercise_games_pagination,
    _expected_game_page_ids,
    _record_request_failure,
    _select_player_range_target,
    _serve,
    _check_threshold_projection,
    _structure_check,
    _read_documents,
)


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _snapshot(tmp_path: Path, *, broken_hash: bool = False):
    out = tmp_path / "out"
    data = out / "data" / "releases" / "snapshot-1"
    media = b"fixture image bytes"
    media_hash = hashlib.sha256(media).hexdigest()
    photo_name = ("0" * 64 if broken_hash else media_hash) + ".png"
    media_path = out / "media" / "player-photos" / "S21" / photo_name
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(media)

    summary = {
        "id": "game-1", "season": "S21", "date": "2026-01-01", "phase": "regular",
        "game_number": 1, "board": {"code": "board-1", "name": "版型"}, "winner": "good",
        "players": [{"id": "player-1", "name": "选手甲", "seat": 1}],
        "ballot_count": 1, "round_count": 1, "search_text": "BVfixture 选手甲",
    }
    profile_photo = {"season": "S21", "url": f"/media/player-photos/S21/{photo_name}"}
    player_summary = {"id": "player-1", "name": "选手甲", "appearances": 1,
                      "roles": [], "photo": profile_photo}
    _write_json(data / "overview.json", {
        "release": {"id": "release-1", "source_hash": "source-hash"},
        "totals": {"games": 1}, "seasons": [{"id": "S21", "games": 1}],
        "boards": [], "recent_games": [summary],
    })
    _write_json(data / "releases.json", {"items": [{"id": "release-1", "active": True}]})
    _write_json(data / "games" / "index.json", {
        "release_id": "release-1", "total": 1, "items": [summary],
    })
    _write_json(data / "games" / "game-1.json", {**summary, "release_id": "release-1"})
    _write_json(data / "players" / "index.json", {
        "release_id": "release-1", "seasons": ["S21"], "items": [{"id": "player-1", "name": "选手甲"}],
    })
    _write_json(data / "players" / "by-season" / "S21.json", {
        "release_id": "release-1", "total": 1, "page": 1, "page_size": 100,
        "items": [player_summary],
    })
    _write_json(data / "players" / "player-1" / "S21--S21.json", {
        "release_id": "release-1", "id": "player-1", "name": "选手甲", "appearances": 1,
        "scope": {"minimum_appearances": 0}, "stats": {"appearances": 1},
    })
    _write_json(data / "stats" / "S21--S21.json", {
        "release_id": "release-1", "scope": {"seasons": ["S21"]},
    })
    _write_json(data / "leaderboards" / "S21" / "all.json", {
        "release_id": "release-1", "season": "S21", "items": [],
    })
    _write_json(data / "bluff-review" / "S21.json", {
        "release_id": "release-1", "season": "S21", "items": [],
    })
    counts = {"games": 1, "players": 1, "game_details": 1, "player_ranges": 1,
              "stats_ranges": 1, "leaderboards": 1, "bluff_reviews": 1, "media_files": 1}
    _write_json(out / "data" / "manifest.json", {
        "schema_version": 1, "snapshot_id": "snapshot-1", "build_id": "build-1",
        "release_id": "release-1", "source_hash": "source-hash", "analytics_version": 1,
        "bluff_publications": [{"season": "S21", "publication_id": None, "payload_hash": None}],
        "media_manifest_hashes": {"player_photos": "a" * 64, "bluff_frames": "b" * 64},
        "generated_at": "2026-11-04T00:00:00Z", "base_path": "/example-site",
        "seasons": [{"id": "S21", "game_count": 1, "phases": ["regular"]}],
        "ranges": [{"start": "S21", "end": "S21", "seasons": ["S21"]}],
        "counts": counts, "complete": True,
        "partial": {"enabled": False, "season": None, "game_id": None, "player_id": None},
    })
    for route in ["", "games", "games/game-1", "players", "players/player-1", "seasons/S21",
                  "stats", "leaderboard", "leaderboard/bluff-review"]:
        html = out / route / "index.html" if route else out / "index.html"
        html.parent.mkdir(parents=True, exist_ok=True)
        content = "<html><main><h1>选手甲</h1></main></html>" if route == "players/player-1" else "<html><main>fixture</main></html>"
        html.write_text(content, encoding="utf-8")
    return out


def test_structure_checks_full_route_range_count_and_content_addressed_media(tmp_path):
    out = _snapshot(tmp_path)
    snapshot = _load_snapshot(out, "/example-site")
    docs = _read_documents(snapshot)

    result = _structure_check(snapshot, docs)

    assert result["state"] == "passed"
    assert result["routes_checked"] == 9
    assert result["media_references_checked"] == 1
    assert result["hashes_checked"] == 1


def test_structure_rejects_media_content_that_does_not_match_filename_hash(tmp_path):
    out = _snapshot(tmp_path, broken_hash=True)
    snapshot = _load_snapshot(out, "/example-site")
    docs = _read_documents(snapshot)

    with pytest.raises(StaticAcceptanceError, match="content hash"):
        _structure_check(snapshot, docs)


def test_structure_requires_player_profile_name_in_server_rendered_heading(tmp_path):
    out = _snapshot(tmp_path)
    player_page = out / "players" / "player-1" / "index.html"
    player_page.write_text("<html><main><h1>选手档案</h1></main></html>", encoding="utf-8")
    snapshot = _load_snapshot(out, "/example-site")

    with pytest.raises(StaticAcceptanceError, match="rendered <h1>"):
        _structure_check(snapshot, _read_documents(snapshot))


def test_structure_reads_player_heading_from_next_stream_segment(tmp_path):
    out = _snapshot(tmp_path)
    player_page = out / "players" / "player-1" / "index.html"
    player_page.write_text(
        "<main><div role='status'>正在加载页面…</div></main>"
        "<div id='S:0' style='display:none'><h1>选手甲</h1></div>", encoding="utf-8")
    snapshot = _load_snapshot(out, "/example-site")

    assert _structure_check(snapshot, _read_documents(snapshot))["state"] == "passed"


def test_manifest_rejects_contradictory_full_and_partial_flags(tmp_path):
    out = _snapshot(tmp_path)
    manifest_path = out / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["partial"]["enabled"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(StaticAcceptanceError, match="contradict"):
        _load_snapshot(out, "/example-site")


def test_partial_snapshot_is_reported_as_partial_and_still_runs_browser(monkeypatch, tmp_path):
    out = _snapshot(tmp_path)
    manifest_path = out / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["complete"] = False
    manifest["partial"] = {"enabled": True, "season": "S21", "game_id": "game-1", "player_id": "player-1"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    browser_calls = []
    monkeypatch.setattr(checker, "_structure_check", lambda *_: {"state": "passed"})
    monkeypatch.setattr(checker, "_api_check", lambda *_: {"state": "passed"})
    monkeypatch.setattr(checker, "_browser_check", lambda *args: browser_calls.append(args) or {"state": "passed"})

    report = checker.check(out, "/example-site", "http://127.0.0.1:8000")

    assert report["state"] == "partial"
    assert report["mode"] == "partial"
    assert report["complete"] is False
    assert len(browser_calls) == 1


@pytest.mark.parametrize("channel", [None, "chromium"])
def test_cli_accepts_builder_arguments_and_defaults_local_browser_to_chrome(monkeypatch, tmp_path, channel):
    calls = []
    report = {"state": "passed", "mode": "full", "complete": True, "snapshot_id": "s",
              "duration_seconds": 0.1, "layers": {"browser": {"routes_checked": 3}}}
    monkeypatch.setattr(checker, "check", lambda *args, **kwargs: calls.append((args, kwargs)) or report)
    args = ["--out", str(tmp_path), "--base-path", "/example-site", "--api-url", "http://127.0.0.1:8000"]
    if channel:
        args.extend(["--browser-channel", channel])

    assert checker.main(args) == 0
    assert calls[0][0][0] == tmp_path
    assert calls[0][1]["browser_channel"] == (channel or "chrome")


def test_static_server_serves_only_the_configured_subpath(tmp_path):
    out = tmp_path / "out"
    (out / "index.html").parent.mkdir(parents=True)
    (out / "index.html").write_text("subpath fixture", encoding="utf-8")
    server, thread = _serve(out, "/example-site")
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/example-site/") as response:
            assert response.read().decode() == "subpath fixture"
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{server.server_port}/")
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_site_size_enforces_github_pages_decimal_limit():
    _check_site_size(999_999_999)
    with pytest.raises(StaticAcceptanceError, match="< 1000000000 bytes"):
        _check_site_size(1_000_000_000)


def test_request_failure_classifier_only_counts_cancelled_document_navigation():
    failed_requests = []
    cancelled_document_navigations = []

    _record_request_failure(
        SimpleNamespace(resource_type="document", failure="net::ERR_ABORTED", url="https://site.test/games/"),
        failed_requests, cancelled_document_navigations)
    _record_request_failure(
        SimpleNamespace(resource_type="xhr", failure="net::ERR_ABORTED", url="https://site.test/data.json"),
        failed_requests, cancelled_document_navigations)
    _record_request_failure(
        SimpleNamespace(resource_type="image", failure="net::ERR_CONNECTION_RESET", url="https://site.test/media/photo.png"),
        failed_requests, cancelled_document_navigations)
    _record_request_failure(
        SimpleNamespace(resource_type="document", failure="net::ERR_CONNECTION_RESET", url="https://site.test/player/"),
        failed_requests, cancelled_document_navigations)

    assert cancelled_document_navigations == ["https://site.test/games/"]
    assert failed_requests == [
        "https://site.test/data.json (xhr; net::ERR_ABORTED)",
        "https://site.test/media/photo.png (image; net::ERR_CONNECTION_RESET)",
        "https://site.test/player/ (document; net::ERR_CONNECTION_RESET)",
    ]


def test_game_page_id_expectations_match_frontend_sort_and_24_row_boundary():
    games = [{"id": f"game-{index:02}", "date": "2026-01-01", "game_number": index}
             for index in range(26)]
    games.append({"id": "latest", "date": "2026-02-01", "game_number": 0})

    assert _expected_game_page_ids(games, 1) == ["latest"] + [f"game-{index:02}" for index in range(25, 2, -1)]
    assert _expected_game_page_ids(games, 2) == ["game-02", "game-01", "game-00"]


def test_partial_games_snapshot_reports_pagination_as_skipped(tmp_path):
    out = _snapshot(tmp_path)
    manifest_path = out / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["complete"] = False
    manifest["partial"] = {"enabled": True, "season": "S21", "game_id": "game-1", "player_id": "player-1"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    snapshot = _load_snapshot(out, "/example-site")

    result = _exercise_games_pagination(None, "", snapshot, {"games_index": {"items": [{"id": "game-1"}]}})

    assert result == {"state": "skipped", "reason": "partial snapshot has one exported game",
                      "matching_count": 1}


def test_player_range_target_selects_an_exported_alternate_with_changed_appearances(tmp_path):
    data = tmp_path / "data"
    profile_dir = data / "players" / "player-1"
    current_path = profile_dir / "S20--S20.json"
    _write_json(current_path, {"id": "player-1", "stats": {"appearances": 8}})
    _write_json(profile_dir / "S21--S21.json", {"id": "player-1", "stats": {"appearances": 3}})
    _write_json(profile_dir / "S20--S21.json", {"id": "player-1", "stats": {"appearances": 8}})
    snapshot = {"data": data, "seasons": ["S20", "S21"], "manifest": {
        "complete": True, "ranges": [
            {"start": "S20", "end": "S20"},
            {"start": "S21", "end": "S21"},
            {"start": "S20", "end": "S21"},
        ],
    }}

    target = _select_player_range_target(snapshot, current_path, {
        "id": "player-1", "appearances": 8, "available_seasons": ["S20", "S21"],
        "stats": {"appearances": 8},
    })

    assert target == profile_dir / "S21--S21.json"


@pytest.mark.parametrize("complete", [False, True])
def test_player_range_target_is_unavailable_when_snapshot_has_one_range(tmp_path, complete):
    data = tmp_path / "data"
    current_path = data / "players" / "player-1" / "S21--S21.json"
    _write_json(current_path, {"id": "player-1", "stats": {"appearances": 2}})
    snapshot = {"data": data, "seasons": ["S21"], "manifest": {
        "complete": complete, "ranges": [{"start": "S21", "end": "S21"}],
    }}

    assert _select_player_range_target(snapshot, current_path, {
        "id": "player-1", "appearances": 2, "available_seasons": ["S21"],
        "stats": {"appearances": 2},
    }) is None


def test_ranking_validation_checks_threshold_and_competition_rank_boundaries():
    stats = {"ranking_boards": {"total_win_rate": [
        {"rank": 1, "value": 0.8, "appearances": 10},
        {"rank": 1, "value": 0.8, "appearances": 8},
        {"rank": 3, "value": 0.6, "appearances": 5},
    ], "losses": [
        {"rank": 1, "value": 0, "appearances": 10},
        {"rank": 2, "value": 1, "appearances": 8},
    ]}}

    assert _check_player_rankings(stats, 5) == 5
    with pytest.raises(StaticAcceptanceError, match="below the appearance threshold"):
        _check_player_rankings(stats, 6)
    stats["ranking_boards"]["total_win_rate"][2]["rank"] = 2
    with pytest.raises(StaticAcceptanceError, match="Competition ranks"):
        _check_player_rankings(stats, 5)


def test_threshold_rank_projection_uses_total_appearances_for_role_boards():
    base = {
        "ranking_boards": {"total_win_rate": [
            {"id": "p1", "rank": 1, "tied": False, "value": 0.8, "appearances": 10, "sample_count": 3},
            {"id": "p2", "rank": 2, "tied": False, "value": 0.5, "appearances": 4, "sample_count": 1},
        ]},
        "rankings": {"total_win_rate": {"rank": 1, "total": 2, "tied": False}},
        "roles": [{"role": "预言家", "appearances": 1,
                   "ranking": {"rank": 1, "total": 2, "tied": False},
                   "ranking_board": [
                       {"id": "p1", "rank": 1, "tied": False, "value": 1.0, "appearances": 1, "sample_count": 1},
                       {"id": "p2", "rank": 2, "tied": False, "value": 0.5, "appearances": 2, "sample_count": 2},
                   ]}],
        "boards": [],
    }
    actual = {
        "ranking_boards": {"total_win_rate": [
            {"id": "p1", "rank": 1, "tied": False, "value": 0.8, "appearances": 10, "sample_count": 3},
        ]},
        "rankings": {"total_win_rate": {"rank": 1, "total": 1, "tied": False}},
        "roles": [{"role": "预言家", "appearances": 1,
                   "ranking": {"rank": 1, "total": 1, "tied": False},
                   "ranking_board": [
                       {"id": "p1", "rank": 1, "tied": False, "value": 1.0, "appearances": 1, "sample_count": 1},
                   ]}],
        "boards": [],
    }

    _check_threshold_projection(base, actual, "p1", 5, {"p1": 10, "p2": 4})

    actual["roles"][0]["ranking_board"].append(base["roles"][0]["ranking_board"][1])
    with pytest.raises(StaticAcceptanceError, match="minimum appearance"):
        _check_threshold_projection(base, actual, "p1", 5, {"p1": 10, "p2": 4})

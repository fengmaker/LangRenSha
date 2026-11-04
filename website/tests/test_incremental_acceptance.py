import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from website.static_publish import check_static as checker
from website.static_publish.export_static import input_hash_for_path
from website.tests.test_static_acceptance import _snapshot, _write_json


def _api_fixture(out: Path, *, reused: bool = True):
    snapshot = checker._load_snapshot(out, "/example-site")
    docs = checker._read_documents(snapshot)
    data = snapshot["data"]
    manifest = snapshot["manifest"]
    release_id = manifest["release_id"]
    media_url = next(iter(checker._snapshot_media_references(snapshot)))
    media_path = out / media_url
    media_hash = hashlib.sha256(media_path.read_bytes()).hexdigest()

    binding = {
        "release_id": release_id,
        "release": {"id": release_id, "source_hash": manifest["source_hash"]},
        "seasons": [{"season": "S21", "game_count": 1, "phases": ["regular"]}],
        "bluff_publications": manifest["bluff_publications"],
        "media_manifest_hashes": manifest["media_manifest_hashes"],
        "media_assets": [{"url": "/" + media_url, "sha256": media_hash}],
        "analytics_version": manifest["analytics_version"],
        "content_fingerprints": {"implementation": "a" * 64,
                                  "games": {"game-1": "b" * 64},
                                  "seasons": {"S21": "c" * 64}},
    }

    def update(relative, changes):
        path = data / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(changes)
        _write_json(path, value)

    update("games/game-1.json", {"analytics_version": 1})
    update("players/player-1/S21--S21.json", {
        "analytics_version": 1,
        "scope": {"season_start": "S21", "season_end": "S21", "seasons": ["S21"],
                  "minimum_appearances": 0},
        "bluff_publications": manifest["bluff_publications"],
    })
    update("stats/S21--S21.json", {
        "analytics_version": 1, "scope": {"season_start": "S21", "season_end": "S21", "seasons": ["S21"]},
    })
    update("leaderboards/S21/all.json", {
        "analytics_version": 1, "phase": "all", "bluff_publication_id": None,
        "bluff_payload_hash": None, "game_count": 1,
    })
    update("bluff-review/S21.json", {
        "analytics_version": 1, "status": "all", "bluff_publication_id": None,
        "bluff_payload_hash": None, "summary": {"games": 1},
    })

    response_paths = {
        "games/game-1.json", "players/player-1/S21--S21.json", "stats/S21--S21.json",
        "leaderboards/S21/all.json", "bluff-review/S21.json",
    }
    index_files = {}
    for path in sorted(data.rglob("*.json")):
        relative = path.relative_to(data).as_posix()
        if relative not in response_paths:
            index_files[relative] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "input_hash": hashlib.sha256(("fresh:" + relative).encode()).hexdigest(),
                "reused": False,
            }
            continue
        path = data / relative
        player_name = "选手甲" if relative.startswith("players/") else None
        input_hash = input_hash_for_path(relative, binding, player_name=player_name,
                                         available_seasons=["S21"])
        assert input_hash
        index_files[relative] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "input_hash": input_hash,
            "reused": reused,
        }
    index = {"schema_version": 1, "metadata": copy.deepcopy(binding), "files": index_files,
             "metrics": {"reused": len(index_files) if reused else 0}}

    calls = []
    release_doc = docs["releases"]
    overview_doc = docs["overview"]
    game_summary = docs["games_index"]["items"][0]
    player_by_season = json.loads((data / "players/by-season/S21.json").read_text(encoding="utf-8"))
    static_profile = json.loads((data / "players/player-1/S21--S21.json").read_text(encoding="utf-8"))
    static_stats = json.loads((data / "stats/S21--S21.json").read_text(encoding="utf-8"))
    static_board = json.loads((data / "leaderboards/S21/all.json").read_text(encoding="utf-8"))
    static_review = json.loads((data / "bluff-review/S21.json").read_text(encoding="utf-8"))

    def get_json(_api_url, request_path):
        parsed = urlsplit(request_path)
        query = parse_qs(parsed.query)
        calls.append((parsed.path, query))
        if parsed.path == "/api/v1/export-manifest":
            return binding
        if parsed.path == "/api/v1/releases":
            return release_doc
        if parsed.path == "/api/v1/overview":
            return overview_doc
        if parsed.path == "/api/v1/games":
            return {"release_id": release_id, "total": 1, "items": [game_summary]}
        if parsed.path == "/api/v1/games/game-1":
            return json.loads((data / "games/game-1.json").read_text(encoding="utf-8"))
        if parsed.path == "/api/v1/players":
            return {"release_id": release_id, "total": player_by_season["total"],
                    "items": player_by_season["items"]}
        if parsed.path == "/api/v1/players/player-1":
            threshold = int(query["minimum_appearances"][0])
            response = copy.deepcopy(static_profile)
            response["scope"]["minimum_appearances"] = threshold
            return response
        if parsed.path == "/api/v1/stats":
            return static_stats
        if parsed.path == "/api/v1/leaderboard":
            return static_board
        if parsed.path == "/api/v1/bluff-review":
            return static_review
        raise AssertionError(request_path)

    return snapshot, docs, binding, index, calls, get_json


def _run_api_check(monkeypatch, fixture, export_index):
    snapshot, docs, _binding, _index, calls, get_json = fixture
    monkeypatch.setattr(checker, "_get_json", get_json)
    report = checker._api_check(snapshot, docs, "http://api.test", export_index)
    return report, calls


def test_incremental_acceptance_skips_reused_file_comparisons_but_keeps_samples(monkeypatch, tmp_path):
    fixture = _api_fixture(_snapshot(tmp_path), reused=True)
    report, calls = _run_api_check(monkeypatch, fixture, fixture[3])

    assert report["api_file_comparisons"] == {
        "game_details": 0, "player_ranges": 0, "stats_ranges": 0,
        "leaderboards": 0, "bluff_reviews": 0, "total": 0,
    }
    assert report["input_fingerprint_reused"] == 5
    assert report["input_fingerprint_reused_by_kind"] == {
        "game_detail": 1, "player_range": 1, "stats_range": 1,
        "leaderboard": 1, "bluff_review": 1,
    }
    assert report["game_filters"]["queries"]
    assert report["player_ranking_samples"]
    assert any(path == "/api/v1/players/player-1" and query["minimum_appearances"] != ["0"]
               for path, query in calls)
    assert not any(path in {"/api/v1/games/game-1", "/api/v1/stats", "/api/v1/leaderboard",
                           "/api/v1/bluff-review"} for path, _query in calls)
    assert not any(path == "/api/v1/players/player-1" and query.get("minimum_appearances") == ["0"]
                   for path, query in calls)


def test_changed_file_is_compared_and_not_counted_as_fingerprint_reuse(monkeypatch, tmp_path):
    fixture = _api_fixture(_snapshot(tmp_path), reused=True)
    index = copy.deepcopy(fixture[3])
    index["files"]["games/game-1.json"]["reused"] = False
    report, calls = _run_api_check(monkeypatch, fixture, index)

    assert report["game_details_checked"] == 1
    assert report["game_details_api_compared"] == 1
    assert report["input_fingerprint_reused"] == 4
    assert report["api_file_comparisons"]["total"] == 1
    assert any(path == "/api/v1/games/game-1" for path, _query in calls)


def test_reused_file_with_wrong_sha_is_rejected(monkeypatch, tmp_path):
    fixture = _api_fixture(_snapshot(tmp_path), reused=True)
    index = copy.deepcopy(fixture[3])
    index["files"]["games/game-1.json"]["sha256"] = "0" * 64
    with pytest.raises(checker.StaticAcceptanceError, match="SHA-256 differs"):
        _run_api_check(monkeypatch, fixture, index)


def test_reused_file_with_wrong_input_hash_is_rejected(monkeypatch, tmp_path):
    fixture = _api_fixture(_snapshot(tmp_path), reused=True)
    index = copy.deepcopy(fixture[3])
    index["files"]["games/game-1.json"]["input_hash"] = "0" * 64
    with pytest.raises(checker.StaticAcceptanceError, match="input_hash differs"):
        _run_api_check(monkeypatch, fixture, index)


def test_reused_file_with_wrong_manifest_binding_is_rejected(monkeypatch, tmp_path):
    out = _snapshot(tmp_path)
    fixture = _api_fixture(out, reused=True)
    index = copy.deepcopy(fixture[3])
    detail_path = fixture[0]["data"] / "games/game-1.json"
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    detail["release_id"] = "stale-release"
    _write_json(detail_path, detail)
    index["files"]["games/game-1.json"]["sha256"] = hashlib.sha256(detail_path.read_bytes()).hexdigest()

    with pytest.raises(checker.StaticAcceptanceError, match="manifest binding differs"):
        _run_api_check(monkeypatch, fixture, index)


def test_index_metadata_must_match_current_api_metadata(monkeypatch, tmp_path):
    fixture = _api_fixture(_snapshot(tmp_path), reused=True)
    index = copy.deepcopy(fixture[3])
    index["metadata"]["content_fingerprints"]["implementation"] = "d" * 64

    with pytest.raises(checker.StaticAcceptanceError, match="metadata differs"):
        _run_api_check(monkeypatch, fixture, index)


def test_invalid_index_schema_is_rejected_instead_of_silently_using_full_checks(monkeypatch, tmp_path):
    fixture = _api_fixture(_snapshot(tmp_path), reused=True)
    index = copy.deepcopy(fixture[3])
    index.pop("schema_version")

    with pytest.raises(checker.StaticAcceptanceError, match="invalid schema"):
        _run_api_check(monkeypatch, fixture, index)


def test_missing_incremental_index_keeps_full_file_api_comparisons(monkeypatch, tmp_path):
    fixture = _api_fixture(_snapshot(tmp_path), reused=True)
    report, calls = _run_api_check(monkeypatch, fixture, None)

    assert report["input_fingerprint_reused"] == 0
    assert report["api_file_comparisons"]["total"] == 5
    assert report["game_details_checked"] == 1
    assert report["player_ranges_checked"] == 1
    assert report["stats_ranges_checked"] == 1
    assert len(report["leaderboards_checked"]) == 1
    assert len(report["bluff_reviews_checked"]) == 1
    assert any(path == "/api/v1/games/game-1" for path, _query in calls)
    assert any(path == "/api/v1/stats" for path, _query in calls)


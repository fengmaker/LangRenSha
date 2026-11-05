import hashlib
import json

import pytest

from website.static_publish.export_static import ExportError
from website.tests.test_incremental_export import FakePublishedAPI, _export, _index, _release_json


@pytest.fixture
def ranking_api(monkeypatch):
    api = FakePublishedAPI()
    request = api.request_json

    def request_json(api_url, path, params=None):
        result = request(api_url, path, params)
        if path == "/api/v1/players/player-1":
            result["stats"] = {
                "appearances": len(result["scope"]["seasons"]),
                "ranking_boards": {"appearances": [
                    {"id": "player-1", "name": "甲", "rank": 1, "tied": False,
                     "value": 2, "appearances": 2, "sample_count": 2},
                ]},
                "rankings": {"appearances": {"rank": 1, "total": 1, "tied": False}},
            }
        return result

    monkeypatch.setattr("website.static_publish.export_static._request_json", request_json)
    monkeypatch.setattr("website.static_publish.export_static._request_bytes", api.media_bytes)
    api.request_json = request_json
    return api


def _data(output):
    manifest = json.loads((output / "data/manifest.json").read_text(encoding="utf-8"))
    return output / "data/releases" / manifest["snapshot_id"]


def test_export_shares_rankings_and_reconstructs_the_original_api_profile(tmp_path, ranking_api):
    from website.static_publish.player_rankings import restore_player_rankings

    output = tmp_path / "first"
    manifest = _export(ranking_api, output)
    assert manifest["schema_version"] == 2
    data = _data(output)
    for interval in manifest["ranges"]:
        name = f"{interval['start']}--{interval['end']}"
        compact = json.loads((data / f"players/player-1/{name}.json").read_text(encoding="utf-8"))
        shared = json.loads((data / f"rankings/{name}.json").read_text(encoding="utf-8"))
        assert "ranking_boards" not in compact["stats"]
        assert shared["ranking_boards"]["appearances"][0]["id"] == "player-1"
        original = ranking_api.request_json("http://api", "/api/v1/players/player-1", {
            "season_start": interval["start"], "season_end": interval["end"],
        })
        assert restore_player_rankings(compact, shared) == json.loads(json.dumps(original))
        assert "ranking_boards" not in compact["stats"]


def test_shared_rankings_survive_incremental_reuse_and_release_rebinding(tmp_path, ranking_api):
    first = tmp_path / "first"
    _export(ranking_api, first)
    ranking_api.release_id = "release-2"
    ranking_api.source_hash = "b" * 64
    incremental = tmp_path / "incremental"
    _export(ranking_api, incremental, reuse_from=first, reuse_index=_index(first))
    assert _index(incremental)["metrics"]["player_ranges"] == {"reused": 3, "fetched": 0}
    shared = json.loads((_data(incremental) / "rankings/S22--S22.json").read_text(encoding="utf-8"))
    assert shared["release_id"] == "release-2"
    full = tmp_path / "full"
    _export(ranking_api, full)
    assert _release_json(incremental) == _release_json(full)


def test_reuse_rejects_modified_shared_rankings(tmp_path, ranking_api):
    first = tmp_path / "first"
    _export(ranking_api, first)
    index = _index(first)
    path = _data(first) / "rankings/S22--S22.json"
    shared = json.loads(path.read_text(encoding="utf-8"))
    shared["ranking_boards"]["appearances"][0]["rank"] = 99
    path.write_text(json.dumps(shared), encoding="utf-8")
    with pytest.raises(ExportError, match="hash mismatch"):
        _export(ranking_api, tmp_path / "second", reuse_from=first, reuse_index=index)


def test_legacy_inline_rankings_are_migrated_without_fetching_profiles(tmp_path, ranking_api):
    from website.static_publish.player_rankings import restore_player_rankings

    first = tmp_path / "legacy"
    _export(ranking_api, first)
    data = _data(first)
    index = _index(first)
    for path in (data / "players").glob("*/*--*.json"):
        if path.parent.name == "by-season":
            continue
        compact = json.loads(path.read_text(encoding="utf-8"))
        shared = json.loads((data / "rankings" / path.name).read_text(encoding="utf-8"))
        path.write_text(json.dumps(restore_player_rankings(compact, shared)), encoding="utf-8")
        index["files"][path.relative_to(data).as_posix()]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (data / "rankings").glob("*.json"):
        del index["files"][path.relative_to(data).as_posix()]
        path.unlink()
    manifest_path = first / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    migrated = tmp_path / "migrated"
    _export(ranking_api, migrated, reuse_from=first, reuse_index=index)
    assert _index(migrated)["metrics"]["player_ranges"] == {"reused": 3, "fetched": 0}
    full = tmp_path / "full"
    _export(ranking_api, full)
    assert _release_json(migrated) == _release_json(full)


def _shared_acceptance_fixture(tmp_path):
    from website.static_publish import check_static as checker
    from website.static_publish.player_rankings import split_player_rankings
    from website.tests.test_incremental_acceptance import _api_fixture
    from website.tests.test_static_acceptance import _snapshot, _write_json

    out = _snapshot(tmp_path)
    path = out / "data/releases/snapshot-1/players/player-1/S21--S21.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["stats"]["ranking_boards"] = {}
    _write_json(path, profile)
    fixture = list(_api_fixture(out, reused=True))
    profile = checker._json(path)
    compact, shared = split_player_rankings(profile)
    _write_json(path, compact)
    shared_path = fixture[0]["data"] / "rankings/S21--S21.json"
    _write_json(shared_path, shared)
    manifest_path = out / "data/manifest.json"
    manifest = checker._json(manifest_path)
    manifest["schema_version"] = 2
    _write_json(manifest_path, manifest)
    index = fixture[3]
    index["files"]["players/player-1/S21--S21.json"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    index["files"]["rankings/S21--S21.json"] = {
        "sha256": hashlib.sha256(shared_path.read_bytes()).hexdigest(),
        "input_hash": "d" * 64, "reused": False,
    }
    fixture[0] = checker._load_snapshot(out, "/example-site")
    return fixture


def test_full_acceptance_compares_shared_rankings_even_when_profiles_are_reused(tmp_path, monkeypatch):
    from website.tests.test_incremental_acceptance import _run_api_check

    fixture = _shared_acceptance_fixture(tmp_path)
    report, calls = _run_api_check(monkeypatch, fixture, fixture[3])
    assert report["api_file_comparisons"]["player_ranges"] == 0
    assert any(path == "/api/v1/players/player-1" and query["minimum_appearances"] == ["0"]
               for path, query in calls)


def test_full_acceptance_rejects_shared_rankings_different_from_the_api(tmp_path, monkeypatch):
    from website.static_publish import check_static as checker
    from website.tests.test_incremental_acceptance import _run_api_check
    from website.tests.test_static_acceptance import _write_json

    fixture = _shared_acceptance_fixture(tmp_path)
    path = fixture[0]["data"] / "rankings/S21--S21.json"
    shared = checker._json(path)
    shared["ranking_boards"] = {"unexpected": []}
    _write_json(path, shared)
    fixture[3]["files"]["rankings/S21--S21.json"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    fixture[0] = checker._load_snapshot(fixture[0]["out"], "/example-site")
    with pytest.raises(checker.StaticAcceptanceError, match="shared player rankings.*differs"):
        _run_api_check(monkeypatch, fixture, fixture[3])


@pytest.mark.parametrize("failure", ["missing", "release", "scope", "duplicate"])
def test_basic_acceptance_rejects_invalid_shared_rankings(tmp_path, failure):
    from website.static_publish import check_static as checker
    from website.tests.test_static_acceptance import _write_json

    fixture = _shared_acceptance_fixture(tmp_path)
    snapshot = fixture[0]
    path = snapshot["data"] / "rankings/S21--S21.json"
    shared = checker._json(path)
    if failure == "missing":
        path.unlink()
    elif failure == "release":
        shared["release_id"] = "stale-release"
        _write_json(path, shared)
    elif failure == "scope":
        shared["scope"]["season_end"] = "S23"
        _write_json(path, shared)
    else:
        profile_path = snapshot["data"] / "players/player-1/S21--S21.json"
        profile = checker._json(profile_path)
        profile["stats"]["ranking_boards"] = {}
        _write_json(profile_path, profile)
    with pytest.raises(checker.StaticAcceptanceError, match="[Ss]hared player ranking"):
        checker.check_basic(snapshot["out"], "/example-site")

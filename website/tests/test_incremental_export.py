from __future__ import annotations

from collections import Counter
import hashlib
from io import BytesIO
import json
from pathlib import Path

import pytest
from PIL import Image

from website.static_publish.export_static import ExportError, export_snapshot


_IMAGE_BUFFER = BytesIO()
Image.new("RGB", (12, 20), "#203040").save(_IMAGE_BUFFER, "JPEG")
_IMAGE = _IMAGE_BUFFER.getvalue()
_IMAGE_HASH = hashlib.sha256(_IMAGE).hexdigest()


class FakePublishedAPI:
    def __init__(self):
        self.calls: Counter[tuple[str, str]] = Counter()
        self.release_id = "release-1"
        self.source_hash = "a" * 64
        self.game_hashes = {"game-s22": "1" * 64, "game-s23": "2" * 64}
        self.season_hashes = {"S22": "3" * 64, "S23": "4" * 64}
        self.implementation_hash = "5" * 64
        self.media_assets = [{"url": f"/media/player-photos/S23/{_IMAGE_HASH}.jpg",
                              "sha256": _IMAGE_HASH}]
        self.publications = {
            "S22": {"season": "S22", "publication_id": "pub-22", "payload_hash": "6" * 64},
            "S23": {"season": "S23", "publication_id": "pub-23", "payload_hash": "7" * 64},
        }

    def reset_calls(self):
        self.calls.clear()

    def media_bytes(self, api_url: str, path: str, params=None) -> tuple[bytes, dict[str, str]]:
        self.calls[("bytes", path)] += 1
        return _IMAGE, {}

    def metadata(self):
        return {
            "release_id": self.release_id,
            "release": {"id": self.release_id, "published_at": "2026-11-04T00:00:00Z",
                        "game_count": 2, "source_hash": self.source_hash},
            "seasons": [
                {"season": "S22", "game_count": 1, "phases": ["regular"]},
                {"season": "S23", "game_count": 1, "phases": ["finals_week", "regular"]},
            ],
            "bluff_publications": [self.publications["S22"], self.publications["S23"]],
            "media_manifest_hashes": {"player_photos": "8" * 64, "bluff_frames": "9" * 64},
            "media_assets": list(self.media_assets),
            "analytics_version": 15,
            "content_fingerprints": {
                "implementation": self.implementation_hash,
                "games": dict(self.game_hashes),
                "seasons": dict(self.season_hashes),
            },
        }

    def release(self):
        return self.metadata()["release"]

    def summaries(self):
        return [
            {"id": "game-s22", "season": "S22", "date": "2026-09-01", "phase": "regular",
             "game_number": 1, "board": {"code": "standard", "name": "标准版"}, "winner": "good",
             "players": [{"id": "player-1", "name": "甲", "seat": 1, "role": "平民",
                          "faction": "good"}], "ballot_count": 1, "round_count": 2,
             "search_text": "game-s22 standard 甲"},
            {"id": "game-s23", "season": "S23", "date": "2026-10-01", "phase": "finals_week",
             "game_number": 1, "board": {"code": "standard", "name": "标准版"}, "winner": "good",
             "players": [{"id": "player-1", "name": "甲", "seat": 1, "role": "平民",
                          "faction": "good"}], "ballot_count": 1, "round_count": 2,
             "search_text": "game-s23 standard 甲"},
        ]

    def game_detail(self, game_id: str):
        summary = next(row for row in self.summaries() if row["id"] == game_id)
        return {**summary, "release_id": self.release_id, "analytics_version": 15,
                "source": {"hidden_detail": self.game_hashes[game_id]}, "voting": {"ballots": []}}

    def _publication(self, season: str):
        return self.publications[season]

    def request_json(self, api_url: str, path: str, params=None):
        params = params or {}
        self.calls[("json", path)] += 1
        metadata = self.metadata()
        release = metadata["release"]
        games = self.summaries()
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/v1/export-manifest":
            return metadata
        if path == "/api/v1/overview":
            return {"release": release, "totals": {"games": 2, "players": 1},
                    "seasons": [{"id": "S22", "name": "S22", "games": 1, "days": 1},
                                {"id": "S23", "name": "S23", "games": 1, "days": 1}],
                    "boards": [], "recent_games": games}
        if path == "/api/v1/releases":
            return {"items": [{**release, "active": True}]}
        if path == "/api/v1/games":
            selected = [game for game in games if not params.get("season") or game["season"] == params["season"]]
            return {"release_id": self.release_id, "total": len(selected), "page": params.get("page", 1),
                    "page_size": 100, "items": selected}
        if path == "/api/v1/players":
            season = params["season"]
            photo = {"url": f"/media/player-photos/S23/{_IMAGE_HASH}.jpg", "sha256": _IMAGE_HASH}
            item = {"id": "player-1", "name": "甲", "appearances": 1, "roles": [], "photo": photo}
            return {"release_id": self.release_id, "analytics_version": 15, "total": 1,
                    "page": params.get("page", 1), "page_size": 100, "items": [item], "season": season}
        if path.startswith("/api/v1/games/"):
            return self.game_detail(path.rsplit("/", 1)[1])
        if path == "/api/v1/players/player-1":
            start, end = params["season_start"], params["season_end"]
            selected = [season for season in ("S22", "S23") if start <= season <= end]
            return {"id": "player-1", "name": "甲", "release_id": self.release_id,
                    "analytics_version": 15,
                    "scope": {"season_start": start, "season_end": end, "seasons": selected,
                              "minimum_appearances": 0},
                    "bluff_publications": [self._publication(season) for season in selected],
                    "season_values": [(season, self.season_hashes[season]) for season in selected]}
        if path == "/api/v1/stats":
            start, end = params["season_start"], params["season_end"]
            selected = [season for season in ("S22", "S23") if start <= season <= end]
            return {"release_id": self.release_id, "analytics_version": 15,
                    "scope": {"season_start": start, "season_end": end, "seasons": selected},
                    "values": [(season, self.season_hashes[season]) for season in selected]}
        if path == "/api/v1/leaderboard":
            season, phase = params["season"], params["phase"]
            game_count = 1 if phase == "all" or season == "S23" else 0
            return {"release_id": self.release_id, "analytics_version": 15, "season": season,
                    "phase": phase, "bluff_publication_id": self._publication(season)["publication_id"],
                    "bluff_payload_hash": self._publication(season)["payload_hash"],
                    "game_count": game_count, "items": [{"id": "player-1", "name": "甲"}]}
        if path == "/api/v1/bluff-review":
            season = params["season"]
            return {"release_id": self.release_id, "analytics_version": 15, "season": season,
                    "status": "all", "bluff_publication_id": self._publication(season)["publication_id"],
                    "bluff_payload_hash": self._publication(season)["payload_hash"],
                    "summary": {"games": 1}, "items": []}
        raise AssertionError((path, params))


def _export(api: FakePublishedAPI, output: Path, *, reuse_from: Path | None = None,
            reuse_index: dict | None = None):
    return export_snapshot("http://test", output, build_id=output.name,
                           reuse_from=reuse_from, reuse_index=reuse_index)


def _index(root: Path) -> dict:
    return json.loads((root / "export-index.json").read_text(encoding="utf-8"))


def _release_json(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "data/manifest.json").read_text(encoding="utf-8"))
    release_root = root / "data" / "releases" / manifest["snapshot_id"]
    return {path.relative_to(release_root).as_posix(): json.loads(path.read_text(encoding="utf-8"))
            for path in release_root.rglob("*.json")}


@pytest.fixture
def api(monkeypatch):
    fake = FakePublishedAPI()
    monkeypatch.setattr("website.static_publish.export_static._request_json", fake.request_json)
    monkeypatch.setattr("website.static_publish.export_static._request_bytes", fake.media_bytes)
    return fake


def test_first_run_without_index_fetches_all_cacheable_data(tmp_path, api):
    output = tmp_path / "first"
    _export(api, output)

    index = _index(output)
    assert index["metrics"] == {
        "game_details": {"reused": 0, "fetched": 2},
        "player_ranges": {"reused": 0, "fetched": 3},
        "stats_ranges": {"reused": 0, "fetched": 3},
        "leaderboards": {"reused": 0, "fetched": 3},
        "reviews": {"reused": 0, "fetched": 2},
        "media": {"reused": 0, "fetched": 1},
    }
    assert all(entry["reused"] is False for entry in index["files"].values())


def test_same_release_reuses_details_ranges_reviews_and_media_and_matches_full_export(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    reuse_index = _index(first)

    api.reset_calls()
    incremental = tmp_path / "incremental"
    _export(api, incremental, reuse_from=first, reuse_index=reuse_index)
    index = _index(incremental)
    assert index["metrics"] == {
        "game_details": {"reused": 2, "fetched": 0},
        "player_ranges": {"reused": 3, "fetched": 0},
        "stats_ranges": {"reused": 3, "fetched": 0},
        "leaderboards": {"reused": 3, "fetched": 0},
        "reviews": {"reused": 2, "fetched": 0},
        "media": {"reused": 1, "fetched": 0},
    }
    assert api.calls[("bytes", f"/api/v1/photos/S23/{_IMAGE_HASH}.jpg")] == 0
    assert _release_json(incremental) == _release_json(first)

    api.reset_calls()
    full = tmp_path / "full-current"
    _export(api, full)
    assert _release_json(incremental) == _release_json(full)


def test_only_changed_season_refetches_its_game_and_dependent_ranges(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    old_index = _index(first)

    api.release_id = "release-2"
    api.source_hash = "b" * 64
    api.game_hashes["game-s23"] = "a" * 64
    api.season_hashes["S23"] = "b" * 64
    api.reset_calls()
    incremental = tmp_path / "incremental"
    _export(api, incremental, reuse_from=first, reuse_index=old_index)
    assert _index(incremental)["metrics"] == {
        "game_details": {"reused": 1, "fetched": 1},
        "player_ranges": {"reused": 1, "fetched": 2},
        "stats_ranges": {"reused": 1, "fetched": 2},
        "leaderboards": {"reused": 1, "fetched": 2},
        "reviews": {"reused": 1, "fetched": 1},
        "media": {"reused": 1, "fetched": 0},
    }
    full = tmp_path / "full-current"
    _export(api, full)
    assert _release_json(incremental) == _release_json(full)


def test_game_fingerprint_catches_hidden_detail_change_without_refetching_season_data(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    old_index = _index(first)
    api.game_hashes["game-s22"] = "c" * 64
    api.reset_calls()

    incremental = tmp_path / "incremental"
    _export(api, incremental, reuse_from=first, reuse_index=old_index)
    metrics = _index(incremental)["metrics"]
    assert metrics["game_details"] == {"reused": 1, "fetched": 1}
    assert metrics["player_ranges"] == {"reused": 3, "fetched": 0}
    assert metrics["stats_ranges"] == {"reused": 3, "fetched": 0}
    assert metrics["leaderboards"] == {"reused": 3, "fetched": 0}
    full = tmp_path / "full-current"
    _export(api, full)
    assert _release_json(incremental) == _release_json(full)


def test_publication_change_rebinds_cached_responses_at_the_top_level(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    old_index = _index(first)
    api.publications["S22"] = {"season": "S22", "publication_id": "pub-22-new",
                               "payload_hash": "d" * 64}
    api.publications["S23"] = {"season": "S23", "publication_id": "pub-23-new",
                               "payload_hash": "e" * 64}
    api.reset_calls()

    incremental = tmp_path / "incremental"
    _export(api, incremental, reuse_from=first, reuse_index=old_index)
    metrics = _index(incremental)["metrics"]
    assert metrics["game_details"]["fetched"] == 0
    assert metrics["player_ranges"]["fetched"] == 0
    assert metrics["leaderboards"]["fetched"] == 0
    current = _release_json(incremental)
    assert current["leaderboards/S22/all.json"]["bluff_publication_id"] == "pub-22-new"
    assert current["bluff-review/S23.json"]["bluff_payload_hash"] == "e" * 64
    player = current["players/player-1/S22--S23.json"]
    assert player["bluff_publications"] == [api.publications["S22"], api.publications["S23"]]
    assert "new" not in json.dumps(player["scope"])


def test_matching_cache_entry_with_corrupt_file_fails_clearly(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    old_index = _index(first)
    manifest = json.loads((first / "data/manifest.json").read_text(encoding="utf-8"))
    cached_game = (first / "data" / "releases" / manifest["snapshot_id"] / "games/game-s22.json")
    cached_game.write_text("{}", encoding="utf-8")

    with pytest.raises(ExportError, match="hash mismatch"):
        _export(api, tmp_path / "incremental", reuse_from=first, reuse_index=old_index)


def test_missing_export_index_runs_full_data_fetch_but_can_reuse_verified_media(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    api.reset_calls()

    incremental = tmp_path / "incremental"
    _export(api, incremental, reuse_from=first, reuse_index=None)
    metrics = _index(incremental)["metrics"]
    assert metrics["game_details"] == {"reused": 0, "fetched": 2}
    assert metrics["player_ranges"] == {"reused": 0, "fetched": 3}
    assert metrics["stats_ranges"] == {"reused": 0, "fetched": 3}
    assert metrics["leaderboards"] == {"reused": 0, "fetched": 3}
    assert metrics["reviews"] == {"reused": 0, "fetched": 2}
    assert metrics["media"] == {"reused": 1, "fetched": 0}


def test_missing_current_fingerprint_disables_json_reuse(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    old_index = _index(first)
    api.implementation_hash = None

    incremental = tmp_path / "incremental"
    _export(api, incremental, reuse_from=first, reuse_index=old_index)
    metrics = _index(incremental)["metrics"]
    assert all(item["reused"] == 0 for name, item in metrics.items() if name != "media")
    assert metrics["game_details"] == {"reused": 0, "fetched": 2}
    assert metrics["player_ranges"] == {"reused": 0, "fetched": 3}
    assert metrics["stats_ranges"] == {"reused": 0, "fetched": 3}
    assert metrics["leaderboards"] == {"reused": 0, "fetched": 3}
    assert metrics["reviews"] == {"reused": 0, "fetched": 2}
    assert metrics["media"] == {"reused": 1, "fetched": 0}


def test_missing_previous_fingerprint_disables_json_reuse(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    old_index = json.loads(json.dumps(_index(first)))
    old_index["metadata"].pop("content_fingerprints")
    api.reset_calls()

    incremental = tmp_path / "incremental"
    _export(api, incremental, reuse_from=first, reuse_index=old_index)
    metrics = _index(incremental)["metrics"]
    assert metrics["game_details"] == {"reused": 0, "fetched": 2}
    assert metrics["player_ranges"] == {"reused": 0, "fetched": 3}
    assert metrics["stats_ranges"] == {"reused": 0, "fetched": 3}
    assert metrics["leaderboards"] == {"reused": 0, "fetched": 3}
    assert metrics["reviews"] == {"reused": 0, "fetched": 2}
    assert metrics["media"] == {"reused": 1, "fetched": 0}


def test_reference_removed_from_current_media_allowlist_is_rejected_even_with_cached_media(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    old_index = _index(first)
    api.media_assets = []

    with pytest.raises(ExportError, match="current export-manifest allowlist"):
        _export(api, tmp_path / "incremental", reuse_from=first, reuse_index=old_index)


def test_frontend_only_build_reuses_api_payloads(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    api.reset_calls()

    frontend_build = tmp_path / "frontend-build"
    _export(api, frontend_build, reuse_from=first, reuse_index=_index(first))
    metrics = _index(frontend_build)["metrics"]
    assert all(item["fetched"] == 0 for name, item in metrics.items() if name != "media")
    assert metrics["media"] == {"reused": 1, "fetched": 0}


def test_partial_development_export_ignores_reuse_inputs(tmp_path, api):
    first = tmp_path / "first"
    _export(api, first)
    api.reset_calls()

    partial = tmp_path / "partial"
    export_snapshot("http://test", partial, build_id="partial", partial_season="S22",
                    reuse_from=first, reuse_index=_index(first))
    metrics = _index(partial)["metrics"]
    assert all(item["reused"] == 0 for item in metrics.values())
    assert metrics["game_details"] == {"reused": 0, "fetched": 1}
    assert metrics["player_ranges"] == {"reused": 0, "fetched": 1}
    assert metrics["stats_ranges"] == {"reused": 0, "fetched": 1}
    assert metrics["leaderboards"] == {"reused": 0, "fetched": 1}
    assert metrics["reviews"] == {"reused": 0, "fetched": 1}
    assert metrics["media"] == {"reused": 0, "fetched": 1}

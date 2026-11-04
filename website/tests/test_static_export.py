from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
import psycopg

from website.api import app as api_module
from website.export_static import ExportError, _ranges, export_snapshot, sync_media


class _Cursor:
    def __init__(self, *, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


def test_game_summary_search_text_matches_publisher_field_order():
    snapshot = {
        "id": "2026-10-01_g01_BV1234567890", "season": "S23", "date": "2026-10-01",
        "phase": "regular", "game_number": 1, "board": {"code": "b", "name": "标准版"},
        "winner": "good", "players": [], "ballot_count": 1, "round_count": 2,
        "source": {"bvid": "BV1234567890"},
        "seats": [{"name": "甲"}, {"name": "乙"}],
    }
    assert api_module._search_text(snapshot) == (
        "2026-10-01_g01_BV1234567890 BV1234567890 2026-10-01 标准版 甲 乙"
    )
    summary = api_module.GameSummary.model_validate({**snapshot, "search_text": api_module._search_text(snapshot)})
    assert summary.model_dump()["search_text"] == api_module._search_text(snapshot)


def test_export_manifest_binds_release_reviews_and_media_and_distinguishes_missing_release(monkeypatch):
    release = {"id": "release-1", "published_at": datetime(2026, 11, 4, tzinfo=timezone.utc),
               "game_count": 2, "source_hash": "a" * 64}
    media_hashes = {"player_photos": "b" * 64, "bluff_frames": "c" * 64}
    monkeypatch.setattr(api_module, "_effective_media_assets", lambda: (media_hashes, []))

    class Connection:
        def execute(self, query, params=None):
            text = str(query)
            if "FROM active_release" in text:
                return _Cursor(row=release)
            if "array_agg(DISTINCT phase" in text:
                return _Cursor(rows=[{"season": "S22", "game_count": 1, "phases": ["regular"]},
                                     {"season": "S23", "game_count": 1,
                                      "phases": ["finals_week", "regular"]}])
            if "active_publication_id" in text:
                return _Cursor(rows=[
                    {"season": "S22", "active_publication_id": None,
                     "publication_id": None, "payload_hash": None},
                    {"season": "S23", "active_publication_id": "pub-23",
                     "publication_id": "pub-23", "payload_hash": "d" * 64},
                ])
            raise AssertionError(text)

    result = api_module.export_manifest(Connection())
    validated = api_module.ExportManifest.model_validate(result).model_dump()
    assert validated["release_id"] == "release-1"
    assert validated["bluff_publications"] == [
        {"season": "S22", "publication_id": None, "payload_hash": None},
        {"season": "S23", "publication_id": "pub-23", "payload_hash": "d" * 64},
    ]
    assert validated["media_manifest_hashes"] == media_hashes
    assert validated["analytics_version"] == api_module.ANALYTICS_VERSION

    class NoRelease:
        def execute(self, query, params=None):
            return _Cursor(row=None)

    with pytest.raises(HTTPException) as missing:
        api_module.export_manifest(NoRelease())
    assert missing.value.detail == "No published release"

    class FailedRead:
        def execute(self, query, params=None):
            raise psycopg.Error("database read failed")

    with pytest.raises(HTTPException) as failed:
        api_module.export_manifest(FailedRead())
    assert failed.value.detail == "Export metadata unavailable"


def test_ranges_include_every_contiguous_season_window():
    assert _ranges(["S21", "S22", "S23"]) == [
        {"start": "S21", "end": "S21", "seasons": ["S21"]},
        {"start": "S21", "end": "S22", "seasons": ["S21", "S22"]},
        {"start": "S21", "end": "S23", "seasons": ["S21", "S22", "S23"]},
        {"start": "S22", "end": "S22", "seasons": ["S22"]},
        {"start": "S22", "end": "S23", "seasons": ["S22", "S23"]},
        {"start": "S23", "end": "S23", "seasons": ["S23"]},
    ]


def test_sync_media_checks_content_addressed_hash_and_writes_allowlisted_asset(tmp_path, monkeypatch):
    content = b"sample image bytes"
    digest = hashlib.sha256(content).hexdigest()
    url = f"/media/player-photos/S23/{digest}.jpg"
    monkeypatch.setattr("website.export_static._request_bytes", lambda api_url, path: (content, {}))

    copied = sync_media("http://127.0.0.1:8000", tmp_path, [{"url": url, "sha256": digest}])
    target = tmp_path / "player-photos" / "S23" / f"{digest}.jpg"
    assert target.read_bytes() == content
    assert copied == [{"url": url, "sha256": digest, "path": f"player-photos/S23/{digest}.jpg"}]

    monkeypatch.setattr("website.export_static._request_bytes", lambda api_url, path: (b"changed", {}))
    with pytest.raises(ExportError, match="content hash mismatch"):
        sync_media("http://127.0.0.1:8000", tmp_path / "bad", [{"url": url, "sha256": digest}])


def test_partial_snapshot_exports_one_season_game_player_and_is_marked_incomplete(tmp_path, monkeypatch):
    release = {"id": "release-1", "published_at": "2026-11-04T00:00:00Z",
               "game_count": 1, "source_hash": "a" * 64}
    metadata = {
        "release_id": "release-1", "release": release,
        "seasons": [{"season": "S23", "game_count": 1, "phases": ["regular"]}],
        "bluff_publications": [{"season": "S23", "publication_id": None, "payload_hash": None}],
        "media_manifest_hashes": {"player_photos": "b" * 64, "bluff_frames": "c" * 64},
        "media_assets": [], "analytics_version": 15,
    }
    summary = {"id": "game-1", "season": "S23", "date": "2026-10-01", "phase": "regular",
               "game_number": 1, "board": {"code": "test", "name": "标准版"}, "winner": "good",
               "players": [{"id": "player-1", "name": "甲", "seat": 1, "role": "平民", "faction": "good"}],
               "ballot_count": 1, "round_count": 2, "search_text": "game-1 BV1234567890 2026-10-01 标准版 甲"}
    game_detail = {**summary, "release_id": "release-1", "analytics_version": 15,
                   "source": {"bvid": "BV1234567890"}, "voting": {"ballots": []}}
    player_summary = {"id": "player-1", "name": "甲", "appearances": 1, "roles": [], "photo": None}
    player_detail = {
        "id": "player-1", "name": "甲", "release_id": "release-1", "analytics_version": 15,
        "bluff_publications": [{"season": "S23", "publication_id": None, "payload_hash": None}],
        "scope": {"season_start": "S23", "season_end": "S23", "seasons": ["S23"],
                  "minimum_appearances": 0},
    }

    def fake_json(api_url, path, params=None):
        params = params or {}
        if path == "/api/v1/releases":
            return {"items": [{**release, "active": True}]}
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/v1/export-manifest":
            return metadata
        if path == "/api/v1/overview":
            return {"release": release, "totals": {"games": 1, "players": 1},
                    "seasons": [{"id": "S23", "name": "S23", "games": 1, "days": 1}],
                    "boards": [], "recent_games": [summary]}
        if path == "/api/v1/games":
            return {"release_id": "release-1", "total": 1, "page": params.get("page", 1),
                    "page_size": 100, "items": [summary]}
        if path == "/api/v1/players":
            return {"release_id": "release-1", "analytics_version": 15, "total": 1,
                    "page": params.get("page", 1), "page_size": 100, "items": [player_summary]}
        if path == "/api/v1/games/game-1":
            return game_detail
        if path == "/api/v1/players/player-1":
            return player_detail
        if path == "/api/v1/stats":
            return {"release_id": "release-1", "analytics_version": 15,
                    "scope": {"season_start": "S23", "season_end": "S23", "seasons": ["S23"]}}
        if path == "/api/v1/leaderboard":
            return {"release_id": "release-1", "analytics_version": 15, "season": "S23",
                    "phase": "all", "bluff_publication_id": None, "bluff_payload_hash": None,
                    "game_count": 1, "items": [player_summary]}
        if path == "/api/v1/bluff-review":
            return {"release_id": "release-1", "analytics_version": 15, "season": "S23",
                    "status": "all", "bluff_publication_id": None, "bluff_payload_hash": None,
                    "summary": {"games": 1}, "items": []}
        raise AssertionError((path, params))

    monkeypatch.setattr("website.export_static._request_json", fake_json)
    result = export_snapshot("http://127.0.0.1:8000", tmp_path / "snapshot", base_path="/langrensha-site",
                             build_id="sample-build", partial_season="S23")

    assert result["complete"] is False
    assert result["partial"] == {"enabled": True, "season": "S23", "game_id": "game-1",
                                  "player_id": "player-1"}
    assert result["counts"]["games"] == 1 and result["counts"]["players"] == 1
    assert result["ranges"] == [{"start": "S23", "end": "S23", "seasons": ["S23"]}]
    data_root = tmp_path / "snapshot" / "data"
    written = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    assert written["build_id"] == "sample-build"
    assert (data_root / "releases" / result["snapshot_id"] / "games/game-1.json").is_file()
    assert (data_root / "releases" / result["snapshot_id"] / "players/player-1/S23--S23.json").is_file()

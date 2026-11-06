from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from website.api import app as api


class _Cursor:
    def __init__(self, *, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


def _game(game_id: str, season: str, person_id: str, name: str, *, hidden: str = "base") -> dict:
    snapshot = {
        "id": game_id, "season": season, "date": f"2026-01-{int(game_id[-1]) + 1:02d}",
        "phase": "regular", "game_number": 1, "board": {"code": "standard", "name": "标准版"},
        "winner": "good", "ballot_count": 1, "round_count": 2,
        "seats": [{"seat": 1, "person_id": person_id, "name": name, "role": "平民", "faction": "good"}],
        "players": [{"id": person_id, "name": name, "seat": 1, "role": "平民", "faction": "good"}],
        "rounds": [], "hidden_input": hidden,
    }
    return {
        "id": game_id, "season": season, "event_date": snapshot["date"], "phase": "regular",
        "game_number": 1, "board_code": "standard", "board_name": "标准版", "winner": "good",
        "bvid": f"BV000000000{game_id[-1]}", "search_text": f"{game_id} {name}",
        "ballot_count": 1, "vote_count": 1, "round_count": 2, "snapshot": snapshot,
    }


class _Connection:
    def __init__(self, games, reviews=None, *, release_id="release-1", pub_suffix="1"):
        self.games = deepcopy(games)
        self.reviews = {
            season: {"season": season, "inference_version": "manual-v1", "games": []}
            for season in {game["season"] for game in games} if season in {"S22", "S23"}
        }
        self.reviews.update(deepcopy(reviews or {}))
        self.release_id = release_id
        self.pub_suffix = pub_suffix
        for game in self.games:
            game["snapshot"]["release_id"] = release_id
        self.release = {
            "id": release_id, "published_at": datetime(2026, 11, 4, tzinfo=timezone.utc),
            "game_count": len(games), "source_hash": "a" * 64,
        }

    def execute(self, query, params=None):
        text = str(query)
        if "FROM active_release" in text:
            return _Cursor(row=self.release)
        if "array_agg(DISTINCT phase" in text:
            seasons = sorted({game["season"] for game in self.games})
            return _Cursor(rows=[{
                "season": season,
                "game_count": sum(game["season"] == season for game in self.games),
                "phases": sorted({game["phase"] for game in self.games if game["season"] == season}),
            } for season in seasons])
        if "active_publication_id" in text:
            seasons = sorted({game["season"] for game in self.games})
            rows = []
            for season in seasons:
                payload = self.reviews.get(season)
                published = payload is not None
                rows.append({
                    "season": season,
                    "active_publication_id": f"pub-{season}-{self.pub_suffix}" if published else None,
                    "publication_id": f"pub-{season}-{self.pub_suffix}" if published else None,
                    "payload_hash": ("b" if self.pub_suffix == "1" else "c") * 64 if published else None,
                    "payload": payload,
                })
            return _Cursor(rows=rows)
        if "round_count, snapshot FROM games" in text:
            return _Cursor(rows=sorted(self.games, key=lambda game: (
                game["event_date"], game["game_number"] is None,
                game["game_number"] if game["game_number"] is not None else 0, game["id"],
            )))
        if "FROM game_players" in text:
            rows = []
            for game in self.games:
                for seat in game["snapshot"].get("seats", []):
                    rows.append({
                        "game_id": game["id"], "person_id": seat["person_id"], "name": seat["name"],
                        "seat": seat["seat"], "role": seat["role"], "faction": seat["faction"],
                    })
            return _Cursor(rows=sorted(rows, key=lambda row: (row["game_id"], row["seat"], row["person_id"])))
        if "FROM players" in text:
            names = {}
            for game in self.games:
                for seat in game["snapshot"].get("seats", []):
                    names.setdefault(seat["person_id"], seat["name"])
            return _Cursor(rows=[{"id": person_id, "name": name} for person_id, name in sorted(names.items())])
        raise AssertionError(text)


def _configure_media(monkeypatch):
    monkeypatch.setattr(api, "_effective_media_assets", lambda: (
        {"player_photos": "d" * 64, "bluff_frames": "e" * 64}, []
    ))
    monkeypatch.setattr(api.photos, "manifest", lambda: {"players": {"S21": {}, "S22": {}, "S23": {}}})
    monkeypatch.setattr(api.bluff_frames, "manifest", lambda: {"frames": {"S21": {}, "S22": {}, "S23": {}}})


def _manifest(games, monkeypatch, reviews=None, *, release_id="release-1", pub_suffix="1"):
    _configure_media(monkeypatch)
    return api.export_manifest(_Connection(
        games, reviews, release_id=release_id, pub_suffix=pub_suffix,
    ))["content_fingerprints"]


def test_s23_game_addition_changes_only_its_game_and_season_inputs(monkeypatch):
    original = [_game("game-1", "S21", "p21", "甲"),
                _game("game-2", "S22", "p22", "乙"),
                _game("game-3", "S23", "p23", "丙")]
    changed = [*original, _game("game-4", "S23", "p24", "丁")]

    before = _manifest(original, monkeypatch)
    after = _manifest(changed, monkeypatch)

    assert after["games"]["game-1"] == before["games"]["game-1"]
    assert after["games"]["game-2"] == before["games"]["game-2"]
    assert after["games"]["game-3"] == before["games"]["game-3"]
    assert after["games"]["game-4"]
    assert after["seasons"]["S21"] == before["seasons"]["S21"]
    assert after["seasons"]["S22"] == before["seasons"]["S22"]
    assert after["seasons"]["S23"] != before["seasons"]["S23"]


def test_hidden_snapshot_field_changes_game_and_own_season_fingerprint(monkeypatch):
    original = [_game("game-1", "S21", "p21", "甲"),
                _game("game-2", "S22", "p22", "乙"),
                _game("game-3", "S23", "p23", "丙")]
    changed = deepcopy(original)
    changed[2]["snapshot"]["hidden_input"] = "changed"

    before = _manifest(original, monkeypatch)
    after = _manifest(changed, monkeypatch)

    assert after["games"]["game-3"] != before["games"]["game-3"]
    assert after["games"]["game-1"] == before["games"]["game-1"]
    assert after["games"]["game-2"] == before["games"]["game-2"]
    assert after["seasons"]["S23"] != before["seasons"]["S23"]
    assert after["seasons"]["S21"] == before["seasons"]["S21"]
    assert after["seasons"]["S22"] == before["seasons"]["S22"]


def test_bluff_public_content_changes_its_season_but_not_game_inputs(monkeypatch):
    games = [_game("game-1", "S21", "p21", "甲"),
             _game("game-2", "S22", "p22", "乙"),
             _game("game-3", "S23", "p23", "丙")]
    original_review = {"season": "S23", "inference_version": "v1", "games": [
        {"game_id": "game-3", "assessments": [{"seat": 1, "decision": "no", "decision_note": "未悍跳"}]}
    ]}
    changed_review = deepcopy(original_review)
    changed_review["games"][0]["assessments"][0]["decision_note"] = "人工修订"

    before = _manifest(games, monkeypatch, {"S23": original_review})
    after = _manifest(games, monkeypatch, {"S23": changed_review})

    assert after["games"] == before["games"]
    assert after["seasons"]["S23"] != before["seasons"]["S23"]
    assert after["seasons"]["S21"] == before["seasons"]["S21"]
    assert after["seasons"]["S22"] == before["seasons"]["S22"]


def test_missing_allowlisted_media_asset_changes_only_its_season_fingerprint(monkeypatch):
    games = [_game("game-1", "S21", "p21", "甲"),
             _game("game-2", "S22", "p22", "乙"),
             _game("game-3", "S23", "p23", "丙")]
    digest = "a" * 64
    filename = f"{digest}.jpg"
    url = f"/media/player-photos/S21/{filename}"
    photo_manifest = {"players": {
        "S21": {"甲": {"asset": f"S21/{filename}", "source_url": "https://example.test/photo",
                        "source_date": "2026-01-01", "photo_id": "P1", "sha256": digest,
                        "season": "S21"}},
        "S22": {}, "S23": {},
    }}
    frame_manifest = {"frames": {"S21": {}, "S22": {}, "S23": {}}}
    monkeypatch.setattr(api.photos, "manifest", lambda: photo_manifest)
    monkeypatch.setattr(api.bluff_frames, "manifest", lambda: frame_manifest)
    available = {"value": True}
    monkeypatch.setattr(api, "photo_path", lambda season, name:
                        Path("available-photo") if available["value"] and season == "S21" and name == filename
                        else None)

    before_result = api.export_manifest(_Connection(games))
    before = before_result["content_fingerprints"]
    assert before_result["media_assets"] == [{"url": url, "sha256": digest}]

    available["value"] = False
    after_result = api.export_manifest(_Connection(games))
    after = after_result["content_fingerprints"]

    assert after_result["media_manifest_hashes"] == before_result["media_manifest_hashes"]
    assert after_result["media_assets"] == []
    assert after["seasons"]["S21"] != before["seasons"]["S21"]
    assert after["seasons"]["S22"] == before["seasons"]["S22"]
    assert after["seasons"]["S23"] == before["seasons"]["S23"]


def test_release_and_publication_binding_changes_do_not_change_semantic_inputs(monkeypatch):
    games = [_game("game-1", "S21", "p21", "甲"),
             _game("game-2", "S22", "p22", "乙"),
             _game("game-3", "S23", "p23", "丙")]
    reviews = {"S23": {"season": "S23", "inference_version": "v1", "games": []}}

    original = _manifest(games, monkeypatch, reviews, release_id="release-1", pub_suffix="1")
    rebound = _manifest(games, monkeypatch, reviews, release_id="release-2", pub_suffix="2")

    assert rebound["games"] == original["games"]
    assert rebound["seasons"] == original["seasons"]


def test_implementation_fingerprint_is_a_cache_input(monkeypatch):
    games = [_game("game-1", "S21", "p21", "甲")]
    original = _manifest(games, monkeypatch)
    monkeypatch.setattr(api, "IMPLEMENTATION_FINGERPRINT", "f" * 64)
    changed = api.export_manifest(_Connection(games))["content_fingerprints"]

    assert changed["implementation"] == "f" * 64
    assert changed["implementation"] != original["implementation"]
    assert changed["games"] == original["games"]
    assert changed["seasons"] == original["seasons"]


def test_write_only_entrypoints_do_not_invalidate_read_api_but_shared_publisher_does(tmp_path, monkeypatch):
    from website.api import app as api
    sources = tmp_path / 'website/api'
    sources.mkdir(parents=True)
    for name in ('app.py', 'publisher.py', 'publish.py', 'publish_bluffs.py'):
        (sources / name).write_text('original', encoding='utf-8')
    original_files = api._implementation_source_files
    monkeypatch.setattr(api, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(api, '_implementation_source_files', lambda: original_files(tmp_path))
    before = api._implementation_fingerprint()
    for name in ('publish.py', 'publish_bluffs.py'):
        (sources / name).write_text('write entrypoint changed', encoding='utf-8')
    assert api._implementation_fingerprint() == before
    (sources / 'publisher.py').write_text('shared runtime changed', encoding='utf-8')
    assert api._implementation_fingerprint() != before


@pytest.mark.parametrize("season", ["S22", "S23"])
def test_export_refuses_a_release_without_its_required_manual_bluff_binding(monkeypatch, season):
    _configure_media(monkeypatch)
    conn = _Connection([_game("game-1", season, "p1", "甲")])
    conn.reviews = {}
    with pytest.raises(HTTPException, match=f"{season}.*人工悍跳尚未绑定当前 release"):
        api.export_manifest(conn)

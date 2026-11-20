from collections import Counter
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import time

import pytest
from PIL import Image

from website.public_data import ROOT, _ranges, build_public_data, check_public_data
from website.static_publish.export_static import (
    ExportError,
    _leaderboard_summary,
    _media_endpoint,
    _safe_base_path,
    export_direct_snapshot,
)
from website.static_publish.snapshot_files import document_path


def test_final_json_covers_all_published_games_and_response_scopes():
    result = check_public_data(ROOT)
    data = build_public_data(ROOT)
    expected_seasons = sorted({game["season"] for game in data["games"]})
    expected_ranges = _ranges(expected_seasons)
    assert result["games"] == len(data["games"])
    assert result["seasons"] == expected_seasons
    assert result["players"] == len(data["player_index"]["items"])
    assert result["ranges_checked"] == len(expected_ranges)
    assert result["leaderboards"] == sum(
        1 + ("finals_week" in row["phases"]) for row in data["season_rows"]
    )

    game_index = data["documents"]["games/index.json"]
    assert game_index["total"] == result["games"]
    game_id = game_index["items"][0]["id"]
    detail = data["documents"][f"games/{game_id}.json"]
    assert {"id", "seats", "rounds", "voting", "endgame", "rules_state", "terminal_events",
            "presentation", "timeline"}.issubset(detail)
    assert not {"schema_version", "bluffs", "bluff_review_available"}.intersection(detail)

    profile = next(value for name, value in data["documents"].items()
                   if name.startswith("players/") and "--" in Path(name).name
                   and isinstance(value["stats"].get("bluff_count"), int)
                   and isinstance(value["stats"].get("bluff_rate"), dict))
    metric = profile["stats"]["bluff_rate"]
    success = profile["stats"]["bluff_success_rate"]
    assert profile["stats"]["bluff_count"] == metric["numerator"]
    assert metric["denominator"] >= 0 and isinstance(metric["samples"], list)
    assert success["denominator"] == profile["stats"]["bluff_count"]

    for season in data["seasons"]:
        board = data["documents"][f"leaderboards/{season}/all.json"]
        assert board["items"]
        assert {"bluff_count", "bluff_count_complete", "bluff_rate", "bluff_success_rate"}.issubset(
            board["items"][0]
        )
        assert all(type(item.get("bluff_count_complete")) is bool for item in board["items"])
        summary = _leaderboard_summary(board)
        assert summary["latest_date"] == max(game["date"] for game in board["sample_games"])
        assert "sample_games" not in summary
        assert [(row["id"], row["rank"], row["points"]) for row in summary["items"]] == [
            (row["id"], row["rank"], row["points"]) for row in board["items"]
        ]
        for compact, full in zip(summary["items"], board["items"]):
            assert set(compact["wolf_vote_rate"]) == {"rate", "numerator", "denominator", "excluded"}
            assert compact["wolf_vote_rate"]["rate"] == full["wolf_vote_rate"]["rate"]
            assert "samples" in full["wolf_vote_rate"]


def test_media_allowlist_and_base_path_validation():
    digest = "a" * 64
    endpoint, relative, path_hash = _media_endpoint(f"/media/player-photos/S23/{digest}.jpg")
    assert endpoint == f"/media/player-photos/S23/{digest}.jpg"
    assert relative == f"player-photos/S23/{digest}.jpg"
    assert path_hash == digest
    assert _safe_base_path("/") == ""
    assert _safe_base_path("/langrensha-site") == "/langrensha-site"
    for invalid in ("relative", "/bad/../path", "/trailing/", "//double"):
        try:
            _safe_base_path(invalid)
        except ExportError:
            continue
        raise AssertionError(f"invalid base path was accepted: {invalid}")

    try:
        _media_endpoint(f"/media/bluff-frames/S23/{digest}.png")
    except ExportError:
        pass
    else:
        raise AssertionError("retired evidence media must not enter the static export")


def test_game_and_catalog_hashes_use_the_bytes_already_read_for_parsing(tmp_path, monkeypatch):
    from website.public_data import _load_catalog, _load_games

    catalog_path = tmp_path / "config/seasons.json"
    game_path = tmp_path / "data/games/S23/game-1/game.json"
    catalog_bytes = b'{"seasons":{"S23":{"name":"test"}}}\r\n'
    game_bytes = b'{"id":"game-1","season":"S23","schema_version":1,"seats":[],"rounds":[]}\r\n'
    for path, body in [(catalog_path, catalog_bytes), (game_path, game_bytes)]:
        path.parent.mkdir(parents=True)
        path.write_bytes(body)

    reads = Counter()
    open_path = Path.open

    def count_open(path, *args, **kwargs):
        reads[path] += 1
        return open_path(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", count_open)
    catalog, catalog_hash = _load_catalog(tmp_path)
    games, hashes = _load_games(tmp_path)
    assert catalog["S23"]["name"] == "test" and games[0]["id"] == "game-1"
    assert catalog_hash == hashlib.sha256(catalog_bytes).hexdigest()
    assert hashes[game_path.relative_to(tmp_path).as_posix()] == hashlib.sha256(game_bytes).hexdigest()
    assert reads == {catalog_path: 1, game_path: 1}


def test_snapshot_id_tracks_response_content_and_is_stable(tmp_path, monkeypatch):
    from website import public_data

    state = {"display": "first"}

    def fixture(_root):
        return {
            "release_id": "direct-" + "a" * 24,
            "source_hash": "b" * 64,
            "documents": {"overview.json": {"display": state["display"]}},
            "season_rows": [{"season": "S23", "game_count": 0, "phases": ["regular"]}],
            "ranges": [],
            "counts": {"games": 0, "players": 0, "game_details": 0,
                       "player_ranges": 0, "stats_ranges": 0, "leaderboards": 0},
        }

    monkeypatch.setattr(public_data, "build_public_data", fixture)
    first = export_direct_snapshot(tmp_path, tmp_path / "first/data", base_path="/site", build_id="build")
    repeated = export_direct_snapshot(tmp_path, tmp_path / "repeated/data", base_path="/site", build_id="build")
    assert repeated["snapshot_id"] == first["snapshot_id"]

    state["display"] = "changed response"
    changed = export_direct_snapshot(tmp_path, tmp_path / "changed/data", base_path="/site", build_id="build")
    assert changed["source_hash"] == first["source_hash"]
    assert changed["snapshot_id"] != first["snapshot_id"]


def test_immutable_documents_reuse_addresses_and_keep_directory_photos_light(tmp_path, monkeypatch):
    from website import public_data

    source = tmp_path / "source.jpg"
    Image.new("RGB", (48, 64), "navy").save(source)
    original = source.read_bytes()
    photo_name = f"{hashlib.sha256(original).hexdigest()}.jpg"
    asset = tmp_path / "website/assets/player-photos/S23" / photo_name
    asset.parent.mkdir(parents=True)
    source.rename(asset)
    photo = {"url": f"/media/player-photos/S23/{photo_name}", "season": "S23", "source_url": "https://example.test/"}
    state = {"release": "r1", "winner": "wolves"}
    game_path = "games/game-1.json"
    directory_path = "players/by-season/S23.json"
    profile_path = "players/p1/S23--S23.json"

    def fixture(_root):
        release_id = state["release"]
        return {"release_id": release_id, "source_hash": release_id, "season_rows": [], "ranges": [], "counts": {},
                "documents": {
                    game_path: {"id": "game-1", "release_id": release_id, "winner": state["winner"]},
                    directory_path: {"release_id": release_id, "total": 2, "page": 1, "page_size": 2, "items": [
                        {"id": "p1", "name": "Player One", "photo": photo, "appearances": 4,
                         "stats": {"wins": 1, "losses": 0,
                                   "total_win_rate": {"rate": None, "game_ids": ["game-1"]}}},
                        {"id": "p2", "name": "Player Two", "appearances": 1},
                    ]},
                    profile_path: {"id": "p1", "release_id": release_id, "analytics_version": 1,
                                   "scope": {"season": "S23"}, "photo": photo},
                }}

    monkeypatch.setattr(public_data, "build_public_data", fixture)
    output = tmp_path / "output/data"
    first = export_direct_snapshot(tmp_path, output)
    game_file = document_path(output, first, game_path)
    assert json.loads(game_file.read_bytes()) == {"id": "game-1", "winner": "wolves"}
    assert hashlib.sha256(game_file.read_bytes()).hexdigest() == game_file.stem
    directory = json.loads(document_path(output, first, directory_path).read_bytes())
    profile = json.loads(document_path(output, first, profile_path).read_bytes())
    assert directory["items"] == [
        {"id": "p1", "name": "Player One", "appearances": 4,
         "stats": {"wins": 1, "losses": 0, "win_rate": None},
         "photo": {"url": profile["photo"]["url"], "season": "S23"}},
        {"id": "p2", "name": "Player Two", "appearances": 1},
    ]
    assert directory["items"][0]["photo"]["url"].endswith(".webp")
    assert profile["photo"]["original_url"] == photo["url"]
    assert profile["photo"]["source_url"] == photo["source_url"]
    assert (output.parent / photo["url"].lstrip("/")).read_bytes() == original

    state["release"] = "r2"
    second = export_direct_snapshot(tmp_path, output)
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["document_hashes"] == first["document_hashes"]
    assert document_path(output, second, game_path) == game_file
    assert game_file.is_file()

    state["winner"] = "good"
    third = export_direct_snapshot(tmp_path, output)
    assert third["document_hashes"][game_path] != first["document_hashes"][game_path]
    assert third["document_hashes"][directory_path] == first["document_hashes"][directory_path]
    assert json.loads(document_path(output, third, game_path).read_bytes())["winner"] == "good"


@pytest.mark.parametrize("lock", ["transient", "persistent", "rollback"])
def test_export_retries_locked_media_directory(tmp_path, monkeypatch, lock):
    from website import public_data

    monkeypatch.setattr(public_data, "build_public_data", lambda _root: {
        "release_id": "release-1", "source_hash": "source-1",
        "documents": {"overview.json": {}}, "season_rows": [], "ranges": [], "counts": {},
    })
    snapshot = tmp_path / "snapshot"
    output = snapshot / "data"
    media = snapshot / "media"
    output.mkdir(parents=True)
    media.mkdir()
    (output / "manifest.json").write_text("previous data", encoding="utf-8")
    (media / "previous.jpg").write_bytes(b"previous media")
    original_rename = Path.rename
    waits = []

    def rename(path, destination):
        incoming_media_locked = destination == media and path.name == "media" and (lock != "transient" or not waits)
        previous_data_locked = lock == "rollback" and path.name == "previous-0"
        if incoming_media_locked or previous_data_locked:
            error = PermissionError("Directory temporarily in use")
            error.winerror = 5
            raise error
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(time, "sleep", waits.append)

    if lock == "transient":
        export_direct_snapshot(tmp_path, output)
        assert len(waits) == 1
        assert (output / "manifest.json").read_text(encoding="utf-8") != "previous data"
        assert media.is_dir()
        assert not list(snapshot.glob(".data.direct-export-*"))
    else:
        with pytest.raises(RuntimeError, match="Windows.*重试 6 次"):
            export_direct_snapshot(tmp_path, output)
        assert (media / "previous.jpg").read_bytes() == b"previous media"
        if lock == "persistent":
            assert len(waits) == 6
            assert (output / "manifest.json").read_text(encoding="utf-8") == "previous data"
            assert not list(snapshot.glob(".data.direct-export-*"))
        else:
            assert len(waits) == 12
            backup, = snapshot.glob(".data.direct-export-*/previous-0/manifest.json")
            assert backup.read_text(encoding="utf-8") == "previous data"


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL inheritance")
def test_exported_public_directories_inherit_workspace_permissions(tmp_path, monkeypatch):
    from website import public_data

    monkeypatch.setattr(public_data, "build_public_data", lambda _root: {
        "release_id": "release-1", "source_hash": "source-1",
        "documents": {"overview.json": {}}, "season_rows": [], "ranges": [], "counts": {},
    })
    output = tmp_path / "snapshot/data"
    output.parent.mkdir()
    shell = shutil.which("pwsh") or shutil.which("powershell")
    env = {**os.environ, "LANGRENSHA_ACL_DATA": str(output),
           "LANGRENSHA_ACL_PARENT": str(output.parent),
           "LANGRENSHA_ACL_MEDIA": str(output.parent / "media")}
    # Reproduce the workspace's inheritable Modify grant. Pytest's own tmp_path
    # is private, so checking only its default ACL would miss the account issue.
    subprocess.run([shell, "-NoProfile", "-Command",
        "$acl = Get-Acl -LiteralPath $env:LANGRENSHA_ACL_PARENT; "
        "$sid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-11'); "
        "$rule = [System.Security.AccessControl.FileSystemAccessRule]::new("
        "$sid, 'Modify', 'ContainerInherit,ObjectInherit', 'None', 'Allow'); "
        "$acl.AddAccessRule($rule); Set-Acl -LiteralPath $env:LANGRENSHA_ACL_PARENT -AclObject $acl",
    ], env=env, capture_output=True, text=True, check=True)
    export_direct_snapshot(tmp_path, output)
    result = subprocess.run([
        shell, "-NoProfile", "-Command",
        "Get-Acl -LiteralPath $env:LANGRENSHA_ACL_DATA,$env:LANGRENSHA_ACL_MEDIA | "
        "ForEach-Object { @($_.Access | Where-Object { "
        "$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value "
        "-eq 'S-1-5-11' -and $_.AccessControlType -eq 'Allow' }).Count -gt 0 }",
    ], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.split() == ["True", "True"]

from pathlib import Path
import os
import shutil
import subprocess

import pytest

from website.public_data import ROOT, _ranges, build_public_data, check_public_data
from website.static_publish.export_static import (
    ExportError,
    _media_endpoint,
    _safe_base_path,
    export_direct_snapshot,
)


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

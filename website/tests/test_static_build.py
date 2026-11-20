import hashlib
import json
import os
from pathlib import Path
import time

import pytest

from website.static_publish import build_static


@pytest.mark.parametrize("fails", [False, True])
def test_stage_timer_records_elapsed_time_even_when_stage_fails(monkeypatch, fails):
    clock = iter([10.0, 12.3456])
    monkeypatch.setattr(time, "perf_counter", lambda: next(clock))
    timings = {}

    def run():
        with build_static.timed_stage(timings, "export_json"):
            if fails:
                raise RuntimeError("export failed")

    if fails:
        with pytest.raises(RuntimeError, match="export failed"):
            run()
    else:
        run()
    assert timings == {"export_json": 2.346}


def compiler_shells(out):
    for family in build_static.ROUTE_FAMILIES:
        shell = out / family / build_static.SHELL_ID
        shell.mkdir(parents=True)
        (shell / "index.html").write_text(f"<html><main>{family} detail</main></html>")
        (shell.parent / "index.html").write_text(f"<html><main>{family} list</main></html>")
    asset = out / "_next/static/chunks/shared.js"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"compiled frontend bytes")


def _snapshot(snapshot, *, game_ids=("game-1",), player_ids=("player-1",), seasons=("S23",)):
    release = snapshot / "data/releases/snapshot-1"
    for family, ids in (("games", game_ids), ("players", player_ids)):
        path = release / family / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"items": [{"id": value} for value in ids]}), encoding="utf-8")
    (release / "releases.json").write_text('{"items": []}', encoding="utf-8")
    (snapshot / "data/manifest.json").write_text(json.dumps({
        "schema_version": 2, "snapshot_id": "snapshot-1", "build_id": "build-1",
        "release_id": "release-1", "complete": True, "base_path": "/site",
        "seasons": [{"id": value} for value in seasons],
    }), encoding="utf-8")
    (snapshot / "media").mkdir(parents=True)
    (snapshot / "media/photo.jpg").write_bytes(b"generated media")


def test_windows_exported_segment_is_served_at_the_browser_requested_url(tmp_path):
    from urllib.request import urlopen
    from website.static_publish.check_static import _serve

    out = tmp_path / "out"
    segment = out / "games/__next.games/__PAGE__.txt"
    segment.parent.mkdir(parents=True)
    segment.write_bytes(b"actual RSC payload")
    build_static.normalize_rsc_paths(out)
    server, thread = _serve(out, "/langrensha-site")
    try:
        url = f"http://127.0.0.1:{server.server_port}/langrensha-site/games/__next.games.__PAGE__.txt"
        with urlopen(url) as response:
            assert response.read() == b"actual RSC payload"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_static_next_build_uses_an_isolated_workspace_root():
    web = Path(__file__).resolve().parents[1] / "web"
    config = (web / "next.config.ts").read_text(encoding="utf-8")
    website_ignore = (web.parent / ".gitignore").read_text(encoding="utf-8")

    assert 'process.env.NEXT_PUBLIC_SITE_MODE === "static"' in config
    assert 'output: staticSite ? "export" : "standalone"' in config
    assert 'turbopack: { root: path.resolve(process.cwd(), "..") }' in config
    assert "web/.static-build/" in website_ignore


def test_prepare_static_workspace_replaces_data_without_touching_local_app(tmp_path, monkeypatch):
    web = tmp_path / "web"
    monkeypatch.setattr(build_static, "WEB", web)
    (web / "src").mkdir(parents=True)
    (web / "public/data").mkdir(parents=True)
    (web / "public/media").mkdir(parents=True)
    (web / "node_modules").mkdir()
    (web / "src/page.tsx").write_text("current page")
    (web / "package.json").write_text('{"scripts":{"build":"next build"}}')
    (web / "public/icon.svg").write_text("icon")
    (web / "public/data/old.json").write_text("old local data")
    (web / "public/media/old.jpg").write_text("old local media")
    (web / "node_modules/keep").write_text("local dependency")
    snapshot = tmp_path / "snapshot"
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "media").mkdir()
    (snapshot / "data/manifest.json").write_text("new static data")
    (snapshot / "media/current.jpg").write_text("current static media")

    workspace = build_static.prepare_static_workspace(snapshot)

    assert workspace == web / ".static-build"
    assert (workspace / "src/page.tsx").read_text() == "current page"
    assert (workspace / "public/data/manifest.json").read_text() == "new static data"
    assert not (workspace / "public/data/old.json").exists()
    assert (workspace / "public/media/current.jpg").read_text() == "current static media"
    assert not (workspace / "public/media/old.jpg").exists()
    assert (workspace / "public/icon.svg").read_text() == "icon"
    assert not (workspace / "node_modules").exists()
    assert (web / "node_modules/keep").read_text() == "local dependency"


def test_materialize_snapshot_removes_stale_routes_and_updates_site_data(tmp_path):
    site = tmp_path / "site"
    compiler_shells(site)
    build_static.retain_route_shells(site)
    (site / "games/old-game").mkdir()
    (site / "players/old-player").mkdir()
    snapshot = tmp_path / "snapshot"
    _snapshot(snapshot, game_ids=("new-game",), player_ids=("new-player",), seasons=("S22", "S23"))

    counts = build_static.materialize_snapshot(site, snapshot)

    assert counts == {"games": 1, "players": 1, "seasons": 2}
    assert (site / "games/new-game/index.html").is_file()
    assert not (site / "games/old-game").exists()
    assert (site / "players/new-player/index.html").is_file()
    assert not (site / "players/old-player").exists()
    assert (site / "seasons/S22/index.html").is_file()
    assert (site / "seasons/S23/index.html").is_file()
    assert (site / "data/manifest.json").is_file()
    assert (site / "media/photo.jpg").read_bytes() == b"generated media"


def test_promote_replaces_ready_site_and_restores_it_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(build_static, "ROOT", tmp_path)
    target = tmp_path / "tmp/preview/site"
    target.mkdir(parents=True)
    (target / "index.html").write_text("previous")
    site = tmp_path / "tmp/candidate/site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("next")

    original_rename = Path.rename

    def fail_candidate(path, destination):
        if path == site:
            raise OSError("simulated promotion failure")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_candidate)
    with pytest.raises(OSError, match="promotion failure"):
        build_static._promote(site, target, "build-1")
    assert (target / "index.html").read_text() == "previous"
    assert (site / "index.html").read_text() == "next"

    monkeypatch.setattr(Path, "rename", original_rename)
    build_static._promote(site, target, "build-2")
    assert (target / "index.html").read_text() == "next"
    assert not list(target.parent.glob(".site-previous-*"))


def test_promote_rejects_outputs_outside_workspace_tmp(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    monkeypatch.setattr(build_static, "ROOT", root)
    site = root / "tmp/candidate/site"
    site.mkdir(parents=True)
    output = tmp_path / "outside/site"
    with pytest.raises(ValueError, match="subdirectory.*tmp"):
        build_static._promote(site, output, "build-1", root=root)


@pytest.mark.parametrize("locked_directory", ["candidate", "ready"])
@pytest.mark.parametrize("winerror", [5, 32])
def test_promote_waits_for_transient_windows_directory_lock(tmp_path, monkeypatch, locked_directory, winerror):
    site = tmp_path / "tmp/candidate/site"
    target = tmp_path / "tmp/preview/site"
    for path, content in ((site, "next"), (target, "previous")):
        path.mkdir(parents=True)
        (path / "index.html").write_text(content)
    locked = site if locked_directory == "candidate" else target
    original_rename = Path.rename
    failures = []
    waits = []

    def rename(path, destination):
        if path == locked and len(failures) < 2:
            failures.append(path)
            error = PermissionError("Directory temporarily in use")
            error.winerror = winerror
            raise error
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(time, "sleep", waits.append)
    build_static._promote(site, target, "transient-lock", root=tmp_path)

    assert len(failures) == len(waits) == 2
    assert (target / "index.html").read_text() == "next"
    assert not site.exists()
    assert not list(target.parent.glob(".site-previous-*"))


def test_promote_reports_persistent_windows_lock_and_restores_previous_site(tmp_path, monkeypatch):
    site = tmp_path / "tmp/candidate/site"
    target = tmp_path / "tmp/preview/site"
    for path, content in ((site, "next"), (target, "previous")):
        path.mkdir(parents=True)
        (path / "index.html").write_text(content)
    original_rename = Path.rename
    waits = []

    def rename(path, destination):
        if path == site:
            error = PermissionError("Directory still in use")
            error.winerror = 5
            raise error
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(time, "sleep", waits.append)
    with pytest.raises(RuntimeError, match="Windows.*目录") as error:
        build_static._promote(site, target, "persistent-lock", root=tmp_path)

    assert str(site) in str(error.value) and str(target) in str(error.value)
    assert 0 < sum(waits) <= 7
    assert (target / "index.html").read_text() == "previous"
    assert (site / "index.html").read_text() == "next"
    assert not list(target.parent.glob(".site-previous-*"))


@pytest.mark.skipif(os.name != "nt", reason="Exercises real Windows directory sharing")
def test_promote_recovers_from_real_windows_child_directory_lock(tmp_path, monkeypatch):
    import ctypes
    from ctypes import wintypes

    site = tmp_path / "tmp/candidate/site"
    target = tmp_path / "tmp/preview/site"
    for path, content in ((site, "next"), (target, "previous")):
        path.mkdir(parents=True)
        (path / "index.html").write_text(content)
    child = site / "data"
    child.mkdir()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Open the child directory with read/write sharing, but without delete sharing.
    handle = kernel.CreateFileW(str(child), 0x80000000, 0x1 | 0x2, None, 3, 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    released = False

    def release_lock(_delay):
        nonlocal released
        assert not released
        assert kernel.CloseHandle(handle)
        released = True

    monkeypatch.setattr(time, "sleep", release_lock)
    try:
        build_static._promote(site, target, "real-lock", root=tmp_path)
    finally:
        if not released:
            kernel.CloseHandle(handle)

    assert released
    assert (target / "index.html").read_text() == "next"
    assert not site.exists()


@pytest.mark.parametrize("schema_version", [2, 3])
def test_static_check_validates_real_route_files_and_local_json(tmp_path, schema_version):
    from website.static_publish.check_static import StaticAcceptanceError, check

    root = tmp_path / "site"
    snapshot_id = "snapshot-" + "a" * 64
    release = root / "data" / "releases" / snapshot_id
    documents = {
        "overview.json": {"totals": {"games": 1}},
        "games/index.json": {"total": 1, "items": [{"id": "game-1"}]},
        "games/game-1.json": {"id": "game-1"},
        "players/index.json": {"items": [{"id": "player-1"}]},
        "players/player-1/S23--S23.json": {"id": "player-1"},
        "stats/S23--S23.json": {"scope": {"seasons": ["S23"]}},
        "leaderboards/S23/all.json": {"items": []},
        "releases.json": {"items": []},
    }
    for relative, value in documents.items():
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
    manifest = {
        "schema_version": schema_version, "snapshot_id": snapshot_id, "build_id": "build-1",
        "release_id": "release-1", "base_path": "/site", "complete": True,
        "seasons": [{"id": "S23"}], "ranges": [{"start": "S23", "end": "S23"}],
        "counts": {"games": 1, "players": 1, "media_files": 0},
    }
    if schema_version == 3:
        objects = root / "data/objects"
        objects.mkdir()
        manifest["document_hashes"] = {}
        game_path = "games/game-1.json"
        (release / game_path).unlink()
        for relative, body in ((game_path, b'{"id":"game-1"}'), ("players/by-season/S23.json", b'{"items":[]}')):
            digest = hashlib.sha256(body).hexdigest()
            (objects / f"{digest}.json").write_bytes(body)
            manifest["document_hashes"][relative] = digest
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for route in ("", "games", "players", "stats", "leaderboard", "games/game-1",
                  "players/player-1", "seasons/S23"):
        path = root / route / "index.html" if route else root / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<!DOCTYPE html><html><body><main><h1>static</h1></main></body></html>", encoding="utf-8")

    result = check(root, "/site")

    assert result["state"] == "passed"
    assert result["snapshot_id"] == snapshot_id
    assert len(result["routes_checked"]) == 8
    if schema_version == 3:
        (objects / f"{manifest['document_hashes'][game_path]}.json").write_bytes(b"{}")
        with pytest.raises(StaticAcceptanceError, match="hash differs from its filename"):
            check(root, "/site")


def test_build_cli_has_no_api_or_incremental_options(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(build_static, "build", lambda base, output, **kwargs:
                        calls.append((base, output, kwargs)) or {"state": "passed"})
    assert build_static.main(["--root", str(tmp_path), "--base-path", "/preview",
                              "--output", str(tmp_path / "preview")]) == 0
    assert calls == [("/preview", tmp_path / "preview", {"root": tmp_path})]
    with pytest.raises(SystemExit) as error:
        build_static.main(["--api-url", "http://localhost"])
    assert error.value.code == 2

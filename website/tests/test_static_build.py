"""The accepted site and its receipt survive an unsuccessful replacement."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from website.static_publish import build_static


def compiler_shells(out):
    for family in build_static.ROUTE_FAMILIES:
        shell = out / family / build_static.SHELL_ID
        shell.mkdir(parents=True)
        (shell / "index.html").write_text(f"<main>{family} shell</main>")
        (shell.parent / "index.html").write_text(f"<main>{family} list</main>")
    review = out / "seasons" / build_static.SHELL_ID / "bluff-review"
    review.mkdir()
    (review / "index.html").write_text("<main>S23 review shell</main>")
    asset = out / "_next/static/chunks/shared.js"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"accepted frontend bytes")


def snapshot_files(snapshot, build_id, *, game_ids=("game-1",), player_ids=("player-1",),
                   season_ids=("S23",), snapshot_id="snapshot-1"):
    release = snapshot / "data/releases" / snapshot_id
    for family, ids in (("games", game_ids), ("players", player_ids)):
        directory = release / family
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "index.json").write_text(json.dumps({"items": [{"id": value} for value in ids]}))
    (release / "releases.json").write_text('{"items": []}')
    (snapshot / "data/manifest.json").write_text(json.dumps({"build_id": build_id,
        "snapshot_id": snapshot_id, "release_id": "release-1", "complete": True,
        "base_path": "/site", "seasons": [{"id": value} for value in season_ids]}))
    media = snapshot / "media"
    media.mkdir(exist_ok=True)
    (media / f"{snapshot_id}.png").write_bytes(b"current media")


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
        with urlopen(f"http://127.0.0.1:{server.server_port}/langrensha-site/games/__next.games.__PAGE__.txt") as response:
            assert response.read() == b"actual RSC payload"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_static_next_build_uses_an_isolated_workspace_root():
    web = Path(__file__).resolve().parents[1] / "web"
    config = (web / "next.config.ts").read_text(encoding="utf-8")
    website_ignore = (web.parent / ".gitignore").read_text(encoding="utf-8")
    docker_ignore = (web.parents[1] / ".dockerignore").read_text(encoding="utf-8")

    assert 'process.env.NEXT_PUBLIC_SITE_MODE === "static"' in config
    assert 'output: staticSite ? "export" : "standalone"' in config
    assert 'import path from "node:path"' in config
    assert 'turbopack: { root: path.resolve(process.cwd(), "..") }' in config
    assert 'distDir:' not in config
    assert "web/.next-static/" in website_ignore
    assert "web/.static-build/" in website_ignore
    assert "**/.next-static" in docker_ignore
    assert "**/.static-build" in docker_ignore


def ready_files(tmp_path, monkeypatch):
    monkeypatch.setattr(build_static, "ROOT", tmp_path)
    target = tmp_path / "tmp/preview/site"
    target.mkdir(parents=True)
    (target / "index.html").write_text("previous accepted site")
    receipt_path = target.parent / "acceptance.json"
    receipt_path.write_text('{"build_id":"old","state":"passed"}')
    site = tmp_path / "candidate"
    site.mkdir()
    (site / "index.html").write_text("new site")
    return target, receipt_path, site


def test_failed_receipt_promotion_restores_accepted_site_and_receipt(tmp_path, monkeypatch):
    target, receipt_path, site = ready_files(tmp_path, monkeypatch)
    original = Path.replace

    def fail_receipt(path, destination):
        if path.name == ".acceptance-new.json":
            raise OSError("simulated receipt failure")
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", fail_receipt)
    with pytest.raises(OSError, match="receipt failure"):
        build_static.promote(site, target, {"build_id": "new", "state": "passed"})
    assert (target / "index.html").read_text() == "previous accepted site"
    assert json.loads(receipt_path.read_text())["build_id"] == "old"


def test_accepted_site_and_receipt_move_together(tmp_path, monkeypatch):
    target, receipt_path, site = ready_files(tmp_path, monkeypatch)
    build_static.promote(site, target, {"build_id": "new", "state": "passed"})
    assert (target / "index.html").read_text() == "new site"
    assert json.loads(receipt_path.read_text())["build_id"] == "new"
    assert not list(target.parent.glob(".site-*"))


def test_export_failure_does_not_replace_previous_ready_site(tmp_path, monkeypatch):
    from website.static_publish import export_static
    target, receipt_path, _ = ready_files(tmp_path, monkeypatch)
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"source_commit": "test", "source_dirty": True})

    def unavailable(*args, **kwargs):
        raise RuntimeError("Published API unavailable")

    monkeypatch.setattr(export_static, "export_snapshot", unavailable)
    timings = {}
    with pytest.raises(RuntimeError, match="Published API unavailable"):
        build_static.build("http://127.0.0.1:1", "/langrensha-site", target, stage_seconds=timings)
    assert (target / "index.html").read_text() == "previous accepted site"
    assert json.loads(receipt_path.read_text())["build_id"] == "old"
    failure, = (tmp_path / "tmp/pages-build").glob("*/receipt.json")
    assert json.loads(failure.read_text())["failed_step"] == "export"
    assert json.loads(failure.read_text())["stage_seconds"] == timings
    assert "export" in timings and timings["export"] >= 0


def accepted_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(build_static, "ROOT", tmp_path)
    site = tmp_path / "tmp/preview/site"
    data = site / "data/releases/snapshot-1"
    data.mkdir(parents=True)
    (data / "releases.json").write_text('{"items": []}')
    (site / "data/manifest.json").write_text(json.dumps({
        "build_id": "old", "snapshot_id": "snapshot-1", "complete": True, "base_path": "/site"}))
    receipt = {"build_id": "old", "snapshot_id": "snapshot-1", "state": "passed", "mode": "complete",
               "build_input_hash": "source-1", "artifact_hash": build_static.tree_hash(site),
               "frontend_input_hash": build_static.frontend_input_hash(),
               "frontend_mode": build_static.FRONTEND_MODE,
               "acceptance": {"layers": {"browser": {"state": "passed"}}},
               "export_index": {"metadata": {"release_id": "release-1"}}}
    (site.parent / "acceptance.json").write_text(json.dumps(receipt))
    return site, receipt


def test_unchanged_update_skips_export_and_next_but_checks_release_history(tmp_path, monkeypatch):
    from website.static_publish import export_static
    site, previous = accepted_baseline(tmp_path, monkeypatch)
    previous["stage_seconds"] = {"export": 99, "frontend_build": 123}
    build_static.write_json(site.parent / "acceptance.json", previous)
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": "source-1"})
    requests = []

    def api(_url, path):
        requests.append(path)
        return {"/health": {"status": "ok"}, "/api/v1/export-manifest": previous["export_index"]["metadata"],
                "/api/v1/releases": {"items": []}}[path]

    monkeypatch.setattr(export_static, "_request_json", api)
    monkeypatch.setattr(export_static, "export_snapshot", lambda *args, **kwargs: pytest.fail("Unchanged export ran"))
    timings = {}
    result = build_static.build("http://api", "/site", site, stage_seconds=timings)
    assert result["build_id"] == "old" and result["update_status"] == "unchanged"
    assert requests == ["/health", "/api/v1/export-manifest", "/api/v1/releases"]
    assert json.loads((site.parent / "acceptance.json").read_text()) == previous
    assert result["stage_seconds"] is timings
    assert "source_consistency" in timings and "export" not in timings and "frontend_build" not in timings


def test_damaged_accepted_artifact_cannot_be_reused(tmp_path, monkeypatch):
    site, _ = accepted_baseline(tmp_path, monkeypatch)
    (site / "data/releases/snapshot-1/releases.json").write_text('changed')
    with pytest.raises(RuntimeError, match="artifact was modified"):
        build_static.accepted_previous(site, "/site")


def test_changed_frontend_inputs_cannot_take_the_no_change_shortcut(tmp_path, monkeypatch):
    from website.static_publish import export_static
    site, previous = accepted_baseline(tmp_path, monkeypatch)
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": "source-1"})
    monkeypatch.setattr(build_static, "frontend_input_hash", lambda: "changed-compiler-inputs")
    def exporting(*args, **kwargs):
        raise RuntimeError("export was reached")
    monkeypatch.setattr(export_static, "export_snapshot", exporting)
    with pytest.raises(RuntimeError, match="export was reached"):
        build_static.build("http://api", "/site", site)
    assert json.loads((site.parent / "acceptance.json").read_text()) == previous


def test_legacy_frontend_mode_cannot_take_the_no_change_shortcut(tmp_path, monkeypatch):
    from website.static_publish import export_static
    site, previous = accepted_baseline(tmp_path, monkeypatch)
    previous["frontend_mode"] = "full_static_export"
    build_static.write_json(site.parent / "acceptance.json", previous)
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": "source-1"})
    monkeypatch.setattr(export_static, "_request_json", lambda *args, **kwargs: pytest.fail("Legacy shortcut ran"))

    def exporting(*args, **kwargs):
        raise RuntimeError("full frontend rebuild reached")

    monkeypatch.setattr(export_static, "export_snapshot", exporting)
    with pytest.raises(RuntimeError, match="full frontend rebuild reached"):
        build_static.build("http://api", "/site", site)
    assert json.loads((site.parent / "acceptance.json").read_text()) == previous


def test_edit_during_build_prevents_promotion_even_after_acceptance(tmp_path, monkeypatch):
    from website.static_publish import check_static, export_static
    target, receipt_path, _ = ready_files(tmp_path, monkeypatch)
    web = tmp_path / "website/web"
    (web / "out").mkdir(parents=True)
    (web / "out/index.html").write_text("new candidate")
    compiler_shells(web / "out")
    monkeypatch.setattr(build_static, "WEB", web)
    monkeypatch.setattr(build_static, "prepare_static_workspace", lambda snapshot: web)
    inputs = iter(["before", "before", "after"])
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": next(inputs)})
    def export(_url, output, **kwargs):
        snapshot_files(output, kwargs["build_id"])
    monkeypatch.setattr(export_static, "export_snapshot", export)
    monkeypatch.setattr(build_static, "node_binary", lambda: str(tmp_path / "node.exe"))
    monkeypatch.setattr(build_static.shutil, "which", lambda *args, **kwargs: str(tmp_path / "npm"))
    monkeypatch.setattr(build_static.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(check_static, "check", lambda *args, **kwargs: {"state": "passed"})
    with pytest.raises(RuntimeError, match="Source inputs changed"):
        build_static.build("http://api", "/site", target, full_check=True)
    assert (target / "index.html").read_text() == "previous accepted site"
    assert json.loads(receipt_path.read_text())["build_id"] == "old"
    failure, = (tmp_path / "tmp/pages-build").glob("*/receipt.json")
    assert json.loads(failure.read_text())["failed_step"] == "source_consistency"


def test_frontend_fingerprint_ignores_exported_data_and_documentation(tmp_path, monkeypatch):
    monkeypatch.setattr(build_static, "ROOT", tmp_path)
    web = tmp_path / "website/web"
    (web / "src").mkdir(parents=True)
    (web / "public/data").mkdir(parents=True)
    (web / "src/page.tsx").write_text("page 1")
    baseline = build_static.frontend_input_hash()
    (web / "public/data/manifest.json").write_text("new data")
    (web / "README.md").write_text("new instructions")
    (web / "tsconfig.static.tsbuildinfo").write_text("generated compiler cache")
    assert build_static.frontend_input_hash() == baseline
    (web / "src/page.tsx").write_text("page 2")
    assert build_static.frontend_input_hash() != baseline


def test_static_workspace_preserves_running_build_and_cache_but_replaces_export_inputs(tmp_path, monkeypatch):
    web = tmp_path / "web"
    monkeypatch.setattr(build_static, "WEB", web)
    for folder in ["src", "public/data", "public/media", ".next/standalone", "node_modules"]:
        (web / folder).mkdir(parents=True, exist_ok=True)
    (web / "src/page.tsx").write_text("current page")
    (web / "package.json").write_text('{"scripts": {"build": "next build"}}')
    (web / "tsconfig.json").write_text("{}")
    (web / ".next/standalone/server.js").write_text("running server")
    (web / "public/icon.svg").write_text("icon")
    (web / "public/data/old.json").write_text("old maintenance data")
    (web / "public/media/old.jpg").write_text("unreferenced maintenance media")
    snapshot = tmp_path / "snapshot"
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "media").mkdir()
    (snapshot / "data/manifest.json").write_text("new snapshot")
    (snapshot / "media/current.jpg").write_text("current media")
    workspace = build_static.prepare_static_workspace(snapshot)
    assert workspace == web / ".static-build"
    assert (workspace / "src/page.tsx").read_text() == "current page"
    assert (workspace / "public/data/manifest.json").read_text() == "new snapshot"
    assert not (workspace / "public/data/old.json").exists()
    assert not (workspace / "public/media/old.jpg").exists()
    assert (workspace / ".static-snapshot/data/manifest.json").read_text() == "new snapshot"
    assert not (workspace / "node_modules").exists()
    assert (web / ".next/standalone/server.js").read_text() == "running server"
    (workspace / ".next/cache").mkdir(parents=True)
    (workspace / ".next/cache/keep").write_text("compiler cache")
    (web / "src/page.tsx").unlink()
    build_static.prepare_static_workspace(snapshot)
    assert not (workspace / "src/page.tsx").exists()
    assert (workspace / ".next/cache/keep").read_text() == "compiler cache"
    assert (web / ".next/standalone/server.js").read_text() == "running server"


def reusable_baseline(tmp_path, monkeypatch):
    from website.static_publish import check_static, export_static
    monkeypatch.setattr(build_static, "ROOT", tmp_path)
    monkeypatch.setattr(build_static, "frontend_input_hash", lambda: "frontend-1")
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": "source-2"})
    site = tmp_path / "tmp/preview/site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<main>fixed entry shell</main>")
    compiler_shells(site)
    build_static.retain_route_shells(site)
    snapshot = tmp_path / "previous-snapshot"
    snapshot_files(snapshot, "old")
    build_static.materialize_snapshot(site, snapshot)
    previous = {"build_id": "old", "snapshot_id": "snapshot-1", "state": "passed", "mode": "complete",
                "build_input_hash": "source-1", "artifact_hash": build_static.tree_hash(site),
                "frontend_input_hash": "frontend-1", "frontend_mode": build_static.FRONTEND_MODE,
                "export_index": {"metadata": {"release_id": "release-1"}},
                "acceptance": {"layers": {"browser": {"state": "passed"}}}}
    build_static.write_json(site.parent / "acceptance.json", previous)
    calls = {"export": [], "check": [], "basic_check": []}

    def export(_url, output, **kwargs):
        calls["export"].append(kwargs)
        snapshot_files(output, kwargs["build_id"], game_ids=("game-2",), player_ids=("player-2",),
                       season_ids=("S23", "S24"), snapshot_id="snapshot-2")
        build_static.write_json(output / "export-index.json", {"metadata": {"release_id": "release-2"}})

    def check(*args, **kwargs):
        calls["check"].append(kwargs)
        return {"layers": {"browser": {"state": "skipped" if kwargs["skip_browser_check"] else "passed"}}}

    def check_basic(*args, **kwargs):
        calls["basic_check"].append(kwargs)
        return {"check_scope": "basic", "layers": {"browser": {"state": "skipped"}}}

    monkeypatch.setattr(export_static, "export_snapshot", export)
    monkeypatch.setattr(check_static, "check", check)
    monkeypatch.setattr(check_static, "check_basic", check_basic, raising=False)
    return site, previous, calls


def test_data_only_update_reuses_assets_and_materializes_new_and_removed_ids(tmp_path, monkeypatch):
    site, previous, calls = reusable_baseline(tmp_path, monkeypatch)
    asset = (site / "_next/static/chunks/shared.js").read_bytes()
    monkeypatch.setattr(build_static, "prepare_static_workspace", lambda *args: pytest.fail("Frontend workspace prepared"))
    monkeypatch.setattr(build_static, "node_binary", lambda: pytest.fail("Node requested for data-only update"))
    original_copy = build_static.shutil.copytree

    def copy_without_previous_snapshot(source, destination, *args, **kwargs):
        assert Path(source) not in (site / "data", site / "media"), "Copied old snapshot before replacing it"
        return original_copy(source, destination, *args, **kwargs)

    monkeypatch.setattr(build_static.shutil, "copytree", copy_without_previous_snapshot)
    result = build_static.build("http://api", "/site", site, skip_browser_check=True)
    assert result["frontend_build"] == "reused" and result["typecheck"] == "reused"
    assert result["browser_check"] == "skipped"
    assert result["materialized_routes"] == {"games": 1, "players": 1, "seasons": 2}
    for family, current, obsolete in (("games", "game-2", "game-1"), ("players", "player-2", "player-1")):
        assert (site / family / current / "index.html").is_file()
        assert not (site / family / obsolete).exists()
        assert (site / build_static.SHELL_DIRECTORY / family / "index.html").is_file()
    assert (site / "seasons/S24/index.html").is_file()
    assert (site / "seasons/S23/bluff-review/index.html").is_file()
    assert not (site / "seasons/S24/bluff-review").exists()
    assert (site / "_next/static/chunks/shared.js").read_bytes() == asset
    assert not (site / "data/releases/snapshot-1").exists()
    assert not (site / "media/snapshot-1.png").exists()
    assert calls["export"][0]["reuse_from"] == site
    assert calls["check"] == [] and len(calls["basic_check"]) == 1
    assert result["check_scope"] == "basic"
    assert {"export", "frontend_reuse", "materialize", "acceptance"} <= result["stage_seconds"].keys()


@pytest.mark.parametrize("change", ["frontend", "legacy_mode"])
def test_frontend_changes_or_legacy_artifacts_force_build_and_typecheck(tmp_path, monkeypatch, change):
    site, previous, _ = reusable_baseline(tmp_path, monkeypatch)
    if change == "frontend":
        monkeypatch.setattr(build_static, "frontend_input_hash", lambda: "frontend-2")
    else:
        previous["frontend_mode"] = "full_static_export"
        build_static.write_json(site.parent / "acceptance.json", previous)
    web = tmp_path / "compiled-web"
    (web / "out").mkdir(parents=True)
    (web / "out/index.html").write_text("<main>new frontend</main>")
    compiler_shells(web / "out")
    monkeypatch.setattr(build_static, "prepare_static_workspace", lambda *args: web)
    monkeypatch.setattr(build_static, "node_binary", lambda: str(tmp_path / "node.exe"))
    monkeypatch.setattr(build_static.shutil, "which", lambda *args, **kwargs: str(tmp_path / "npm"))
    commands = []
    monkeypatch.setattr(build_static.subprocess, "run", lambda args, **kwargs:
                        commands.append(args) or SimpleNamespace(returncode=0))
    result = build_static.build("http://api", "/site", site)
    assert [args[-1] for args in commands] == ["build", "typecheck"]
    assert result["frontend_build"] == "compiled" and result["typecheck"] == "passed"
    assert result["frontend_mode"] == build_static.FRONTEND_MODE
    assert (site / "index.html").read_text() == "<main>new frontend</main>"


def test_full_refetch_can_reuse_frontend_and_keeps_previous_browser_scope(tmp_path, monkeypatch):
    site, previous, calls = reusable_baseline(tmp_path, monkeypatch)
    monkeypatch.setattr(build_static, "node_binary", lambda: pytest.fail("Full data refetch requested Node"))
    result = build_static.build("http://api", "/site", site, incremental=False, full_check=True)
    assert result["frontend_build"] == "reused"
    assert calls["export"][0]["reuse_from"] is None and calls["export"][0]["reuse_index"] is None
    assert calls["check"][0]["previous_export_index"] == previous["export_index"]


@pytest.mark.parametrize("full_check", [False, True])
def test_failed_reused_candidate_keeps_previous_site_and_receipt(tmp_path, monkeypatch, full_check):
    from website.static_publish import check_static
    site, previous, _ = reusable_baseline(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("candidate acceptance failed")

    monkeypatch.setattr(check_static, "check" if full_check else "check_basic", fail)
    with pytest.raises(RuntimeError, match="candidate acceptance failed"):
        build_static.build("http://api", "/site", site, full_check=full_check)
    assert build_static.tree_hash(site) == previous["artifact_hash"]
    assert json.loads((site.parent / "acceptance.json").read_text()) == previous


def test_source_edit_is_rejected_before_expensive_acceptance(tmp_path, monkeypatch):
    site, previous, calls = reusable_baseline(tmp_path, monkeypatch)
    inputs = iter(["source-2", "edited-during-export"])
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": next(inputs)})
    with pytest.raises(RuntimeError, match="Source inputs changed"):
        build_static.build("http://api", "/site", site)
    assert calls["check"] == [] and calls["basic_check"] == []
    assert build_static.tree_hash(site) == previous["artifact_hash"]
    failure, = (tmp_path / "tmp/pages-build").glob("*/receipt.json")
    assert json.loads(failure.read_text())["failed_step"] == "source_consistency_before_acceptance"


@pytest.mark.parametrize("browser_state", ["passed", "skipped"])
def test_explicit_full_check_runs_even_on_an_unchanged_previously_checked_site(tmp_path, monkeypatch, browser_state):
    from website.static_publish import check_static, export_static
    site, previous = accepted_baseline(tmp_path, monkeypatch)
    previous["acceptance"]["layers"]["browser"]["state"] = browser_state
    build_static.write_json(site.parent / "acceptance.json", previous)
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": "source-1"})
    monkeypatch.setattr(export_static, "_request_json", lambda _url, path:
        {"/health": {"status": "ok"}, "/api/v1/export-manifest": previous["export_index"]["metadata"],
         "/api/v1/releases": {"items": []}}[path])
    monkeypatch.setattr(export_static, "export_snapshot", lambda *args, **kwargs: pytest.fail("Unchanged export ran"))
    checks = []
    monkeypatch.setattr(check_static, "check", lambda *args, **kwargs:
                        checks.append(kwargs) or {"layers": {"browser": {"state": "passed"}}})
    result = build_static.build("http://api", "/site", site, full_check=True)
    assert result["update_status"] == "unchanged" and result["browser_check"] == "passed"
    assert len(checks) == 1 and checks[0]["skip_browser_check"] is False
    assert json.loads((site.parent / "acceptance.json").read_text())["acceptance"]["layers"]["browser"]["state"] == "passed"


def test_default_unchanged_update_reuses_prior_acceptance_without_full_checks(tmp_path, monkeypatch):
    from website.static_publish import check_static, export_static
    site, previous = accepted_baseline(tmp_path, monkeypatch)
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"build_input_hash": "source-1"})
    monkeypatch.setattr(export_static, "_request_json", lambda _url, path:
        {"/health": {"status": "ok"}, "/api/v1/export-manifest": previous["export_index"]["metadata"],
         "/api/v1/releases": {"items": []}}[path])
    monkeypatch.setattr(check_static, "check", lambda *args, **kwargs: pytest.fail("Skipped unchanged acceptance ran"))
    result = build_static.build("http://api", "/site", site)
    assert result["browser_check"] == "skipped" and result["acceptance_reused"] is True
    assert result["acceptance"]["layers"]["browser"]["state"] == "passed"
    assert json.loads((site.parent / "acceptance.json").read_text()) == previous
    audit, = (tmp_path / "tmp/pages-build").glob("*/receipt.json")
    assert json.loads(audit.read_text())["browser_check"] == "skipped"


def test_default_build_does_not_run_api_or_browser_acceptance(tmp_path, monkeypatch):
    from website.static_publish import check_static
    site, _, calls = reusable_baseline(tmp_path, monkeypatch)
    monkeypatch.setattr(check_static, "check", lambda *args, **kwargs: pytest.fail("Full acceptance ran by default"))
    result = build_static.build("http://api", "/site", site)
    assert result["check_scope"] == "basic" and result["browser_check"] == "skipped"
    assert len(calls["basic_check"]) == 1


def test_build_cli_propagates_browser_skip_and_full(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(build_static.sys, "argv", ["build_static.py", "--api-url", "http://api",
        "--output", str(tmp_path / "site"), "--skip-browser-check", "--full", "--full-check"])
    monkeypatch.setattr(build_static, "build", lambda *args, **kwargs: calls.append(kwargs))
    assert build_static.main() == 0
    assert calls[0]["skip_browser_check"] is True and calls[0]["incremental"] is False
    assert calls[0]["full_check"] is True

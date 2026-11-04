import json
from pathlib import Path
import subprocess

import pytest

from website.static_publish import sync_pages
from website.static_publish.build_static import tree_hash


def test_git_status_retains_the_leading_column_for_unstaged_edits(tmp_path):
    repository = tmp_path / "publication"
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(repository)], check=True)
    sync_pages.git(repository, "config", "user.name", "Pages test")
    sync_pages.git(repository, "config", "user.email", "pages-test@example.invalid")
    path = repository / "index.html"
    path.write_text("original")
    sync_pages.git(repository, "add", "index.html")
    sync_pages.git(repository, "-c", "maintenance.auto=false", "commit", "--quiet", "-m", "Test fixture")
    path.write_text("changed")
    status = sync_pages.git(repository, "status", "--porcelain=v1")
    assert status == " M index.html"


def test_mirror_writes_only_changed_files_and_removes_obsolete_generated_files(tmp_path):
    source = tmp_path / "ready"
    target = tmp_path / "publication/site"
    source.mkdir()
    target.mkdir(parents=True)
    (source / "same.bin").write_bytes(b"same")
    (source / "new.html").write_text("new")
    (target / "same.bin").write_bytes(b"same")
    (target / "old.html").write_text("old")
    original_mtime = (target / "same.bin").stat().st_mtime_ns
    counts = sync_pages.sync_tree(source, target)
    assert counts == {"written": 1, "unchanged": 1, "removed": 1}
    assert (target / "same.bin").stat().st_mtime_ns == original_mtime
    assert tree_hash(source) == tree_hash(target)


def fixture(tmp_path, monkeypatch):
    ready = tmp_path / "preview/site"
    (ready / "data/releases/snapshot-1").mkdir(parents=True)
    manifest = {"build_id": "build-1", "snapshot_id": "snapshot-1", "complete": True,
                "base_path": "/langrensha-site", "seasons": [{"id": "S23"}]}
    (ready / "data/manifest.json").write_text(json.dumps(manifest))
    (ready / "index.html").write_text("<main>ready</main>")
    receipt = {"state": "passed", "mode": "complete", "build_id": "build-1", "artifact_hash": tree_hash(ready)}
    repo = tmp_path / "publication"
    repo.mkdir()
    calls = []

    def git(path, *args):
        calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return repo.as_posix()
        if args == ("remote", "get-url", "origin"):
            return sync_pages.ORIGIN
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("diff", "--cached", "--name-only"):
            return "site/index.html\n.github/workflows/deploy-pages.yml\nREADME.md"
        if args == ("rev-parse", "HEAD"):
            return "commit-1"
        return ""

    monkeypatch.setattr(sync_pages, "git", git)
    monkeypatch.setattr(sync_pages, "wait_for_deployment", lambda commit, timeout: {"id": 1, "conclusion": "success"})
    monkeypatch.setattr(sync_pages, "verify_online", lambda ready, manifest: {"state": "passed"})
    return ready, receipt, repo, calls


def test_sync_pushes_only_accepted_site_and_owned_configuration(tmp_path, monkeypatch):
    ready, receipt, repo, calls = fixture(tmp_path, monkeypatch)
    record = sync_pages.publish_site(ready, receipt, repo)
    assert record["state"] == "passed" and record["commit"] == "commit-1"
    assert ("push", "origin", "main") in calls
    assert (repo / ".github/workflows/deploy-pages.yml").read_bytes() == (sync_pages.ROOT / "website/static_publish/templates/deploy-pages.yml").read_bytes()
    assert not list((repo / "site").rglob("*receipt*"))
    assert json.loads((ready.parent / "publication.json").read_text())["state"] == "passed"


def test_partial_or_damaged_build_never_reaches_publication_commit(tmp_path, monkeypatch):
    ready, receipt, repo, calls = fixture(tmp_path, monkeypatch)
    receipt["mode"] = "partial"
    with pytest.raises(ValueError, match="complete accepted"):
        sync_pages.publish_site(ready, receipt, repo)
    receipt["mode"] = "complete"
    (ready / "index.html").write_text("modified")
    with pytest.raises(ValueError, match="changed before publication"):
        sync_pages.publish_site(ready, receipt, repo)
    assert not any(args[0] in {"add", "commit", "push"} for args in calls)


def test_wrong_remote_and_independent_edits_are_preserved(tmp_path, monkeypatch):
    ready, receipt, repo, calls = fixture(tmp_path, monkeypatch)
    original = sync_pages.git

    def wrong_remote(path, *args):
        return "https://github.com/someone/other.git" if args == ("remote", "get-url", "origin") else original(path, *args)

    monkeypatch.setattr(sync_pages, "git", wrong_remote)
    with pytest.raises(ValueError, match="configured"):
        sync_pages.publish_site(ready, receipt, repo)

    def dirty(path, *args):
        return " M README.md" if args[0] == "status" else original(path, *args)

    monkeypatch.setattr(sync_pages, "git", dirty)
    with pytest.raises(RuntimeError, match="independent edits"):
        sync_pages.publish_site(ready, receipt, repo)


def test_deployment_failure_keeps_local_accepted_build_and_records_remote_commit(tmp_path, monkeypatch):
    ready, receipt, repo, calls = fixture(tmp_path, monkeypatch)
    def failed(*args):
        raise RuntimeError("Pages deployment failure")
    monkeypatch.setattr(sync_pages, "wait_for_deployment", failed)
    with pytest.raises(RuntimeError, match="deployment failure"):
        sync_pages.publish_site(ready, receipt, repo)
    assert tree_hash(ready) == receipt["artifact_hash"]
    record = json.loads((ready.parent / "publication.json").read_text())
    assert record["state"] == "failed" and record["commit"] == "commit-1"


def test_workflow_automatically_deploys_publication_main_and_keeps_manual_entry():
    workflow = (sync_pages.ROOT / "website/static_publish/templates/deploy-pages.yml").read_text()
    assert "push:" in workflow and "branches: [main]" in workflow
    assert "'site/**'" in workflow and "workflow_dispatch:" in workflow
    assert "path: site" in workflow
    assert "include-hidden-files: true" in workflow


def test_sync_cli_propagates_only_browser_skip_and_full_to_build(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sync_pages.sys, "argv", ["sync_pages.py", "--api-url", "http://api",
        "--output", str(tmp_path / "site"), "--skip-browser-check", "--full"])
    receipt = {"state": "passed", "browser_check": "skipped"}
    monkeypatch.setattr(sync_pages, "build", lambda *args, **kwargs: calls.append((args, kwargs)) or receipt)
    published = []
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args: published.append(args))
    assert sync_pages.main() == 0
    assert calls[0][1]["skip_browser_check"] is True and calls[0][1]["incremental"] is False
    assert published[0][1] == receipt


def test_explicit_api_is_reused_and_never_stopped(monkeypatch):
    monkeypatch.setattr(sync_pages.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Started another API"))
    with sync_pages.published_api("http://my-api") as url:
        assert url == "http://my-api"


def test_temporary_api_is_owned_and_cleaned_on_build_failure(tmp_path, monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    calls = []
    process = SimpleNamespace(pid=12345, poll=lambda: None, wait=lambda **kwargs: calls.append("wait"),
                              terminate=lambda: calls.append("terminate"), kill=lambda: calls.append("kill"))
    monkeypatch.setattr(sync_pages.subprocess, "Popen", lambda args, **kwargs: calls.append(args) or process)
    monkeypatch.setattr(sync_pages.subprocess, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(sync_pages, "urlopen", lambda *args, **kwargs: BytesIO(b'{"status":"ok"}'))
    with pytest.raises(RuntimeError, match="build failure"):
        with sync_pages.published_api(None) as url:
            assert url.startswith("http://127.0.0.1:") and not url.endswith(":8000")
            raise RuntimeError("build failure")
    assert "wait" in calls
    if sync_pages.os.name == "nt":
        assert ["taskkill", "/PID", "12345", "/T", "/F"] in calls
    else:
        assert "terminate" in calls

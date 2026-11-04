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
    assert set(record["stage_seconds"]) == {"publication_check", "sync", "commit", "push", "deployment", "online_check"}
    assert all(value >= 0 for value in record["stage_seconds"].values())
    assert record["commit_created"] is True


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
    assert record["failed_stage"] == "deployment"
    assert "deployment" in record["stage_seconds"] and "online_check" not in record["stage_seconds"]


def test_sync_history_keeps_separate_attempts_for_the_same_build(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    monkeypatch.setattr(sync_pages.sys, "argv", ["sync_pages.py", "--api-url", "http://api",
                                              "--output", str(tmp_path / "ready/site")])

    def build(*args, **kwargs):
        kwargs["stage_seconds"]["export"] = 1.25
        return {"build_id": "same-build", "update_status": "unchanged", "frontend_build": "reused"}

    def publish(*args, record):
        record["commit"] = "same-commit"

    monkeypatch.setattr(sync_pages, "build", build)
    monkeypatch.setattr(sync_pages, "publish_site", publish)
    assert sync_pages.main() == 0
    latest_path = tmp_path / "ready/publication.json"
    first_attempt = json.loads(latest_path.read_text(encoding="utf-8"))
    assert sync_pages.main() == 0
    latest_attempt = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest_attempt["publication_id"] != first_attempt["publication_id"]
    paths = sorted((tmp_path / "website/artifacts/pages-publications").glob("*.json"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    assert len(records) == 2 and records[0]["publication_id"] != records[1]["publication_id"]
    for record in records:
        assert record["state"] == "passed" and record["build_id"] == "same-build"
        assert record["started_at"].endswith("+08:00") and record["finished_at"].endswith("+08:00")
        assert record["finished_at"] >= record["started_at"]
        assert record["timezone"] == "Asia/Shanghai" and record["duration_seconds"] >= 0
        assert set(record["stage_seconds"]) == {"api_start", "build"}
        assert record["build_stage_seconds"] == {"export": 1.25}
    assert first_attempt in records and latest_attempt in records


def test_failed_build_records_partial_timings_without_publishing(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    monkeypatch.setattr(sync_pages.sys, "argv", ["sync_pages.py", "--api-url", "http://api",
                                              "--output", str(tmp_path / "ready/site")])

    def failed_build(*args, **kwargs):
        kwargs["stage_seconds"].update(export=1.5, frontend_build=2.5)
        raise RuntimeError("frontend compilation failed")

    monkeypatch.setattr(sync_pages, "build", failed_build)
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: pytest.fail("published failed build"))
    assert sync_pages.main() == 1
    path, = (tmp_path / "website/artifacts/pages-publications").glob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["state"] == "failed" and record["failed_stage"] == "build"
    assert record["error"] == "frontend compilation failed" and record["finished_at"]
    assert "build" in record["stage_seconds"] and "push" not in record["stage_seconds"]
    assert record["build_stage_seconds"] == {"export": 1.5, "frontend_build": 2.5}
    assert json.loads((tmp_path / "ready/publication.json").read_text(encoding="utf-8")) == record


def test_workflow_automatically_deploys_publication_main_and_keeps_manual_entry():
    workflow = (sync_pages.ROOT / "website/static_publish/templates/deploy-pages.yml").read_text()
    assert "push:" in workflow and "branches: [main]" in workflow
    assert "'site/**'" in workflow and "workflow_dispatch:" in workflow
    assert "path: site" in workflow
    assert "include-hidden-files: true" in workflow


@pytest.mark.parametrize("check_only", [False, True])
def test_sync_cli_uses_basic_checks_for_publication_and_full_checks_only_on_request(monkeypatch, tmp_path, check_only):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    calls = []
    argv = ["sync_pages.py", "--api-url", "http://api", "--output", str(tmp_path / "site"),
            "--skip-browser-check", "--full"]
    if check_only:
        argv.append("--check-only")
    monkeypatch.setattr(sync_pages.sys, "argv", argv)
    receipt = {"state": "passed", "browser_check": "skipped"}
    monkeypatch.setattr(sync_pages, "build", lambda *args, **kwargs: calls.append((args, kwargs)) or receipt)
    published = []
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: published.append(args))
    assert sync_pages.main() == 0
    assert calls[0][1]["skip_browser_check"] is True and calls[0][1]["incremental"] is False
    assert calls[0][1]["full_check"] is check_only
    path, = (tmp_path / "website/artifacts/pages-publications").glob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["operation"] == ("check" if check_only else "publish")
    if check_only:
        assert published == []
    else:
        assert published[0][1] == receipt


def test_failed_standalone_full_check_never_publishes(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    monkeypatch.setattr(sync_pages.sys, "argv", ["sync_pages.py", "--api-url", "http://api", "--check-only",
                                               "--output", str(tmp_path / "site")])

    def fail(*args, **kwargs):
        raise RuntimeError("browser interaction failed")

    monkeypatch.setattr(sync_pages, "build", fail)
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: pytest.fail("Published during standalone check"))
    assert sync_pages.main() == 1


def test_explicit_api_is_reused_and_never_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    (tmp_path / ".secrets").mkdir()
    (tmp_path / ".secrets/database.json").write_text("{}")
    monkeypatch.setattr(sync_pages.subprocess, "run", lambda *args, **kwargs: pytest.fail("Started local database"))
    monkeypatch.setattr(sync_pages.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Started another API"))
    with sync_pages.published_api("http://my-api") as url:
        assert url == "http://my-api"


@pytest.mark.skipif(sync_pages.os.name != "nt", reason="Project-local PostgreSQL runs on Windows")
def test_temporary_api_starts_local_database_before_health_check(tmp_path, monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace
    from urllib.error import HTTPError

    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    (tmp_path / ".secrets").mkdir()
    (tmp_path / ".secrets/database.json").write_text("{}")
    calls = []
    process = SimpleNamespace(pid=12345, poll=lambda: None, wait=lambda **kwargs: calls.append("wait"))

    def run(args, **kwargs):
        if args[0] == "taskkill":
            return
        assert args == [sync_pages.sys.executable, str(tmp_path / "scripts/local_postgres.py"), "start"]
        assert kwargs["check"] is True and kwargs["cwd"] == tmp_path
        calls.append("database")

    def health(url, **kwargs):
        calls.append("health")
        if "database" not in calls:
            raise HTTPError(url, 503, "Unhealthy", {}, BytesIO(b'{"detail":"Database unavailable"}'))
        return BytesIO(b'{"status":"ok"}')

    monkeypatch.setattr(sync_pages.subprocess, "run", run)
    monkeypatch.setattr(sync_pages.subprocess, "Popen", lambda *args, **kwargs: calls.append("api") or process)
    monkeypatch.setattr(sync_pages, "urlopen", health)
    with sync_pages.published_api(None) as url:
        assert url.startswith("http://127.0.0.1:")
    assert calls == ["database", "api", "health", "wait"]


@pytest.mark.skipif(sync_pages.os.name != "nt", reason="Project-local PostgreSQL runs on Windows")
def test_local_database_start_failure_is_recorded_before_build_or_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    (tmp_path / ".secrets").mkdir()
    (tmp_path / ".secrets/database.json").write_text("{}")
    monkeypatch.setattr(sync_pages.sys, "argv", ["sync_pages.py", "--output", str(tmp_path / "ready/site")])

    def failed_start(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(sync_pages.subprocess, "run", failed_start)
    monkeypatch.setattr(sync_pages.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Started API without database"))
    monkeypatch.setattr(sync_pages, "build", lambda *args, **kwargs: pytest.fail("Built without database"))
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: pytest.fail("Published without database"))
    assert sync_pages.main() == 1
    path, = (tmp_path / "website/artifacts/pages-publications").glob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["state"] == "failed" and record["failed_stage"] == "api_start"
    assert "local_postgres.py" in record["error"]
    assert set(record["stage_seconds"]) == {"api_start"}


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


@pytest.mark.parametrize(("status", "message"), [
    (503, "数据库.*只读账号配置"), (500, "HTTP 500"),
])
def test_unhealthy_api_is_reported_without_waiting_for_startup_deadline(tmp_path, monkeypatch, status, message):
    from io import BytesIO
    from types import SimpleNamespace
    from urllib.error import HTTPError

    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    ticks = iter([0, 0, 31])
    monkeypatch.setattr(sync_pages.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sync_pages.time, "sleep", lambda seconds: None)
    calls = []
    process = SimpleNamespace(pid=12345, poll=lambda: None, wait=lambda **kwargs: calls.append("wait"),
                              terminate=lambda: None, kill=lambda: None)
    monkeypatch.setattr(sync_pages.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(sync_pages.subprocess, "run", lambda *args, **kwargs: None)

    def health(url, **kwargs):
        calls.append("health")
        raise HTTPError(url, status, "Unhealthy", {}, BytesIO(b'{"detail":"Database unavailable"}'))

    monkeypatch.setattr(sync_pages, "urlopen", health)
    with pytest.raises(RuntimeError, match=message):
        with sync_pages.published_api(None):
            pytest.fail("unhealthy API was accepted")
    assert calls == ["health", "wait"]


def test_pending_api_prints_start_and_wait_progress(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from urllib.error import URLError

    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    ticks = iter([0, 0, 5, 31])
    monkeypatch.setattr(sync_pages.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sync_pages.time, "sleep", lambda seconds: None)
    process = SimpleNamespace(pid=12345, poll=lambda: None, wait=lambda **kwargs: None,
                              terminate=lambda: None, kill=lambda: None)
    monkeypatch.setattr(sync_pages.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(sync_pages.subprocess, "run", lambda *args, **kwargs: None)

    def pending(*args, **kwargs):
        raise URLError("not listening yet")

    monkeypatch.setattr(sync_pages, "urlopen", pending)
    with pytest.raises(TimeoutError, match="did not become ready"):
        with sync_pages.published_api(None):
            pytest.fail("API did not become ready")
    output = capsys.readouterr().out
    assert "Starting temporary published API" in output
    assert "Waiting for temporary API health: 5s / 30s" in output

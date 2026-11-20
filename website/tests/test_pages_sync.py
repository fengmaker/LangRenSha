from http.client import IncompleteRead
from io import BytesIO
import json
import os
from pathlib import Path
import ssl
import stat
from urllib.error import HTTPError, URLError

import pytest

from website.static_publish import sync_pages


class OnlineResponse(BytesIO):
    status = 200


def test_deployment_poll_retries_tls_eof(monkeypatch):
    commit = "abc123"
    run = {"id": 1, "head_sha": commit, "status": "completed", "conclusion": "success",
           "html_url": "https://example.test/run/1"}
    responses = iter([
        URLError(ssl.SSLEOFError(8, "UNEXPECTED_EOF_WHILE_READING")),
        OnlineResponse(json.dumps({"workflow_runs": [run]}).encode()),
    ])
    requests = []
    waits = []

    def urlopen(request, *, timeout):
        requests.append((request.full_url, timeout))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(sync_pages, "urlopen", urlopen)
    monkeypatch.setattr(sync_pages.time, "sleep", waits.append)

    assert sync_pages.wait_for_deployment(commit, 30) == {
        "id": 1, "url": "https://example.test/run/1", "conclusion": "success",
    }
    assert len(waits) == 1
    assert len(requests) == 2
    assert requests[0][0] == requests[1][0]
    assert all(0 < timeout <= 30 for _, timeout in requests)


def test_online_verification_retries_only_the_failed_request(monkeypatch, tmp_path):
    manifest = {"build_id": "build-1", "snapshot_id": "snapshot-1", "seasons": [{"id": "S23"}]}
    index = tmp_path / "data/releases/snapshot-1/games/index.json"
    index.parent.mkdir(parents=True)
    index.write_text('{"items": [{"id": "game-1", "season": "S23"}]}', encoding="utf-8")
    manifest_url = sync_pages.WEB_URL + "/data/manifest.json?build_id=build-1"
    home_url = sync_pages.WEB_URL + "/"
    game_url = sync_pages.WEB_URL + "/games/game-1/"

    class InterruptedResponse(OnlineResponse):
        def read(self):
            raise IncompleteRead(b"<ma", 5)

    responses = iter([
        OnlineResponse(json.dumps(manifest).encode()),
        HTTPError(home_url, 503, "Service Unavailable", {}, BytesIO()),
        OnlineResponse(b"<main>home</main>"),
        InterruptedResponse(),
        OnlineResponse(b"<main>game</main>"),
    ])
    requests = []
    waits = []

    def urlopen(request, *, timeout):
        requests.append(request.full_url)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(sync_pages, "urlopen", urlopen)
    monkeypatch.setattr(sync_pages.time, "sleep", waits.append)
    assert sync_pages.verify_online(tmp_path, manifest) == {
        "state": "passed", "manifest_matches": True, "routes": ["/", "/games/game-1/"],
    }
    assert requests == [manifest_url, home_url, home_url, game_url, game_url]
    assert waits == [1, 1]


@pytest.mark.parametrize("reason, timeout, expected, attempts", [
    (TimeoutError("no response"), 30, RuntimeError, 4),
    (TimeoutError("no response"), 1, RuntimeError, 1),
    (ssl.SSLCertVerificationError(1, "certificate verification failed"), 30, URLError, 1),
])
def test_deployment_poll_limits_retries(monkeypatch, reason, timeout, expected, attempts):
    waits = []
    requests = []
    clock = [0]

    def sleep(delay):
        waits.append(delay)
        clock[0] += delay

    def urlopen(request, *, timeout):
        requests.append(timeout)
        raise URLError(reason)

    monkeypatch.setattr(sync_pages, "urlopen", urlopen)
    monkeypatch.setattr(sync_pages.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sync_pages.time, "sleep", sleep)
    with pytest.raises(expected, match=str(reason)):
        sync_pages.wait_for_deployment("abc123", timeout)
    assert len(requests) == attempts
    assert len(waits) == attempts - 1
    assert requests == [timeout - sum(waits[:attempt]) for attempt in range(attempts)]


def test_pages_deploy_waits_for_upload_and_reuses_its_unique_artifact_name():
    workflow = (sync_pages.ROOT / "website/static_publish/templates/deploy-pages.yml").read_text(encoding="utf-8")
    upload, deploy = workflow.split("  deploy:\n", 1)
    artifact_name = "github-pages-${{ github.run_id }}-${{ github.run_attempt }}"
    assert f"artifact_name: {artifact_name}" in upload
    assert f"name: {artifact_name}" in upload
    assert "needs: upload" in deploy
    assert "artifact_name: ${{ needs.upload.outputs.artifact_name }}" in deploy
    assert "upload-pages-artifact@" not in deploy


@pytest.mark.parametrize("proxies,expected", [
    ({"https": "http://proxy.test:8080"}, {"HTTPS_PROXY": "http://proxy.test:8080"}),
    ({"http": "http://proxy.test:8080", "all": "socks5://proxy.test"},
     {"HTTP_PROXY": "http://proxy.test:8080", "ALL_PROXY": "socks5://proxy.test"}),
    ({}, {}),
])
def test_git_push_uses_system_proxy_without_mutating_process_environment(monkeypatch, tmp_path, proxies, expected):
    observed = {}
    monkeypatch.setattr(sync_pages, "getproxies", lambda: proxies)

    class Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def run(command, **kwargs):
        observed.update(kwargs)
        return Result()

    monkeypatch.setattr(sync_pages.subprocess, "run", run)
    before = dict(os.environ)
    assert sync_pages.git(tmp_path, "push", "origin", "main") == "ok"
    assert dict(os.environ) == before
    assert {key: observed["env"].get(key) for key in expected} == expected


def test_local_git_commands_do_not_override_proxy_settings(monkeypatch, tmp_path):
    observed = {}

    class Result:
        returncode = 0
        stdout = "main\n"
        stderr = ""

    def run(command, **kwargs):
        observed.update(kwargs)
        return Result()

    monkeypatch.setattr(sync_pages.subprocess, "run", run)
    assert sync_pages.git(tmp_path, "branch", "--show-current") == "main"
    assert observed.get("env") is None


def test_sync_tree_mirrors_only_generated_site_files(tmp_path):
    source = tmp_path / "source"
    (source / "data").mkdir(parents=True)
    (source / "data/manifest.json").write_text("new", encoding="utf-8")
    (source / "index.html").write_text("home", encoding="utf-8")
    destination = tmp_path / "publish" / "site"
    (destination / "obsolete").mkdir(parents=True)
    (destination / "obsolete/old.json").write_text("old", encoding="utf-8")
    (destination / "index.html").write_text("old!", encoding="utf-8")

    first = sync_pages.sync_tree(source, destination)
    assert first == {"written": 2, "unchanged": 0, "removed": 1}
    assert (destination / "data/manifest.json").read_text(encoding="utf-8") == "new"
    assert not (destination / "obsolete").exists()
    assert sync_pages.sync_tree(source, destination) == {"written": 0, "unchanged": 2, "removed": 0}


def test_sync_tree_rejects_linked_generated_paths(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "publish" / "site"
    destination.parent.mkdir()
    try:
        destination.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ValueError, match="links"):
        sync_pages.sync_tree(source, destination)


def test_publication_repository_requires_exact_target_and_no_independent_edits(tmp_path, monkeypatch):
    repository = tmp_path / "publish"
    repository.mkdir()
    calls = []
    answers = {
        ("rev-parse", "--show-toplevel"): repository.as_posix(),
        ("remote", "get-url", "origin"): sync_pages.ORIGIN,
        ("branch", "--show-current"): "main",
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
    }

    def fake_git(repo, *args):
        calls.append(args)
        return answers[args]

    monkeypatch.setattr(sync_pages, "git", fake_git)
    target, templates = sync_pages._check_repository(repository)
    assert target == repository / "site"
    assert set(templates) == {".github/workflows/deploy-pages.yml", "README.md"}

    answers[("status", "--porcelain=v1", "--untracked-files=all")] = " M notes.txt"
    with pytest.raises(RuntimeError, match="independent edits"):
        sync_pages._check_repository(repository)


@pytest.mark.parametrize("failed_stage", [None, "deployment", "verify_online"])
def test_publish_retries_push_even_when_no_new_commit_is_needed(tmp_path, monkeypatch, failed_stage):
    root = tmp_path / "workspace"
    ready = root / "tmp" / "ready"
    (ready / "data").mkdir(parents=True)
    manifest = {"build_id": "build-1", "snapshot_id": "snapshot-1", "release_id": "release-1",
                "complete": True, "base_path": "/langrensha-site", "seasons": []}
    (ready / "data/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (ready / "index.html").write_text("home", encoding="utf-8")
    repository = tmp_path / "publish"
    site = repository / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("home", encoding="utf-8")
    templates = {}
    monkeypatch.setattr(sync_pages, "ROOT", root)
    monkeypatch.setattr(sync_pages, "_check_repository", lambda path: (site, templates))
    git_calls = []
    hashed = []
    file_hash = sync_pages._file_hash
    target_scans = []
    rglob = Path.rglob

    def tracked_hash(path):
        hashed.append(path)
        return file_hash(path)

    def tracked_rglob(path, pattern):
        if path == site:
            target_scans.append(pattern)
        return rglob(path, pattern)

    monkeypatch.setattr(sync_pages, "_file_hash", tracked_hash)
    monkeypatch.setattr(Path, "rglob", tracked_rglob)

    def fake_git(repo, *args):
        git_calls.append(args)
        if args[:1] == ("diff",):
            return ""
        if args[:2] == ("rev-parse", "HEAD"):
            return "abc123"
        return ""

    monkeypatch.setattr(sync_pages, "git", fake_git)
    def deployment(commit, timeout):
        if failed_stage == "deployment":
            raise RuntimeError("connection lost")
        return {"conclusion": "success"}

    def verify_online(ready, manifest):
        if failed_stage == "verify_online":
            raise RuntimeError("connection lost")
        return {"state": "passed"}

    monkeypatch.setattr(sync_pages, "wait_for_deployment", deployment)
    monkeypatch.setattr(sync_pages, "verify_online", verify_online)

    if failed_stage:
        with pytest.raises(sync_pages.PublicationCheckError, match="已推送 abc123.*connection lost") as error:
            sync_pages.publish_site(ready, repository)
        assert error.value.stage == failed_stage
        assert git_calls.count(("push", "origin", "main")) == 1
        return

    result = sync_pages.publish_site(ready, repository)
    assert result["commit_created"] is False
    assert hashed.count(ready / "index.html") == 1
    assert hashed.count(site / "index.html") == 2  # Comparison and final readback.
    assert target_scans == ["*", "*"]  # Inventory and final verification.
    assert ("push", "origin", "main") in git_calls
    assert result["workflow"]["conclusion"] == "success"
    assert set(result["timings_seconds"]) == {
        "publication_preflight", "hash_source", "sync_files", "scan_target",
        "compare_target", "copy_files", "remove_stale_files", "verify_files",
        "commit", "push", "deployment", "verify_online",
    }


def test_check_only_builds_locally_without_publishing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sync_pages, "build", lambda base_path, output: calls.append((base_path, output)) or {"state": "passed"})
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: pytest.fail("must not publish"))
    monkeypatch.setattr(sync_pages, "cleanup", lambda *args, **kwargs: pytest.fail("must not clean"))

    assert sync_pages.main(["--check-only", "--output", str(tmp_path / "preview")]) == 0
    assert calls == [("/langrensha-site", tmp_path / "preview")]


@pytest.mark.parametrize("failed_stage", [None, "push", "deployment"])
def test_sync_records_build_and_publication_timings_on_success_or_failure(monkeypatch, tmp_path, failed_stage):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    built = {"state": "passed", "build_id": "build-1", "source_hash": "source-1",
             "timings_seconds": {"export_json": 2.5, "build_total": 3.0}}
    monkeypatch.setattr(sync_pages, "build", lambda *args: built)

    def publish(*args, timings, **kwargs):
        timings["push"] = 0.5
        if failed_stage == "push":
            raise RuntimeError("push failed")
        if failed_stage == "deployment":
            raise sync_pages.PublicationCheckError("abc123", "deployment", RuntimeError("connection lost"))
        return {"state": "passed", "commit": "abc123"}

    monkeypatch.setattr(sync_pages, "publish_site", publish)
    cleaned = []
    monkeypatch.setattr(sync_pages, "cleanup", lambda *args: cleaned.append(args) or {
        "state": "passed", "completed_games": 0, "pending_games": 0,
    })
    assert sync_pages.main([]) == (1 if failed_stage else 0)
    assert len(cleaned) == (0 if failed_stage else 1)
    report = json.loads((tmp_path / "tmp/pages-build/build-1/sync-result.json").read_text(encoding="utf-8"))
    assert report["state"] == ("failed" if failed_stage else "passed")
    if failed_stage == "deployment":
        assert report["commit"] == "abc123"
        assert report["push_succeeded"] is True
        assert report["failed_stage"] == "deployment"
    else:
        assert "push_succeeded" not in report
    assert report["timings_seconds"]["export_json"] == 2.5
    assert report["timings_seconds"]["push"] == 0.5
    assert report["timings_seconds"]["total"] >= report["timings_seconds"]["publication_total"]
    assert built["timings_seconds"] == {"export_json": 2.5, "build_total": 3.0}


@pytest.mark.parametrize("keep_temp", [False, True])
def test_cleanup_failure_does_not_misreport_verified_deployment_as_failed(monkeypatch, tmp_path, keep_temp):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    monkeypatch.setattr(sync_pages, "build", lambda *args: {
        "build_id": "build-1", "source_hash": "source-1", "timings_seconds": {},
    })
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: {"state": "passed"})
    calls = []

    def clean(*args):
        calls.append(args)
        raise PermissionError("occupied")

    monkeypatch.setattr(sync_pages, "cleanup", clean)
    assert sync_pages.main(["--keep-temp"] if keep_temp else []) == 0
    report = json.loads((tmp_path / "tmp/pages-build/build-1/sync-result.json").read_text(encoding="utf-8"))
    assert report["state"] == "passed"
    if keep_temp:
        assert calls == []
        assert "cleanup" not in report
    else:
        assert report["cleanup"] == {"state": "failed", "errors": ["occupied"]}


def test_default_sync_output_reports_outcome_without_dumping_internal_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sync_pages, "ROOT", tmp_path)
    monkeypatch.setattr(sync_pages, "build", lambda *args: {
        "state": "passed", "build_id": "build-1", "source_hash": "source-1",
        "routes": {"games": 380, "players": 95, "seasons": 3}, "timings_seconds": {},
    })
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: {
        "state": "passed", "url": "https://example.test/", "commit": "abc123",
    })
    monkeypatch.setattr(sync_pages, "cleanup", lambda *args: {
        "state": "passed", "completed_games": 4, "pending_games": 0, "paths": [], "errors": [],
    })
    assert sync_pages.main([]) == 0
    output = capsys.readouterr().out
    assert "上线成功" in output
    assert "https://example.test/" in output
    assert '"timings_seconds"' not in output
    assert '"source_hash"' not in output
    assert len(output.splitlines()) <= 6
    report = json.loads((tmp_path / "tmp/pages-build/build-1/sync-result.json").read_text(encoding="utf-8"))
    assert report["build"]["source_hash"] == "source-1"

import json
import os
from pathlib import Path
import stat

import pytest

from website.static_publish import sync_pages


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
    (destination / "index.html").write_text("stale", encoding="utf-8")

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


def test_publish_retries_push_even_when_no_new_commit_is_needed(tmp_path, monkeypatch):
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
    templates = {}
    monkeypatch.setattr(sync_pages, "ROOT", root)
    monkeypatch.setattr(sync_pages, "_check_repository", lambda path: (site, templates))
    git_calls = []

    def fake_git(repo, *args):
        git_calls.append(args)
        if args[:1] == ("diff",):
            return ""
        if args[:2] == ("rev-parse", "HEAD"):
            return "abc123"
        return ""

    monkeypatch.setattr(sync_pages, "git", fake_git)
    monkeypatch.setattr(sync_pages, "wait_for_deployment", lambda commit, timeout: {"conclusion": "success"})
    monkeypatch.setattr(sync_pages, "verify_online", lambda ready, manifest: {"state": "passed"})

    result = sync_pages.publish_site(ready, repository)

    assert result["commit_created"] is False
    assert ("push", "origin", "main") in git_calls
    assert result["workflow"]["conclusion"] == "success"


def test_check_only_builds_locally_without_publishing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sync_pages, "build", lambda base_path, output: calls.append((base_path, output)) or {"state": "passed"})
    monkeypatch.setattr(sync_pages, "publish_site", lambda *args, **kwargs: pytest.fail("must not publish"))

    assert sync_pages.main(["--check-only", "--output", str(tmp_path / "preview")]) == 0
    assert calls == [("/langrensha-site", tmp_path / "preview")]

"""Offline deployment regressions; not a substitute for Compose/container/DB QA."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

from website.api import bluff_store, publish, publish_bluffs

ROOT = Path(__file__).resolve().parents[2]
WEBSITE = ROOT / "website"


def _service(name: str) -> str:
    # Inspect this file's two-space service blocks without adding a YAML dependency.
    # Docker Compose's own `config --quiet` is the separate schema validation step.
    source = (WEBSITE / "compose.yaml").read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:|^volumes:|\Z)",
                      source, re.MULTILINE | re.DOTALL)
    assert match, f"missing deployment service: {name}"
    return match.group(1)


def test_formal_publish_mounts_cover_both_seasons_and_default_full_release(tmp_path):
    service = _service("publish")
    assert 'command: ["--seasons", "S22", "S23"]' in service
    assert 'entrypoint: ["python", "-m", "website.api.publish"]' in service
    assert "MASTERS_SOURCE_ROOT: /source" in service
    for season in ("S22", "S23"):
        assert f"../data/games/{season}:/source/data/games/{season}:ro" in service
        assert f"../data/extractions/{season}/voting:/source/data/extractions/{season}/voting:ro" in service
    # Materialize only declared mounts, without requiring Windows symlink privileges.
    for source, target in re.findall(r"^      - (.+):(/source/[^:]+):ro$", service, re.MULTILINE):
        destination = tmp_path / target.removeprefix("/source/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        origin = (WEBSITE / source).resolve()
        if origin.is_dir():
            # Preflight reads text evidence, not the archived audio/video.
            shutil.copytree(origin, destination, ignore=shutil.ignore_patterns("*.m4a", "*.mp4"))
        elif origin.is_file():
            shutil.copyfile(origin, destination)
        else:
            # Voting audit directories are optional; no source mutation here.
            assert "/extractions/" in target and target.endswith("/voting")
            destination.mkdir()
    result = publish._preflight(tmp_path, ["S22", "S23"], None)
    expected = publish._preflight(ROOT, ["S22", "S23"], None)
    assert result == expected  # Includes voting-audit hashes, not just game count.
    assert result["seasons"] == ["S22", "S23"]


def test_bluff_tool_uses_package_config_and_explicit_season_cli(monkeypatch):
    service = _service("publish-bluffs")
    assert 'profiles: ["tools"]' in service
    assert "../config:/app/config:ro" in service
    assert 'entrypoint: ["python", "-m", "website.api.publish_bluffs"]' in service
    assert 'command: ["--season", "S22", "--check"]' in service
    calls = []

    def fake_publish(season, path, check):
        calls.append((season, path, check))
        return {"checked": check, "published": not check}

    monkeypatch.setattr(bluff_store, "publish_review", fake_publish)
    for check in (True, False):
        for season in ("S22", "S23"):
            assert publish_bluffs.main(["--season", season] + (["--check"] if check else [])) == 0
    assert calls == [(season, None, check) for check in (True, False) for season in ("S22", "S23")]
    # The mounted config must include each guard's source, not just seasons.json.
    for season in ("S22", "S23"):
        assert bluff_store._expected_game_count(season) is not None


def test_api_image_includes_all_manifest_frames():
    dockerfile = (WEBSITE / "Dockerfile.api").read_text(encoding="utf-8")
    assert "COPY website/assets/bluff-frames /app/website/assets/bluff-frames" in dockerfile
    assert "COPY website/api /app/website/api" in dockerfile
    manifest = json.loads((WEBSITE / "api/bluff_frames.json").read_text(encoding="utf-8"))
    for season, frames in manifest["frames"].items():
        for filename in frames:
            assert (WEBSITE / "assets/bluff-frames" / season / filename).is_file()


def test_runtime_and_publication_credentials_remain_separate():
    api = _service("api")
    assert "postgresql://masters_web_reader:" in api
    assert "postgresql://masters:" not in api
    assert "volumes:" not in api
    for tool in ("publish", "publish-bluffs", "reader-setup"):
        service = _service(tool)
        assert 'profiles: ["tools"]' in service
        assert "postgresql://masters:${POSTGRES_PASSWORD}@db:5432/masters" in service
    assert 'command: ["python", "-m", "website.grant_reader"]' in _service("reader-setup")

"""Offline deployment regressions; not a substitute for Compose/container/DB QA."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

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


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        # Text evidence is required; archived media and Python caches are not.
        shutil.copytree(source, destination, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.m4a", "*.mp4", "*.wav", "__pycache__"))
    else:
        shutil.copyfile(source, destination)


def _materialize_mounts(service: str, target_prefix: str, destination: Path) -> None:
    for source, target in re.findall(rf"^      - (.+):({target_prefix}/[^:]+):ro$",
                                     _service(service), re.MULTILINE):
        target_path = destination / target.removeprefix(target_prefix + "/")
        origin = (WEBSITE / source).resolve()
        if origin.exists():
            _copy(origin, target_path)
        else:
            # These optional voting directories currently have no source files.
            assert "/extractions/" in target and target.endswith("/voting")
            target_path.mkdir(parents=True, exist_ok=True)


def test_formal_publish_mounts_cover_all_seasons_and_default_full_release(tmp_path):
    service = _service("publish")
    seasons = ["S21", "S22", "S23"]
    assert 'command: ["--seasons", "S21", "S22", "S23"]' in service
    assert 'entrypoint: ["python", "-m", "website.api.publish"]' in service
    assert "MASTERS_SOURCE_ROOT: /source" in service
    for season in seasons:
        assert f"../data/games/{season}:/source/data/games/{season}:ro" in service
        assert f"../data/extractions/{season}/voting:/source/data/extractions/{season}/voting:ro" in service
    # Materialize only declared mounts, without requiring Windows symlink privileges.
    source_root = tmp_path / "source"
    _materialize_mounts("publish", "/source", source_root)
    expected = publish._preflight(ROOT, seasons, None)

    # Execute with only the API image's COPY inputs, outside the repo import path.
    # This catches missing delayed imports and rule-source fingerprint files too.
    image_root = tmp_path / "app"
    for line in (WEBSITE / "Dockerfile.api").read_text(encoding="utf-8").splitlines():
        if line.startswith("COPY "):
            *sources, target = line.split()[1:]
            for source in sources:
                destination = image_root / target.removeprefix("/app/")
                if target.endswith("/"):
                    destination /= Path(source).name
                _copy(ROOT / source, destination)
    _materialize_mounts("publish-bluffs", "/app", image_root)
    code = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from website.api import app, bluff_store, publish
print(json.dumps({
    "publication": publish._preflight(Path(sys.argv[2]), ["S21", "S22", "S23"], None),
    "bluff_counts": {season: bluff_store._expected_game_count(season) for season in ["S22", "S23"]},
}))
"""
    process = subprocess.run([sys.executable, "-I", "-c", code, str(image_root), str(source_root)],
                             cwd=image_root, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert process.returncode == 0, process.stderr
    isolated = json.loads(process.stdout)
    result = isolated["publication"]
    assert result == expected  # Includes voting-audit hashes, not just game count.
    assert result["seasons"] == seasons
    assert isolated["bluff_counts"] == {
        season: bluff_store._expected_game_count(season) for season in ("S22", "S23")
    }


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
        for filename, record in frames.items():
            asset = WEBSITE / "assets/bluff-frames" / season / filename
            assert hashlib.sha256(asset.read_bytes()).hexdigest() == record["sha256"]


def test_api_image_includes_all_manifest_photos():
    dockerfile = (WEBSITE / "Dockerfile.api").read_text(encoding="utf-8")
    assert "COPY website/assets/player-photos /app/website/assets/player-photos" in dockerfile
    manifest = json.loads((WEBSITE / "api/player_photos.json").read_text(encoding="utf-8"))
    for players in manifest["players"].values():
        for record in players.values():
            asset = WEBSITE / "assets/player-photos" / record["asset"]
            assert hashlib.sha256(asset.read_bytes()).hexdigest() == record["sha256"]


def test_api_image_packages_shared_timeline_and_its_rule_dependencies():
    dockerfile = (WEBSITE / "Dockerfile.api").read_text(encoding="utf-8")
    for module in ("game_timeline", "game_inference", "game_time", "board_config",
                   "role_constraints", "rule_config", "season_config", "game_derivations",
                   "board_outcomes", "sheriff_speech_evidence", "voting_records", "incremental_scope"):
        assert f"scripts/{module}.py" in dockerfile
    assert "COPY config/game_rules.json /app/config/game_rules.json" in dockerfile
    assert "COPY config/board_templates /app/config/board_templates" in dockerfile


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

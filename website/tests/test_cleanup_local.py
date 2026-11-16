import hashlib
import json
import subprocess

import pytest

from website.public_data import _load_catalog, _load_games, _source_fingerprint
from website.static_publish.cleanup_local import cleanup


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.fixture
def batch(tmp_path):
    root = tmp_path
    write(root / "config/seasons.json", {"seasons": {"S23": {}}})
    entry = {"bvid": "BV1AbCdeFgHi", "cid": 10, "page": 1}
    formal = write(root / "data/games/S23/game-1/game.json", {
        "schema_version": 1, "id": "game-1", "season": "S23", "seats": [], "rounds": [],
        "source": {"media": [entry]},
    })
    item = {"entry": entry, "applied": True, "formal_dir": "data/games/S23/game-1",
            "game_sha256": hashlib.sha256(formal.read_bytes()).hexdigest()}
    state = write(root / "data/reports/S23/incremental/state.json", {
        "season": "S23", "items": {"done": item}, "weibo": {},
    })
    work = root / "data/extractions/S23/incremental/BV1AbCdeFgHi_p01_cid10"
    write(work / "candidate.json", {})
    raw = root / "data/raw/bilibili/BV1AbCdeFgHi/p01"
    write(raw / "manifest.json", entry)
    review = root / "data/manual_review/S23_新增对局人工复核.html"
    write(review, {})
    write(root / "data/manual_review/feedback/S23_逐局复核意见.json", {})
    transcript = root / "data/transcripts/S23/BV1AbCdeFgHi_p01_cid10_funasr"
    write(transcript / "transcript.json", {"source": entry})
    archive = root / "data/raw/weibo/window"
    write(archive / "manifest.json", {
        "mode": "author", "request": {"uid": "7525583841", "since": "2026-11-12", "until": "2026-11-13"},
        "window_scan_status": "completed", "incremental_scan_completed_at_utc": "2026-11-13T01:00:00Z",
        "counts": {"unparseable_dates_skipped": 0, "images_not_downloaded": 0,
                   "long_posts_expanded": 2, "long_posts": 2},
        "posts": [{"post_id": "post-1", "published_date": "2026-11-12"},
                  {"post_id": "post-2", "published_date": "2026-11-13"}],
    })
    checkpoint = root / "data/sources/weibo_checkpoint.json"
    write(checkpoint, {"uid": "7525583841", "complete_intervals": [["2026-11-01", "2026-11-11"]],
                       "posts": {"old-post": "2026-11-10"}})
    output = root / "tmp/pages-preview/site"
    write(output / "data/manifest.json", {})
    write(root / "tmp/pages-build/current/result.json", {"state": "passed"})
    write(root / "tmp/pages-build/current/sync-result.json", {"state": "passed"})
    write(root / "tmp/pages-build/current/snapshot/data.json", {})
    write(root / "tmp/pages-build/old/result.json", {"state": "failed"})
    write(root / "tmp/pages-build/running/snapshot/data.json", {})
    for path in ["website/web/.static-build/out/index.html", "website/web/.static-build/public/data/data.json",
                 "website/web/.static-build/.static-snapshot/data/data.json",
                 "website/web/.static-build/.next/cache/cache.json", "website/web/public/data/data.json",
                 ".models/weights.json", ".secrets/cookie.json", "tmp/unrelated/work.json"]:
        write(root / path, {})
    _, hashes = _load_games(root)
    _, catalog_hash = _load_catalog(root)
    source_hash = _source_fingerprint(root, hashes, catalog_hash)
    return locals()


def run(batch, **kwargs):
    return cleanup(batch["root"], batch["output"], "current", batch["source_hash"], **kwargs)


def test_completed_batch_cleanup_preserves_formal_data_and_weibo_progress(batch):
    result = run(batch, dry_run=True)
    assert result["state"] == "planned"
    assert batch["raw"].is_dir()
    assert json.loads(batch["checkpoint"].read_text())["complete_intervals"] == [["2026-11-01", "2026-11-11"]]
    result = run(batch)
    assert result["state"] == "passed"
    assert result["completed_games"] == 1
    for key in ("work", "raw", "transcript", "review", "archive", "output", "state"):
        assert not batch[key].exists(), key
    saved = json.loads(batch["checkpoint"].read_text())
    assert saved["complete_intervals"] == [["2026-11-01", "2026-11-12"]]
    assert saved["posts"] == {"old-post": "2026-11-10", "post-1": "2026-11-12", "post-2": "2026-11-13"}
    root = batch["root"]
    assert batch["formal"].is_file()
    for path in ["tmp/pages-build/current/result.json", "tmp/pages-build/current/sync-result.json",
                 "tmp/pages-build/running/snapshot/data.json", "website/web/.static-build/.next/cache/cache.json",
                 "website/web/public/data/data.json", ".models/weights.json", ".secrets/cookie.json",
                 "tmp/unrelated/work.json"]:
        assert (root / path).is_file(), path
    assert not (root / "tmp/pages-build/old").exists()
    assert not (root / "tmp/pages-build/current/snapshot").exists()
    assert not (root / "website/web/.static-build/public").exists()


def test_pending_match_keeps_shared_media_reviews_and_weibo(batch):
    state = json.loads(batch["state"].read_text())
    state["items"]["pending"] = {"entry": {**batch["entry"], "cid": 11}, "applied": False}
    write(batch["state"], state)
    pending = batch["work"].with_name("BV1AbCdeFgHi_p01_cid11")
    write(pending / "candidate.json", {})
    before = batch["checkpoint"].read_bytes()
    result = run(batch)
    assert result["pending_games"] == 1
    assert set(json.loads(batch["state"].read_text())["items"]) == {"pending"}
    assert not batch["work"].exists()
    assert pending.is_dir()
    assert batch["raw"].is_dir()
    assert batch["review"].is_file()
    assert batch["archive"].is_dir()
    assert batch["checkpoint"].read_bytes() == before


def test_modified_applied_game_keeps_its_temporary_materials(batch):
    state = json.loads(batch["state"].read_text())
    state["items"]["done"]["game_sha256"] = "older-applied-version"
    write(batch["state"], state)
    assert run(batch)["pending_games"] == 1
    assert batch["work"].is_dir()
    assert batch["archive"].is_dir()


def test_source_changed_since_build_does_not_delete_anything(batch):
    batch["formal"].write_text(batch["formal"].read_text() + "\n")
    with pytest.raises(ValueError, match="构建后发生变化"):
        run(batch)
    assert batch["output"].is_dir()
    assert batch["work"].is_dir()


def test_incomplete_weibo_window_is_kept(batch):
    path = batch["archive"] / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["counts"]["images_not_downloaded"] = 1
    write(path, manifest)
    before = batch["checkpoint"].read_bytes()
    assert run(batch)["state"] == "passed"
    assert batch["archive"].is_dir()
    assert json.loads(batch["checkpoint"].read_text()) == json.loads(before)


def test_checkpoint_write_failure_prevents_all_deletion(batch, monkeypatch):
    from website.static_publish import cleanup_local

    def fail(*args):
        raise PermissionError("checkpoint is read-only")

    monkeypatch.setattr(cleanup_local, "write_json", fail)
    with pytest.raises(PermissionError, match="checkpoint is read-only"):
        run(batch)
    for key in ("work", "raw", "archive", "state", "output"):
        assert batch[key].exists(), key


def test_external_output_is_rejected_before_any_deletion(batch):
    batch["output"] = batch["formal"].parent
    with pytest.raises(ValueError, match="leaves its temporary directory"):
        run(batch)
    assert batch["work"].is_dir()
    assert batch["formal"].is_file()


def test_junction_inside_temporary_materials_is_rejected_before_deletion(batch, tmp_path):
    link = batch["work"] / "formal-link"
    try:
        link.symlink_to(batch["formal"].parent, target_is_directory=True)
    except OSError:
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(batch["formal"].parent)],
                                capture_output=True)
        if result.returncode:
            pytest.skip("directory links are unavailable")
    try:
        with pytest.raises(ValueError, match="links or junctions"):
            run(batch)
        assert batch["formal"].is_file()
        assert batch["raw"].is_dir()
    finally:
        # rmdir/unlink removes the link itself, never the referenced directory.
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_locked_file_reports_partial_cleanup_and_keeps_resumable_state(batch, monkeypatch):
    from website.static_publish import cleanup_local
    original = cleanup_local.shutil.rmtree

    def remove(path):
        if path == batch["work"]:
            raise PermissionError("file is occupied")
        original(path)

    monkeypatch.setattr(cleanup_local.shutil, "rmtree", remove)
    result = run(batch)
    assert result["state"] == "partial"
    assert "file is occupied" in result["errors"][0]
    assert batch["state"].is_file()
    assert run(batch)["state"] == "partial"


def test_publication_cleanup_does_not_delete_another_accounts_pytest_cache(batch, monkeypatch):
    from website.static_publish import cleanup_local
    cache = batch["root"] / ".pytest_cache"
    write(cache / "v/cache/nodeids", [])
    original = cleanup_local.shutil.rmtree

    def remove(path):
        if path == cache:
            raise PermissionError(5, "Access is denied", str(cache))
        original(path)

    monkeypatch.setattr(cleanup_local.shutil, "rmtree", remove)
    assert run(batch)["state"] == "passed"
    assert cache.is_dir()

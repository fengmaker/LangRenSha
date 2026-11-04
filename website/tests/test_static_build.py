"""The accepted site and its receipt survive an unsuccessful replacement."""
import json
from pathlib import Path

import pytest

from website import build_static


def test_windows_exported_segment_is_served_at_the_browser_requested_url(tmp_path):
    from urllib.request import urlopen
    from website.check_static import _serve
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
    from website import export_static
    target, receipt_path, _ = ready_files(tmp_path, monkeypatch)
    monkeypatch.setattr(build_static, "source_receipt", lambda: {"source_commit": "test", "source_dirty": True})

    def unavailable(*args, **kwargs):
        raise RuntimeError("Published API unavailable")

    monkeypatch.setattr(export_static, "export_snapshot", unavailable)
    with pytest.raises(RuntimeError, match="Published API unavailable"):
        build_static.build("http://127.0.0.1:1", "/langrensha-site", target)
    assert (target / "index.html").read_text() == "previous accepted site"
    assert json.loads(receipt_path.read_text())["build_id"] == "old"
    failure, = (tmp_path / "tmp/pages-build").glob("*/receipt.json")
    assert json.loads(failure.read_text())["failed_step"] == "export"

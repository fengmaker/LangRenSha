import builtins
from pathlib import Path

import pytest

import website.static_publish.check_static as checker
from website.static_publish.check_static import StaticAcceptanceError
from website.tests.test_static_acceptance import _snapshot, _write_json


def test_check_basic_reports_basic_scope_without_api_browser_or_media_hashing(
        monkeypatch, tmp_path, capsys):
    out = _snapshot(tmp_path, broken_hash=True)
    report_path = tmp_path / "basic-report.json"

    def fail_if_called(*_args, **_kwargs):
        pytest.fail("basic acceptance must not call API or browser checks")

    monkeypatch.setattr(checker, "_api_check", fail_if_called)
    monkeypatch.setattr(checker, "_get_json", fail_if_called)
    monkeypatch.setattr(checker, "_snapshot_media_references", fail_if_called)
    monkeypatch.setattr(checker, "_browser_check", fail_if_called)
    monkeypatch.setattr(checker, "urlopen", fail_if_called)
    monkeypatch.setattr(checker.hashlib, "file_digest", fail_if_called)
    original_import = builtins.__import__

    def reject_playwright(name, *args, **kwargs):
        if name.startswith("playwright"):
            pytest.fail("basic acceptance must not import Playwright")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_playwright)

    report = checker.check_basic(out, "/example-site", output=report_path)

    assert report["state"] == "basic"
    assert report["check_scope"] == "basic"
    assert report["complete"] is True
    assert report["layers"]["structure"]["state"] == "passed"
    assert report["layers"]["structure"]["hashes_checked"] == 0
    assert report["layers"]["api"]["state"] == "skipped"
    assert report["layers"]["browser"]["state"] == "skipped"
    assert report["stage_durations_seconds"]["api"] == 0.0
    assert report["stage_durations_seconds"]["browser"] == 0.0
    assert report_path.is_file()
    assert "Acceptance stage seconds:" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["game_detail", "javascript", "media"])
def test_check_basic_rejects_missing_required_data_or_assets(tmp_path, missing):
    out = _snapshot(tmp_path)
    if missing == "game_detail":
        (out / "data/releases/snapshot-1/games/game-1.json").unlink()
        error = "Game detail files do not exactly cover"
    elif missing == "javascript":
        index = out / "index.html"
        index.write_text('<html><script src="/example-site/assets/missing.js"></script></html>',
                         encoding="utf-8")
        error = "Static asset reference is missing"
    else:
        snapshot = checker._load_snapshot(out, "/example-site")
        reference = next(iter(checker._snapshot_media_references(snapshot)))
        (out / Path(reference)).unlink()
        error = "Manifest media_files count differs"

    with pytest.raises(StaticAcceptanceError, match=error):
        checker.check_basic(out, "/example-site")


def test_check_basic_rejects_mixed_release_binding(tmp_path):
    out = _snapshot(tmp_path)
    detail_path = out / "data/releases/snapshot-1/games/game-1.json"
    detail = checker._json(detail_path)
    detail["release_id"] = "another-release"
    _write_json(detail_path, detail)

    with pytest.raises(StaticAcceptanceError, match="Stale release binding"):
        checker.check_basic(out, "/example-site")


def test_basic_acceptance_reuses_each_game_file_stat_within_its_inventory(tmp_path, monkeypatch):
    out = _snapshot(tmp_path)
    target = out / 'data/releases/snapshot-1/games/game-1.json'
    original = Path.stat
    calls = []
    def track(path, *args, **kwargs):
        if path == target:
            calls.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', track)
    checker.check_basic(out, '/example-site')
    assert len(calls) == 1


def test_local_asset_check_resolves_cloned_html_assets_once(monkeypatch, tmp_path):
    out = _snapshot(tmp_path)
    asset_root = out / "assets"
    asset_root.mkdir()
    javascript = asset_root / "shared.js"
    stylesheet = asset_root / "shared.css"
    javascript.write_text("window.ready = true;", encoding="utf-8")
    stylesheet.write_text("main { color: black; }", encoding="utf-8")
    for html_file in out.rglob("*.html"):
        html_file.write_text(
            '<html><script src="/example-site/assets/shared.js"></script>'
            '<link href="/example-site/assets/shared.css" rel="stylesheet"></html>',
            encoding="utf-8")

    resolve_calls = {javascript: 0, stylesheet: 0}
    is_file_calls = {javascript: 0, stylesheet: 0}
    original_resolve = Path.resolve
    original_is_file = Path.is_file

    def count_resolve(path, *args, **kwargs):
        if path in resolve_calls:
            resolve_calls[path] += 1
        return original_resolve(path, *args, **kwargs)

    def count_is_file(path):
        if path in is_file_calls:
            is_file_calls[path] += 1
        return original_is_file(path)

    monkeypatch.setattr(Path, "resolve", count_resolve)
    monkeypatch.setattr(Path, "is_file", count_is_file)

    assert checker._check_local_assets(checker._load_snapshot(out, "/example-site")) == 2
    assert resolve_calls == {javascript: 1, stylesheet: 1}
    assert is_file_calls == {javascript: 1, stylesheet: 1}

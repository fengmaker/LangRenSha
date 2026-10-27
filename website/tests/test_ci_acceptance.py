"""Offline guard tests; these are NOT proof of a successful live CI run."""
from pathlib import Path

import pytest

from website.ci_acceptance import require_disposable_database, require_test_execution


def test_ci_guard_refuses_non_ci_or_external_database(monkeypatch):
    monkeypatch.setenv("CI", "true")
    for url in ("", "postgresql://masters_ci:x@prod.example/masters_ci",
                "postgresql://masters_ci:x@127.0.0.1:5432/production"):
        monkeypatch.setenv("DATABASE_URL", url)
        with pytest.raises(RuntimeError):
            require_disposable_database()
    monkeypatch.setenv("DATABASE_URL", "postgresql://masters_ci:x@127.0.0.1:5432/masters_ci")
    require_disposable_database()
    monkeypatch.setenv("CI", "false")
    with pytest.raises(RuntimeError):
        require_disposable_database()


@pytest.mark.parametrize("content", ["", '<testcase name="db"><skipped/></testcase>',
                                    '<testcase name="db"><failure/></testcase>',
                                    '<testcase name="db"><error/></testcase>',
                                    '<testcase name="wrong"/>'])
def test_junit_guard_rejects_false_green(tmp_path: Path, content: str):
    path = tmp_path / "report.xml"
    path.write_text(f"<testsuites><testsuite>{content}</testsuite></testsuites>")
    with pytest.raises(RuntimeError):
        require_test_execution(path, {"db"})


def test_junit_guard_accepts_executed_required_test(tmp_path: Path):
    path = tmp_path / "report.xml"
    path.write_text('<testsuites><testsuite><testcase name="db"/></testsuite></testsuites>')
    assert require_test_execution(path, {"db"}) == 1


def test_artifacts_only_stage_sanitized_allowlisted_files(tmp_path, monkeypatch):
    from website.ci_acceptance import stage_artifacts, ROOT
    source, target = tmp_path / "raw", tmp_path / "upload"
    source.mkdir()
    monkeypatch.setenv("DATABASE_URL", "postgresql://masters_ci:owner-password@127.0.0.1:5432/masters_ci")
    monkeypatch.setenv("MASTERS_READER_PASSWORD", "reader-password")
    (source / "server.log").write_text(f"owner-password reader-password {ROOT} "
                                      "postgresql://user:pass@localhost/db")
    (source / "private.xml").write_text("do not upload")
    (source / ".env").write_text("do not upload")
    stage_artifacts(source, target)
    assert sorted(path.name for path in target.iterdir()) == ["server.log"]
    value = (target / "server.log").read_text()
    assert "owner-password" not in value and "reader-password" not in value
    assert "postgresql://" not in value and str(ROOT) not in value
    assert "owner-password" in (source / "server.log").read_text()

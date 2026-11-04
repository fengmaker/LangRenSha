from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege

from website.api import app as api_app


class _Connection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))
        return self


def test_local_api_uses_separate_reader_credentials_even_with_publisher_database_url(
        monkeypatch, tmp_path):
    reader_config = tmp_path / "masters_web_reader.json"
    config = {
        "host": "127.0.0.1",
        "port": 55432,
        "dbname": "jcms",
        "user": "masters_web_reader",
        "password": "test-only-reader-password-012345",
    }
    reader_config.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(api_app, "LOCAL_READER_CONFIG", reader_config)
    monkeypatch.setenv("DATABASE_URL", "postgresql://publisher.invalid/unused")

    connection = _Connection()
    attempted = []

    def connect(**kwargs):
        attempted.append(kwargs)
        return connection

    monkeypatch.setattr(api_app.psycopg, "connect", connect)
    result = api_app._connect_readonly()

    assert result is connection
    assert attempted == [{
        **{key: config[key] for key in ("host", "port", "dbname", "user", "password")},
        "row_factory": api_app.dict_row,
    }]
    assert any("BEGIN READ ONLY" in statement for statement in connection.statements)


def test_configured_reader_can_read_active_release_but_cannot_update_it():
    config_path = Path(__file__).resolve().parents[2] / ".secrets" / "masters_web_reader.json"
    if not config_path.is_file():
        pytest.skip("local reader account is not configured")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    with psycopg.connect(**config) as conn:
        account = conn.execute(
            "SELECT current_user, r.rolsuper, r.rolinherit, "
            "EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid), "
            "current_setting('default_transaction_read_only') "
            "FROM pg_roles r WHERE r.rolname=current_user"
        ).fetchone()
        assert account == ("masters_web_reader", False, False, False, "on")
        assert conn.execute(
            "SELECT 1 FROM masters_web.active_release a "
            "JOIN masters_web.releases r ON r.id=a.release_id WHERE a.singleton=true"
        ).fetchone()
        conn.rollback()

        conn.execute("SET default_transaction_read_only=off")
        conn.commit()
        conn.execute("BEGIN READ WRITE")
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "off"
        with pytest.raises(InsufficientPrivilege):
            conn.execute("UPDATE masters_web.active_release SET release_id=release_id WHERE false")
        conn.rollback()


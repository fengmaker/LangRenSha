"""Provision and verify the database role used by the read-only website API."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import InsufficientPrivilege

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ADMIN_CONFIG = ROOT / ".secrets" / "database.json"
LOCAL_READER_CONFIG = ROOT / ".secrets" / "masters_web_reader.json"
ROLE_NAME = "masters_web_reader"
WRITE_PRIVILEGES = "INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"


def _local_connection_options(config: dict) -> dict:
    return {key: config[key] for key in ("host", "port", "dbname", "user", "password")
            if key in config}


def _connect(connection):
    return psycopg.connect(**connection) if isinstance(connection, dict) else psycopg.connect(connection)


def _verify_account_setup(conn) -> None:
    state = conn.execute(
        "SELECT r.rolsuper, r.rolcreaterole, r.rolcreatedb, r.rolreplication, r.rolbypassrls, "
        "r.rolinherit, "
        "EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid) "
        "FROM pg_roles r WHERE r.rolname = %s", (ROLE_NAME,)
    ).fetchone()
    if not state or any(state):
        raise RuntimeError("只读角色仍有管理属性或角色继承关系，停止配置。")

    owned = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='masters_web' AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)) "
        "OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='masters_web' "
        "AND n.nspowner=(SELECT oid FROM pg_roles WHERE rolname=%s)) "
        "OR EXISTS (SELECT 1 FROM pg_database d WHERE d.datdba=(SELECT oid FROM pg_roles WHERE rolname=%s))",
        (ROLE_NAME, ROLE_NAME, ROLE_NAME),
    ).fetchone()[0]
    if owned:
        raise RuntimeError("只读角色拥有数据库对象，停止配置。")

    rights = conn.execute(
        "SELECT has_schema_privilege(%s, 'masters_web', 'CREATE'), "
        "has_table_privilege(%s, 'masters_web.active_release', 'UPDATE'), "
        "COALESCE((SELECT bool_or(has_table_privilege(%s, c.oid, %s)) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='masters_web' AND c.relkind IN ('r','p','v','m','f')), false), "
        "has_table_privilege(%s, 'masters_web.active_release', 'SELECT')",
        (ROLE_NAME, ROLE_NAME, ROLE_NAME, WRITE_PRIVILEGES, ROLE_NAME),
    ).fetchone()
    if rights[0] or rights[1] or rights[2] or not rights[3]:
        raise RuntimeError("masters_web_reader 的有效读写权限不符合只读契约，停止配置。")


def _verify_reader_login(reader_connection) -> None:
    with _connect(reader_connection) as conn:
        identity = conn.execute(
            "SELECT current_user, current_setting('default_transaction_read_only')"
        ).fetchone()
        if identity[0] != ROLE_NAME or identity[1] != "on":
            raise RuntimeError("只读角色登录身份或默认只读设置不符合预期。")
        snapshot = conn.execute(
            "SELECT r.id FROM masters_web.active_release a "
            "JOIN masters_web.releases r ON r.id=a.release_id WHERE a.singleton=true"
        ).fetchone()
        if not snapshot:
            raise RuntimeError("只读角色无法读取活动快照。")
        conn.rollback()

        # Prove table ACLs still block writes after the role's default read-only
        # transaction setting is explicitly disabled. WHERE false guarantees
        # the probe cannot change the active release even if ACLs regress.
        conn.execute("SET default_transaction_read_only = off")
        conn.commit()
        conn.execute("BEGIN READ WRITE")
        if conn.execute("SHOW transaction_read_only").fetchone()[0] != "off":
            conn.rollback()
            raise RuntimeError("无法开启显式读写事务，未能完成权限隔离验证。")
        try:
            conn.execute(
                "UPDATE masters_web.active_release SET release_id=release_id WHERE false"
            )
        except InsufficientPrivilege:
            conn.rollback()
        else:
            conn.rollback()
            raise RuntimeError("只读角色在显式读写事务中仍可更新 active_release。")


def _configure(dsn: str | None, admin_options: dict | None, reader_password: str,
               *, local: bool) -> dict | None:
    if not reader_password or len(reader_password) < 20:
        raise SystemExit("只读账号密码至少需要20字符。")
    admin_connection = dsn if dsn else admin_options
    if not admin_connection:
        raise SystemExit("需要管理员数据库连接配置。")
    reader_connection = (make_conninfo(dsn, user=ROLE_NAME, password=reader_password)
                         if dsn else {**admin_options, "user": ROLE_NAME, "password": reader_password})
    role = sql.Identifier(ROLE_NAME)

    with _connect(admin_connection) as conn:
        if not conn.execute("SELECT to_regclass('masters_web.releases')").fetchone()[0]:
            raise SystemExit("请先发布数据，再建立只读账号。")
        existing = conn.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, "
            "EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member=pg_roles.oid) "
            "FROM pg_roles WHERE rolname=%s", (ROLE_NAME,)
        ).fetchone()
        if existing and any(existing):
            raise SystemExit("同名角色已有管理属性或角色继承关系，停止自动配置。")
        if existing:
            conn.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                                 "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS")
                         .format(role, sql.Literal(reader_password)))
        else:
            conn.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                                 "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS")
                         .format(role, sql.Literal(reader_password)))
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
        conn.execute(sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA masters_web FROM {}").format(role))
        conn.execute(sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA masters_web FROM {}").format(role))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA masters_web TO {}").format(role))
        conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA masters_web TO {}").format(role))
        conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA masters_web GRANT SELECT ON TABLES TO {}")
                     .format(role))
        _verify_account_setup(conn)

    _verify_reader_login(reader_connection)
    if local:
        return {
            "host": admin_options["host"],
            "port": admin_options["port"],
            "dbname": admin_options["dbname"],
            "user": ROLE_NAME,
            "password": reader_password,
        }
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true",
                        help="use .secrets/database.json and save a separate local reader credential")
    args = parser.parse_args()
    if args.local:
        if not LOCAL_ADMIN_CONFIG.is_file():
            raise SystemExit("请先运行 scripts/local_postgres.py setup。")
        admin_config = json.loads(LOCAL_ADMIN_CONFIG.read_text(encoding="utf-8"))
        reader_config = (json.loads(LOCAL_READER_CONFIG.read_text(encoding="utf-8"))
                         if LOCAL_READER_CONFIG.is_file() else {})
        if reader_config and reader_config.get("user") != ROLE_NAME:
            raise SystemExit("本机只读凭据文件中的角色名不符合预期。")
        password = reader_config.get("password") or secrets.token_urlsafe(32)
        output = _configure(None, _local_connection_options(admin_config), password, local=True)
        LOCAL_READER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        temporary = LOCAL_READER_CONFIG.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        temporary.replace(LOCAL_READER_CONFIG)
        print("已配置本机 masters_web_reader；活动快照读取成功，显式读写事务更新 active_release 被拒绝。")
        return

    dsn = os.environ.get("DATABASE_URL")
    password = os.environ.get("MASTERS_READER_PASSWORD")
    if not dsn or not password:
        raise SystemExit("部署授权需要管理员 DATABASE_URL 和 MASTERS_READER_PASSWORD；本机请使用 --local。")
    _configure(dsn, None, password, local=False)
    print("已配置并验证 masters_web_reader，仅授予发布库读取权限。")


if __name__ == "__main__":
    main()

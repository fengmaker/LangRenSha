"""Provision the deployment's database reader; credentials stay in environment."""
from __future__ import annotations

import os

import psycopg
from psycopg import sql


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    password = os.environ.get("MASTERS_READER_PASSWORD")
    if not dsn or not password or len(password) < 20:
        raise SystemExit("需要管理员 DATABASE_URL 和至少20字符的 MASTERS_READER_PASSWORD。")
    role_name = "masters_web_reader"
    role = sql.Identifier(role_name)
    with psycopg.connect(dsn) as conn:
        if not conn.execute("SELECT to_regclass('masters_web.releases')").fetchone()[0]:
            raise SystemExit("请先发布数据，再建立只读账号。")
        existing = conn.execute("SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=%s",
                                (role_name,)).fetchone()
        if existing and any(existing):
            raise SystemExit("同名角色已有管理权限，停止自动配置。")
        if not existing:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
        else:
            conn.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA masters_web TO {}").format(role))
        conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA masters_web TO {}").format(role))
        conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA masters_web GRANT SELECT ON TABLES TO {}").format(role))
    print("已配置 masters_web_reader，仅授予发布库读取权限。")


if __name__ == "__main__":
    main()

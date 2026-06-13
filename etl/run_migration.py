"""
etl/run_migration.py
====================
Chay mot file .sql migration ma KHONG can cai psql.
Dung psycopg2 (da co san trong venv) de thuc thi.

Cach chay (tai thu muc goc du an, noi co .env):
    python -m etl.run_migration infra/db/migration_backfill_price_per_m2.sql

An toan:
  - Chay trong 1 transaction: neu loi giua chung -> ROLLBACK (khong sua nua chung).
  - In ra cac thong bao NOTICE tu PostgreSQL (vd: so dong da backfill).
"""

from __future__ import annotations

import sys
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    if len(sys.argv) < 2:
        print("Dung: python -m etl.run_migration <duong_dan_file.sql>", file=sys.stderr)
        return 1

    sql_path = sys.argv[1]
    if not os.path.isfile(sql_path):
        print(f"[LOI] Khong tim thay file: {sql_path}", file=sys.stderr)
        return 1

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("[LOI] Thieu DATABASE_URL trong .env", file=sys.stderr)
        return 1

    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    print(f"[1/2] Ket noi DB va chay: {sql_path}")
    conn = psycopg2.connect(database_url, connect_timeout=20)
    try:
        # File migration tu quan ly BEGIN/COMMIT, nen tat autocommit cua psycopg2
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
            # In cac thong bao NOTICE (RAISE NOTICE trong SQL)
            for notice in conn.notices:
                print("   ", notice.strip())
        print("[2/2] XONG — migration chay thanh cong.")
        return 0
    except Exception as exc:
        print(f"[LOI] Migration that bai: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

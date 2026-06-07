"""
Kết nối DB dùng chung cho tất cả pages.
Dùng st.cache_resource để giữ connection pool qua các lần rerun.
"""

from __future__ import annotations

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
import psycopg2.extras
import streamlit as st
from typing import Any


@st.cache_resource(show_spinner=False)
def _get_conn():
    """Tạo kết nối psycopg2 tái sử dụng (cached ở process level)."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "Thiếu biến môi trường DATABASE_URL. "
            "Chạy: export DATABASE_URL=postgresql://..."
        )
    conn = psycopg2.connect(db_url)
    conn.autocommit = True   # read-only dashboard — autocommit OK
    return conn


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Chạy SELECT, trả về list of dict. Tự reconnect nếu connection đã đóng."""
    conn = _get_conn()
    # Kiểm tra connection còn sống không
    try:
        conn.cursor().execute("SELECT 1")
    except psycopg2.OperationalError:
        # Xóa cache để tạo lại connection
        _get_conn.clear()
        conn = _get_conn()

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

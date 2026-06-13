"""Tầng truy cập dữ liệu — kết nối PostgreSQL (Supabase Gold) bằng psycopg2.

Dùng một connection pool (ThreadedConnectionPool) khởi tạo lúc startup để
tái sử dụng kết nối giữa các request. Mọi truy vấn ở đây là READ-ONLY
(web app chỉ đọc tầng Gold), nên bật autocommit cho đơn giản.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from .config import get_settings

logger = logging.getLogger("hanoirent.db")

# Pool toàn cục, khởi tạo ở init_pool() khi app startup.
_pool: ThreadedConnectionPool | None = None


def init_pool(minconn: int = 1, maxconn: int = 5) -> None:
    """Khởi tạo connection pool. Gọi 1 lần lúc FastAPI startup."""
    global _pool
    if _pool is not None:
        return

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "Thiếu DATABASE_URL. Đặt biến môi trường trỏ tới Supabase PostgreSQL, "
            "ví dụ trong backend/.env hoặc .env gốc repo."
        )

    _pool = ThreadedConnectionPool(
        minconn,
        maxconn,
        dsn=settings.database_url,
        # Supabase pooler đôi khi cần keepalive để tránh idle disconnect.
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
        connect_timeout=10,
    )
    logger.info("DB pool đã khởi tạo (min=%s, max=%s).", minconn, maxconn)


def close_pool() -> None:
    """Đóng toàn bộ pool khi app shutdown."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("DB pool đã đóng.")


@contextmanager
def _get_conn() -> Iterator[Any]:
    """Mượn 1 connection từ pool và trả lại sau khi dùng."""
    if _pool is None:
        raise RuntimeError("DB pool chưa được khởi tạo. Gọi init_pool() trước.")

    conn = _pool.getconn()
    try:
        conn.autocommit = True
        yield conn
    finally:
        _pool.putconn(conn)


def query(sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    """Chạy SELECT, trả về list of dict (RealDictCursor).

    Tự reconnect 1 lần nếu connection trong pool đã chết.
    """
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params or ())
                return [dict(r) for r in cur.fetchall()]
    except psycopg2.OperationalError:
        # Connection hỏng — thử lại 1 lần với connection mới.
        logger.warning("Connection lỗi, thử query lại lần 2.")
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params or ())
                return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    """Chạy SELECT trả về 1 dòng (hoặc None)."""
    rows = query(sql, params)
    return rows[0] if rows else None


def ping() -> bool:
    """Kiểm tra DB còn sống (dùng cho /health)."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("DB ping thất bại: %s", exc)
        return False

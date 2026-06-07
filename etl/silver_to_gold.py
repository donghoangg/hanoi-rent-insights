"""
ETL: Silver → Gold

Xây dựng các bảng gold từ silver.listings đã sạch:
  - gold.price_stats_overall   — tính ngưỡng phân vị để phân loại price_segment
  - gold.listings_for_map      — tin có lat/lng hợp lệ, dùng cho web app
  - gold.price_stats_by_ward   — thống kê giá theo phường + loại hình, dùng cho dashboard

Chạy:
    python -m etl.silver_to_gold
    python -m etl.silver_to_gold --table map          # chỉ refresh gold.listings_for_map
    python -m etl.silver_to_gold --table stats        # chỉ refresh stats
    python -m etl.silver_to_gold --table all          # mặc định: refresh tất cả
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("silver_to_gold")


# =============================================================
# Step 1: Tính price_stats_overall (percentile để phân segment)
# =============================================================

_STATS_OVERALL_SQL = """
-- Xoá dữ liệu cũ
TRUNCATE gold.price_stats_overall;

-- Tính percentile p33/p67 cho từng property_type
-- Dùng percentile_cont (continuous interpolation) — chuẩn thống kê
INSERT INTO gold.price_stats_overall
    (property_type, listing_count, avg_price_vnd, median_price_vnd,
     p33_price_vnd, p67_price_vnd, refreshed_at)
SELECT
    property_type,
    COUNT(*)                                                    AS listing_count,
    ROUND(AVG(price_vnd))::BIGINT                               AS avg_price_vnd,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY price_vnd)::BIGINT AS median_price_vnd,
    percentile_cont(0.33) WITHIN GROUP (ORDER BY price_vnd)::BIGINT AS p33_price_vnd,
    percentile_cont(0.67) WITHIN GROUP (ORDER BY price_vnd)::BIGINT AS p67_price_vnd,
    NOW()
FROM silver.listings
WHERE price_status = 'ok'
  AND price_vnd IS NOT NULL
  AND property_type IS NOT NULL
GROUP BY property_type
HAVING COUNT(*) >= 5;   -- Bỏ qua loại hình có quá ít tin (không đủ ý nghĩa thống kê)

-- Thêm row tổng hợp 'all' cho các tin không rõ property_type
INSERT INTO gold.price_stats_overall
    (property_type, listing_count, avg_price_vnd, median_price_vnd,
     p33_price_vnd, p67_price_vnd, refreshed_at)
SELECT
    'all',
    COUNT(*),
    ROUND(AVG(price_vnd))::BIGINT,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY price_vnd)::BIGINT,
    percentile_cont(0.33) WITHIN GROUP (ORDER BY price_vnd)::BIGINT,
    percentile_cont(0.67) WITHIN GROUP (ORDER BY price_vnd)::BIGINT,
    NOW()
FROM silver.listings
WHERE price_status = 'ok'
  AND price_vnd IS NOT NULL
ON CONFLICT (property_type) DO UPDATE
    SET listing_count    = EXCLUDED.listing_count,
        avg_price_vnd    = EXCLUDED.avg_price_vnd,
        median_price_vnd = EXCLUDED.median_price_vnd,
        p33_price_vnd    = EXCLUDED.p33_price_vnd,
        p67_price_vnd    = EXCLUDED.p67_price_vnd,
        refreshed_at     = EXCLUDED.refreshed_at;
"""


# =============================================================
# Step 2: Rebuild gold.listings_for_map
# Dùng TRUNCATE + INSERT thay vì upsert để đảm bảo map luôn
# phản ánh đúng trạng thái silver hiện tại (tin bị xoá ở silver
# sẽ tự biến mất khỏi gold sau mỗi lần refresh).
# =============================================================

_LISTINGS_FOR_MAP_SQL = """
TRUNCATE gold.listings_for_map;

INSERT INTO gold.listings_for_map (
    listing_id, title, price_vnd, area_m2, bedrooms,
    property_type, province, ward,
    latitude, longitude,
    source_name, source_url,
    thumbnail_url,
    posted_at,
    price_per_m2,
    price_segment,
    has_air_con, has_parking, has_elevator, has_wifi, has_washing_machine,
    is_active, refreshed_at
)
SELECT
    s.listing_id,
    s.title,
    s.price_vnd,
    s.area_m2,
    s.bedrooms,
    s.property_type,
    s.province,
    s.ward,
    s.latitude,
    s.longitude,
    s.source_name,
    s.source_url,
    -- Ưu tiên thumbnail đã upload lên Supabase, fallback sang URL gốc
    COALESCE(s.self_thumbnail_url, s.original_thumbnail_url)    AS thumbnail_url,
    s.posted_at,
    -- price_per_m2: tránh chia cho 0
    CASE
        WHEN s.area_m2 IS NOT NULL AND s.area_m2 > 0
        THEN ROUND(s.price_vnd::NUMERIC / s.area_m2)::BIGINT
        ELSE NULL
    END                                                          AS price_per_m2,
    -- price_segment: so sánh với p33/p67 của cùng property_type
    -- Fallback sang stats 'all' nếu property_type không có trong bảng stats
    CASE
        WHEN s.price_vnd <= COALESCE(pt.p33_price_vnd, all_pt.p33_price_vnd)
            THEN 'thap'
        WHEN s.price_vnd >= COALESCE(pt.p67_price_vnd, all_pt.p67_price_vnd)
            THEN 'cao'
        ELSE 'trung_binh'
    END                                                          AS price_segment,
    s.has_air_con,
    s.has_parking,
    s.has_elevator,
    s.has_wifi,
    s.has_washing_machine,
    TRUE                                                         AS is_active,
    NOW()                                                        AS refreshed_at
FROM silver.listings s
-- Join stats theo property_type
LEFT JOIN gold.price_stats_overall pt
    ON pt.property_type = s.property_type
-- Luôn có fallback 'all'
LEFT JOIN gold.price_stats_overall all_pt
    ON all_pt.property_type = 'all'
WHERE s.latitude  IS NOT NULL
  AND s.longitude IS NOT NULL
  AND s.price_status = 'ok'
  AND s.price_vnd IS NOT NULL;
"""


# =============================================================
# Step 3: Rebuild gold.price_stats_by_ward
# =============================================================

_STATS_BY_WARD_SQL = """
TRUNCATE gold.price_stats_by_ward;

INSERT INTO gold.price_stats_by_ward (
    ward, province, property_type,
    listing_count,
    avg_price_vnd, median_price_vnd,
    p25_price_vnd, p75_price_vnd,
    avg_area_m2, avg_price_per_m2,
    refreshed_at
)
SELECT
    s.ward,
    s.province,
    s.property_type,
    COUNT(*)                                                        AS listing_count,
    ROUND(AVG(s.price_vnd))::BIGINT                                 AS avg_price_vnd,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY s.price_vnd)::BIGINT AS median_price_vnd,
    percentile_cont(0.25) WITHIN GROUP (ORDER BY s.price_vnd)::BIGINT AS p25_price_vnd,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY s.price_vnd)::BIGINT AS p75_price_vnd,
    ROUND(AVG(s.area_m2), 2)                                        AS avg_area_m2,
    CASE
        WHEN AVG(s.area_m2) > 0
        THEN ROUND(AVG(s.price_vnd) / NULLIF(AVG(s.area_m2), 0))::BIGINT
        ELSE NULL
    END                                                             AS avg_price_per_m2,
    NOW()
FROM silver.listings s
WHERE s.price_status = 'ok'
  AND s.price_vnd IS NOT NULL
  AND s.ward IS NOT NULL
  AND s.property_type IS NOT NULL
GROUP BY s.ward, s.province, s.property_type
HAVING COUNT(*) >= 3;   -- Ít nhất 3 tin mới có ý nghĩa thống kê cho ward
"""


# =============================================================
# Runner
# =============================================================

def _run_sql(conn: psycopg2.extensions.connection, label: str, sql: str):
    """Chạy multi-statement SQL, log thời gian."""
    t0 = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        # psycopg2 không hỗ trợ multi-statement trong 1 execute;
        # tách theo ";" và chạy từng statement thực sự (bỏ qua comment-only).
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            # Bỏ qua nếu toàn bộ statement chỉ là comment SQL
            non_comment = "\n".join(
                line for line in stmt.splitlines()
                if not line.strip().startswith("--")
            ).strip()
            if not non_comment:
                continue
            cur.execute(stmt)
    conn.commit()
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    logger.info("[%s] Done in %.2fs", label, elapsed)


def _log_counts(conn: psycopg2.extensions.connection):
    """Log số lượng bản ghi trong các bảng gold sau refresh."""
    queries = {
        "gold.listings_for_map":    "SELECT COUNT(*) FROM gold.listings_for_map",
        "gold.price_stats_by_ward": "SELECT COUNT(*) FROM gold.price_stats_by_ward",
        "gold.price_stats_overall": "SELECT COUNT(*) FROM gold.price_stats_overall",
    }
    with conn.cursor() as cur:
        for table, q in queries.items():
            cur.execute(q)
            count = cur.fetchone()[0]
            logger.info("  %s: %d rows", table, count)


def run(
    database_url: str,
    table: str = "all",   # 'all' | 'map' | 'stats'
):
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    logger.info("Connected to database")

    if table in ("all", "stats"):
        logger.info("Step 1/3: Rebuilding price_stats_overall...")
        _run_sql(conn, "price_stats_overall", _STATS_OVERALL_SQL)

    if table in ("all", "map"):
        logger.info("Step 2/3: Rebuilding listings_for_map...")
        _run_sql(conn, "listings_for_map", _LISTINGS_FOR_MAP_SQL)

    if table in ("all", "stats"):
        logger.info("Step 3/3: Rebuilding price_stats_by_ward...")
        _run_sql(conn, "price_stats_by_ward", _STATS_BY_WARD_SQL)

    logger.info("Row counts after refresh:")
    _log_counts(conn)
    conn.close()
    logger.info("silver_to_gold complete")


# =============================================================
# CLI
# =============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Silver → Gold ETL")
    parser.add_argument(
        "--table",
        choices=["all", "map", "stats"],
        default="all",
        help="Bảng gold cần refresh (mặc định: all)",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("Thiếu biến môi trường DATABASE_URL")

    run(database_url=db_url, table=args.table)

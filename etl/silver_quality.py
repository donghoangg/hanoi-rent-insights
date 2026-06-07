"""
etl/silver_quality.py
=====================
Chạy sau bronze_to_silver. Thực hiện 2 bước kiểm tra chất lượng trên silver.listings:

1. IQR Outlier Detection
   - Tính Q1, Q3, IQR theo từng (property_type, source_name)
   - Ngưỡng: price_vnd < Q1 - 1.5*IQR  hoặc  price_vnd > Q3 + 1.5*IQR
   - Hard limit bổ sung: < 500_000 VND/tháng hoặc > 100_000_000 VND/tháng
   - UPDATE silver.listings SET is_price_outlier = TRUE/FALSE

2. Cross-source Duplicate Detection
   - Tin bị coi là trùng khi: cùng ward + price_vnd (±5%) + area_m2 (±5%)
     và xuất hiện ở ít nhất 2 source khác nhau
   - Gán cùng duplicate_group_id (dùng listing_id nhỏ nhất làm group id)
   - UPDATE silver.listings SET duplicate_group_id = ...

Chạy:
    python -m etl.silver_quality
    python -m etl.silver_quality --skip-outlier
    python -m etl.silver_quality --skip-duplicate
    python -m etl.silver_quality --dry-run   (chỉ in report, không UPDATE)
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================
# 1. IQR Outlier Detection
# =============================================================

# Hard limits tuyệt đối — bất kể property_type
PRICE_MIN_VND = 500_000        # 500k/tháng
PRICE_MAX_VND = 100_000_000    # 100 triệu/tháng
IQR_MULTIPLIER = 1.5


def run_outlier_detection(conn: psycopg2.extensions.connection, dry_run: bool = False) -> dict:
    """
    Tính IQR theo (property_type, source_name), UPDATE is_price_outlier.
    Trả về dict thống kê.
    """
    logger.info("=== Outlier Detection (IQR) ===")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Bước 1: Reset tất cả về FALSE trước
        if not dry_run:
            cur.execute("UPDATE silver.listings SET is_price_outlier = FALSE")
            logger.info("Reset all is_price_outlier → FALSE")

        # Bước 2: Tính IQR theo từng nhóm (property_type, source_name)
        cur.execute("""
            SELECT
                property_type,
                source_name,
                COUNT(*)                                                    AS cnt,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_vnd)    AS q1,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_vnd)    AS q3
            FROM silver.listings
            WHERE price_vnd IS NOT NULL
              AND price_status = 'ok'
            GROUP BY property_type, source_name
            HAVING COUNT(*) >= 10   -- cần đủ mẫu để IQR có nghĩa
        """)
        groups = cur.fetchall()
        logger.info("Found %d groups for IQR calculation", len(groups))

        total_outlier = 0
        group_stats = []

        for g in groups:
            q1 = float(g["q1"])
            q3 = float(g["q3"])
            iqr = q3 - q1
            lower = max(PRICE_MIN_VND, q1 - IQR_MULTIPLIER * iqr)
            upper = min(PRICE_MAX_VND, q3 + IQR_MULTIPLIER * iqr)

            if dry_run:
                cur.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM silver.listings
                    WHERE property_type = %s
                      AND source_name = %s
                      AND price_vnd IS NOT NULL
                      AND price_status = 'ok'
                      AND (price_vnd < %s OR price_vnd > %s)
                """, (g["property_type"], g["source_name"], lower, upper))
                outlier_cnt = cur.fetchone()["cnt"]
            else:
                cur.execute("""
                    UPDATE silver.listings
                    SET is_price_outlier = TRUE
                    WHERE property_type = %s
                      AND source_name = %s
                      AND price_vnd IS NOT NULL
                      AND price_status = 'ok'
                      AND (price_vnd < %s OR price_vnd > %s)
                """, (g["property_type"], g["source_name"], lower, upper))
                outlier_cnt = cur.rowcount

            total_outlier += outlier_cnt
            group_stats.append({
                "property_type": g["property_type"] or "khac",
                "source_name":   g["source_name"],
                "count":         g["cnt"],
                "q1":            int(q1),
                "q3":            int(q3),
                "lower_bound":   int(lower),
                "upper_bound":   int(upper),
                "outliers":      outlier_cnt,
            })
            logger.info(
                "  %s / %s: Q1=%.0f Q3=%.0f → [%.0f, %.0f] — %d outliers",
                g["property_type"], g["source_name"], q1, q3, lower, upper, outlier_cnt,
            )

        # Bước 3: Hard limit cho các tin có price_vnd ngoài range tuyệt đối
        if not dry_run:
            cur.execute("""
                UPDATE silver.listings
                SET is_price_outlier = TRUE
                WHERE price_vnd IS NOT NULL
                  AND (price_vnd < %s OR price_vnd > %s)
            """, (PRICE_MIN_VND, PRICE_MAX_VND))
            hard_limit_cnt = cur.rowcount
            logger.info("Hard limit outliers (outside absolute range): %d", hard_limit_cnt)
        else:
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM silver.listings
                WHERE price_vnd IS NOT NULL
                  AND (price_vnd < %s OR price_vnd > %s)
            """, (PRICE_MIN_VND, PRICE_MAX_VND))
            hard_limit_cnt = cur.fetchone()["cnt"]

        # Tổng kết
        cur.execute("SELECT COUNT(*) AS cnt FROM silver.listings WHERE is_price_outlier = TRUE")
        final_outlier_total = cur.fetchone()["cnt"] if not dry_run else total_outlier

        cur.execute("SELECT COUNT(*) AS cnt FROM silver.listings")
        total_rows = cur.fetchone()["cnt"]

        if not dry_run:
            conn.commit()

        stats = {
            "total_rows":      total_rows,
            "total_outliers":  final_outlier_total,
            "outlier_rate_pct": round(100 * final_outlier_total / max(total_rows, 1), 2),
            "hard_limit_cnt":  hard_limit_cnt,
            "group_stats":     group_stats,
        }
        logger.info(
            "Outlier detection done — %d / %d rows flagged (%.1f%%)",
            final_outlier_total, total_rows, stats["outlier_rate_pct"],
        )
        return stats


# =============================================================
# 2. Cross-source Duplicate Detection
# =============================================================

PRICE_TOLERANCE  = 0.05   # ±5%
AREA_TOLERANCE   = 0.05   # ±5%


def run_duplicate_detection(conn: psycopg2.extensions.connection, dry_run: bool = False) -> dict:
    """
    Tìm tin trùng cross-source: cùng ward + price gần bằng + area gần bằng
    từ ít nhất 2 source khác nhau.
    Gán duplicate_group_id = listing_id nhỏ nhất trong nhóm.
    """
    logger.info("=== Duplicate Detection (cross-source) ===")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Reset
        if not dry_run:
            cur.execute("UPDATE silver.listings SET duplicate_group_id = NULL")
            logger.info("Reset all duplicate_group_id → NULL")

        # Tìm các cặp tin nghi trùng:
        # Self-join trên ward + price ±5% + area ±5% + khác source
        cur.execute("""
            WITH candidates AS (
                SELECT
                    a.listing_id  AS id_a,
                    b.listing_id  AS id_b,
                    LEAST(a.listing_id, b.listing_id) AS group_id
                FROM silver.listings a
                JOIN silver.listings b
                    ON a.ward IS NOT NULL
                    AND a.ward = b.ward
                    AND a.source_name <> b.source_name
                    AND a.listing_id < b.listing_id   -- tránh đếm đôi
                    AND a.price_vnd IS NOT NULL AND b.price_vnd IS NOT NULL
                    AND a.area_m2   IS NOT NULL AND b.area_m2   IS NOT NULL
                    AND ABS(a.price_vnd - b.price_vnd)::FLOAT / NULLIF(a.price_vnd, 0) <= %s
                    AND ABS(a.area_m2  - b.area_m2 )::FLOAT / NULLIF(a.area_m2,   0) <= %s
                WHERE a.price_status = 'ok'
                  AND b.price_status = 'ok'
                  AND a.is_price_outlier = FALSE
                  AND b.is_price_outlier = FALSE
            )
            SELECT
                id_a, id_b, group_id,
                COUNT(*) OVER () AS total_pairs
            FROM candidates
        """, (PRICE_TOLERANCE, AREA_TOLERANCE))
        pairs = cur.fetchall()

        if not pairs:
            logger.info("No duplicate pairs found")
            if not dry_run:
                conn.commit()
            return {"total_pairs": 0, "total_duplicates": 0}

        total_pairs = pairs[0]["total_pairs"] if pairs else 0
        logger.info("Found %d duplicate pairs", total_pairs)

        if not dry_run:
            # UPDATE từng listing_id với group_id tương ứng
            # Dùng UPDATE ... FROM VALUES để batch update hiệu quả
            values = []
            group_map: dict[int, int] = {}
            for p in pairs:
                group_map[p["id_a"]] = min(group_map.get(p["id_a"], p["group_id"]), p["group_id"])
                group_map[p["id_b"]] = min(group_map.get(p["id_b"], p["group_id"]), p["group_id"])

            if group_map:
                values_str = ",".join(f"({lid}, {gid})" for lid, gid in group_map.items())
                cur.execute(f"""
                    UPDATE silver.listings AS s
                    SET duplicate_group_id = v.group_id
                    FROM (VALUES {values_str}) AS v(listing_id, group_id)
                    WHERE s.listing_id = v.listing_id
                """)
                total_duplicates = cur.rowcount
                logger.info("Marked %d listings as duplicates in %d groups",
                            total_duplicates, len(set(group_map.values())))
            else:
                total_duplicates = 0

            conn.commit()
        else:
            total_duplicates = len(set(p["id_a"] for p in pairs) | set(p["id_b"] for p in pairs))

        stats = {
            "total_pairs":      total_pairs,
            "total_duplicates": total_duplicates,
        }
        logger.info("Duplicate detection done — %d listings flagged", total_duplicates)
        return stats


# =============================================================
# Runner
# =============================================================

def run(
    database_url: str,
    skip_outlier:   bool = False,
    skip_duplicate: bool = False,
    dry_run:        bool = False,
) -> dict:
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    logger.info("Connected to database%s", " (DRY RUN)" if dry_run else "")

    results = {}

    if not skip_outlier:
        results["outlier"] = run_outlier_detection(conn, dry_run=dry_run)

    if not skip_duplicate:
        results["duplicate"] = run_duplicate_detection(conn, dry_run=dry_run)

    conn.close()

    # In summary
    logger.info("=" * 50)
    logger.info("QUALITY CHECK SUMMARY%s", " (DRY Run — no changes)" if dry_run else "")
    if "outlier" in results:
        o = results["outlier"]
        logger.info(
            "Outliers:    %d / %d rows (%.1f%%)",
            o["total_outliers"], o["total_rows"], o["outlier_rate_pct"],
        )
    if "duplicate" in results:
        d = results["duplicate"]
        logger.info(
            "Duplicates:  %d listings in %d pairs",
            d["total_duplicates"], d["total_pairs"],
        )
    logger.info("=" * 50)

    return results


# =============================================================
# CLI
# =============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Silver layer quality checks")
    parser.add_argument("--skip-outlier",   action="store_true", help="Bỏ qua outlier detection")
    parser.add_argument("--skip-duplicate", action="store_true", help="Bỏ qua duplicate detection")
    parser.add_argument("--dry-run",        action="store_true", help="Chỉ report, không UPDATE DB")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("ERROR: DATABASE_URL not set in environment or .env")

    run(
        database_url=database_url,
        skip_outlier=args.skip_outlier,
        skip_duplicate=args.skip_duplicate,
        dry_run=args.dry_run,
    )

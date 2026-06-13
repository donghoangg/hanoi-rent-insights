"""
etl/export_silver.py
====================
Xuất toàn bộ silver.listings ra CSV để phục vụ EDA (phân tích khám phá dữ liệu).

Mục đích: lấy snapshot dữ liệu Silver ra file CSV, dùng để phân tích insight
trước khi xây dashboard tầng Gold.

Cách chạy (tại thư mục gốc dự án hanoi-rent-insights, nơi có .env):
    python -m etl.export_silver
    python -m etl.export_silver --out data/silver_listings_export.csv
    python -m etl.export_silver --all-columns      # SELECT * (phòng khi thiếu cột)

File CSV xuất ra dùng encoding utf-8-sig để mở bằng Excel không bị lỗi tiếng Việt.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Danh sách cột khớp đúng schema thật của silver.listings
# (theo migration_add_monitoring.sql + code bronze_to_silver.py / silver_quality.py)
COLUMNS = [
    "listing_id", "source_name", "source_id", "source_url",
    "title", "description",
    "price_vnd", "price_per_m2", "deposit_vnd", "is_negotiable",
    "area_m2", "bedrooms", "bathrooms",
    "property_type", "furnishing_level",
    "address", "province", "ward", "address_status",
    "latitude", "longitude", "geocode_status",
    "has_air_conditioner", "has_water_heater", "has_fridge", "has_washing_machine",
    "has_furniture", "has_wifi", "has_kitchen", "is_self_contained",
    "free_hours", "landlord_shared", "good_security", "near_market",
    "thumbnail_status",
    "price_status", "is_price_outlier", "duplicate_group_id",
    "posted_at", "created_at",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export silver.listings → CSV cho EDA")
    parser.add_argument(
        "--out",
        default="silver_listings_export.csv",
        help="Đường dẫn file CSV xuất ra (mặc định: silver_listings_export.csv)",
    )
    parser.add_argument(
        "--all-columns",
        action="store_true",
        help="Dùng SELECT * thay vì danh sách cột cố định (phòng khi DB thiếu/khác cột)",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("[LỖI] Không tìm thấy DATABASE_URL trong .env", file=sys.stderr)
        return 1

    if args.all_columns:
        query = "SELECT * FROM silver.listings ORDER BY listing_id"
    else:
        col_list = ",\n        ".join(COLUMNS)
        query = f"SELECT\n        {col_list}\n    FROM silver.listings ORDER BY listing_id"

    print("[1/3] Đang kết nối tới database...")
    try:
        conn = psycopg2.connect(database_url, connect_timeout=15)
    except Exception as exc:
        print(f"[LỖI] Kết nối DB thất bại: {exc}", file=sys.stderr)
        return 1

    try:
        with conn.cursor() as cur:
            print("[2/3] Đang truy vấn silver.listings...")
            try:
                cur.execute(query)
            except psycopg2.errors.UndefinedColumn as exc:
                conn.rollback()
                print(
                    f"[LỖI] Có cột không tồn tại trong DB:\n  {exc}\n"
                    "  → Thử chạy lại với cờ --all-columns:\n"
                    "      python -m etl.export_silver --all-columns",
                    file=sys.stderr,
                )
                return 2

            header = [d[0] for d in cur.description]

            # Tạo thư mục cha nếu cần
            out_dir = os.path.dirname(os.path.abspath(args.out))
            os.makedirs(out_dir, exist_ok=True)

            print(f"[3/3] Đang ghi ra file: {args.out}")
            rows_written = 0
            with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                for row in cur:
                    writer.writerow(row)
                    rows_written += 1

        print(f"\n✓ XONG: đã xuất {rows_written} dòng ({len(header)} cột) → {args.out}")
        print("  Tiếp theo: copy file CSV này vào thư mục dự án để gửi cho Claude phân tích.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

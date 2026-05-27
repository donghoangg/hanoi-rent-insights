# scraper/pipelines.py
"""
Scrapy Item Pipelines cho HanoiRent Insights.

Thứ tự xử lý (theo priority trong settings.py):
1. ValidationPipeline (100)  — kiểm tra field bắt buộc, bỏ item lỗi
2. DuplicatesPipeline (200)  — check trùng source_id+source_name trong DB
3. BronzePipeline (300)      — ghi raw data vào bronze schema
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
from scrapy import Spider
from scrapy.exceptions import DropItem

from .items import RentingItem

logger = logging.getLogger(__name__)


# =============================================================
# 1. ValidationPipeline
# =============================================================

class ValidationPipeline:
    """
    Kiểm tra field bắt buộc, loại bỏ item không hợp lệ.
    Ghi log số lượng item bị drop sau mỗi spider.
    """

    REQUIRED_FIELDS = ["source_name", "source_id", "source_url", "price_vnd"]
    MIN_PRICE = 500_000          # 500k VND/tháng — lọc rác
    MAX_PRICE = 100_000_000      # 100 triệu VND/tháng — loại bỏ outlier rõ ràng

    def __init__(self):
        self._stats = {}

    def open_spider(self, spider: Spider):
        self._stats[spider.name] = {"total": 0, "dropped": 0}

    def close_spider(self, spider: Spider):
        s = self._stats.get(spider.name, {})
        logger.info(
            "[%s] ValidationPipeline: %d total, %d dropped (%.1f%%)",
            spider.name,
            s.get("total", 0),
            s.get("dropped", 0),
            100 * s.get("dropped", 0) / max(s.get("total", 1), 1),
        )

    def process_item(self, item: RentingItem, spider: Spider) -> RentingItem:
        self._stats[spider.name]["total"] += 1

        # Kiểm tra field bắt buộc
        for field in self.REQUIRED_FIELDS:
            if not item.get(field):
                self._stats[spider.name]["dropped"] += 1
                raise DropItem(f"[{spider.name}] Missing required field '{field}': {item.get('source_url', 'N/A')}")

        # Kiểm tra giá hợp lệ
        try:
            price = int(item["price_vnd"])
        except (ValueError, TypeError):
            self._stats[spider.name]["dropped"] += 1
            raise DropItem(f"[{spider.name}] Invalid price_vnd='{item['price_vnd']}': {item['source_url']}")

        if not (self.MIN_PRICE <= price <= self.MAX_PRICE):
            self._stats[spider.name]["dropped"] += 1
            raise DropItem(
                f"[{spider.name}] Price out of range ({price:,} VND): {item['source_url']}"
            )

        # Chuẩn hoá kiểu dữ liệu
        item["price_vnd"] = price
        if item.get("area_m2"):
            try:
                item["area_m2"] = float(item["area_m2"])
            except (ValueError, TypeError):
                item["area_m2"] = None

        for int_field in ("bedrooms", "bathrooms"):
            if item.get(int_field):
                try:
                    item[int_field] = int(item[int_field])
                except (ValueError, TypeError):
                    item[int_field] = None

        return item


# =============================================================
# 2. DuplicatesPipeline
# =============================================================

class DuplicatesPipeline:
    """
    Bỏ qua item đã tồn tại trong bronze.listings_raw (theo source_name + source_id).
    Dùng in-memory set sau khi load từ DB khi spider open — hiệu quả hơn query từng item.
    """

    def __init__(self):
        self._seen: set[tuple[str, str]] = set()
        self._conn = None
        self._dropped = 0

    def open_spider(self, spider: Spider):
        database_url = spider.settings.get("DATABASE_URL")
        if not database_url:
            logger.warning("[DuplicatesPipeline] DATABASE_URL not set — dedup disabled")
            return

        try:
            self._conn = psycopg2.connect(database_url)
            cur = self._conn.cursor()
            cur.execute("SELECT source_name, source_id FROM bronze.listings_raw")
            self._seen = {(row[0], row[1]) for row in cur.fetchall()}
            cur.close()
            logger.info(
                "[DuplicatesPipeline] Loaded %d existing entries from bronze",
                len(self._seen),
            )
        except Exception as exc:
            logger.error("[DuplicatesPipeline] Failed to load existing entries: %s", exc)
            self._seen = set()

    def close_spider(self, spider: Spider):
        if self._conn:
            self._conn.close()
        logger.info("[DuplicatesPipeline] Dropped %d duplicate items", self._dropped)

    def process_item(self, item: RentingItem, spider: Spider) -> RentingItem:
        key = (item["source_name"], item["source_id"])
        if key in self._seen:
            self._dropped += 1
            raise DropItem(
                f"[{spider.name}] Duplicate: {item['source_name']}:{item['source_id']}"
            )
        self._seen.add(key)
        return item


# =============================================================
# 3. BronzePipeline
# =============================================================

class BronzePipeline:
    """
    Ghi item vào bronze layer:
    - bronze.listings_raw  — toàn bộ raw_payload dạng JSONB
    - bronze.listing_images_raw — danh sách image_urls
    """

    def __init__(self):
        self._conn = None
        self._cur = None
        self._inserted = 0
        self._errors = 0

    def open_spider(self, spider: Spider):
        database_url = spider.settings.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is not configured in settings")

        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = False
        self._cur = self._conn.cursor()
        logger.info("[BronzePipeline] Connected to database")

    def close_spider(self, spider: Spider):
        if self._conn:
            try:
                self._conn.commit()
            except Exception as exc:
                logger.error("[BronzePipeline] Final commit failed: %s", exc)
                self._conn.rollback()
            finally:
                self._cur.close()
                self._conn.close()
        logger.info(
            "[BronzePipeline] Closed — %d inserted, %d errors",
            self._inserted, self._errors,
        )

    def process_item(self, item: RentingItem, spider: Spider) -> RentingItem:
        try:
            self._insert_listing(item)
            self._insert_images(item)
            self._conn.commit()
            self._inserted += 1
        except Exception as exc:
            self._conn.rollback()
            self._errors += 1
            logger.error(
                "[BronzePipeline] Insert failed for %s:%s — %s",
                item.get("source_name"), item.get("source_id"), exc,
            )

        return item

    # ----------------------------------------------------------
    def _build_raw_payload(self, item: RentingItem) -> dict:
        """
        Nếu spider đã set raw_payload thì dùng luôn.
        Nếu không, serialize toàn bộ item fields (bỏ image_urls nếu quá dài).
        """
        if item.get("raw_payload"):
            return item["raw_payload"]

        payload = dict(item)
        # image_urls có thể rất dài, đã lưu riêng ở bảng images
        payload.pop("image_urls", None)
        return payload

    def _insert_listing(self, item: RentingItem):
        payload = self._build_raw_payload(item)
        self._cur.execute(
            """
            INSERT INTO bronze.listings_raw
                (source_name, source_id, source_url, raw_payload, scraped_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_name, source_id) DO NOTHING
            """,
            (
                item["source_name"],
                item["source_id"],
                item.get("source_url"),
                json.dumps(payload, ensure_ascii=False, default=str),
                datetime.now(timezone.utc),
            ),
        )

    def _insert_images(self, item: RentingItem):
        image_urls: list[str] = item.get("image_urls") or []
        # Đảm bảo thumbnail chắc chắn có trong danh sách
        thumbnail = item.get("thumbnail_url")
        if thumbnail and thumbnail not in image_urls:
            image_urls = [thumbnail] + list(image_urls)

        if not image_urls:
            return

        rows = [
            (item["source_name"], item["source_id"], url, order)
            for order, url in enumerate(image_urls)
        ]
        psycopg2.extras.execute_values(
            self._cur,
            """
            INSERT INTO bronze.listing_images_raw
                (source_name, source_id, image_url, image_order, scraped_at)
            VALUES %s
            ON CONFLICT DO NOTHING
            """,
            rows,
            template="(%s, %s, %s, %s, NOW())",
        )

# scraper/pipelines.py
"""
Scrapy Item Pipelines cho HanoiRent Insights.

Thứ tự xử lý (theo priority trong settings.py):
1. ValidationPipeline (100)  — kiểm tra field bắt buộc cứng (URL + địa chỉ),
                                ghi tin lỗi vào bronze.listings_quarantine thay vì drop hẳn
2. DuplicatesPipeline (200)  — check trùng source_id+source_name trong DB
3. BronzePipeline (300)      — ghi raw data vào bronze.listings_raw

Điều kiện CÁCH LY (quarantine) — tin bị đưa vào bronze.listings_quarantine:
  - Thiếu source_url (URL)
  - Thiếu address (địa chỉ)

Các trường thiếu khác (title, price, area...) KHÔNG cách ly — tin vẫn vào bronze.listings_raw
và được gắn cờ ở bước Silver ETL sau.
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
# 1. ValidationPipeline + QuarantinePipeline (ghép chung)
# =============================================================

class ValidationPipeline:
    """
    - Tin thiếu source_url hoặc address → ghi vào bronze.listings_quarantine, drop khỏi pipeline.
    - Tin còn lại → chuẩn hoá kiểu dữ liệu cơ bản, chuyển sang pipeline tiếp theo.
    - Ghi log thống kê cuối spider: total / quarantined / passed.
    """

    # Hai field bắt buộc cứng — thiếu 1 trong 2 thì cách ly
    QUARANTINE_FIELDS = ["source_url", "address"]

    def __init__(self):
        self._conn = None
        self._stats: dict[str, dict] = {}

    def open_spider(self, spider: Spider):
        self._stats[spider.name] = {"total": 0, "quarantined": 0, "passed": 0}
        database_url = spider.settings.get("DATABASE_URL")
        if database_url:
            try:
                self._conn = psycopg2.connect(database_url)
                self._conn.autocommit = False
                logger.info("[ValidationPipeline] DB connected for quarantine")
            except Exception as exc:
                logger.error("[ValidationPipeline] DB connect failed: %s — quarantine disabled", exc)
                self._conn = None
        else:
            logger.warning("[ValidationPipeline] DATABASE_URL not set — quarantine will only log, not persist")

    def close_spider(self, spider: Spider):
        if self._conn:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass
        s = self._stats.get(spider.name, {})
        total = s.get("total", 0)
        quarantined = s.get("quarantined", 0)
        passed = s.get("passed", 0)
        pass_rate = 100 * passed / max(total, 1)
        logger.info(
            "[%s] ValidationPipeline: total=%d  passed=%d  quarantined=%d  pass_rate=%.1f%%",
            spider.name, total, passed, quarantined, pass_rate,
        )
        # Chia sẻ quarantine_count cho BronzePipeline đọc khi ghi scrape_runs
        if spider.crawler and spider.crawler.stats:
            spider.crawler.stats.set_value("hanoi/quarantine_count", quarantined)
            spider.crawler.stats.set_value("hanoi/total_scraped", total)

    def process_item(self, item: RentingItem, spider: Spider) -> RentingItem:
        self._stats[spider.name]["total"] += 1

        # Xác định các field bị thiếu trong danh sách bắt buộc cứng
        missing = [f for f in self.QUARANTINE_FIELDS if not item.get(f)]

        if missing:
            self._stats[spider.name]["quarantined"] += 1
            error_reason = "missing:" + ",".join(missing)
            self._quarantine(item, spider, error_reason, missing)
            raise DropItem(
                f"[{spider.name}] Quarantined ({error_reason}): {item.get('source_url') or item.get('source_id', 'N/A')}"
            )

        # Chuẩn hoá kiểu dữ liệu cơ bản cho các field tuỳ chọn
        if item.get("price_vnd") is not None:
            try:
                item["price_vnd"] = int(float(str(item["price_vnd"]).replace(",", "").strip()))
            except (ValueError, TypeError):
                item["price_vnd"] = None   # giá sai định dạng → để None, xử lý ở Silver

        if item.get("area_m2") is not None:
            try:
                item["area_m2"] = float(item["area_m2"])
            except (ValueError, TypeError):
                item["area_m2"] = None

        for int_field in ("bedrooms", "bathrooms"):
            if item.get(int_field) is not None:
                try:
                    item[int_field] = int(item[int_field])
                except (ValueError, TypeError):
                    item[int_field] = None

        self._stats[spider.name]["passed"] += 1
        return item

    def _quarantine(self, item: RentingItem, spider: Spider, error_reason: str, missing_fields: list[str]):
        """Ghi item lỗi vào bronze.listings_quarantine để audit sau."""
        payload = {k: v for k, v in dict(item).items() if k != "image_urls"}
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        missing_json = json.dumps(missing_fields)

        if self._conn:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO bronze.listings_quarantine
                            (source_name, source_id, source_url, raw_payload,
                             error_reason, missing_fields, scraped_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            item.get("source_name", spider.name),
                            item.get("source_id"),
                            item.get("source_url"),
                            payload_json,
                            error_reason,
                            missing_json,
                            datetime.now(timezone.utc),
                        ),
                    )
                self._conn.commit()
            except Exception as exc:
                self._conn.rollback()
                logger.error("[ValidationPipeline] Quarantine insert failed: %s", exc)
        else:
            # Fallback: chỉ log nếu không có DB
            logger.warning(
                "[%s] QUARANTINE (no DB): %s | reason=%s",
                spider.name, item.get("source_url") or item.get("source_id"), error_reason,
            )

        # Đánh dấu internal flag trên item (không ghi ra DB nhưng hữu ích khi debug)
        item["_quarantine"] = True
        item["_error_reason"] = error_reason
        item["_missing_fields"] = missing_fields
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
        # Chia sẻ duplicate_count cho BronzePipeline đọc khi ghi scrape_runs
        if spider.crawler and spider.crawler.stats:
            spider.crawler.stats.set_value("hanoi/duplicate_count", self._dropped)

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
        self._run_id: int | None = None
        self._started_at: datetime | None = None

    def open_spider(self, spider: Spider):
        database_url = spider.settings.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is not configured in settings")

        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = False
        self._cur = self._conn.cursor()
        logger.info("[BronzePipeline] Connected to database")

        # Ghi hàng 'running' vào bronze.scrape_runs để tracking realtime
        self._started_at = datetime.now(timezone.utc)
        source_name = getattr(spider, "source_name", spider.name)
        try:
            self._cur.execute(
                """
                INSERT INTO bronze.scrape_runs
                    (source_name, spider_name, started_at, status)
                VALUES (%s, %s, %s, 'running')
                RETURNING run_id
                """,
                (source_name, spider.name, self._started_at),
            )
            self._run_id = self._cur.fetchone()[0]
            self._conn.commit()
            logger.info("[BronzePipeline] scrape_runs run_id=%d started", self._run_id)
        except Exception as exc:
            self._conn.rollback()
            logger.warning("[BronzePipeline] Could not insert scrape_run: %s", exc)
            self._run_id = None

    def close_spider(self, spider: Spider):
        if self._conn:
            try:
                self._conn.commit()
            except Exception as exc:
                logger.error("[BronzePipeline] Final commit failed: %s", exc)
                self._conn.rollback()

        logger.info(
            "[BronzePipeline] Closed — %d inserted, %d errors",
            self._inserted, self._errors,
        )

        # Cập nhật scrape_runs với kết quả cuối
        if self._run_id is not None and self._conn:
            finished_at = datetime.now(timezone.utc)
            duration_sec = (
                (finished_at - self._started_at).total_seconds()
                if self._started_at else None
            )

            # Đọc counts từ Scrapy stats (được set bởi Validation và DuplicatesPipeline)
            stats = spider.crawler.stats if spider.crawler else None
            quarantine_count = int(stats.get_value("hanoi/quarantine_count", 0)) if stats else 0
            duplicate_count  = int(stats.get_value("hanoi/duplicate_count",  0)) if stats else 0
            total_scraped    = int(stats.get_value("hanoi/total_scraped",     0)) if stats else 0

            # total_scraped từ ValidationPipeline = total trước khi dedup
            # Nếu không có, tính lại từ các thành phần
            if total_scraped == 0:
                total_scraped = self._inserted + quarantine_count + duplicate_count + self._errors

            pass_count = self._inserted
            pass_rate_pct = round(100.0 * pass_count / max(total_scraped, 1), 1)

            try:
                self._cur.execute(
                    """
                    UPDATE bronze.scrape_runs SET
                        finished_at      = %s,
                        duration_sec     = %s,
                        total_scraped    = %s,
                        pass_count       = %s,
                        quarantine_count = %s,
                        duplicate_count  = %s,
                        error_count      = %s,
                        pass_rate_pct    = %s,
                        status           = 'finished'
                    WHERE run_id = %s
                    """,
                    (
                        finished_at,
                        duration_sec,
                        total_scraped,
                        pass_count,
                        quarantine_count,
                        duplicate_count,
                        self._errors,
                        pass_rate_pct,
                        self._run_id,
                    ),
                )
                self._conn.commit()
                logger.info(
                    "[BronzePipeline] scrape_runs run_id=%d finished — "
                    "total=%d pass=%d quar=%d dup=%d err=%d rate=%.1f%%",
                    self._run_id, total_scraped, pass_count,
                    quarantine_count, duplicate_count, self._errors, pass_rate_pct,
                )
            except Exception as exc:
                self._conn.rollback()
                logger.error("[BronzePipeline] Could not update scrape_run: %s", exc)

        if self._conn:
            try:
                self._cur.close()
                self._conn.close()
            except Exception:
                pass

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

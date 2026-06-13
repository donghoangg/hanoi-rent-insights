"""
ETL: Download & upload thumbnails cho silver.listings

Quy trình:
  1. Query silver.listings WHERE thumbnail_status = 'pending'
  2. Với mỗi tin: download ảnh gốc → resize 300×200 JPEG q75 → upload Supabase Storage
  3. Cập nhật self_thumbnail_url + thumbnail_status = 'success' | 'failed'

Chạy:
    python -m etl.download_thumbnails
    python -m etl.download_thumbnails --batch-size 50   # mặc định 100
    python -m etl.download_thumbnails --retry-failed    # thử lại các tin status='failed'
    python -m etl.download_thumbnails --limit 200       # debug
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
load_dotenv()
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import psycopg2
import psycopg2.extras
import requests
from PIL import Image
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("download_thumbnails")

# =============================================================
# Config
# =============================================================

THUMB_WIDTH  = 300
THUMB_HEIGHT = 200
JPEG_QUALITY = 75
BUCKET_NAME  = "listing-thumbnails"

# Timeout khi download ảnh gốc
DOWNLOAD_TIMEOUT = 12  # giây

# Số luồng song song (cẩn thận với rate limit của web nguồn)
MAX_WORKERS = 4

BATCH_SIZE = 100

# Headers giả lập browser để tránh bị block ảnh
DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    "Referer": "https://www.nhatot.com/",
}

# Delay nhỏ giữa các download để tránh bị rate-limit
INTER_DOWNLOAD_DELAY = 0.2  # giây


# =============================================================
# Dataclass
# =============================================================

@dataclass
class DownloadResult:
    listing_id: int
    success: bool
    public_url: Optional[str] = None
    error: Optional[str] = None


# =============================================================
# Image processing
# =============================================================

def _download_and_resize(image_url: str) -> Optional[bytes]:
    """
    Download ảnh từ URL, resize về 300×200, encode JPEG q75.
    Trả về bytes hoặc None nếu thất bại.

    Các trường hợp xử lý:
    - Ảnh không phải RGB (RGBA, P, L...) → convert về RGB trước khi save JPEG
    - Ảnh nhỏ hơn target → thumbnail() không upscale, giữ nguyên tỷ lệ
    - Response không phải ảnh (HTML lỗi) → PIL sẽ raise, bắt exception
    """
    resp = requests.get(
        image_url,
        timeout=DOWNLOAD_TIMEOUT,
        headers=DOWNLOAD_HEADERS,
        stream=True,
    )
    resp.raise_for_status()

    # Giới hạn kích thước tải về (tránh ảnh quá lớn chiếm RAM)
    content = b""
    max_bytes = 10 * 1024 * 1024  # 10 MB
    for chunk in resp.iter_content(chunk_size=8192):
        content += chunk
        if len(content) > max_bytes:
            raise ValueError(f"Image too large (>{max_bytes // 1024 // 1024} MB): {image_url}")

    img = Image.open(BytesIO(content))

    # Convert sang RGB — JPEG không hỗ trợ alpha channel (RGBA, PA) hay palette (P)
    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    # thumbnail() giữ tỷ lệ, không upscale nếu ảnh đã nhỏ hơn target
    img.thumbnail((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


# =============================================================
# Supabase uploader
# =============================================================

class SupabaseUploader:
    def __init__(self, supabase_url: str, supabase_key: str):
        self._client: Client = create_client(supabase_url, supabase_key)
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Tạo bucket nếu chưa tồn tại (idempotent)."""
        try:
            buckets = self._client.storage.list_buckets()
            existing = {b.name for b in buckets}
            if BUCKET_NAME not in existing:
                self._client.storage.create_bucket(
                    BUCKET_NAME,
                    options={"public": True},
                )
                logger.info("Created bucket: %s", BUCKET_NAME)
        except Exception as exc:
            # Bucket đã tồn tại hoặc lỗi không nghiêm trọng
            logger.debug("_ensure_bucket: %s", exc)

    def upload(self, listing_id: int, image_bytes: bytes) -> str:
        """
        Upload bytes lên Supabase Storage.
        Trả về public URL.
        Path: {listing_id}.jpg
        """
        file_path = f"{listing_id}.jpg"
        self._client.storage.from_(BUCKET_NAME).upload(
            path=file_path,
            file=image_bytes,
            file_options={
                "content-type": "image/jpeg",
                "cache-control": "public, max-age=31536000",
                "upsert": "true",   # ghi đè nếu đã tồn tại (idempotent)
            },
        )
        return self._client.storage.from_(BUCKET_NAME).get_public_url(file_path)


# =============================================================
# DB helpers
# =============================================================

def _read_pending_batch(
    conn: psycopg2.extensions.connection,
    statuses: tuple[str, ...],
    after_id: int,
    limit: int,
) -> list[dict]:
    """
    Đọc batch listing cần xử lý thumbnail.

    Dùng con trỏ theo listing_id (cursor-based) thay vì OFFSET: luôn lấy các tin
    có listing_id > after_id. Tránh bug OFFSET — vì sau mỗi batch các tin đã xử lý
    đổi status (không còn pending), nếu dùng OFFSET cố định thì offset nhảy qua cả
    những tin chưa xử lý → bỏ sót data. Cursor-based cũng tránh lặp vô hạn ở chế độ
    --retry-failed (tin failed mãi vẫn không bị đọc lại trong cùng một lần chạy).
    """
    placeholders = ", ".join(["%s"] * len(statuses))
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT listing_id, original_thumbnail_url, source_name
            FROM silver.listings
            WHERE thumbnail_status IN ({placeholders})
              AND original_thumbnail_url IS NOT NULL
              AND listing_id > %s
            ORDER BY listing_id
            LIMIT %s
            """,
            (*statuses, after_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def _update_batch(
    conn: psycopg2.extensions.connection,
    results: list[DownloadResult],
):
    """Batch update silver.listings với kết quả download."""
    success_rows = [
        (r.public_url, "success", r.listing_id)
        for r in results if r.success
    ]
    failed_rows = [
        ("failed", r.listing_id)
        for r in results if not r.success
    ]

    with conn.cursor() as cur:
        if success_rows:
            psycopg2.extras.execute_batch(
                cur,
                """
                UPDATE silver.listings
                SET self_thumbnail_url = %s,
                    thumbnail_status   = %s,
                    updated_at         = NOW()
                WHERE listing_id = %s
                """,
                success_rows,
            )
        if failed_rows:
            psycopg2.extras.execute_batch(
                cur,
                """
                UPDATE silver.listings
                SET thumbnail_status = %s,
                    updated_at       = NOW()
                WHERE listing_id = %s
                """,
                failed_rows,
            )
    conn.commit()


# =============================================================
# Worker
# =============================================================

def _process_one(
    row: dict,
    uploader: SupabaseUploader,
) -> DownloadResult:
    """
    Xử lý 1 listing: download → resize → upload.
    Chạy trong thread pool.
    """
    listing_id: int = row["listing_id"]
    image_url: str = row["original_thumbnail_url"]

    # Delay nhỏ để tránh đồng loạt request
    time.sleep(INTER_DOWNLOAD_DELAY)

    try:
        image_bytes = _download_and_resize(image_url)
        if not image_bytes:
            return DownloadResult(listing_id, False, error="Empty image bytes")

        public_url = uploader.upload(listing_id, image_bytes)
        return DownloadResult(listing_id, True, public_url=public_url)

    except requests.HTTPError as exc:
        return DownloadResult(listing_id, False, error=f"HTTP {exc.response.status_code}: {image_url}")
    except requests.exceptions.RequestException as exc:
        return DownloadResult(listing_id, False, error=f"Request error: {exc}")
    except Exception as exc:
        return DownloadResult(listing_id, False, error=str(exc))


# =============================================================
# Main runner
# =============================================================

def run(
    database_url: str,
    supabase_url: str,
    supabase_key: str,
    retry_failed: bool = False,
    limit: Optional[int] = None,
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_WORKERS,
):
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    logger.info("Connected to database")

    uploader = SupabaseUploader(supabase_url, supabase_key)
    logger.info("Supabase uploader ready (bucket: %s)", BUCKET_NAME)

    # Các status cần xử lý
    statuses = ("pending", "failed") if retry_failed else ("pending",)
    logger.info("Processing status: %s", statuses)

    total_processed = 0
    total_success = 0
    total_failed = 0
    after_id = 0  # con trỏ: chỉ lấy tin có listing_id > after_id

    while True:
        effective_limit = batch_size
        if limit is not None:
            effective_limit = min(batch_size, limit - total_processed)
            if effective_limit <= 0:
                break

        rows = _read_pending_batch(conn, statuses, after_id, effective_limit)
        if not rows:
            break

        logger.info("Batch after_id=%d: %d listings to process", after_id, len(rows))

        # Chạy song song với ThreadPoolExecutor
        results: list[DownloadResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_one, row, uploader): row
                for row in rows
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if result.success:
                    total_success += 1
                    logger.debug("OK  listing_id=%d → %s", result.listing_id, result.public_url)
                else:
                    total_failed += 1
                    logger.warning("FAIL listing_id=%d: %s", result.listing_id, result.error)

        # Batch update DB
        _update_batch(conn, results)

        total_processed += len(rows)
        # Đẩy con trỏ tới listing_id lớn nhất đã đọc (rows đã ORDER BY listing_id)
        after_id = rows[-1]["listing_id"]

        logger.info(
            "Progress: %d processed, %d success, %d failed",
            total_processed, total_success, total_failed,
        )

        if len(rows) < effective_limit:
            break

    conn.close()
    logger.info(
        "Done — total: %d, success: %d, failed: %d",
        total_processed, total_success, total_failed,
    )


# =============================================================
# CLI entry point
# =============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download & upload thumbnails")
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="Thử lại các tin đã failed (thêm vào pending)"
    )
    parser.add_argument("--limit", type=int, help="Giới hạn số tin xử lý (debug)")
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE,
        help=f"Batch size (mặc định {BATCH_SIZE})"
    )
    parser.add_argument(
        "--workers", type=int, default=MAX_WORKERS,
        help=f"Số luồng song song (mặc định {MAX_WORKERS})"
    )
    args = parser.parse_args()

    db_url       = os.environ.get("DATABASE_URL")
    supa_url     = os.environ.get("SUPABASE_URL")
    supa_key     = os.environ.get("SUPABASE_SERVICE_KEY")

    missing = [k for k, v in {
        "DATABASE_URL": db_url,
        "SUPABASE_URL": supa_url,
        "SUPABASE_SERVICE_KEY": supa_key,
    }.items() if not v]

    if missing:
        raise SystemExit(f"Thiếu biến môi trường: {', '.join(missing)}")

    run(
        database_url=db_url,
        supabase_url=supa_url,
        supabase_key=supa_key,
        retry_failed=args.retry_failed,
        limit=args.limit,
        batch_size=args.batch_size,
        max_workers=args.workers,
    )

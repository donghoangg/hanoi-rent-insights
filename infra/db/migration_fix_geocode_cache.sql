-- =============================================================
-- Migration: Đồng bộ schema silver.geocode_cache
-- =============================================================
-- Lý do: migration cũ (002_silver_schema.sql) tạo cột `geocode_src`,
-- nhưng code ETL (etl/bronze_to_silver.py) lại INSERT/SELECT theo
-- cột `status` + `provider`. Migration này vá các DB đã tồn tại với
-- schema cũ về đúng schema code đang dùng.
--
-- An toàn chạy nhiều lần (idempotent).
-- =============================================================

-- 1) Tạo bảng nếu chưa có (schema đúng) -----------------------
CREATE TABLE IF NOT EXISTS silver.geocode_cache (
    address_key  TEXT PRIMARY KEY,
    latitude     NUMERIC(10, 7),
    longitude    NUMERIC(10, 7),
    status       VARCHAR(20) DEFAULT 'success',  -- 'success' | 'failed'
    provider     VARCHAR(50),                    -- 'google' | 'nominatim' | 'ward_centroid' | 'failed'
    created_at   TIMESTAMP DEFAULT NOW()
);

-- 2) Thêm cột mới nếu thiếu -----------------------------------
ALTER TABLE silver.geocode_cache
    ADD COLUMN IF NOT EXISTS status   VARCHAR(20) DEFAULT 'success';

ALTER TABLE silver.geocode_cache
    ADD COLUMN IF NOT EXISTS provider VARCHAR(50);

-- 3) Migrate dữ liệu từ cột cũ `geocode_src` (nếu còn tồn tại)
--    Cột cũ chứa giá trị provider ('nominatim' | 'ward_centroid' | 'failed').
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'silver'
          AND table_name   = 'geocode_cache'
          AND column_name  = 'geocode_src'
    ) THEN
        -- provider: lấy từ geocode_src nếu provider đang rỗng
        UPDATE silver.geocode_cache
           SET provider = geocode_src
         WHERE provider IS NULL
           AND geocode_src IS NOT NULL;

        -- status: suy ra từ geocode_src ('failed' → failed, còn lại → success)
        UPDATE silver.geocode_cache
           SET status = CASE
                            WHEN geocode_src = 'failed' THEN 'failed'
                            WHEN latitude IS NULL        THEN 'failed'
                            ELSE 'success'
                        END
         WHERE status IS NULL;

        -- Bỏ cột cũ sau khi migrate xong
        ALTER TABLE silver.geocode_cache DROP COLUMN geocode_src;
    END IF;
END $$;

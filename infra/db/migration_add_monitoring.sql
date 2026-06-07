-- =============================================================
-- Migration: Thêm các bảng/cột mới cho monitoring & quarantine
-- Chạy file này trong Supabase SQL Editor nếu schema cũ đã chạy từ trước.
-- File này IDEMPOTENT — chạy nhiều lần không bị lỗi.
-- =============================================================

-- 1) Bảng quarantine (nếu chưa có) ----------------------------
CREATE TABLE IF NOT EXISTS bronze.listings_quarantine (
    id             BIGSERIAL PRIMARY KEY,
    source_name    VARCHAR(50)  NOT NULL,
    source_id      VARCHAR(200),
    source_url     TEXT,
    raw_payload    JSONB        NOT NULL,
    error_reason   TEXT         NOT NULL,
    missing_fields JSONB,
    scraped_at     TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quar_source
    ON bronze.listings_quarantine (source_name);
CREATE INDEX IF NOT EXISTS idx_quar_scraped_at
    ON bronze.listings_quarantine (scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_quar_reason
    ON bronze.listings_quarantine (error_reason);


-- 2) Bảng scrape_runs (mới hoàn toàn) -------------------------
CREATE TABLE IF NOT EXISTS bronze.scrape_runs (
    run_id           BIGSERIAL PRIMARY KEY,
    source_name      VARCHAR(50)   NOT NULL,
    spider_name      VARCHAR(100)  NOT NULL,
    started_at       TIMESTAMP     NOT NULL,
    finished_at      TIMESTAMP,
    duration_sec     NUMERIC(10, 2),
    total_scraped    INT NOT NULL DEFAULT 0,
    pass_count       INT NOT NULL DEFAULT 0,
    quarantine_count INT NOT NULL DEFAULT 0,
    duplicate_count  INT NOT NULL DEFAULT 0,
    error_count      INT NOT NULL DEFAULT 0,
    pass_rate_pct    NUMERIC(5, 1),
    status           VARCHAR(20) DEFAULT 'running',
    note             TEXT
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_source
    ON bronze.scrape_runs (source_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_status
    ON bronze.scrape_runs (status);


-- 3) View v_ingestion_monitor (tạo hoặc thay thế) -------------
CREATE OR REPLACE VIEW bronze.v_ingestion_monitor AS
WITH last_raw AS (
    SELECT source_name, COUNT(*) AS pass_count, MAX(scraped_at) AS last_scraped
    FROM bronze.listings_raw
    GROUP BY source_name
),
last_quar AS (
    SELECT source_name, COUNT(*) AS quarantine_count
    FROM bronze.listings_quarantine
    GROUP BY source_name
)
SELECT
    COALESCE(r.source_name, q.source_name)                        AS source_name,
    COALESCE(r.pass_count, 0)                                     AS pass_count,
    COALESCE(q.quarantine_count, 0)                               AS quarantine_count,
    COALESCE(r.pass_count, 0) + COALESCE(q.quarantine_count, 0)   AS total_count,
    ROUND(
        100.0 * COALESCE(r.pass_count, 0)
        / NULLIF(COALESCE(r.pass_count, 0) + COALESCE(q.quarantine_count, 0), 0)
    , 1)                                                          AS pass_rate_pct,
    r.last_scraped
FROM last_raw r
FULL OUTER JOIN last_quar q ON r.source_name = q.source_name;


-- 4) Bảng silver.listings — thêm các cột còn thiếu (nếu chưa có)
-- Dùng ADD COLUMN IF NOT EXISTS để an toàn
ALTER TABLE silver.listings
    ADD COLUMN IF NOT EXISTS is_negotiable      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS deposit_vnd        BIGINT,
    ADD COLUMN IF NOT EXISTS furnishing_level   VARCHAR(20),
    ADD COLUMN IF NOT EXISTS has_air_conditioner BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_water_heater   BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_fridge         BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_washing_machine BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_furniture      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_wifi           BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_kitchen        BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_self_contained  BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS free_hours         BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS landlord_shared    BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS good_security      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS near_market        BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS amenities          JSONB,
    ADD COLUMN IF NOT EXISTS address_status     VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS is_price_outlier   BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS duplicate_group_id BIGINT,
    ADD COLUMN IF NOT EXISTS original_thumbnail_url TEXT,
    ADD COLUMN IF NOT EXISTS self_thumbnail_url TEXT,
    ADD COLUMN IF NOT EXISTS thumbnail_status   VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS price_per_m2       BIGINT,
    ADD COLUMN IF NOT EXISTS price_status       VARCHAR(20) DEFAULT 'ok';


-- 5) Bảng silver.geocode_cache (nếu chưa có) ------------------
CREATE TABLE IF NOT EXISTS silver.geocode_cache (
    address_key   TEXT PRIMARY KEY,
    latitude      NUMERIC(10, 7),
    longitude     NUMERIC(10, 7),
    status        VARCHAR(20) DEFAULT 'success',
    provider      VARCHAR(50),
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);


-- 6) Bảng gold.price_stats_overall (nếu chưa có) --------------
CREATE TABLE IF NOT EXISTS gold.price_stats_overall (
    property_type    VARCHAR(50) PRIMARY KEY,
    listing_count    INT,
    avg_price_vnd    BIGINT,
    median_price_vnd BIGINT,
    p33_price_vnd    BIGINT,
    p67_price_vnd    BIGINT,
    refreshed_at     TIMESTAMP DEFAULT NOW()
);


-- 7) Bảng gold.price_stats_by_ward (nếu chưa có) -------------
CREATE TABLE IF NOT EXISTS gold.price_stats_by_ward (
    ward             VARCHAR(100) NOT NULL,
    province         VARCHAR(100) NOT NULL DEFAULT 'Hà Nội',
    property_type    VARCHAR(50)  NOT NULL,
    listing_count    INT,
    avg_price_vnd    BIGINT,
    median_price_vnd BIGINT,
    p25_price_vnd    BIGINT,
    p75_price_vnd    BIGINT,
    avg_area_m2      NUMERIC(8, 2),
    avg_price_per_m2 BIGINT,
    refreshed_at     TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ward, property_type)
);


-- 8) Trigger updated_at cho silver.listings (nếu chưa có) -----
CREATE OR REPLACE FUNCTION silver.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_silver_updated_at ON silver.listings;
CREATE TRIGGER trg_silver_updated_at
    BEFORE UPDATE ON silver.listings
    FOR EACH ROW EXECUTE FUNCTION silver.set_updated_at();


-- Kiểm tra nhanh sau khi chạy:
SELECT 'bronze.listings_quarantine' AS tbl, COUNT(*) FROM bronze.listings_quarantine
UNION ALL
SELECT 'bronze.scrape_runs',               COUNT(*) FROM bronze.scrape_runs
UNION ALL
SELECT 'bronze.listings_raw',              COUNT(*) FROM bronze.listings_raw
UNION ALL
SELECT 'silver.listings',                  COUNT(*) FROM silver.listings;

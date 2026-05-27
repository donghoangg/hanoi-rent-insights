-- =============================================================
-- HanoiRent Insights — Database Schema (Medallion Architecture)
-- PostgreSQL (Supabase)
-- Chạy file này trong Supabase SQL Editor
-- =============================================================

-- Tạo 3 schemas
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- =============================================================
-- BRONZE LAYER — Raw data, giữ nguyên từ scraper
-- =============================================================

CREATE TABLE IF NOT EXISTS bronze.listings_raw (
    id           BIGSERIAL PRIMARY KEY,
    source_name  VARCHAR(50)  NOT NULL,   -- 'nhatot', 'batdongsan', 'mogi'
    source_id    VARCHAR(200) NOT NULL,   -- ID gốc từ web nguồn
    source_url   TEXT,
    raw_payload  JSONB        NOT NULL,   -- toàn bộ data dạng JSON
    scraped_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE (source_name, source_id)
);

CREATE INDEX IF NOT EXISTS idx_bronze_source
    ON bronze.listings_raw (source_name, source_id);
CREATE INDEX IF NOT EXISTS idx_bronze_scraped_at
    ON bronze.listings_raw (scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_bronze_payload
    ON bronze.listings_raw USING GIN (raw_payload);

COMMENT ON TABLE bronze.listings_raw IS
    'Raw scraped listings — không chỉnh sửa, chỉ thêm. Dùng để replay/debug.';


CREATE TABLE IF NOT EXISTS bronze.listing_images_raw (
    id           BIGSERIAL PRIMARY KEY,
    source_name  VARCHAR(50)  NOT NULL,
    source_id    VARCHAR(200) NOT NULL,
    image_url    TEXT         NOT NULL,
    image_order  INT          NOT NULL DEFAULT 0,  -- 0 = thumbnail đầu tiên
    scraped_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bronze_img_source
    ON bronze.listing_images_raw (source_name, source_id);
CREATE INDEX IF NOT EXISTS idx_bronze_img_order
    ON bronze.listing_images_raw (source_name, source_id, image_order);

COMMENT ON TABLE bronze.listing_images_raw IS
    'URL ảnh gốc từ scraper. image_order=0 là thumbnail chính.';


-- =============================================================
-- SILVER LAYER — Cleaned, normalized, geocoded
-- =============================================================

CREATE TABLE IF NOT EXISTS silver.listings (
    listing_id              BIGSERIAL PRIMARY KEY,
    source_name             VARCHAR(50)   NOT NULL,
    source_id               VARCHAR(200)  NOT NULL,
    source_url              TEXT,

    -- Thông tin tin đăng
    title                   TEXT,
    description             TEXT,
    price_vnd               BIGINT,                    -- VND/tháng
    area_m2                 NUMERIC(8, 2),             -- m²
    bedrooms                INT,
    bathrooms               INT,
    property_type           VARCHAR(50),               -- 'phong_tro', 'chung_cu', 'nha_nguyen_can', 'can_ho_dich_vu'
    furnishing_level        VARCHAR(20),               -- 'bare' | 'partial' | 'full' | 'luxury' (từ scraper hoặc NLP)
    amenities               JSONB,                     -- ['dieu_hoa', 'tu_lanh', 'may_giat', ...] — NLP extracted ở Silver ETL

    -- Địa chỉ (đã chuẩn hoá)
    address                 TEXT,
    district                VARCHAR(100),              -- 'Cầu Giấy', 'Đống Đa' ...
    ward                    VARCHAR(100),              -- phường/xã

    -- Geocoding (OpenStreetMap Nominatim)
    latitude                NUMERIC(10, 7),
    longitude               NUMERIC(10, 7),
    geocode_status          VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'success', 'failed', 'centroid'

    -- Ảnh thumbnail
    original_thumbnail_url  TEXT,
    self_thumbnail_url      TEXT,                      -- URL trên Supabase Storage
    thumbnail_status        VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'success', 'failed'

    -- Thời gian
    posted_at               DATE,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE (source_name, source_id)
);

CREATE INDEX IF NOT EXISTS idx_silver_source
    ON silver.listings (source_name, source_id);
CREATE INDEX IF NOT EXISTS idx_silver_district
    ON silver.listings (district);
CREATE INDEX IF NOT EXISTS idx_silver_price
    ON silver.listings (price_vnd);
CREATE INDEX IF NOT EXISTS idx_silver_area
    ON silver.listings (area_m2);
CREATE INDEX IF NOT EXISTS idx_silver_property_type
    ON silver.listings (property_type);
CREATE INDEX IF NOT EXISTS idx_silver_posted_at
    ON silver.listings (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_silver_furnishing
    ON silver.listings (furnishing_level)
    WHERE furnishing_level IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_silver_amenities
    ON silver.listings USING GIN (amenities)
    WHERE amenities IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_silver_geo
    ON silver.listings (latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

COMMENT ON TABLE silver.listings IS
    'Listings đã được làm sạch, chuẩn hoá đơn vị, geocoded. Source of truth cho ETL.';


-- =============================================================
-- GOLD LAYER — Analytics-ready, phục vụ web app & dashboard
-- =============================================================

CREATE TABLE IF NOT EXISTS gold.listings_for_map (
    listing_id      BIGINT PRIMARY KEY,
    title           TEXT,
    price_vnd       BIGINT,
    area_m2         NUMERIC(8, 2),
    bedrooms        INT,
    property_type   VARCHAR(50),
    district        VARCHAR(100),
    ward            VARCHAR(100),
    latitude        NUMERIC(10, 7) NOT NULL,
    longitude       NUMERIC(10, 7) NOT NULL,
    source_name     VARCHAR(50),
    source_url      TEXT,
    thumbnail_url   TEXT,          -- self_thumbnail_url (Supabase Storage)
    posted_at       DATE,
    price_per_m2    BIGINT,        -- price_vnd / area_m2, để filter/sort
    price_segment    VARCHAR(20),   -- 'thap' (<3tr), 'trung_binh' (3-7tr), 'cao' (>7tr)
    furnishing_level VARCHAR(20),   -- 'bare' | 'partial' | 'full' | 'luxury'
    amenities        JSONB,         -- ['dieu_hoa', 'tu_lanh', ...] từ NLP
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    refreshed_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_map_geo
    ON gold.listings_for_map (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_map_price
    ON gold.listings_for_map (price_vnd)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_map_district
    ON gold.listings_for_map (district)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_map_property_type
    ON gold.listings_for_map (property_type)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_map_active
    ON gold.listings_for_map (is_active, price_vnd);

COMMENT ON TABLE gold.listings_for_map IS
    'Listings có toạ độ hợp lệ, phục vụ trực tiếp Leaflet map API. Refresh sau mỗi ETL run.';


CREATE TABLE IF NOT EXISTS gold.price_by_district (
    id               BIGSERIAL PRIMARY KEY,
    district         VARCHAR(100) NOT NULL,
    property_type    VARCHAR(50),                -- NULL = tổng hợp tất cả loại
    avg_price_vnd    BIGINT,
    median_price_vnd BIGINT,
    min_price_vnd    BIGINT,
    max_price_vnd    BIGINT,
    avg_price_per_m2 BIGINT,
    avg_area_m2      NUMERIC(8, 2),
    listing_count    INT,
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (district, property_type)
);

CREATE INDEX IF NOT EXISTS idx_price_district
    ON gold.price_by_district (district);

COMMENT ON TABLE gold.price_by_district IS
    'Thống kê giá tổng hợp theo quận & loại hình. Refresh sau mỗi ETL run.';


-- =============================================================
-- HELPER: Function tự cập nhật updated_at cho silver.listings
-- =============================================================

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

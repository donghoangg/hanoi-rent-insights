-- =============================================================
-- HanoiRent Insights — Database Schema (Medallion Architecture)
-- PostgreSQL (Supabase)
-- Chạy file này trong Supabase SQL Editor
--
-- ĐỊA GIỚI HÀNH CHÍNH: theo mô hình 2 cấp (từ 01/07/2025)
--   cấp tỉnh  = province (Tỉnh / Thành phố trực thuộc TW)
--   cấp xã    = ward     (Phường / Xã / Đặc khu)
--   (KHÔNG còn cấp quận/huyện)
-- =============================================================

-- Tạo 3 schemas
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- =============================================================
-- BRONZE LAYER — Raw data, giữ nguyên từ scraper
-- =============================================================

-- 1) Dữ liệu thô HỢP LỆ (đủ trường bắt buộc) -----------------
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
    'Raw scraped listings hợp lệ — không chỉnh sửa, chỉ thêm. Dùng để replay/debug.';


-- 2) Dữ liệu thô LỖI / bị CÁCH LY (quarantine) ---------------
-- Tin thiếu một trong các trường bắt buộc (Tiêu đề / Giá / URL)
-- sẽ vào đây thay vì bị loại bỏ, để rà soát và sửa spider sau.
CREATE TABLE IF NOT EXISTS bronze.listings_quarantine (
    id             BIGSERIAL PRIMARY KEY,
    source_name    VARCHAR(50)  NOT NULL,
    source_id      VARCHAR(200),           -- có thể NULL nếu không parse được ID
    source_url     TEXT,
    raw_payload    JSONB        NOT NULL,   -- toàn bộ data thô để rà soát
    error_reason   TEXT         NOT NULL,   -- lý do bị cách ly (vd: 'missing:price_vnd')
    missing_fields JSONB,                   -- danh sách trường thiếu: ['price_vnd', ...]
    scraped_at     TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quar_source
    ON bronze.listings_quarantine (source_name);
CREATE INDEX IF NOT EXISTS idx_quar_scraped_at
    ON bronze.listings_quarantine (scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_quar_reason
    ON bronze.listings_quarantine (error_reason);

COMMENT ON TABLE bronze.listings_quarantine IS
    'Tin bị lỗi/thiếu trường bắt buộc (Tiêu đề/Giá/URL). Cách ly để rà soát, không làm bẩn dữ liệu sạch.';


-- 3) Ảnh thô --------------------------------------------------
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
    price_vnd               BIGINT,                    -- VND/tháng (đã chuẩn hoá)
    price_per_m2            BIGINT,                    -- price_vnd / area_m2
    is_negotiable           BOOLEAN DEFAULT FALSE,     -- tin 'thoả thuận' / không có giá
    deposit_vnd             BIGINT,                    -- tiền cọc (VND), NULL nếu không ghi
    area_m2                 NUMERIC(8, 2),             -- m²
    bedrooms                INT,
    bathrooms               INT,
    property_type           VARCHAR(50),               -- 'phong_tro' | 'chung_cu_mini' | 'chung_cu' | 'nha_nguyen_can' | 'khac'
    furnishing_level        VARCHAR(20),               -- 'bare' | 'partial' | 'full' | 'luxury'

    -- Tiện ích (boolean, trích từ mô tả ở Silver ETL) ---------
    has_air_conditioner     BOOLEAN DEFAULT FALSE,     -- điều hoà
    has_water_heater        BOOLEAN DEFAULT FALSE,     -- nóng lạnh
    has_fridge              BOOLEAN DEFAULT FALSE,     -- tủ lạnh
    has_washing_machine     BOOLEAN DEFAULT FALSE,     -- máy giặt
    has_furniture           BOOLEAN DEFAULT FALSE,     -- giường tủ
    has_wifi                BOOLEAN DEFAULT FALSE,     -- wifi/internet
    has_kitchen             BOOLEAN DEFAULT FALSE,     -- tủ bếp/kệ bếp
    is_self_contained       BOOLEAN DEFAULT FALSE,     -- khép kín
    free_hours              BOOLEAN DEFAULT FALSE,     -- giờ giấc tự do
    landlord_shared         BOOLEAN DEFAULT FALSE,     -- chung chủ
    good_security           BOOLEAN DEFAULT FALSE,     -- an ninh tốt
    near_market             BOOLEAN DEFAULT FALSE,     -- gần chợ
    -- Giữ thêm dạng JSONB để linh hoạt mở rộng tiện ích mới
    amenities               JSONB,

    -- Địa chỉ (chuẩn hoá theo địa giới 2 cấp) ----------------
    address                 TEXT,                      -- địa chỉ gốc đầy đủ
    province                VARCHAR(100),              -- cấp tỉnh: 'Hà Nội', 'TP Hồ Chí Minh', ...
    ward                    VARCHAR(100),              -- cấp xã: 'Phường Cầu Giấy', 'Xã ...'
    address_status          VARCHAR(20) DEFAULT 'pending',  -- 'pending'|'mapped'|'unmapped' (ánh xạ địa danh cũ→mới)

    -- Geocoding (OpenStreetMap Nominatim)
    latitude                NUMERIC(10, 7),
    longitude               NUMERIC(10, 7),
    geocode_status          VARCHAR(20) DEFAULT 'pending',  -- 'pending'|'success'|'failed'|'centroid'

    -- Cờ chất lượng dữ liệu ----------------------------------
    is_price_outlier        BOOLEAN DEFAULT FALSE,     -- ngoại lai giá (rule-based + IQR)
    duplicate_group_id      BIGINT,                    -- nhóm tin nghi trùng (NULL nếu không trùng)

    -- Ảnh thumbnail
    original_thumbnail_url  TEXT,
    self_thumbnail_url      TEXT,                      -- URL trên Supabase Storage
    thumbnail_status        VARCHAR(20) DEFAULT 'pending',

    -- Thời gian
    posted_at               DATE,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE (source_name, source_id)
);

CREATE INDEX IF NOT EXISTS idx_silver_source
    ON silver.listings (source_name, source_id);
CREATE INDEX IF NOT EXISTS idx_silver_province
    ON silver.listings (province);
CREATE INDEX IF NOT EXISTS idx_silver_ward
    ON silver.listings (ward);
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
CREATE INDEX IF NOT EXISTS idx_silver_outlier
    ON silver.listings (is_price_outlier);

COMMENT ON TABLE silver.listings IS
    'Listings đã làm sạch, chuẩn hoá đơn vị, tách tiện ích, gắn cờ chất lượng, geocoded. Source of truth cho ETL.';


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
    province        VARCHAR(100),
    ward            VARCHAR(100),
    latitude        NUMERIC(10, 7) NOT NULL,
    longitude       NUMERIC(10, 7) NOT NULL,
    source_name     VARCHAR(50),
    source_url      TEXT,
    thumbnail_url   TEXT,
    posted_at       DATE,
    price_per_m2    BIGINT,
    price_segment    VARCHAR(20),   -- 'thap' (<3tr), 'trung_binh' (3-7tr), 'cao' (>7tr)
    furnishing_level VARCHAR(20),
    amenities        JSONB,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    refreshed_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_map_geo
    ON gold.listings_for_map (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_map_price
    ON gold.listings_for_map (price_vnd)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_map_province
    ON gold.listings_for_map (province)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_map_property_type
    ON gold.listings_for_map (property_type)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_map_active
    ON gold.listings_for_map (is_active, price_vnd);

COMMENT ON TABLE gold.listings_for_map IS
    'Listings có toạ độ hợp lệ (đã lọc outlier), phục vụ trực tiếp Leaflet map API. Refresh sau mỗi ETL run.';


-- Thống kê giá theo địa giới 2 cấp (tỉnh + phường) ----------
CREATE TABLE IF NOT EXISTS gold.price_by_area (
    id               BIGSERIAL PRIMARY KEY,
    province         VARCHAR(100) NOT NULL,
    ward             VARCHAR(100),               -- NULL = tổng hợp toàn tỉnh
    property_type    VARCHAR(50),                -- NULL = tổng hợp tất cả loại
    avg_price_vnd    BIGINT,
    median_price_vnd BIGINT,
    min_price_vnd    BIGINT,
    max_price_vnd    BIGINT,
    avg_price_per_m2 BIGINT,
    avg_area_m2      NUMERIC(8, 2),
    listing_count    INT,
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (province, ward, property_type)
);

CREATE INDEX IF NOT EXISTS idx_price_province
    ON gold.price_by_area (province);
CREATE INDEX IF NOT EXISTS idx_price_ward
    ON gold.price_by_area (province, ward);

COMMENT ON TABLE gold.price_by_area IS
    'Thống kê giá tổng hợp theo tỉnh/phường & loại hình (chỉ tính tin không outlier). Refresh sau mỗi ETL run.';


-- =============================================================
-- MONITORING — Giám sát chất lượng vùng đệm (Bronze)
-- =============================================================
-- View tổng quan: số tin pass / quarantine / tỉ lệ pass theo từng nguồn.
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
    COALESCE(r.source_name, q.source_name)                       AS source_name,
    COALESCE(r.pass_count, 0)                                    AS pass_count,
    COALESCE(q.quarantine_count, 0)                              AS quarantine_count,
    COALESCE(r.pass_count, 0) + COALESCE(q.quarantine_count, 0)  AS total_count,
    ROUND(
        100.0 * COALESCE(r.pass_count, 0)
        / NULLIF(COALESCE(r.pass_count, 0) + COALESCE(q.quarantine_count, 0), 0)
    , 1)                                                         AS pass_rate_pct,
    r.last_scraped
FROM last_raw r
FULL OUTER JOIN last_quar q ON r.source_name = q.source_name;

COMMENT ON VIEW bronze.v_ingestion_monitor IS
    'KPI giám sát vùng đệm: số tin pass, quarantine, tỉ lệ pass theo từng nguồn.';


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

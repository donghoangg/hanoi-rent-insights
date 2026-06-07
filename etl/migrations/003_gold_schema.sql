-- =============================================================
-- Migration: Tạo Gold layer
-- Chạy sau 002_silver_schema.sql
-- =============================================================

CREATE SCHEMA IF NOT EXISTS gold;

-- -------------------------------------------------------------
-- gold.listings_for_map
-- Phục vụ trực tiếp web app (map view + filter sidebar)
-- Chỉ chứa tin có lat/lng hợp lệ và price_status = 'ok'
-- Refresh bằng silver_to_gold.py sau mỗi lần cào
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.listings_for_map (
    listing_id      BIGINT PRIMARY KEY,
    title           TEXT,
    price_vnd       BIGINT,
    area_m2         NUMERIC(8, 2),
    bedrooms        INT,
    property_type   VARCHAR(50),
    province        VARCHAR(100),
    ward            VARCHAR(100),
    latitude        NUMERIC(10, 7)  NOT NULL,
    longitude       NUMERIC(10, 7)  NOT NULL,
    source_name     VARCHAR(50),
    source_url      TEXT,
    thumbnail_url   TEXT,           -- self_thumbnail_url từ silver (hoặc original nếu chưa upload)
    posted_at       DATE,
    price_per_m2    BIGINT,         -- price_vnd / area_m2, NULL nếu area_m2 = 0 hoặc NULL
    price_segment   VARCHAR(20),    -- 'thap' | 'trung_binh' | 'cao' (theo phân vị toàn bộ dataset)
    -- Amenities hay dùng nhất cho filter web app
    has_air_con         BOOLEAN,
    has_parking         BOOLEAN,
    has_elevator        BOOLEAN,
    has_wifi            BOOLEAN,
    has_washing_machine BOOLEAN,
    is_active       BOOLEAN DEFAULT TRUE,
    refreshed_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gold_map_geo
    ON gold.listings_for_map (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_gold_map_price
    ON gold.listings_for_map (price_vnd);
CREATE INDEX IF NOT EXISTS idx_gold_map_ward
    ON gold.listings_for_map (ward);
CREATE INDEX IF NOT EXISTS idx_gold_map_proptype
    ON gold.listings_for_map (property_type);

-- -------------------------------------------------------------
-- gold.price_stats_by_ward
-- Thống kê giá theo phường + loại hình — cho dashboard
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.price_stats_by_ward (
    ward            VARCHAR(100)    NOT NULL,
    province        VARCHAR(100)    NOT NULL DEFAULT 'Hà Nội',
    property_type   VARCHAR(50)     NOT NULL,
    listing_count   INT,
    avg_price_vnd   BIGINT,
    median_price_vnd BIGINT,
    p25_price_vnd   BIGINT,         -- percentile 25
    p75_price_vnd   BIGINT,         -- percentile 75
    avg_area_m2     NUMERIC(8, 2),
    avg_price_per_m2 BIGINT,
    refreshed_at    TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ward, property_type)
);

-- -------------------------------------------------------------
-- gold.price_stats_overall
-- Thống kê toàn dataset — dùng để tính price_segment
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.price_stats_overall (
    property_type       VARCHAR(50) PRIMARY KEY,
    listing_count       INT,
    avg_price_vnd       BIGINT,
    median_price_vnd    BIGINT,
    p33_price_vnd       BIGINT,     -- ngưỡng dưới: 'thap' nếu price <= p33
    p67_price_vnd       BIGINT,     -- ngưỡng trên: 'cao' nếu price >= p67
    refreshed_at        TIMESTAMP DEFAULT NOW()
);

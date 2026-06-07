-- =============================================================
-- Migration: Tạo Silver layer
-- Chạy sau 001_bronze_schema.sql
-- =============================================================

CREATE SCHEMA IF NOT EXISTS silver;

-- -------------------------------------------------------------
-- Bảng geocode cache — tránh gọi Nominatim lại cho cùng địa chỉ
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.geocode_cache (
    address_key  TEXT PRIMARY KEY,          -- normalized address string dùng làm key
    latitude     NUMERIC(10, 7),
    longitude    NUMERIC(10, 7),
    geocode_src  VARCHAR(20),               -- 'nominatim' | 'ward_centroid' | 'failed'
    created_at   TIMESTAMP DEFAULT NOW()
);

-- -------------------------------------------------------------
-- Bảng chính: silver.listings
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.listings (
    -- Định danh
    listing_id   BIGSERIAL PRIMARY KEY,
    source_name  VARCHAR(50)  NOT NULL,     -- 'nhatot' | 'mogi'
    source_id    VARCHAR(100) NOT NULL,
    source_url   TEXT,

    -- Thông tin chính
    title            TEXT,
    description      TEXT,
    price_vnd        BIGINT,
    area_m2          NUMERIC(8, 2),
    bedrooms         INT,
    bathrooms        INT,
    property_type    VARCHAR(50),           -- 'phong_tro' | 'chung_cu' | 'chung_cu_mini'
                                            -- | 'can_ho_dich_vu' | 'nha_nguyen_can' | 'biet_thu' | 'khac'
    furnishing_level VARCHAR(20),           -- 'bare' | 'partial' | 'full' | 'luxury'

    -- Địa chỉ (địa giới 2 cấp: tỉnh + phường/xã, KHÔNG có quận)
    address   TEXT,
    province  VARCHAR(100),                 -- luôn là 'Hà Nội' với dự án này
    ward      VARCHAR(100),                 -- tên phường/xã đã chuẩn hoá (bỏ tiền tố "Phường ")

    -- Geocoding
    latitude         NUMERIC(10, 7),
    longitude        NUMERIC(10, 7),
    geocode_source   VARCHAR(20),           -- 'provider' | 'nominatim' | 'ward_centroid' | 'failed'

    -- Amenities (boolean) — extract từ title + description
    has_air_con          BOOLEAN DEFAULT FALSE,
    has_parking          BOOLEAN DEFAULT FALSE,
    has_security         BOOLEAN DEFAULT FALSE,
    has_elevator         BOOLEAN DEFAULT FALSE,
    has_balcony          BOOLEAN DEFAULT FALSE,
    has_washing_machine  BOOLEAN DEFAULT FALSE,
    has_fridge           BOOLEAN DEFAULT FALSE,
    has_water_heater     BOOLEAN DEFAULT FALSE,
    has_wifi             BOOLEAN DEFAULT FALSE,
    has_kitchen          BOOLEAN DEFAULT FALSE,
    has_private_wc       BOOLEAN DEFAULT FALSE,
    pet_allowed          BOOLEAN DEFAULT FALSE,
    near_university      BOOLEAN DEFAULT FALSE,

    -- Thumbnail
    original_thumbnail_url  TEXT,
    thumbnail_status        VARCHAR(20) DEFAULT 'pending',  -- 'pending' | 'success' | 'failed'
    self_thumbnail_url      TEXT,                           -- URL trên Supabase Storage (điền sau)

    -- Quality flags
    price_status    VARCHAR(20) DEFAULT 'ok',   -- 'ok' | 'suspect' | 'missing'

    -- Thời gian
    posted_at   DATE,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW(),

    UNIQUE (source_name, source_id)
);

-- Index cho map query (lat/lng bbox)
CREATE INDEX IF NOT EXISTS idx_silver_geo
    ON silver.listings (latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Index cho filter thường dùng
CREATE INDEX IF NOT EXISTS idx_silver_price      ON silver.listings (price_vnd);
CREATE INDEX IF NOT EXISTS idx_silver_ward       ON silver.listings (ward);
CREATE INDEX IF NOT EXISTS idx_silver_proptype   ON silver.listings (property_type);
CREATE INDEX IF NOT EXISTS idx_silver_posted     ON silver.listings (posted_at);

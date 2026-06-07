-- =============================================================
-- Migration: Gold Layer → Star Schema
-- Chạy trong Supabase SQL Editor
-- IDEMPOTENT — chạy nhiều lần không lỗi
--
-- Thay thế các bảng gold phẳng cũ bằng star schema:
--   gold.dim_location       — địa điểm (province + ward + toạ độ)
--   gold.dim_property_type  — loại hình BĐS
--   gold.dim_source         — nguồn dữ liệu
--   gold.dim_date           — ngày đăng
--   gold.fct_listings       — fact table trung tâm
--   gold.listings_for_map   — giữ lại cho web app map (sửa cột amenity)
-- =============================================================

-- -------------------------------------------------------------
-- 1. DROP bảng gold cũ (chưa có data thực)
-- -------------------------------------------------------------
DROP TABLE IF EXISTS gold.price_by_area        CASCADE;
DROP TABLE IF EXISTS gold.price_stats_overall  CASCADE;
DROP TABLE IF EXISTS gold.price_stats_by_ward  CASCADE;
DROP TABLE IF EXISTS gold.listings_for_map     CASCADE;


-- -------------------------------------------------------------
-- 2. dim_location
-- Mỗi row = 1 tổ hợp (province, ward) duy nhất.
-- lat/lng là centroid của ward (lấy từ tin đăng, avg hoặc hardcode).
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.dim_location (
    location_key    BIGSERIAL   PRIMARY KEY,
    province        VARCHAR(100) NOT NULL,
    ward            VARCHAR(100),                   -- NULL = không rõ phường
    latitude        NUMERIC(10, 7),                 -- centroid ward
    longitude       NUMERIC(10, 7),
    UNIQUE (province, ward)
);

CREATE INDEX IF NOT EXISTS idx_dim_loc_province ON gold.dim_location (province);
CREATE INDEX IF NOT EXISTS idx_dim_loc_ward     ON gold.dim_location (ward);

COMMENT ON TABLE gold.dim_location IS
    'Dimension địa điểm: tỉnh + phường theo địa giới 2 cấp (từ 01/07/2025).';


-- -------------------------------------------------------------
-- 3. dim_property_type
-- Danh sách loại hình BĐS chuẩn hoá.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.dim_property_type (
    property_type_key   SERIAL      PRIMARY KEY,
    property_type_code  VARCHAR(50) NOT NULL UNIQUE,  -- 'phong_tro', 'chung_cu_mini', ...
    property_type_name  VARCHAR(100),                  -- tên hiển thị tiếng Việt
    property_type_group VARCHAR(50)                    -- nhóm: 'can_ho' | 'nha_o' | 'phong'
);

COMMENT ON TABLE gold.dim_property_type IS
    'Dimension loại hình BĐS: phong_tro, chung_cu_mini, chung_cu, nha_nguyen_can, khac.';

-- Seed dữ liệu cố định
INSERT INTO gold.dim_property_type
    (property_type_code, property_type_name, property_type_group)
VALUES
    ('phong_tro',      'Phòng trọ',          'phong'),
    ('chung_cu_mini',  'Chung cư mini',       'can_ho'),
    ('chung_cu',       'Chung cư',            'can_ho'),
    ('nha_nguyen_can', 'Nhà nguyên căn',      'nha_o'),
    ('khac',           'Khác',                'khac')
ON CONFLICT (property_type_code) DO NOTHING;


-- -------------------------------------------------------------
-- 4. dim_source
-- Nguồn dữ liệu (spider).
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.dim_source (
    source_key      SERIAL      PRIMARY KEY,
    source_name     VARCHAR(50) NOT NULL UNIQUE,
    source_url_base TEXT,                           -- domain gốc
    is_active       BOOLEAN DEFAULT TRUE
);

COMMENT ON TABLE gold.dim_source IS
    'Dimension nguồn dữ liệu: nhatot, mogi, batdongsan.';

-- Seed
INSERT INTO gold.dim_source (source_name, source_url_base)
VALUES
    ('nhatot',      'https://www.nhatot.com'),
    ('mogi',        'https://mogi.vn'),
    ('batdongsan',  'https://batdongsan.com.vn')
ON CONFLICT (source_name) DO NOTHING;


-- -------------------------------------------------------------
-- 5. dim_date
-- Ngày đăng tin — phân tích theo thời gian.
-- Populate bằng generate_series (2020–2030).
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.dim_date (
    date_key    INT         PRIMARY KEY,   -- format YYYYMMDD, vd: 20260607
    full_date   DATE        NOT NULL UNIQUE,
    year        SMALLINT    NOT NULL,
    quarter     SMALLINT    NOT NULL,      -- 1–4
    month       SMALLINT    NOT NULL,      -- 1–12
    month_name  VARCHAR(20),               -- 'Tháng 1', ...
    week        SMALLINT    NOT NULL,      -- ISO week 1–53
    day_of_week SMALLINT    NOT NULL,      -- 1=Mon ... 7=Sun
    is_weekend  BOOLEAN     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dim_date_year_month ON gold.dim_date (year, month);

COMMENT ON TABLE gold.dim_date IS
    'Dimension ngày: phân tích theo year/quarter/month/week.';

-- Populate 2020–2030 (idempotent)
INSERT INTO gold.dim_date (
    date_key, full_date, year, quarter, month, month_name,
    week, day_of_week, is_weekend
)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INT             AS date_key,
    d                                        AS full_date,
    EXTRACT(YEAR    FROM d)::SMALLINT        AS year,
    EXTRACT(QUARTER FROM d)::SMALLINT        AS quarter,
    EXTRACT(MONTH   FROM d)::SMALLINT        AS month,
    'Tháng ' || EXTRACT(MONTH FROM d)::INT  AS month_name,
    EXTRACT(WEEK    FROM d)::SMALLINT        AS week,
    EXTRACT(ISODOW  FROM d)::SMALLINT        AS day_of_week,
    EXTRACT(ISODOW  FROM d) IN (6, 7)        AS is_weekend
FROM generate_series('2020-01-01'::DATE, '2030-12-31'::DATE, '1 day'::INTERVAL) AS d
ON CONFLICT (date_key) DO NOTHING;


-- -------------------------------------------------------------
-- 6. fct_listings — Fact table trung tâm
-- Mỗi row = 1 tin đăng. FK → 4 dim.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.fct_listings (
    -- Surrogate key
    listing_key         BIGSERIAL   PRIMARY KEY,

    -- Natural key (truy về silver)
    source_name         VARCHAR(50)  NOT NULL,
    source_id           VARCHAR(200) NOT NULL,
    source_url          TEXT,

    -- Foreign keys → dimensions
    location_key        BIGINT      REFERENCES gold.dim_location(location_key),
    property_type_key   INT         REFERENCES gold.dim_property_type(property_type_key),
    source_key          INT         REFERENCES gold.dim_source(source_key),
    date_key            INT         REFERENCES gold.dim_date(date_key),  -- posted_at

    -- Measures
    price_vnd           BIGINT,
    area_m2             NUMERIC(8, 2),
    price_per_m2        BIGINT,
    deposit_vnd         BIGINT,
    bedrooms            INT,
    bathrooms           INT,

    -- Amenity flags (boolean — 12 cột, khớp silver.listings)
    has_air_conditioner BOOLEAN DEFAULT FALSE,
    has_water_heater    BOOLEAN DEFAULT FALSE,
    has_fridge          BOOLEAN DEFAULT FALSE,
    has_washing_machine BOOLEAN DEFAULT FALSE,
    has_furniture       BOOLEAN DEFAULT FALSE,
    has_wifi            BOOLEAN DEFAULT FALSE,
    has_kitchen         BOOLEAN DEFAULT FALSE,
    is_self_contained   BOOLEAN DEFAULT FALSE,
    free_hours          BOOLEAN DEFAULT FALSE,
    landlord_shared     BOOLEAN DEFAULT FALSE,
    good_security       BOOLEAN DEFAULT FALSE,
    near_market         BOOLEAN DEFAULT FALSE,

    -- Chất lượng / metadata
    furnishing_level    VARCHAR(20),
    is_price_outlier    BOOLEAN DEFAULT FALSE,
    is_negotiable       BOOLEAN DEFAULT FALSE,
    price_status        VARCHAR(20),
    geocode_status      VARCHAR(20),

    -- Thumbnail
    thumbnail_url       TEXT,

    -- Timestamps
    posted_at           DATE,
    silver_created_at   TIMESTAMP,
    refreshed_at        TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE (source_name, source_id)
);

CREATE INDEX IF NOT EXISTS idx_fct_location     ON gold.fct_listings (location_key);
CREATE INDEX IF NOT EXISTS idx_fct_proptype     ON gold.fct_listings (property_type_key);
CREATE INDEX IF NOT EXISTS idx_fct_source       ON gold.fct_listings (source_key);
CREATE INDEX IF NOT EXISTS idx_fct_date         ON gold.fct_listings (date_key);
CREATE INDEX IF NOT EXISTS idx_fct_price        ON gold.fct_listings (price_vnd) WHERE price_status = 'ok';
CREATE INDEX IF NOT EXISTS idx_fct_area         ON gold.fct_listings (area_m2);
CREATE INDEX IF NOT EXISTS idx_fct_outlier      ON gold.fct_listings (is_price_outlier);

COMMENT ON TABLE gold.fct_listings IS
    'Fact table trung tâm: 1 row/tin đăng. Measures: price, area. FK → 4 dim.';


-- -------------------------------------------------------------
-- 7. listings_for_map — giữ lại cho web app
-- Rebuild từ fct_listings JOIN dim_location sau mỗi ETL run.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.listings_for_map (
    listing_key         BIGINT      PRIMARY KEY REFERENCES gold.fct_listings(listing_key),
    -- Denormalized để web app query nhanh (không cần join)
    title               TEXT,
    price_vnd           BIGINT,
    area_m2             NUMERIC(8, 2),
    price_per_m2        BIGINT,
    bedrooms            INT,
    property_type       VARCHAR(50),
    furnishing_level    VARCHAR(20),
    price_segment       VARCHAR(20),  -- 'thap' | 'trung_binh' | 'cao'
    province            VARCHAR(100),
    ward                VARCHAR(100),
    latitude            NUMERIC(10, 7) NOT NULL,
    longitude           NUMERIC(10, 7) NOT NULL,
    source_name         VARCHAR(50),
    source_url          TEXT,
    thumbnail_url       TEXT,
    posted_at           DATE,
    -- Amenities cho filter sidebar
    has_air_conditioner BOOLEAN,
    has_water_heater    BOOLEAN,
    has_fridge          BOOLEAN,
    has_washing_machine BOOLEAN,
    has_furniture       BOOLEAN,
    has_wifi            BOOLEAN,
    has_kitchen         BOOLEAN,
    is_self_contained   BOOLEAN,
    free_hours          BOOLEAN,
    landlord_shared     BOOLEAN,
    good_security       BOOLEAN,
    near_market         BOOLEAN,
    is_active           BOOLEAN DEFAULT TRUE,
    refreshed_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_map_geo          ON gold.listings_for_map (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_map_price        ON gold.listings_for_map (price_vnd) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_map_ward         ON gold.listings_for_map (ward);
CREATE INDEX IF NOT EXISTS idx_map_proptype     ON gold.listings_for_map (property_type) WHERE is_active = TRUE;

COMMENT ON TABLE gold.listings_for_map IS
    'Denormalized view cho web app map: tin có lat/lng hợp lệ, không outlier. Refresh sau mỗi ETL run.';


-- -------------------------------------------------------------
-- Kiểm tra sau khi chạy
-- -------------------------------------------------------------
SELECT 'gold.dim_location'      AS tbl, COUNT(*) FROM gold.dim_location
UNION ALL
SELECT 'gold.dim_property_type', COUNT(*) FROM gold.dim_property_type
UNION ALL
SELECT 'gold.dim_source',        COUNT(*) FROM gold.dim_source
UNION ALL
SELECT 'gold.dim_date',          COUNT(*) FROM gold.dim_date
UNION ALL
SELECT 'gold.fct_listings',      COUNT(*) FROM gold.fct_listings
UNION ALL
SELECT 'gold.listings_for_map',  COUNT(*) FROM gold.listings_for_map;

-- staging/stg_listings.sql
-- Source: silver.listings
-- Chuẩn hoá nhẹ trước khi vào marts — không transform nặng ở đây.

WITH source AS (
    SELECT * FROM {{ source('silver', 'listings') }}
)

SELECT
    -- Natural key
    source_name,
    source_id,
    source_url,

    -- Content
    title,
    description,
    price_vnd,
    area_m2,
    CASE
        WHEN area_m2 IS NOT NULL AND area_m2 > 0 AND price_vnd IS NOT NULL
        THEN ROUND(price_vnd::NUMERIC / area_m2)::BIGINT
        ELSE NULL
    END                                             AS price_per_m2,
    deposit_vnd,
    bedrooms,
    bathrooms,
    furnishing_level,

    -- Property type: chuẩn hoá NULL → 'khac'
    COALESCE(property_type, 'khac')                 AS property_type,

    -- Location
    province,
    ward,
    latitude,
    longitude,
    geocode_status,

    -- Amenities
    has_air_conditioner,
    has_water_heater,
    has_fridge,
    has_washing_machine,
    has_furniture,
    has_wifi,
    has_kitchen,
    is_self_contained,
    free_hours,
    landlord_shared,
    good_security,
    near_market,

    -- Quality flags
    price_status,
    is_price_outlier,
    is_negotiable,

    -- Duplicate cross-source (gan co o silver_quality.py; group_id = MIN(listing_id) cua nhom)
    listing_id                                      AS silver_listing_id,
    duplicate_group_id,
    -- is_duplicate_secondary = TRUE neu tin KHONG phai dai dien nhom trung
    CASE
        WHEN duplicate_group_id IS NOT NULL
             AND listing_id <> duplicate_group_id
        THEN TRUE
        ELSE FALSE
    END                                             AS is_duplicate_secondary,

    -- Thumbnail
    COALESCE(self_thumbnail_url, original_thumbnail_url) AS thumbnail_url,

    -- Dates
    posted_at,
    created_at,
    updated_at

FROM source
WHERE price_status IN ('ok', 'suspect')   -- bỏ tin missing price hoàn toàn

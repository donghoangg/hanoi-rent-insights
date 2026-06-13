-- marts/listings_for_map.sql
-- Denormalized table cho web app map.
-- Chỉ tin: có lat/lng hợp lệ + price_status='ok' + không outlier.
-- Tính price_segment từ percentile p33/p67 của dataset.

{{
    config(
        materialized='table',
        pre_hook="TRUNCATE gold.listings_for_map"
    )
}}

WITH fct AS (
    SELECT * FROM {{ ref('fct_listings') }}
),

loc AS (
    SELECT location_key, province, ward, latitude, longitude
    FROM {{ ref('dim_location') }}
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
),

pt AS (
    SELECT property_type_key, property_type_code
    FROM {{ ref('dim_property_type') }}
),

-- Tính ngưỡng p33/p67 để phân segment giá theo từng loại hình
price_percentiles AS (
    SELECT
        f.property_type_key,
        PERCENTILE_CONT(0.33) WITHIN GROUP (ORDER BY f.price_vnd) AS p33,
        PERCENTILE_CONT(0.67) WITHIN GROUP (ORDER BY f.price_vnd) AS p67
    FROM fct f
    WHERE f.price_status = 'ok'
      AND f.price_vnd IS NOT NULL
      AND f.is_price_outlier = FALSE
      -- Khu trung cross-source (percentile cung bo tin trung)
      AND f.is_duplicate_secondary = FALSE
    GROUP BY f.property_type_key
),

-- Fallback percentile toàn dataset
price_overall AS (
    SELECT
        PERCENTILE_CONT(0.33) WITHIN GROUP (ORDER BY price_vnd) AS p33,
        PERCENTILE_CONT(0.67) WITHIN GROUP (ORDER BY price_vnd) AS p67
    FROM fct
    WHERE price_status = 'ok'
      AND price_vnd IS NOT NULL
      AND is_price_outlier = FALSE
)

SELECT
    f.listing_key,
    -- Cần title từ silver — join lại qua source_name + source_id
    s.title,
    f.price_vnd,
    f.area_m2,
    f.price_per_m2,
    f.bedrooms,
    pt.property_type_code                       AS property_type,
    f.furnishing_level,
    -- price_segment
    CASE
        WHEN f.price_vnd <= COALESCE(pp.p33, po.p33) THEN 'thap'
        WHEN f.price_vnd >= COALESCE(pp.p67, po.p67) THEN 'cao'
        ELSE 'trung_binh'
    END                                         AS price_segment,
    loc.province,
    loc.ward,
    loc.latitude,
    loc.longitude,
    ds.source_name,
    f.source_url,
    f.thumbnail_url,
    f.posted_at,
    -- Amenities
    f.has_air_conditioner,
    f.has_water_heater,
    f.has_fridge,
    f.has_washing_machine,
    f.has_furniture,
    f.has_wifi,
    f.has_kitchen,
    f.is_self_contained,
    f.free_hours,
    f.landlord_shared,
    f.good_security,
    f.near_market,
    TRUE                                        AS is_active,
    NOW()                                       AS refreshed_at

FROM fct f
INNER JOIN loc
    ON f.location_key = loc.location_key
LEFT JOIN pt
    ON f.property_type_key = pt.property_type_key
LEFT JOIN {{ ref('dim_source') }} ds
    ON f.source_key = ds.source_key
LEFT JOIN {{ source('silver', 'listings') }} s
    ON f.source_name = s.source_name AND f.source_id = s.source_id
LEFT JOIN price_percentiles pp
    ON f.property_type_key = pp.property_type_key
CROSS JOIN price_overall po

WHERE f.price_status = 'ok'
  AND f.price_vnd IS NOT NULL
  AND f.is_price_outlier = FALSE
  -- Khu trung cross-source: chi giu 1 dai dien moi nhom trung
  AND f.is_duplicate_secondary = FALSE

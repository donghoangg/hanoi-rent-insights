-- marts/fct_listings.sql
-- Fact table trung tâm: join stg_listings với 4 dim để lấy surrogate keys.
-- FULL REFRESH mỗi lần chạy (TRUNCATE + INSERT).

{{
    config(
        materialized='table',
        unique_key='listing_key',
        pre_hook="TRUNCATE gold.fct_listings RESTART IDENTITY CASCADE"
    )
}}

WITH stg AS (
    SELECT * FROM {{ ref('stg_listings') }}
),

dim_loc AS (
    SELECT location_key, province, ward
    FROM {{ ref('dim_location') }}
),

dim_pt AS (
    SELECT property_type_key, property_type_code
    FROM {{ ref('dim_property_type') }}
),

dim_src AS (
    SELECT source_key, source_name
    FROM {{ ref('dim_source') }}
),

dim_dt AS (
    SELECT date_key, full_date
    FROM {{ ref('dim_date') }}
)

SELECT
    ROW_NUMBER() OVER (ORDER BY stg.source_name, stg.source_id) AS listing_key,

    -- Natural keys
    stg.source_name,
    stg.source_id,
    stg.source_url,

    -- Foreign keys → dimensions
    dim_loc.location_key,
    dim_pt.property_type_key,
    dim_src.source_key,
    dim_dt.date_key,

    -- Measures
    stg.price_vnd,
    stg.area_m2,
    stg.price_per_m2,
    stg.deposit_vnd,
    stg.bedrooms,
    stg.bathrooms,

    -- Amenities
    stg.has_air_conditioner,
    stg.has_water_heater,
    stg.has_fridge,
    stg.has_washing_machine,
    stg.has_furniture,
    stg.has_wifi,
    stg.has_kitchen,
    stg.is_self_contained,
    stg.free_hours,
    stg.landlord_shared,
    stg.good_security,
    stg.near_market,

    -- Metadata
    stg.furnishing_level,
    stg.price_status,
    COALESCE(stg.is_price_outlier, FALSE)   AS is_price_outlier,
    COALESCE(stg.is_negotiable, FALSE)      AS is_negotiable,
    stg.geocode_status,
    stg.thumbnail_url,

    -- Duplicate cross-source (mang tu silver len de KPI khong dem trung)
    stg.duplicate_group_id,
    stg.is_duplicate_secondary,

    -- Dates
    stg.posted_at,
    stg.created_at                          AS silver_created_at,
    NOW()                                   AS refreshed_at

FROM stg

-- Join dim_location: match province + ward (NULL-safe)
LEFT JOIN dim_loc
    ON stg.province = dim_loc.province
    AND (
        (stg.ward IS NULL AND dim_loc.ward IS NULL)
        OR stg.ward = dim_loc.ward
    )

-- Join dim_property_type
LEFT JOIN dim_pt
    ON stg.property_type = dim_pt.property_type_code

-- Join dim_source
LEFT JOIN dim_src
    ON stg.source_name = dim_src.source_name

-- Join dim_date
LEFT JOIN dim_dt
    ON stg.posted_at = dim_dt.full_date

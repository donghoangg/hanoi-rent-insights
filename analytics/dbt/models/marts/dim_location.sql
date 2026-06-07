-- marts/dim_location.sql
-- Dimension địa điểm: dedup (province, ward), centroid = avg lat/lng của các tin.
-- FULL REFRESH mỗi lần chạy.

{{
    config(
        materialized='table',
        unique_key='location_key',
        pre_hook="TRUNCATE gold.dim_location RESTART IDENTITY CASCADE"
    )
}}

WITH location_pairs AS (
    SELECT DISTINCT
        province,
        ward
    FROM {{ ref('stg_listings') }}
    WHERE province IS NOT NULL
),

centroids AS (
    SELECT
        province,
        ward,
        ROUND(AVG(latitude)::NUMERIC, 7)  AS latitude,
        ROUND(AVG(longitude)::NUMERIC, 7) AS longitude
    FROM {{ ref('stg_listings') }}
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    GROUP BY province, ward
)

SELECT
    ROW_NUMBER() OVER (ORDER BY lp.province, lp.ward NULLS LAST) AS location_key,
    lp.province,
    lp.ward,
    c.latitude,
    c.longitude
FROM location_pairs lp
LEFT JOIN centroids c
    ON lp.province = c.province
    AND (lp.ward = c.ward OR (lp.ward IS NULL AND c.ward IS NULL))

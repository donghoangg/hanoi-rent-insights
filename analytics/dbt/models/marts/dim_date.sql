-- marts/dim_date.sql
-- Dimension ngày — đọc từ bảng đã populate trong schema (2020–2030).

{{
    config(materialized='table')
}}

SELECT
    date_key,
    full_date,
    year,
    quarter,
    month,
    month_name,
    week,
    day_of_week,
    is_weekend
FROM gold.dim_date

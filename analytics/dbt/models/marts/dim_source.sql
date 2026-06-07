-- marts/dim_source.sql
-- Dimension nguồn dữ liệu — static lookup table.

{{
    config(
        materialized='table',
        pre_hook="TRUNCATE gold.dim_source RESTART IDENTITY"
    )
}}

SELECT *
FROM (VALUES
    (1, 'nhatot',      'https://www.nhatot.com',  TRUE),
    (2, 'mogi',        'https://mogi.vn',          TRUE),
    (3, 'batdongsan',  'https://batdongsan.com.vn', FALSE)
) AS t(source_key, source_name, source_url_base, is_active)

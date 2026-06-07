-- marts/dim_property_type.sql
-- Dimension loại hình BĐS — static lookup table.

{{
    config(
        materialized='table',
        pre_hook="TRUNCATE gold.dim_property_type RESTART IDENTITY"
    )
}}

SELECT *
FROM (VALUES
    (1, 'room',       N'Phòng trọ',        N'Phòng'),
    (2, 'apartment',  N'Chung cư / căn hộ', N'Căn hộ'),
    (3, 'house',      N'Nhà nguyên căn',    N'Nhà'),
    (4, 'studio',     N'Studio',            N'Phòng'),
    (5, 'other',      N'Khác',              N'Khác')
) AS t(property_type_key, property_type_code, property_type_name, property_type_group)

-- marts/dim_property_type.sql
-- Dimension loại hình BĐS — static lookup table.
-- property_type_code KHỚP với silver.listings (phong_tro / chung_cu / nha_nguyen_can
-- / can_ho_dich_vu / khac) để fct_listings join ra property_type_key.
-- Trước đây seed dùng room/apartment/house nên join trượt → property_type Gold bị NULL.

{{
    config(
        materialized='table',
        pre_hook="TRUNCATE gold.dim_property_type RESTART IDENTITY"
    )
}}

SELECT *
FROM (VALUES
    (1, 'phong_tro',      'Phòng trọ',        'Phòng'),
    (2, 'chung_cu',       'Chung cư',         'Căn hộ'),
    (3, 'nha_nguyen_can', 'Nhà nguyên căn',   'Nhà'),
    (4, 'can_ho_dich_vu', 'Căn hộ dịch vụ',   'Căn hộ'),
    (5, 'khac',           'Khác',             'Khác')
) AS t(property_type_key, property_type_code, property_type_name, property_type_group)

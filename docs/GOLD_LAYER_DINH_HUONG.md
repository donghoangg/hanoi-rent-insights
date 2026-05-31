# Định hướng tầng Gold — Star Schema (dbt)

> Ghi chú định hướng. **Chưa triển khai.** File này để chốt hướng đi trước khi code,
> tránh phải làm lại về sau.

## Quyết định

- **Tầng Gold sẽ được xây theo mô hình Star Schema** (1 bảng fact ở trung tâm + các bảng dimension xung quanh), thay cho 2 bảng phẳng hiện có trong `infra/db/schema.sql` (`gold.listings_for_map`, `gold.price_by_area`).
- **Công cụ xây dựng: dbt (dbt-core + dbt-postgres)** — đúng định hướng trong `.cursorrules` và tương tự kiến trúc Đồ án 2.
- Bronze và Silver **không bị ảnh hưởng** — star schema chỉ là cách tổ chức tầng Gold. Logic Silver/Gold hiện **chưa được viết**, nên việc theo star schema gần như không tốn chi phí làm lại.

## Phác thảo Star Schema dự kiến (sẽ tinh chỉnh khi triển khai)

**Bảng fact (trung tâm):**

- `gold.fct_listings` — mỗi dòng là một tin đăng. Chứa:
  - Các số đo (measures): `price_vnd`, `area_m2`, `price_per_m2`, `deposit_vnd`
  - Các khóa ngoại (foreign keys) trỏ tới dimension: `location_key`, `property_type_key`, `source_key`, `date_key`
  - Cờ chất lượng: `is_price_outlier`, `is_negotiable`

**Các bảng dimension:**

- `gold.dim_location` — tỉnh/thành (province) + phường/xã (ward) + toạ độ (lat/long), theo địa giới 2 cấp (từ 01/07/2025).
- `gold.dim_property_type` — loại hình: phòng trọ, chung cư mini, nhà nguyên căn, căn hộ...
- `gold.dim_source` — nguồn dữ liệu: nhatot, mogi, batdongsan.
- `gold.dim_date` — ngày đăng (day/month/quarter/year) phục vụ phân tích theo thời gian.
- Tiện ích (amenities): cân nhắc bridge table `gold.bridge_listing_amenities` hoặc giữ các cột boolean ngay trên fact — quyết định khi triển khai.

## Tổ chức dbt dự kiến

```
analytics/                 # dbt project
├── dbt_project.yml
├── models/
│   ├── staging/           # nguồn từ silver.listings
│   │   └── stg_listings.sql
│   ├── marts/
│   │   ├── dim_location.sql
│   │   ├── dim_property_type.sql
│   │   ├── dim_source.sql
│   │   ├── dim_date.sql
│   │   └── fct_listings.sql
│   └── schema.yml         # tests: not_null, unique, relationships (FK fact→dim)
└── profiles.yml           # kết nối Supabase (đọc từ .env)
```

## Việc cần làm khi triển khai (chưa làm)

1. Viết tầng Silver ETL (đọc bronze → làm sạch → ghi `silver.listings`).
2. Bỏ 2 bảng Gold phẳng trong `schema.sql`, thay bằng fact + dimension.
3. Khởi tạo dbt project, viết các model dim/fact theo star schema.
4. Thêm dbt tests (unique key dimension, quan hệ FK fact→dim, not_null các số đo).
5. Cập nhật `.cursorrules` / `CLAUDE.md` ghi rõ Gold = star schema dựng bằng dbt.

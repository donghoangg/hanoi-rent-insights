# CLAUDE.md — HanoiRent Insights · Scraper Context

> Đọc file này đầu mỗi session để tiếp tục làm việc ngay, không cần hỏi lại.

---

## 1. Tổng quan dự án

**HanoiRent Insights** — nền tảng phân tích thị trường nhà/phòng **cho thuê** tại **Hà Nội**.
- Mục tiêu: Thu thập, làm sạch, và phân tích dữ liệu giá thuê theo quận/loại hình
- Kiến trúc: **Medallion** — Bronze (raw) → Silver (cleaned/geocoded) → Gold (analytics)
- Database: **PostgreSQL trên Supabase** (free tier, Singapore)
  - Credentials nằm trong `.env` (đã gitignore — KHÔNG commit)
  - DB host: `aws-1-ap-southeast-1.pooler.supabase.com`, password: `datnthanhcong`

---

## 2. Cấu trúc thư mục

```
hanoi-rent-insights/
├── .env                        # Supabase credentials (gitignored)
├── requirements.txt            # Python deps (scrapy, playwright, psycopg2, supabase...)
├── infra/db/schema.sql         # DDL: bronze/silver/gold schemas
└── scraper/
    ├── CLAUDE.md               # ← file này
    ├── scrapy.cfg
    ├── __init__.py
    ├── items.py                # RentingItem definition
    ├── settings.py             # Scrapy config + pipeline order
    ├── middlewares.py          # RandomUserAgent + SmartRetry
    ├── pipelines.py            # Validation → Duplicates → Bronze DB
    └── spiders/
        ├── nhatot_spider.py    # API JSON (no Playwright needed)
        ├── mogi_spider.py      # HTML SSR (no Playwright)
        └── batdongsan_spider.py # Next.js SPA (Playwright required)
```

---

## 3. Chạy spiders

```bash
cd hanoi-rent-insights/scraper

# Thử nhanh (50 tin)
scrapy crawl nhatot      -s CLOSESPIDER_ITEMCOUNT=50
scrapy crawl mogi        -s CLOSESPIDER_ITEMCOUNT=50
scrapy crawl batdongsan  -s CLOSESPIDER_ITEMCOUNT=30

# Chạy đầy đủ
scrapy crawl nhatot
scrapy crawl mogi
scrapy crawl batdongsan

# Playwright cần cài trước (chỉ cho batdongsan)
playwright install chromium
```

---

## 4. Chi tiết từng spider

### 4.1 Nhatot (`nhatot_spider.py`) — API JSON public

**Endpoint:** `https://gateway.chotot.com/v1/public/ad-listing`

**Category codes cho thuê (đã xác nhận live):**

| `cg` | `category_name` | `st` | Ghi chú |
|------|----------------|------|---------|
| `1050` | Phòng trọ | `u` | type=`u` trong response |
| `1010` | Căn hộ/Chung cư | `u` | type=`u` |
| `1020` | Nhà nguyên căn | `u` | type=`u` |

- `st=u` = cho thuê ("use"), `st=s` = bán ("sell") → **phải dùng `st=u`**
- `region_v2=12000` = Hà Nội
- Tham số `type=r` hoặc `st=r` **không hoạt động** — phải dùng `st=u`
- **GPS native**: Nhatot trả `latitude`/`longitude` trực tiếp → không cần geocode
- `furnishing_rent` (0=bare, 1=partial, 2=full, 3=luxury) — rental dùng `furnishing_rent`, KHÔNG phải `furnishing_sell`
- Detail API: `https://gateway.chotot.com/v2/public/ad-listing/{list_id}`

**Guard:** Drop listing nếu `type == "s"` trong `parse_detail`.

### 4.2 Mogi (`mogi_spider.py`) — HTML SSR

**URLs danh sách:**
```
https://mogi.vn/ha-noi/cho-thue-phong-tro?p={page}
https://mogi.vn/ha-noi/cho-thue-nha?p={page}
https://mogi.vn/ha-noi/cho-thue-can-ho?p={page}
```

- Server-side rendered → WebFetch/HTTP thuần **không lấy được nội dung** (trả empty)
- Scrapy thường hoạt động vì gửi real HTTP request với UA rotation
- Guard: URL detail phải chứa keyword `cho-thue` hoặc `thue-phong`
- `furnishing_level` extract từ CSS: `span.info-item:contains('Nội thất') strong::text`
- Source ID từ regex số cuối URL: `/(\d{7,12})(?:\.html)?`

### 4.3 Batdongsan (`batdongsan_spider.py`) — Next.js SPA

**URLs danh sách:**
```
https://batdongsan.com.vn/cho-thue-phong-tro-ha-noi?sortValue=1&pageIndex={page}
https://batdongsan.com.vn/cho-thue-chung-cu-ha-noi?sortValue=1&pageIndex={page}
https://batdongsan.com.vn/cho-thue-nha-rieng-ha-noi?sortValue=1&pageIndex={page}
https://batdongsan.com.vn/cho-thue-nha-dat-ha-noi?sortValue=1&pageIndex={page}
```

- **Playwright bắt buộc** cho trang danh sách (wait_for_selector `div.js__card`)
- Parse từ `<script id="__NEXT_DATA__">` (nhanh) → fallback CSS selectors
- Trang detail: thử HTTP thuần trước, nếu 403 retry với Playwright
- Guard: URL phải chứa `cho-thue`
- Source ID từ regex: `pr(\d{6,12})` trong URL
- `furnishing` từ `__NEXT_DATA__`: field `furniture` hoặc `interiorStatus`

---

## 5. RentingItem fields (`items.py`)

```python
source_name      # 'nhatot' | 'mogi' | 'batdongsan'
source_id        # str: ID gốc trên web nguồn
source_url       # str: URL đầy đủ
title            # str
description      # str
price_vnd        # int: VND/tháng
area_m2          # float: m²
bedrooms         # int | None
bathrooms        # int | None
property0_type    # 'phong_tro'|'chung_cu'|'nha_nguyen_can'|'can_ho_dich_vu'
furnishing_level # 'bare'|'partial'|'full'|'luxury' | None  ← THÊM session này
amenities        # list[str] | None  ← THÊM session này (NLP ở Silver ETL)
address          # str: địa chỉ thô
district         # str: tên quận
ward             # str | None: tên phường
thumbnail_url    # str | None
image_urls       # list[str]
posted_at        # str | None: ISO date
raw_payload      # dict: toàn bộ data thô
```

---

## 6. Pipeline (`pipelines.py`)

Thứ tự: `ValidationPipeline(100)` → `DuplicatesPipeline(200)` → `BronzePipeline(300)`

- **ValidationPipeline**: kiểm tra required fields, price range 500k–100M VND
- **DuplicatesPipeline**: load (source_name, source_id) từ DB vào memory set khi spider mở
- **BronzePipeline**: INSERT vào `bronze.listings_raw` + `bronze.listing_images_raw` (ON CONFLICT DO NOTHING)

---

## 7. Database Schema (`infra/db/schema.sql`)

### Bronze
- `bronze.listings_raw`: BIGSERIAL PK, source_name, source_id, source_url, raw_payload JSONB, scraped_at
- `bronze.listing_images_raw`: source_name, source_id, image_url, image_order

### Silver (`silver.listings`)
Thêm session này: **`furnishing_level VARCHAR(20)`** + **`amenities JSONB`**
- `geocode_status`: 'pending' | 'success' | 'failed' | 'centroid'
- `thumbnail_status`: 'pending' | 'success' | 'failed'
- Trigger `silver.set_updated_at()` tự cập nhật `updated_at`

### Gold
- `gold.listings_for_map`: có `price_segment`, `furnishing_level`, `amenities`, `is_active`
- `gold.price_by_district`: stats tổng hợp avg/median/min/max theo quận

---

## 8. NLP Amenity Extraction (Silver ETL — chưa implement)

Xử lý tại stage Silver, đọc `description` + `title` → điền `amenities JSONB`.

Từ khoá đã định nghĩa (trong pipeline demo):
```
dieu_hoa, tu_lanh, may_giat, nong_lanh, bep, internet,
truyen_hinh, giu_xe, an_ninh, thang_may, ban_cong, giuong, tu_quan_ao
```

---

## 9. Phần việc TIẾP THEO (chưa làm)

Các bước theo kiến trúc Medallion sau khi scraper hoàn chỉnh:

- [ ] **ETL Silver**: Script Python đọc từ `bronze.listings_raw` → clean → geocode (geopy/Nominatim) → NLP amenities → insert `silver.listings`
- [ ] **ETL Gold / dbt**: Transform từ Silver → Gold (`listings_for_map`, `price_by_district`)
  - Dùng dbt-postgres (đã có trong requirements.txt)
  - Hoặc script Python thuần nếu không dùng dbt
- [ ] **Thumbnail pipeline**: Download ảnh → resize/compress (Pillow) → upload Supabase Storage → cập nhật `self_thumbnail_url`
- [ ] **FastAPI backend**: Endpoint `/api/listings` phục vụ map (`gold.listings_for_map`)
- [ ] **Streamlit dashboard**: Map (Folium/streamlit-folium) + charts (Plotly) + filters
- [ ] **Geocoding**: Nhatot có GPS native; Mogi + BDS cần geocode bằng `geopy.Nominatim` từ `address`

---

## 10. Lưu ý kỹ thuật quan trọng

- **`.env` KHÔNG commit** — đã trong `.gitignore`. Credentials thật nằm ở `.env`
- **Sandbox network**: môi trường Linux sandbox (bash) bị block outbound HTTPS → dùng `mcp__workspace__web_fetch` để test API, không dùng `curl`/`requests` trong bash
- **Mogi + BDS** là JS-SPA → `web_fetch` trả empty — chỉ Scrapy thật (với Playwright) mới fetch được
- **Nhatot** là API JSON public → `web_fetch` hoạt động bình thường, có thể test trực tiếp
- **`furnishing_sell`** (Nhatot, bên bán) ≠ **`furnishing_rent`** (Nhatot, bên thuê) — rental listings dùng `furnishing_rent`
- **`st=u`** (not `st=r`) là param đúng cho Nhatot rental filter

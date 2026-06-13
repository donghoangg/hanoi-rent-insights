# Pipeline chi tiết — HanoiRent Insights (tài liệu viết báo cáo)

> Tài liệu mô tả end-to-end toàn bộ pipeline dữ liệu: từng bước, công cụ, cách xử lý từng phần việc nhỏ.
> Dùng làm nền viết chương "Thiết kế & triển khai hệ thống" trong báo cáo đồ án.
> Đối chiếu trực tiếp với source code thực tế (không phải kế hoạch lý tưởng) — có ghi rõ các điểm lệch giữa code và kế hoạch.

---

## 0. Tổng quan luồng dữ liệu

```
Websites nguồn          Scrapy spiders        PostgreSQL (Supabase) — Medallion          Phục vụ
─────────────           ──────────────        ─────────────────────────────────         ───────
Nhatot  (API JSON) ─┐                   ┌─ bronze.listings_raw ──┐
Mogi    (HTML)    ──┼─► 3 Item Pipelines├─ bronze.listings_quarantine                   FastAPI ─► Next.js (map)
Batdongsan (DISABLED)│   Validate→Dedup→ └─ bronze.scrape_runs    │                       Streamlit (dashboard)
                    │   Bronze                                    ▼
                    │                       silver.listings ◄── bronze_to_silver.py (clean+geocode+NLP)
                    │                              │         ◄── silver_quality.py (outlier + dedup)
                    │                              ▼
                    │                       gold.* ◄── dbt run (star schema)  HOẶC silver_to_gold.py (bảng phẳng)
                    │                              │
                    └──────────────────────► download_thumbnails.py ─► Supabase Storage
```

Năm giai đoạn chính, chạy tuần tự mỗi khi có data mới:

```
1. scrapy crawl nhatot   /   scrapy crawl mogi      → ghi Bronze
2. python -m etl.bronze_to_silver                   → Bronze → Silver (clean, geocode, NLP tiện ích)
3. python -m etl.silver_quality                     → gắn cờ outlier + duplicate trên Silver
4. dbt run                                           → Silver → Gold (star schema)
5. python -m etl.download_thumbnails                → tải ảnh về Supabase Storage
```

### Công cụ tổng thể

| Tầng | Công cụ chính | Hosting |
|------|---------------|---------|
| Scraping | Scrapy 2.11 (3 item pipeline, 2 middleware) | GitHub Actions cron (kế hoạch) |
| Database | PostgreSQL 3 schema (bronze/silver/gold) | Supabase free tier |
| Bronze→Silver | Python + psycopg2 + geopy(Nominatim) + regex NLP | local / CI |
| Quality | Python + SQL (IQR, self-join dedup) | local / CI |
| Silver→Gold | dbt-core 1.7 (star schema) + Python fallback | local / CI |
| Ảnh | Pillow + Supabase Storage client | local |
| Dashboard | Streamlit + Altair/Plotly + folium | Streamlit Cloud |
| Backend | FastAPI + uvicorn | Render |
| Frontend | Next.js + React-Leaflet | Vercel |

---

## 1. GIAI ĐOẠN 1 — Scraping (Scrapy)

### 1.1. Cấu trúc & cấu hình (`scraper/settings.py`)

Cấu hình "lịch sự" để tránh bị chặn:

- `ROBOTSTXT_OBEY = False` — các site BĐS VN không có robots.txt hợp lệ (ghi rõ lý do trong báo cáo để minh bạch về mặt đạo đức scraping).
- `DOWNLOAD_DELAY = 2s` + `RANDOMIZE_DOWNLOAD_DELAY = True` → delay thực tế dao động 0.5×–1.5× để giả lập hành vi người.
- `CONCURRENT_REQUESTS = 4`, mỗi domain tối đa 2 request đồng thời.
- **AutoThrottle bật**: Scrapy tự điều chỉnh tốc độ theo response time của server (start 2s, max 10s) — tự chậm lại khi server tải nặng.
- **Retry**: 3 lần, cho các mã `500/502/503/504/408/429/403`.
- `TWISTED_REACTOR = AsyncioSelectorReactor` — bắt buộc cho Scrapy bản mới + spider async.

### 1.2. Item — hợp đồng dữ liệu (`scraper/items.py`)

`RentingItem` là schema thống nhất mọi spider phải tuân theo: định danh nguồn (`source_name/source_id/source_url`), thông tin chính (`price_vnd/area_m2/bedrooms/property_type/furnishing_level`), địa chỉ **2 cấp** (`province/ward`, **không có quận** theo địa giới mới 01/07/2025), ảnh, `posted_at`, và `raw_payload` (toàn bộ JSON gốc để Bronze giữ nguyên). Các trường bắt đầu bằng `_` (`_quarantine/_error_reason/_missing_fields`) là cờ nội bộ pipeline, không ghi ra DB.

### 1.3. Middleware chống chặn (`scraper/middlewares.py`)

Hai middleware tự viết:

`RandomUserAgentMiddleware` (priority 400) — thay built-in UA middleware, gán ngẫu nhiên 1 trong **8 User-Agent** (Chrome/Firefox/Edge/Safari trên Win/Mac/Android) cho mỗi request.

`SmartRetryMiddleware` (priority 550) — kế thừa `RetryMiddleware`, thêm logic:
- HTTP **429** (Too Many Requests): exponential backoff `5×2^retry` giây, tối đa 60s.
- HTTP **403/503**: sleep random 3–8s rồi retry.

### 1.4. Spider Nhatot — qua API JSON (`nhatot_spider.py`)

Nguồn **dễ cào nhất** vì Chợ Tốt có API public, không cần Playwright:

- **List API**: `gateway.chotot.com/v1/public/ad-listing` với `region_v2=12000` (Hà Nội), phân trang `page`, `limit=50`, `MAX_PAGES=100`.
- Cào **3 category cho thuê**: `cg=1050` (phòng trọ), `cg=1010` (chung cư), `cg=1020` (nhà nguyên căn); tham số `st=u` = cho thuê (phân biệt với `st=s` = bán).
- **Detail API**: `v2/public/ad-listing/{ad_id}` lấy đầy đủ thông tin + ảnh.
- **Guard 2 lớp**: bỏ qua mọi listing `type != "u"` ở cả list lẫn detail → đảm bảo chỉ lấy tin cho thuê.
- **Xử lý từng trường**: giá normalize thông minh (nếu < 1000 coi là đơn vị triệu, < 100k coi là nghìn); `property_type` suy từ `category` + `house_type`; `furnishing_rent` (0–3) map sang bare/partial/full/luxury.
- **Lợi thế lớn**: Nhatot trả sẵn `latitude/longitude` → **không cần geocoding** cho nguồn này.

### 1.5. Spider Mogi — qua HTML (`mogi_spider.py`)

Mogi.vn server-side render → parse HTML bằng CSS selector, không cần Playwright. Crawl trang list cho thuê có phân trang → lấy URL từng tin → request detail page → parse. `property_type` suy từ **slug URL** (`cho-thue-phong-tro` → `phong_tro`) hoặc text trên trang. Mogi không có toạ độ → **cần geocoding ở tầng Silver**.

### 1.6. Spider Batdongsan — ĐÃ TẮT (quan trọng ghi vào báo cáo)

Batdongsan.com.vn dùng **Cloudflare Bot Management cấp enterprise**. Đã thử Playwright, undetected-chromedriver, Selenium + remote debugging — **tất cả đều bị chặn**. Spider được giữ lại để tham khảo nhưng **không chạy production**. Đây là một **rủi ro kỹ thuật thực tế** đáng phân tích trong báo cáo: kế hoạch ban đầu đặt Batdongsan là nguồn "bắt buộc", thực tế phải chuyển sang Nhatot + Mogi làm 2 nguồn chính. Bài học: nên khảo sát khả năng chống bot trước khi cam kết nguồn.

### 1.7. Item Pipeline — 3 bước nối tiếp (`scraper/pipelines.py`)

Mỗi item đi qua 3 pipeline theo thứ tự priority:

**Bước 1 — `ValidationPipeline` (100):** Quy tắc cách ly: tin thiếu **`source_url` HOẶC `address`** (2 trường bắt buộc cứng) → ghi vào `bronze.listings_quarantine` kèm `error_reason` (vd `missing:address`) rồi `DropItem`. Các trường khác thiếu (title/price/area) **không cách ly** — tin vẫn vào Bronze, xử lý ở Silver. Đồng thời chuẩn hoá kiểu cơ bản (ép `price_vnd/area_m2/bedrooms` về số). Triết lý: **không vứt data, chỉ cách ly để audit** — đây là điểm "ăn điểm" về data quality.

**Bước 2 — `DuplicatesPipeline` (200):** Khi spider mở, load toàn bộ `(source_name, source_id)` đã có trong `bronze.listings_raw` vào một `set` trong RAM. Mỗi item check trong set → trùng thì drop. Cách này nhanh hơn nhiều so với query DB từng item.

**Bước 3 — `BronzePipeline` (300):** Ghi `raw_payload` (JSONB) vào `bronze.listings_raw`, ảnh vào `bronze.listing_images_raw`. Quan trọng: ghi **log mỗi lần chạy** vào `bronze.scrape_runs` — insert row `status='running'` khi mở spider, update `finished/duration/total/pass/quarantine/duplicate/pass_rate` khi đóng. Các count được chia sẻ giữa pipeline qua `crawler.stats`.

---

## 2. GIAI ĐOẠN 2 — Bronze → Silver (`etl/bronze_to_silver.py`)

Đây là tầng transform nặng nhất. Đọc `bronze.listings_raw` theo batch (100 tin), transform, upsert vào `silver.listings`.

### 2.1. Chuẩn hoá giá (`_normalize_price`)

Trả về `(price_vnd, price_status)` với 3 trạng thái: `ok` (trong khoảng 500k–100tr), `suspect` (ngoài khoảng nhưng vẫn giữ lại), `missing` (null/0/parse lỗi). `price_status` này là **bộ lọc xuyên suốt** các tầng sau — Gold chỉ lấy `ok`.

### 2.2. Tách tiện ích bằng NLP regex (`_extract_amenities`)

Quét `title + description` (lowercase) bằng **12 pattern regex** tương ứng 12 cột boolean trong `silver.listings`: điều hoà, nóng lạnh, tủ lạnh, máy giặt, nội thất, wifi, bếp, khép kín, giờ tự do, chung chủ, an ninh, gần chợ.

**Xử lý phủ định (điểm tinh tế):** với mỗi match, kiểm tra 40 ký tự ngay trước nó; nếu có từ phủ định (`không/cấm/ko có/...`) thì bỏ qua match — tránh hiểu sai "không có điều hoà" thành "có điều hoà".

### 2.3. Chuẩn hoá địa chỉ 2 cấp

`_normalize_province` (alias `hanoi/hn/tp hà nội` → `Hà Nội`), `_normalize_ward`, và `_extract_address_parts` tách ward từ chuỗi địa chỉ. Có danh sách tên quận cũ (`HANOI_DISTRICT_NAMES`) **chỉ để nhận diện và bỏ qua** phần "quận" khi tách ward (vì địa giới mới không dùng quận nữa).

### 2.4. Geocoding (`GeocoderWrapper`)

Chiến lược 3 tầng, ưu tiên tiết kiệm request Nominatim (free, giới hạn 1 req/s):
1. **Nhatot**: dùng lat/lng có sẵn từ API → bỏ qua geocoding hoàn toàn.
2. **Cache**: bảng `silver.geocode_cache` (key = address normalize). Load toàn bộ vào RAM khi khởi động; trước khi gọi Nominatim luôn check cache.
3. **Nominatim** (OpenStreetMap, free): geocode địa chỉ Mogi.
4. **Fallback centroid**: nếu Nominatim fail, dùng **bảng hardcode `WARD_CENTROIDS`** (~180 phường Hà Nội với toạ độ trung tâm). `geocode_status` ghi rõ `success/centroid/failed/pending`.

**Hạn chế (ghi báo cáo):** geocoding chỉ chính xác cấp phường, không tới số nhà → frontend cần thêm jitter ±100m để marker không chồng.

### 2.5. Upsert vào Silver

Dùng `INSERT ... ON CONFLICT (source_name, source_id) DO UPDATE` → idempotent, chạy lại không tạo trùng. Xử lý theo batch để giảm round-trip DB.

---

## 3. GIAI ĐOẠN 3 — Data Quality (`etl/silver_quality.py`)

Chạy sau bronze_to_silver, gắn cờ chất lượng trên `silver.listings`. Có `--dry-run` (chỉ in report, không UPDATE).

### 3.1. Phát hiện outlier giá (IQR)

- Tính `Q1, Q3` theo từng nhóm **`(property_type, source_name)`**, chỉ nhóm có ≥10 tin (đủ mẫu).
- Ngưỡng IQR: `price < Q1 - 1.5×IQR` hoặc `price > Q3 + 1.5×IQR` → outlier.
- Bổ sung **hard limit tuyệt đối**: < 500k hoặc > 100 triệu/tháng → outlier bất kể nhóm.
- `UPDATE silver.listings SET is_price_outlier = TRUE/FALSE` (reset hết về FALSE trước, rồi gắn TRUE).

### 3.2. Phát hiện trùng cross-source

Tin bị coi là trùng khi: **cùng `ward` + giá lệch ≤5% + diện tích lệch ≤5% + khác `source_name`**. Thực hiện bằng **self-join** trên `silver.listings` (a.listing_id < b.listing_id để tránh đếm đôi). Gán `duplicate_group_id = LEAST(listing_id)` của nhóm. Mục đích: phát hiện 1 căn được đăng ở cả Nhatot lẫn Mogi.

> ⚠️ **Điểm cần lưu ý:** cờ `duplicate_group_id` hiện **chỉ tồn tại ở Silver**, chưa được mang lên Gold → các KPI count ở Gold có thể đếm trùng. (Xem `KPI_DINH_HUONG.md` mục "3 việc nên fix".)

---

## 4. GIAI ĐOẠN 4 — Silver → Gold

> ⚠️ **ĐIỂM LỆCH QUAN TRỌNG giữa code và kế hoạch — cần thống nhất trước khi viết báo cáo.**
> Hiện có **HAI đường** build Gold, KHÔNG tương thích nhau:
>
> | | `etl/silver_to_gold.py` (Python) | `analytics/dbt/` (dbt) |
> |---|---|---|
> | Mô hình | **Bảng phẳng** cũ | **Star schema** (1 fact + 4 dim) |
> | Bảng tạo | `listings_for_map`, `price_stats_overall`, `price_stats_by_ward` | `fct_listings`, `dim_location/property_type/source/date`, `listings_for_map` |
> | Cột amenity map | `has_air_con/has_parking/has_elevator` (3 cột, **không khớp** silver) | 12 cột boolean khớp silver |
>
> Migration `migration_gold_star_schema.sql` **DROP các bảng phẳng cũ** rồi tạo star schema. Nghĩa là nếu chạy migration star schema thì `silver_to_gold.py` sẽ lỗi (bảng không còn). **Khuyến nghị: chọn dbt làm đường chính thức** (đúng định hướng "modern data stack", ăn điểm), và hoặc xoá `silver_to_gold.py` hoặc giữ lại như tài liệu lịch sử. Cần ghi rõ quyết định này trong báo cáo.

### 4.1. Đường chính thức — dbt (`analytics/dbt/`)

Cấu hình (`dbt_project.yml`): staging = **view** trên schema `silver` (không tốn storage), marts = **table** trên schema `gold` (query nhanh).

**Staging** (`stg_listings.sql`): đọc `silver.listings`, chuẩn hoá nhẹ — tính `price_per_m2`, `COALESCE(property_type,'khac')`, gộp thumbnail, lọc `price_status IN ('ok','suspect')`.

**Dimensions:**
- `dim_location` — dedup `(province, ward)`, centroid = `AVG(lat/lng)` các tin cùng phường. Full refresh mỗi lần.
- `dim_property_type` — **seed cố định** 5 loại (phong_tro/chung_cu_mini/chung_cu/nha_nguyen_can/khac) + nhóm.
- `dim_source` — seed (nhatot/mogi/batdongsan).
- `dim_date` — `generate_series` 2020–2030, đủ year/quarter/month/week/is_weekend.

**Fact** (`fct_listings.sql`): full refresh (`pre_hook` TRUNCATE), join stg với 4 dim lấy surrogate key, mang theo measures (price/area/price_per_m2/deposit) + 12 amenity + metadata. `listing_key` sinh bằng `ROW_NUMBER()`.

**Map mart** (`listings_for_map.sql`): denormalized cho web app — chỉ tin **có lat/lng + price_status='ok' + không outlier**. Tính `price_segment` (thap/trung_binh/cao) từ percentile **p33/p67 theo từng property_type**, fallback percentile toàn dataset.

**Tests** (`schema.yml`): `unique/not_null` cho các key, `relationships` test FK của fact → các dim. Đây là điểm cộng — chứng minh hiểu data testing.

### 4.2. Đường thay thế — Python (`etl/silver_to_gold.py`)

Build 3 bảng phẳng bằng SQL thuần: `price_stats_overall` (percentile p33/p67 để phân segment), `listings_for_map`, `price_stats_by_ward` (thống kê giá theo phường × loại hình). Dùng TRUNCATE+INSERT để Gold luôn phản ánh đúng Silver. **Lưu ý đây là phiên bản cũ trước khi chuyển sang star schema.**

---

## 5. GIAI ĐOẠN 5 — Ảnh thumbnail (`etl/download_thumbnails.py`)

Chạy 1 lần sau khi cào: với mỗi tin, tải ảnh gốc → resize **300×200, JPEG q75** (~30KB) bằng Pillow → upload Supabase Storage bucket `listing-thumbnails` (cache 1 năm) → cập nhật `self_thumbnail_url` + `thumbnail_status`. Tổng ~150MB cho 5K tin (15% quota free). URL gốc 404 → `thumbnail_status='failed'`, frontend dùng `<img onError>` hiện placeholder.

---

## 6. Phục vụ — Dashboard, API, Web

### 6.1. Dashboard Streamlit (`analytics/dashboard/`)

- `db.py` — kết nối psycopg2 cached qua `st.cache_resource`, hàm `query()` tự reconnect khi connection chết, read-only autocommit.
- `Home.py` — entry, menu điều hướng.
- `pages/1_Monitoring.py` — theo dõi scraping: scrape_runs, pass rate, quarantine, chất lượng Silver.
- `pages/2_Quality.py` — outlier (IQR + bảng ngưỡng), duplicate cross-source, completeness (% null từng cột), validity (phân bố price_status). Có nút bấm chạy thẳng `silver_quality.py` từ sidebar (kèm checkbox dry-run/skip).

### 6.2. Backend FastAPI (kế hoạch — chưa code)

2 endpoint: `/api/listings/map` (filter giá/diện tích/quận/loại hình/bbox) và `/api/stats/summary`. Với cách 2 (dashboard native) sẽ thêm các endpoint thống kê — xem `KPI_DINH_HUONG.md`.

### 6.3. Frontend Next.js (kế hoạch — chưa code)

2 tab: Tra cứu (Leaflet map + marker label giá + popup "Xem tin gốc" mở tab mới) và Phân tích (dashboard). Theo quyết định mới: chart native React/Recharts thay vì nhúng Streamlit.

---

## 7. Cách vận hành (chạy lại khi có data mới)

```bash
# 1. Cào
scrapy crawl nhatot
scrapy crawl mogi

# 2. Bronze → Silver (clean + geocode + NLP tiện ích)
python -m etl.bronze_to_silver
#    tuỳ chọn: --source nhatot | --limit 500 | --batch-size 50

# 3. Quality (outlier + duplicate)
python -m etl.silver_quality
#    tuỳ chọn: --dry-run | --skip-outlier | --skip-duplicate

# 4. Silver → Gold (star schema)
cd analytics/dbt && dbt run && dbt test

# 5. Ảnh (chạy 1 lần / chỉ tin mới)
python -m etl.download_thumbnails
```

Lập lịch: GitHub Actions cron (free 2000 phút/tháng) chạy bước 1–4 hàng ngày/tuần.

---

## 8. Các điểm "ăn điểm" & rủi ro đã gặp (cho phần kết luận báo cáo)

**Ăn điểm:**
1. Medallion 3 tầng tách bạch, Bronze giữ raw JSONB để replay.
2. Data quality nhiều lớp: quarantine (không vứt data), IQR outlier, dedup cross-source, NLP tiện ích có xử lý phủ định.
3. dbt star schema + relationship tests — modern data stack.
4. Geocoding nhiều tầng có cache + fallback centroid, tiết kiệm request free tier.
5. Logging vận hành đầy đủ (`scrape_runs`) → dashboard monitoring.

**Rủi ro thực tế đã gặp:**
1. **Batdongsan bị Cloudflare chặn hoàn toàn** → phải bỏ, dựa vào Nhatot + Mogi. Bài học: khảo sát anti-bot trước khi cam kết nguồn.
2. **Hai đường build Gold không tương thích** (Python phẳng vs dbt star) → cần chọn 1, khuyến nghị dbt.
3. **`duplicate_group_id` chưa lên Gold** → KPI có thể đếm trùng.
4. Geocoding chỉ cấp phường → chấp nhận, jitter ở frontend.
5. `posted_at` có thể thiếu nhiều ở một số nguồn → KPI theo thời gian cần kiểm tra coverage.

---

## 9. Việc cần làm tiếp (gợi ý roadmap còn lại)

- [ ] Chốt 1 đường build Gold (khuyến nghị: dbt), dọn `silver_to_gold.py`.
- [x] **(ĐÃ FIX 13/06/2026)** Mang `duplicate_group_id` + cờ `is_duplicate_secondary` lên `fct_listings` (qua `stg_listings`); `listings_for_map` đã lọc `is_duplicate_secondary = FALSE` → bỏ 53 tin trùng, KPI không còn đếm trùng.
- [x] **(ĐÃ FIX 13/06/2026)** ETL `bronze_to_silver.py` nay ghi `price_per_m2` (+ `deposit_vnd`) xuống Silver; kèm `infra/db/migration_backfill_price_per_m2.sql` backfill data hiện có (idempotent, không mất dữ liệu).
- [ ] Viết endpoint FastAPI thống kê cho dashboard native.
- [ ] Port dashboard demo (đã prototype) thành component Next.js + Recharts.
- [ ] Kiểm tra coverage `posted_at`/`area_m2` để chốt KPI làm được.
- [ ] Thiết lập GitHub Actions cron cho bước 1–4.

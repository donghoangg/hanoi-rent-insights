# Phần 3 — Phân tích và thiết kế hệ thống

> Nội dung soạn để chèn vào báo cáo đồ án (chương "Phân tích và thiết kế hệ thống").
> Bám sát kiến trúc & source code thực tế của dự án HanoiRent Insights (dữ liệu thuê nhà Hà Nội).
> Cấu trúc tham chiếu báo cáo mẫu nhưng giữ đúng thiết kế hiện tại: Bronze → Silver → Gold, **không tách Gate Layer riêng** — bước kiểm duyệt chất lượng được thực hiện ngay trong pipeline thu thập (ValidationPipeline) và một module quality độc lập trên Silver (silver_quality).
>
> Ghi chú: các chỗ `[Hình …]` là vị trí chèn ảnh/sơ đồ; `[Bảng …]` là vị trí chèn bảng mô tả cột.

---

## 3.1 Nhu cầu phân tích

Dự án giải quyết bài toán thực tế của người đi thuê nhà tại Hà Nội: thị trường tin đăng phân tán trên nhiều website, không có công cụ so sánh giá theo khu vực, người thuê khó biết "giá hợp lý" ở từng phường và khó hình dung phân bố nhà trọ trên bản đồ. Từ đó, hệ thống cần trả lời được các nhóm câu hỏi phân tích sau:

**Về mặt bằng giá theo khu vực:**
- Giá thuê trung bình / trung vị ở từng phường là bao nhiêu? Phường nào đắt nhất, rẻ nhất?
- Đơn giá theo m² (đồng/m²/tháng) chênh lệch giữa các khu vực ra sao?
- "Khoảng giá hợp lý" (p25–p75) ở mỗi phường là bao nhiêu để người thuê tự đối chiếu?

**Về cơ cấu & loại hình:**
- Thị trường thuê Hà Nội chủ yếu là loại hình nào: phòng trọ, chung cư mini, chung cư, nhà nguyên căn?
- Quan hệ giữa giá và diện tích như thế nào? Thuê diện tích lớn hơn có đắt hơn tương ứng không?

**Về tiện ích & chất lượng tin:**
- Tin có điều hoà / khép kín / máy giặt có mức giá chênh lệch bao nhiêu so với tin không có?
- Mức độ đầy đủ nội thất (furnishing) ảnh hưởng thế nào đến giá?

**Về độ tin cậy dữ liệu (vận hành):**
- Mỗi lần cào thu được bao nhiêu tin, tỉ lệ tin hợp lệ (pass) là bao nhiêu, bao nhiêu tin bị cách ly do thiếu trường bắt buộc?
- Tỉ lệ tin trùng giữa các nguồn, tỉ lệ tin có giá bất thường (outlier) là bao nhiêu?

`[Hình 3.1: Cây phân tích các câu hỏi nghiệp vụ → chỉ số đo lường]`

> Gợi ý vẽ cây phân tích: gốc là "Phân tích thị trường thuê nhà Hà Nội", 3 nhánh chính (Giá theo khu vực, Cơ cấu loại hình, Tiện ích) cộng 1 nhánh phụ (Chất lượng dữ liệu), mỗi nhánh rẽ ra các KPI cụ thể đã liệt kê trong `KPI_DINH_HUONG.md`.

---

## 3.2 Phân tích và thiết kế kiến trúc toàn dự án

Hệ thống được thiết kế theo kiến trúc **Medallion (Bronze – Silver – Gold)**, một mô hình phổ biến trong Lakehouse và được áp dụng cho Data Warehouse của dự án. Toàn bộ luồng dữ liệu chia thành 5 giai đoạn, nhìn từ trái sang phải:

`[Hình 3.2: Kiến trúc tổng thể toàn dự án]`

### Giai đoạn 1 — Xác định mục tiêu thu thập dữ liệu

Sau khi khảo sát các website rao tin cho thuê, dự án chốt thu thập từ **2 nguồn chính**: **Nhatot.com (Chợ Tốt)** và **Mogi.vn**. Trường thông tin cần trích xuất gồm: tiêu đề, mô tả, giá, diện tích, số phòng ngủ/vệ sinh, loại hình, mức độ nội thất, địa chỉ (cấp tỉnh + phường theo địa giới hành chính 2 cấp từ 01/07/2025), toạ độ, ảnh đại diện và ngày đăng.

> **Lưu ý kỹ thuật quan trọng (nên nêu trong báo cáo):** kế hoạch ban đầu dự kiến cào cả **Batdongsan.com.vn** làm nguồn chính. Tuy nhiên trong quá trình triển khai, Batdongsan sử dụng **Cloudflare Bot Management cấp doanh nghiệp** chặn mọi phương pháp tự động hoá (Playwright, undetected-chromedriver, Selenium). Sau khi thử nghiệm thất bại, dự án quyết định loại bỏ nguồn này và tập trung vào Nhatot + Mogi. Đây là một rủi ro kỹ thuật thực tế và bài học: cần đánh giá khả năng chống bot của nguồn trước khi cam kết.

### Giai đoạn 2 — Trích xuất và lưu dữ liệu vào Supabase

Dùng **Scrapy** thu thập dữ liệu từ 2 nguồn rồi đổ vào **PostgreSQL trên Supabase**. Trong quá trình đổ, dữ liệu phải đi qua một chuỗi **Item Pipeline** để validate — đảm bảo tin đăng vào vùng đệm có đủ các yếu tố thiết yếu nhất (URL + địa chỉ). Tin thiếu sẽ được tách riêng để rà soát thay vì bị loại bỏ.

### Giai đoạn 3 — Thiết kế Data Warehouse (Medallion)

- **Tầng Bronze:** lưu dữ liệu thô chưa làm sạch (giữ nguyên JSON gốc). Cần một dashboard để giám sát chất lượng dữ liệu ở tầng này.
- **Tầng Silver:** lưu dữ liệu đã làm sạch, chuẩn hoá đơn vị, geocoded và đã tách các thuộc tính tiện ích. Trước khi phục vụ phân tích, dữ liệu Silver được chạy qua một bước **kiểm soát chất lượng** (phát hiện giá ngoại lai bằng IQR và phát hiện tin trùng giữa các nguồn) — gắn cờ chứ không xoá, để bảo toàn khả năng audit.
- **Tầng Gold:** gồm các bảng sẵn sàng phân tích, tổ chức theo **lược đồ ngôi sao (Star Schema)**.

Quá trình biến đổi và kiểm thử dữ liệu từ Silver lên Gold do **dbt** (data build tool) phụ trách; việc lập lịch chạy định kỳ dự kiến dùng **GitHub Actions cron**.

> **Khác biệt so với báo cáo mẫu:** dự án này **không thiết kế một tầng "Gate" riêng biệt** giữa Bronze và Silver. Lý do: với 2 nguồn và quy mô ~5.000 tin, việc kiểm duyệt được thực hiện hiệu quả ngay trong pipeline thu thập (ValidationPipeline cách ly tin thiếu trường bắt buộc) kết hợp một module quality độc lập chạy trên Silver (silver_quality). Cách này giảm số tầng trung gian, vẫn đảm bảo đủ các bài kiểm tra chất lượng.

### Giai đoạn 4 — Website tra cứu nhà cho thuê

Sau khi có dữ liệu sạch ở Silver/Gold, xây dựng website tra cứu gồm **bản đồ tương tác (Leaflet)** cho phép lọc và xem tin, click marker mở tin gốc. Backend dùng **FastAPI** (deploy Render), frontend **Next.js** (deploy Vercel).

### Giai đoạn 5 — Tạo các báo cáo / dashboard phân tích

Sau khi có dữ liệu Gold, xây dựng các dashboard phục vụ phân tích và kể chuyện dữ liệu (storytelling) về thị trường thuê nhà.

---

## 3.3 Thiết kế vùng đệm (Bronze Layer)

### 3.3.1 Thiết kế các bảng vùng đệm

Vùng Bronze gồm **ba bảng**:

**Bảng 1 — `bronze.listings_raw`:** lưu trữ tin đăng hợp lệ sau khi thu thập bằng Scrapy. Mỗi dòng giữ nguyên toàn bộ dữ liệu gốc dưới dạng `raw_payload` (kiểu JSONB) để có thể replay/debug khi cần. Khoá định danh: `(source_name, source_id)`.

`[Bảng 3.1: Cấu trúc bảng bronze.listings_raw — id, source_name, source_id, source_url, raw_payload (JSONB), scraped_at]`

**Bảng 2 — `bronze.listings_quarantine`:** lưu trữ tin bị lỗi. Tin bị coi là lỗi khi thiếu một trong các trường bắt buộc cứng: **`source_url`** hoặc **`address`**. Thay vì loại bỏ, các tin này được cách ly để rà soát và cải tiến spider sau, kèm `error_reason` (ví dụ `missing:address`) và `missing_fields`.

`[Bảng 3.2: Cấu trúc bảng bronze.listings_quarantine — thêm error_reason, missing_fields]`

**Bảng 3 — `bronze.listing_images_raw`:** lưu URL ảnh gốc, với `image_order = 0` là ảnh thumbnail chính.

### 3.3.2 Thiết kế giám sát cho vùng đệm

Để theo dõi chất lượng dữ liệu thô, mỗi lần chạy spider được ghi log vào bảng **`bronze.scrape_runs`** (thời điểm bắt đầu/kết thúc, thời lượng, tổng thu thập, số pass / cách ly / trùng, tỉ lệ pass, trạng thái). Từ đó xây dựng dashboard giám sát với:

**Các KPI chính:**
- Thời điểm thu thập lần cuối là khi nào?
- Tổng số bản ghi thu được ở lần cào gần nhất?
- Những nguồn dữ liệu đã thu thập (Nhatot, Mogi)?
- Tỉ lệ dữ liệu pass trung bình là bao nhiêu?

**Các biểu đồ cần theo dõi:**
- Tổng số tin thu được từ các nguồn theo thời gian.
- Tỉ lệ tin bị cách ly theo từng nguồn theo thời gian.
- Tỉ lệ tin pass theo từng nguồn theo thời gian.
- Tỉ lệ giá trị thiếu (null) theo từng cột quan trọng cho từng nguồn.
- Một bảng tổng quan tình hình dữ liệu của lần cào gần nhất.

`[Hình 3.3: Minh hoạ dashboard giám sát vùng đệm — trang Monitoring]`

---

## 3.4 Biến đổi và kiểm soát chất lượng (Bronze → Silver)

> Mục này thay thế vai trò của "Gate Layer" trong báo cáo mẫu. Trong dự án, việc biến đổi và kiểm soát chất lượng được thực hiện bởi module `bronze_to_silver.py` (biến đổi) và `silver_quality.py` (kiểm soát chất lượng), không tạo thành một schema riêng.

### 3.4.1 Điều kiện và nguyên tắc biến đổi

Dữ liệu từ Bronze được đọc theo lô (batch 100 tin) và biến đổi trước khi ghi vào Silver. Việc ghi dùng cơ chế **upsert** (`INSERT … ON CONFLICT DO UPDATE`) nên chạy lại nhiều lần không tạo bản ghi trùng (idempotent). Các phép biến đổi chính trên từng cột:

**Cột giá (`price_vnd`):** chuẩn hoá về đơn vị **VND/tháng**. Gắn nhãn trạng thái `price_status`: `ok` (trong khoảng 500.000 – 100.000.000), `suspect` (ngoài khoảng nhưng vẫn giữ), `missing` (rỗng/0/lỗi parse). Nhãn này là bộ lọc xuyên suốt các tầng sau — Gold chỉ lấy tin `ok`. Bổ sung tính `price_per_m2` (giá / diện tích).

**Cột tiện ích (trích từ văn bản):** quét `title + description` bằng **12 biểu thức chính quy (Regex)** để xác định 12 thuộc tính boolean: điều hoà, bình nóng lạnh, tủ lạnh, máy giặt, nội thất, wifi, bếp, khép kín, giờ giấc tự do, chung chủ, an ninh, gần chợ. Đặc biệt có **xử lý phủ định**: nếu trong 40 ký tự ngay trước từ khoá xuất hiện từ phủ định ("không", "cấm", "ko có"…) thì bỏ qua, tránh hiểu sai "không có điều hoà" thành "có điều hoà".

**Cột địa chỉ (chuẩn hoá địa giới 2 cấp):** chuẩn hoá cấp tỉnh (các biến thể "hanoi", "tp hà nội"… → "Hà Nội") và tách cấp phường (`ward`) từ chuỗi địa chỉ. Có danh sách tên quận cũ chỉ dùng để nhận diện và **bỏ qua** phần "quận" khi tách phường (vì địa giới mới không còn cấp quận).

**Toạ độ (geocoding):** áp dụng chiến lược nhiều tầng để tiết kiệm tài nguyên: (1) với Nhatot dùng lat/lng có sẵn từ API → không cần geocode; (2) tra **cache** (`silver.geocode_cache`); (3) gọi **Nominatim (OpenStreetMap, miễn phí)** cho Mogi; (4) nếu thất bại, dùng **bảng centroid phường hardcode** (~180 phường Hà Nội). Trạng thái ghi rõ `success/centroid/failed`. Hạn chế: chỉ chính xác cấp phường, nên frontend cần thêm jitter ±100m để marker không chồng lên nhau.

`[Bảng 3.3: Tổng hợp các phép biến đổi theo từng cột — cột gốc → cột sau biến đổi]`

### 3.4.2 Các bài kiểm tra chất lượng trước khi phục vụ phân tích

Module `silver_quality.py` chạy trên Silver, thực hiện 2 kiểm tra (có chế độ `--dry-run` chỉ in báo cáo, không cập nhật):

**Kiểm tra 1 — Phát hiện giá ngoại lai (IQR Outlier Detection):**
- Tính tứ phân vị `Q1, Q3` theo từng nhóm `(loại hình, nguồn)`, chỉ với nhóm có ≥ 10 tin (đủ mẫu thống kê).
- Tin có giá ngoài khoảng `[Q1 − 1.5×IQR, Q3 + 1.5×IQR]` → gắn cờ `is_price_outlier = TRUE`.
- Bổ sung ngưỡng tuyệt đối: giá < 500k hoặc > 100 triệu/tháng → ngoại lai, bất kể nhóm.

**Kiểm tra 2 — Phát hiện trùng lặp giữa các nguồn (Cross-source Duplicate):**
- Hai tin bị coi là trùng khi: **cùng phường + giá lệch ≤ 5% + diện tích lệch ≤ 5% + khác nguồn**.
- Thực hiện bằng phép **self-join** trên bảng Silver; gán cùng `duplicate_group_id` cho nhóm trùng (lấy listing_id nhỏ nhất làm id nhóm). Mục đích: nhận diện một căn được đăng đồng thời trên cả Nhatot và Mogi.

`[Hình 3.4: Minh hoạ trang Data Quality — phân bố giá, ngưỡng IQR, bảng tin trùng]`

---

## 3.5 Thiết kế vùng dữ liệu sạch (Silver Layer)

Tầng Silver gồm bảng chính **`silver.listings`** — một bảng lớn chứa toàn bộ tin đã làm sạch, chuẩn hoá đơn vị, tách tiện ích, gắn cờ chất lượng và geocoded. Đây là **nguồn sự thật (source of truth)** cho cả website tra cứu lẫn việc modeling tầng Gold.

Các nhóm cột chính của `silver.listings`:
- **Định danh:** `listing_id, source_name, source_id, source_url`.
- **Thông tin tin đăng:** `title, description, price_vnd, price_per_m2, deposit_vnd, is_negotiable, area_m2, bedrooms, bathrooms, property_type, furnishing_level`.
- **12 cột tiện ích boolean** + cột `amenities` (JSONB, để mở rộng linh hoạt).
- **Địa chỉ:** `address, province, ward, address_status`.
- **Toạ độ:** `latitude, longitude, geocode_status`.
- **Cờ chất lượng:** `is_price_outlier, duplicate_group_id, price_status`.
- **Ảnh:** `original_thumbnail_url, self_thumbnail_url, thumbnail_status`.
- **Thời gian:** `posted_at, created_at, updated_at`.

`[Bảng 3.4: Mô tả chi tiết các cột của silver.listings]`

---

## 3.6 Thiết kế vùng dữ liệu phục vụ phân tích (Gold Layer)

Tầng Gold được thiết kế theo mô hình **Star Schema**, xây dựng bằng **dbt** từ dữ liệu Silver. Gồm **1 bảng fact trung tâm + 4 bảng dimension + 1 bảng denormalized** phục vụ web app:

**Các bảng Dimension:**
- **`dim_location`** — chiều địa điểm: mỗi dòng là một tổ hợp (tỉnh, phường) duy nhất, kèm toạ độ centroid của phường (trung bình lat/lng các tin trong phường).
- **`dim_property_type`** — chiều loại hình: danh mục cố định 5 loại (phòng trọ, chung cư mini, chung cư, nhà nguyên căn, khác) kèm nhóm.
- **`dim_source`** — chiều nguồn dữ liệu (nhatot, mogi, batdongsan).
- **`dim_date`** — chiều thời gian: tạo sẵn từ 2020–2030, đủ year/quarter/month/week/is_weekend, dùng cho phân tích theo ngày đăng.

**Bảng Fact:**
- **`fct_listings`** — fact trung tâm, mỗi dòng là một tin đăng. Chứa khoá ngoại tới 4 dimension, các **measure** (giá, diện tích, giá/m², tiền cọc, số phòng), 12 cờ tiện ích, và các cột metadata chất lượng. Được làm tươi toàn bộ (full refresh) mỗi lần dbt chạy.

**Bảng phục vụ web app:**
- **`listings_for_map`** — bảng denormalized chỉ chứa tin có toạ độ hợp lệ, giá `ok` và không ngoại lai; tính sẵn `price_segment` (thấp/trung bình/cao) theo phân vị p33/p67 của từng loại hình, để web app query nhanh không cần join.

**Kiểm thử dữ liệu (dbt tests):** áp dụng test `unique`, `not_null` cho các khoá và `relationships` để kiểm tra toàn vẹn khoá ngoại của fact tới các dimension — chứng minh hiểu biết về data testing trong modern data stack.

`[Hình 3.5: Sơ đồ Star Schema — fct_listings ở trung tâm, 4 dimension xung quanh]`

> **Ghi chú triển khai (nên thống nhất trước khi viết phần Xây dựng hệ thống):** hiện trong mã nguồn tồn tại song song hai cách build Gold — một bằng dbt (star schema, là cách chính thức) và một bằng Python (`silver_to_gold.py`, theo mô hình bảng phẳng cũ). Dự án sẽ chọn dbt làm chuẩn và dọn bỏ phiên bản Python để tránh xung đột.

---

## 3.7 Phân tích website

Website được thiết kế với hai mục đích: **tra cứu nhà cho thuê** trên bản đồ và **xem dashboard phân tích** thị trường. Do là phần mở rộng nên kiến trúc được giữ gọn:

**Backend:**
- Ngôn ngữ: Python; Framework: **FastAPI** (hiệu năng cao, tự sinh tài liệu Swagger).
- Server: **Uvicorn** (ASGI).
- Truy cập DB: psycopg2 / SQLAlchemy tới PostgreSQL (Supabase).
- Validate dữ liệu: Pydantic.

**Frontend:**
- Framework: **Next.js** (React) + **TailwindCSS**.
- Bản đồ: **React-Leaflet** + OpenStreetMap tiles (miễn phí, không cần API key) + marker clustering.
- Biểu đồ dashboard: render native bằng Recharts/Chart.js (không nhúng iframe), đảm bảo giao diện đồng nhất giữa hai tab.

**Các tính năng chính (gợi ý vẽ Use case):**
- Người dùng lọc tin theo loại hình, khoảng giá, diện tích, phường, tiện ích.
- Xem tin trên bản đồ; click marker mở popup (ảnh, giá, địa chỉ) và nút "Xem tin gốc" mở tab mới sang website nguồn.
- Chuyển sang tab Dashboard để xem các phân tích: giá theo phường, so sánh phường, premium tiện ích, phân bố giá…

`[Hình 3.6: Sơ đồ Use case cho người tìm nhà]`
`[Hình 3.7: Activity Diagram — luồng tra cứu và lọc tin]`
`[Hình 3.8: Sequence Diagram — frontend → FastAPI → Gold layer]`

---

## Phụ lục — Bảng ánh xạ với báo cáo mẫu (để bạn tự đối chiếu khi viết)

| Mục báo cáo mẫu (tuyển dụng) | Tương ứng trong dự án (thuê nhà) | Khác biệt cần lưu ý |
|---|---|---|
| 9 nguồn tuyển dụng | 2 nguồn: Nhatot + Mogi | Batdongsan bị Cloudflare chặn, đã loại |
| Gate Layer riêng | Không tách Gate | Logic gộp vào ValidationPipeline + silver_quality |
| Cột job_title, salary, location… | Cột price, area, ward, property_type, amenities… | Domain khác nhưng cùng kỹ thuật Regex/chuẩn hoá |
| Airflow điều phối | GitHub Actions cron | Đơn giản hơn, đủ cho scope đồ án |
| dbt + star schema | dbt + star schema | Giống nhau |
| FastAPI + React + Vite | FastAPI + Next.js | Đều React, khác build tool |
| 6 dimension + 1 fact | 4 dimension + 1 fact + 1 map | Quy mô nhỏ hơn, thêm bảng phục vụ map |

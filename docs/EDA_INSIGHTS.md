# Phân tích khám phá dữ liệu (EDA) — HanoiRent Insights

> Tài liệu phân tích khám phá trên `silver.listings` (snapshot ngày 13/06/2026, **1.945 tin**).
> Mục đích: rút ra các insight thị trường thuê nhà Hà Nội làm nền cho việc thiết kế **dashboard phân tích (tầng Gold)** và viết chương "Kết quả phân tích" trong báo cáo đồ án.
> Mọi KPI về giá được tính trên **tập đã làm sạch**: `price_status = 'ok'` **AND** `is_price_outlier = FALSE`, và **đã khử trùng cross-source** (mỗi `duplicate_group_id` chỉ giữ 1 đại diện) → còn **1.595 tin**.

---

## 0. Tóm tắt nhanh (executive summary)

- Thị trường thuê Hà Nội trong dữ liệu **áp đảo bởi phòng trọ (72%)**; chung cư và nhà nguyên căn mỗi loại ~13–15%.
- **Giá thuê median toàn thị trường ≈ 4 triệu/tháng**, diện tích median ≈ 28 m². Phòng trọ median **3 triệu**, chung cư **6,5 triệu**, nhà nguyên căn **11 triệu**.
- **Chênh lệch giá theo khu vực rất rõ**: cùng là phòng trọ, phường đắt nhất (Dịch Vọng Hậu ~5 tr) cao gấp **2,5 lần** phường rẻ nhất (Tứ Liên ~2 tr) — chênh 150%.
- **Tiện ích kéo giá lên ~33%**: phòng trọ có tủ lạnh / máy giặt / wifi có median 4 tr so với 3 tr ở phòng không có.
- **Cảnh báo chất lượng dữ liệu** (ảnh hưởng trực tiếp KPI nào làm được): `ngày đăng` chỉ phủ 38% (chỉ Nhatot có), `số phòng ngủ` 24%, `nội thất`/`tiền cọc` hiện **trống 100%**. Tỉ lệ outlier giá 15,3% (chủ yếu là phòng trọ Mogi ghi nhầm đơn vị giá).

---

## 1. Tổng quan & độ phủ dữ liệu

Snapshot gồm **1.945 tin** từ 2 nguồn: **Mogi (1.199)** và **Nhatot (746)**. Geocoding gần như tuyệt đối: 1.943/1.945 tin có toạ độ (99,9%) — nhờ Nhatot trả sẵn lat/lng và Nominatim + centroid phường xử lý tốt phần Mogi.

![Độ phủ dữ liệu các trường](eda_charts/01_coverage.png)

**Đọc biểu đồ này trước khi tin bất kỳ KPI nào.** Mức độ phủ quyết định KPI nào có ý nghĩa:

| Trường | Độ phủ | Hệ quả cho phân tích |
|--------|--------|----------------------|
| Giá, Diện tích | 100% | KPI giá & price/m² **dùng tốt** |
| Phường, Toạ độ | 99,9% | KPI theo khu vực & bản đồ **dùng tốt** |
| Ngày đăng (`posted_at`) | **38,4%** | Chỉ Nhatot có → **KPI theo thời gian chưa làm được**, ghi "định hướng tương lai" |
| Số phòng ngủ / WC | 24% / 17% | Chỉ phân tích định tính, **không đưa vào KPI chính** |
| Nội thất (`furnishing_level`) | **0%** | Cột tồn tại nhưng **chưa điền** → KPI furnishing (C2) tạm hoãn |
| Tiền cọc (`deposit_vnd`) | **0%** | Chưa khai thác được |
| `price_per_m2` | **0%** | DB chưa điền — EDA này **tự tính** từ `price/area` |

> **Khuyến nghị pipeline:** ba cột `price_per_m2`, `furnishing_level`, `deposit_vnd` đang trống. `price_per_m2` nên được tính sẵn ở `bronze_to_silver` (hoặc trong dbt staging) vì KPI A3 cần nó. `furnishing_level` cần spider/NLP điền thì mới làm được KPI C2.

---

## 2. Chất lượng dữ liệu — outlier & trùng lặp

**Outlier giá: 297 tin (15,3%).** Phân rã cho thấy **249/297 là phòng trọ từ Mogi** — phần lớn là tin ghi nhầm đơn vị giá (giá trải từ 1 triệu tới 999 triệu/tháng cho một phòng trọ). Đây là minh chứng tốt cho báo cáo về vai trò của bước `silver_quality.py` (IQR + hard limit): nếu không lọc, median và mean bị kéo lệch nghiêm trọng (mean toàn tập **11,9 tr** rơi về **5,0 tr** sau khi lọc outlier).

**Trùng cross-source: 79 tin thuộc 26 nhóm.** Đây là các căn được đăng đồng thời trên cả Nhatot và Mogi. Khi khử trùng (giữ 1 đại diện/nhóm), tập sạch giảm từ 1.648 → **1.595 tin** (bỏ 53 tin trùng).

> ⚠️ **Điểm cần fix trước khi lên dashboard (đã nêu trong `KPI_DINH_HUONG.md`):** cờ `duplicate_group_id` hiện **chỉ có ở Silver, chưa mang lên `fct_listings`**. Nếu dashboard query thẳng Gold mà không khử trùng, mọi KPI `count` và trung bình sẽ đếm trùng 53 tin này. EDA này đã khử trùng thủ công; **dashboard cần `DISTINCT ON (duplicate_group_id)`** hoặc thêm cột `is_duplicate` vào fact.

---

## 3. Cơ cấu thị trường theo loại hình

![Cơ cấu loại hình](eda_charts/02_property_type.png)

Thị trường thuê Hà Nội (theo dữ liệu thu thập) **chủ yếu là phòng trọ — 72%** (1.148 tin), phản ánh đúng nhu cầu thuê của sinh viên và người đi làm thu nhập trung bình. Chung cư chiếm 14,7% (235 tin) và nhà nguyên căn 13,3% (212 tin). Hệ quả cho dashboard: **phòng trọ là phân khúc đủ mẫu nhất để phân tích theo phường**; chung cư/nhà nguyên căn chỉ nên phân tích ở cấp toàn thành phố hoặc cụm phường.

---

## 4. Mặt bằng giá theo loại hình

![Phân bố giá theo loại hình](eda_charts/03_price_boxplot.png)

| Loại hình | Số tin | Median | p25 | p75 | Mean |
|-----------|--------|--------|-----|-----|------|
| Phòng trọ | 1.148 | **3,0 tr** | 3,0 | 4,0 | 3,5 |
| Chung cư | 235 | **6,5 tr** | 4,8 | 9,5 | 7,4 |
| Nhà nguyên căn | 212 | **11,0 tr** | 7,0 | 15,0 | 10,9 |

Phòng trọ có dải giá hẹp và tập trung (p25–p75 chỉ 3–4 tr), trong khi nhà nguyên căn dao động rất rộng (7–15 tr) — phù hợp với việc "nhà nguyên căn" gộp nhiều quy mô khác nhau. Median luôn ≤ mean ở cả 3 loại → phân phối **lệch phải** (vài tin giá cao kéo trung bình lên), khẳng định **nên dùng median thay vì mean** cho mọi KPI giá trên dashboard.

### Đơn giá theo m²

![Giá theo m²](eda_charts/08_price_per_m2.png)

Xét trên đơn giá đồng/m²/tháng: **nhà nguyên căn đắt nhất (~252 nghìn/m²)**, chung cư (~160k/m²), phòng trọ rẻ nhất (~133k/m²). Điều này hơi phản trực giác (nhà to thường rẻ/m²) nhưng hợp lý ở đây vì "nhà nguyên căn" cho thuê thường ở vị trí mặt phố/kinh doanh nên đơn giá cao.

---

## 5. Chênh lệch giá theo khu vực (insight lõi)

![Top phường đắt/rẻ](eda_charts/04_top_wards.png)

Đây là insight trả lời trực tiếp bài toán gốc của dự án. Xét riêng **phòng trọ** (loại đủ mẫu nhất, 39/166 phường có ≥10 tin):

- **Đắt nhất:** Dịch Vọng Hậu, Trung Hòa, Nhật Tân, Dịch Vọng (~5 tr) — đều là khu Cầu Giấy/Tây Hồ gần trường đại học và trung tâm.
- **Rẻ nhất:** Tứ Liên (2 tr), Khương Trung (2,6 tr), rồi nhóm 3 tr (Mộ Lao, Khương Đình, Thanh Liệt…) — khu xa trung tâm hơn.
- **Chênh lệch 2,5 lần** giữa phường đắt nhất và rẻ nhất cho cùng một loại hình → khẳng định "vị trí quyết định giá thuê".

Về đơn giá/m², các phường đắt nhất là Bưởi, Dịch Vọng Hậu, Yên Hòa (~165 nghìn/m²) — trùng khớp với nhóm phường có median cao, củng cố độ tin cậy của insight.

> **Lưu ý cho dashboard:** địa giới 2 cấp (166 phường) **khá mảnh** — chỉ 39 phường đủ ≥10 tin phòng trọ. Dashboard nên (a) đặt ngưỡng tối thiểu `HAVING COUNT(*) >= 10` để median không nhiễu, và (b) cân nhắc thêm cột **cụm phường** để fallback cho các phường ít tin.

---

## 6. Quan hệ giá – diện tích

![Scatter giá-diện tích](eda_charts/05_price_area_scatter.png)

Tương quan giá–diện tích **dương vừa phải toàn thị trường (Pearson r = 0,57)** nhưng **khác hẳn theo loại hình**:

- **Chung cư: r = 0,83** — quan hệ rất chặt, giá gần như tỉ lệ thuận diện tích (thị trường định giá chuẩn theo m²).
- **Phòng trọ: r = 0,32** — quan hệ yếu, vì giá phòng trọ phụ thuộc **vị trí và tiện ích** nhiều hơn diện tích.
- **Nhà nguyên căn: r = 0,23** — yếu nhất, do giá bị chi phối bởi vị trí (mặt phố vs trong ngõ) và mục đích sử dụng.

Insight cho người thuê: với phòng trọ, "thuê to hơn chưa chắc đắt hơn nhiều" — nên so sánh theo khu vực + tiện ích thay vì chỉ nhìn diện tích.

---

## 7. Ảnh hưởng của tiện ích lên giá (điểm khác biệt)

![Premium tiện ích](eda_charts/06_amenity_premium.png)

Nhờ 12 cột tiện ích boolean đã tách ở Silver (qua NLP regex), ta phân tích được "premium" của từng tiện ích — phân tích mà ít đồ án làm được. Trên phòng trọ:

| Tiện ích | Median không có | Median có | Premium |
|----------|-----------------|-----------|---------|
| Tủ lạnh | 3,0 tr | 4,0 tr | **+33%** |
| Máy giặt | 3,0 tr | 4,0 tr | **+33%** |
| Wifi | 3,0 tr | 4,0 tr | **+33%** |
| Giờ tự do | 3,0 tr | 3,2 tr | +7% |
| Điều hoà / Nóng lạnh | 3,0 tr | 3,0 tr | ~0% |
| Khép kín | 3,4 tr | 3,0 tr | **−12%** (xem ghi chú) |

Nhóm "đồ điện gia dụng" (tủ lạnh, máy giặt, wifi) đi kèm premium rõ +33% — thường là dấu hiệu của **phòng full nội thất**. Điều hoà/nóng lạnh không tạo premium vì đã gần như phổ biến (mặc định).

> **Hai cảnh báo khi diễn giải (quan trọng cho báo cáo):**
> 1. **Đây là tương quan, không phải nhân quả.** Phòng có máy giặt thường cũng to/mới hơn — không nên nói "máy giặt làm giá tăng 33%". Muốn chặt hơn phải so trong cùng phường + cùng khoảng diện tích.
> 2. **Premium âm của "khép kín" là ảo giác do median bị lượng tử hoá.** Giá phòng trọ dồn cục ở mốc tròn (125 tin đúng 2 tr, rất nhiều tin đúng 3 tr) nên median nhảy bậc, kém nhạy. Nên dùng **mean trong cùng phường** hoặc kiểm định thống kê thay vì so median thô cho tiện ích này.

---

## 8. Phân khúc giá phòng trọ

![Phân khúc giá phòng trọ](eda_charts/07_price_segment.png)

Phần lớn phòng trọ rơi vào khoảng **2–3 triệu (38%)** và **3–4 triệu (26%)**. Phân khúc trên 5 triệu rất hiếm (chỉ 26 tin). Đây là "vùng giá thị trường" để người thuê tự đối chiếu: một phòng trọ Hà Nội điển hình thuê **2–4 triệu/tháng**.

---

## 9. Khuyến nghị cho Dashboard tầng Gold

Dựa trên EDA, các view nên đưa vào dashboard phân tích (ưu tiên theo độ "ăn điểm" + độ phủ dữ liệu đủ):

| Ưu tiên | View | KPI nguồn | Đủ dữ liệu? |
|---------|------|-----------|-------------|
| ⭐⭐⭐ | Metric cards (median giá, giá/m², phường đắt/rẻ) | A1, A3 | ✅ |
| ⭐⭐⭐ | Top phường đắt–rẻ (bar ngang, lọc theo loại hình) | A2 | ✅ (chỉ phòng trọ đủ mẫu) |
| ⭐⭐⭐ | Bảng "giá hợp lý" p25–median–p75 theo phường | B3 | ✅ |
| ⭐⭐⭐ | Premium tiện ích (grouped bar) | C1 | ✅ (kèm cảnh báo diễn giải) |
| ⭐⭐ | Boxplot giá theo loại hình | A4 | ✅ |
| ⭐⭐ | Scatter giá–diện tích + hệ số tương quan | B2 | ✅ |
| ⭐⭐ | Cơ cấu loại hình & phân khúc giá | B1 | ✅ |
| ⭐ | Bản đồ nhiệt giá theo phường (choropleth) | A1, A3 | ✅ (cần GeoJSON ranh giới phường) |
| ⏸ | Furnishing vs giá | C2 | ❌ cột trống — hoãn |
| ⏸ | Trend giá theo thời gian | D1, D2 | ❌ posted_at chỉ 38% — hoãn |

**3 việc nên fix ở pipeline trước khi dashboard chính thức:**

1. **Mang `duplicate_group_id` lên `fct_listings`** → tránh đếm trùng 53 tin cross-source trong mọi KPI.
2. **Điền `price_per_m2`** ở tầng Silver hoặc dbt staging (hiện trống, EDA phải tự tính).
3. **Đặt ngưỡng `HAVING COUNT(*) >= 10`** cho mọi KPI theo phường; cân nhắc thêm cột cụm phường để fallback khi phường ít tin (do địa giới 2 cấp mảnh).

---

## Phụ lục — Phương pháp

- **Nguồn:** `silver.listings`, snapshot 13/06/2026, export qua `etl/export_silver.py`.
- **Tập phân tích KPI giá:** `price_status='ok' AND is_price_outlier=FALSE`, khử trùng theo `duplicate_group_id` (giữ `MIN(listing_id)` mỗi nhóm) → n = 1.595.
- **Giá hiển thị:** median (trung vị) thay vì mean, do phân phối lệch phải.
- **Ngưỡng mẫu:** chỉ xếp hạng phường có ≥10 tin/loại hình.
- **Biểu đồ:** sinh bằng matplotlib, lưu tại `docs/eda_charts/`. Script phân tích có thể tái lập từ cùng file CSV.

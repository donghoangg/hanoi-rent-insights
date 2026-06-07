# Định hướng KPI — Market Insights (Giá & Khu vực)

> Tài liệu đề xuất bộ KPI phân tích thị trường nhà cho thuê Hà Nội, build trên Gold star schema (`gold.fct_listings` + dim tables).
> Mỗi KPI kèm: ý nghĩa → công thức SQL chạy thẳng trên Gold → gợi ý chart → lưu ý/cạm bẫy.
>
> Phạm vi tài liệu này: **chỉ nhóm Market Insights** (theo lựa chọn). Data Quality & Operational KPI tách riêng.

---

## 0. Kiểm tra coverage TRƯỚC khi tính KPI

KPI chỉ có ý nghĩa nếu cột nguồn đủ đầy. Chạy query này đầu tiên để biết KPI nào dùng được, KPI nào cần ghi chú "coverage thấp" trong báo cáo.

```sql
SELECT
    COUNT(*)                                                          AS total,
    ROUND(100.0 * COUNT(price_vnd)        / COUNT(*), 1)              AS pct_has_price,
    ROUND(100.0 * COUNT(area_m2)          / COUNT(*), 1)              AS pct_has_area,
    ROUND(100.0 * COUNT(posted_at)        / COUNT(*), 1)             AS pct_has_date,
    ROUND(100.0 * COUNT(*) FILTER (WHERE area_m2 > 0)  / COUNT(*),1)  AS pct_area_positive,
    ROUND(100.0 * COUNT(*) FILTER (WHERE geocode_status IN ('success','centroid')) / COUNT(*),1) AS pct_geocoded,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_price_outlier) / COUNT(*),1) AS pct_outlier
FROM gold.fct_listings;
```

Nguyên tắc xuyên suốt: **mọi KPI giá đều lọc `price_status = 'ok' AND is_price_outlier = FALSE`** để outlier không kéo lệch trung bình.

> ⚠️ **Cạm bẫy duplicate cross-source:** `silver.listings.duplicate_group_id` đánh dấu tin trùng giữa các nguồn, nhưng cờ này **chưa được mang lên `fct_listings`**. Hệ quả: 1 căn đăng ở 2 nguồn bị đếm 2 lần → mọi KPI `listing_count` và trung bình giá hơi lệch. **Khuyến nghị fix:** thêm cột `is_duplicate`/`duplicate_group_id` vào `fct_listings`, và trong các KPI count thì lọc về 1 đại diện mỗi nhóm (vd `DISTINCT ON (duplicate_group_id)`). Trước khi fix, ghi rõ limitation này trong báo cáo.

---

## Nhóm A — Giá theo khu vực (lõi của đồ án)

### A1. Giá thuê trung bình & trung vị theo phường + loại hình

**Ý nghĩa:** KPI nền tảng — trả lời "thuê phòng trọ ở phường X tốn bao nhiêu/tháng". Median quan trọng hơn mean vì giá thuê lệch phải (vài tin cao kéo mean lên).

```sql
SELECT
    l.ward,
    pt.property_type_name,
    COUNT(*)                                                          AS so_tin,
    ROUND(AVG(f.price_vnd))                                           AS gia_tb,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_vnd)          AS gia_median,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.price_vnd)         AS p25,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.price_vnd)         AS p75
FROM gold.fct_listings f
JOIN gold.dim_location      l  ON f.location_key      = l.location_key
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
GROUP BY l.ward, pt.property_type_name
HAVING COUNT(*) >= 10            -- chỉ lấy phường đủ mẫu thống kê
ORDER BY l.ward, gia_median DESC;
```

**Chart:** bảng có thể sort + heatmap (ward × property_type, màu theo median). **Đây cũng chính là nội dung `gold.price_stats_by_ward`** nếu bạn rebuild bảng đó.

**Lưu ý:** `HAVING COUNT(*) >= 10` rất cần — địa giới phường (2 cấp) mảnh hơn quận cũ, nhiều phường sẽ < 10 tin và median sẽ "nhiễu". Cân nhắc thêm 1 cột nhóm cụm phường để fallback khi mẫu nhỏ.

---

### A2. Top 10 phường đắt nhất & rẻ nhất (theo median, chuẩn hoá theo loại hình)

**Ý nghĩa:** Insight "ăn điểm" trực tiếp — bảng xếp hạng khu vực. Phải so cùng 1 loại hình, nếu không sẽ so phòng trọ với chung cư (vô nghĩa).

```sql
-- Đổi 'phong_tro' sang loại hình muốn xếp hạng
WITH ranked AS (
    SELECT
        l.ward,
        COUNT(*)                                                       AS so_tin,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_vnd)       AS median_price
    FROM gold.fct_listings f
    JOIN gold.dim_location      l  ON f.location_key      = l.location_key
    JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
    WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
      AND pt.property_type_code = 'phong_tro'
    GROUP BY l.ward
    HAVING COUNT(*) >= 10
)
(SELECT 'dat_nhat'  AS nhom, ward, so_tin, median_price FROM ranked ORDER BY median_price DESC LIMIT 10)
UNION ALL
(SELECT 're_nhat'   AS nhom, ward, so_tin, median_price FROM ranked ORDER BY median_price ASC  LIMIT 10);
```

**Chart:** horizontal bar chart, 2 cụm (đắt nhất màu đỏ, rẻ nhất màu xanh).

---

### A3. Đơn giá thuê theo m² (price/m²) theo phường

**Ý nghĩa:** So sánh công bằng giữa các khu vực bất kể diện tích — "đồng/m²/tháng". Đây là metric chuẩn để nói "Cầu Giấy đắt thứ N Hà Nội".

```sql
SELECT
    l.ward,
    COUNT(*) FILTER (WHERE f.price_per_m2 IS NOT NULL)               AS so_tin_co_dien_tich,
    ROUND(AVG(f.price_per_m2))                                       AS gia_m2_tb,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_per_m2)      AS gia_m2_median
FROM gold.fct_listings f
JOIN gold.dim_location l ON f.location_key = l.location_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
  AND f.price_per_m2 IS NOT NULL
GROUP BY l.ward
HAVING COUNT(*) FILTER (WHERE f.price_per_m2 IS NOT NULL) >= 10
ORDER BY gia_m2_median DESC;
```

**Chart:** choropleth-style bar (xếp hạng phường) hoặc bản đồ tô màu phường theo price/m².

**Lưu ý coverage:** phòng trọ hay thiếu `area_m2` → price/m² chỉ tính được trên tập con. **Bắt buộc** hiển thị `so_tin_co_dien_tich` cạnh KPI để người đọc biết độ phủ. Nếu `pct_area_positive` từ mục 0 dưới ~60%, ghi chú rõ "KPI này dựa trên X% tin có diện tích".

---

### A4. Phân bố giá theo loại hình (boxplot data)

**Ý nghĩa:** Cho thấy độ dao động giá, không chỉ điểm trung bình. Phát hiện loại hình nào "giá loạn" (range rộng).

```sql
SELECT
    pt.property_type_name,
    COUNT(*)                                                          AS so_tin,
    MIN(f.price_vnd)                                                  AS gia_min,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.price_vnd)         AS q1,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY f.price_vnd)         AS median,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.price_vnd)         AS q3,
    MAX(f.price_vnd)                                                  AS gia_max
FROM gold.fct_listings f
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
GROUP BY pt.property_type_name
ORDER BY median;
```

**Chart:** boxplot (Altair/Plotly) — trục x loại hình, trục y giá. Một trong những chart trực quan nhất cho hội đồng.

---

## Nhóm B — Cấu trúc & phân khúc thị trường

### B1. Cơ cấu nguồn cung theo loại hình & phân khúc giá

**Ý nghĩa:** "Thị trường thuê Hà Nội chủ yếu là gì" — tỉ trọng phòng trọ vs chung cư mini vs chung cư. Kết hợp `price_segment` (đã có trong `listings_for_map`) để thấy nguồn cung tập trung phân khúc nào.

```sql
SELECT
    pt.property_type_name,
    m.price_segment,                         -- 'thap' | 'trung_binh' | 'cao'
    COUNT(*)                                                          AS so_tin,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)               AS pct_thi_truong
FROM gold.listings_for_map m
JOIN gold.fct_listings      f  ON m.listing_key       = f.listing_key
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
GROUP BY pt.property_type_name, m.price_segment
ORDER BY so_tin DESC;
```

**Chart:** stacked bar (loại hình × phân khúc) hoặc treemap. Pie chart nếu chỉ xem cơ cấu loại hình.

---

### B2. Giá vs Diện tích (scatter + đường hồi quy)

**Ý nghĩa:** Quan hệ giá-diện tích, và điểm "lệch" (cùng diện tích nhưng giá rất khác → khu vực/tiện ích quyết định). Nền cho insight "thuê to chưa chắc đắt hơn nhiều".

```sql
SELECT
    f.area_m2,
    f.price_vnd,
    pt.property_type_name,
    l.ward
FROM gold.fct_listings f
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
JOIN gold.dim_location      l  ON f.location_key      = l.location_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
  AND f.area_m2 BETWEEN 8 AND 200     -- cắt đuôi vô lý còn sót
  AND f.price_vnd IS NOT NULL;
```

**Chart:** scatter, màu theo loại hình, kèm trendline. Tính thêm hệ số tương quan Pearson ở Python (`df['area_m2'].corr(df['price_vnd'])`) để báo cáo có con số.

---

### B3. "Mức giá hợp lý" theo phường (khoảng p25–p75)

**Ý nghĩa:** Trả lời trực tiếp bài toán gốc của dự án — "giá hợp lý ở phường này là bao nhiêu". Dùng khoảng liên tứ phân vị (p25–p75) làm "vùng giá thị trường", tin dưới p25 = rẻ bất thường (cần xem kỹ), trên p75 = cao.

```sql
SELECT
    l.ward,
    pt.property_type_name,
    COUNT(*)                                                          AS so_tin,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.price_vnd)         AS gia_hop_ly_tu,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.price_vnd)         AS gia_hop_ly_den
FROM gold.fct_listings f
JOIN gold.dim_location      l  ON f.location_key      = l.location_key
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
GROUP BY l.ward, pt.property_type_name
HAVING COUNT(*) >= 10;
```

**Chart:** bảng tra cứu, hoặc error-bar chart (điểm = median, thanh = p25→p75). KPI này có thể nhúng vào popup web app sau này.

---

## Nhóm C — Ảnh hưởng tiện ích lên giá (điểm khác biệt, dễ "ăn điểm")

### C1. Premium giá theo tiện ích

**Ý nghĩa:** "Có điều hoà / khép kín / máy giặt thì đắt hơn bao nhiêu %". Đây là phân tích ít đồ án làm được vì cần tiện ích đã tách boolean — bạn đã có sẵn 12 cột boolean trong `fct_listings`, rất đáng khai thác.

```sql
-- Ví dụ với điều hoà; lặp cho từng tiện ích quan tâm
SELECT
    pt.property_type_name,
    f.has_air_conditioner,
    COUNT(*)                                                          AS so_tin,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_vnd)          AS median_price
FROM gold.fct_listings f
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
GROUP BY pt.property_type_name, f.has_air_conditioner
ORDER BY pt.property_type_name, f.has_air_conditioner;
```

So sánh median của nhóm `TRUE` vs `FALSE` trong cùng loại hình → ra "premium %". Lặp cho `is_self_contained` (khép kín), `has_washing_machine`, `free_hours` (giờ giấc tự do)...

**Chart:** grouped bar (loại hình × có/không tiện ích), hoặc bảng % premium.

**Lưu ý:** đây là tương quan, **không phải nhân quả** — phòng có điều hoà thường cũng to/mới hơn. Trong báo cáo nên nói "tin có điều hoà có median cao hơn X%", tránh khẳng định "điều hoà làm giá tăng X%". Muốn chặt hơn thì so trong cùng phường + cùng khoảng diện tích.

---

### C2. Mức độ "đầy đủ nội thất" (furnishing_level) vs giá

**Ý nghĩa:** `furnishing_level` (bare/partial/full/luxury) là biến thứ bậc — xem giá tăng theo mức độ trang bị.

```sql
SELECT
    f.furnishing_level,
    pt.property_type_name,
    COUNT(*)                                                          AS so_tin,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_vnd)          AS median_price
FROM gold.fct_listings f
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
  AND f.furnishing_level IS NOT NULL
GROUP BY f.furnishing_level, pt.property_type_name
ORDER BY pt.property_type_name,
    CASE f.furnishing_level
        WHEN 'bare' THEN 1 WHEN 'partial' THEN 2
        WHEN 'full' THEN 3 WHEN 'luxury' THEN 4 END;
```

**Chart:** line/bar theo bậc furnishing trong từng loại hình.

---

## Nhóm D — KPI theo thời gian (ĐIỀU KIỆN: cần `posted_at` đủ)

> ⚠️ **Chỉ làm nếu mục 0 cho thấy `pct_has_date` đủ cao (gợi ý ≥ 60%).** `fct_listings.date_key` join theo `posted_at`; nếu nhiều tin thiếu ngày đăng thì các KPI dưới sẽ rỗng/lệch. Nếu data mới cào < 1 tháng, KPI trend chưa có ý nghĩa — ghi rõ trong báo cáo là "định hướng tương lai".

### D1. Số tin đăng mới theo tuần/tháng

```sql
SELECT
    d.year, d.month, d.month_name,
    COUNT(*)                                                          AS so_tin_moi
FROM gold.fct_listings f
JOIN gold.dim_date d ON f.date_key = d.date_key
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;
```

### D2. Trend median giá theo tháng (theo loại hình)

```sql
SELECT
    d.year, d.month,
    pt.property_type_name,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_vnd)          AS median_price,
    COUNT(*)                                                          AS so_tin
FROM gold.fct_listings f
JOIN gold.dim_date          d  ON f.date_key          = d.date_key
JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
WHERE f.price_status = 'ok' AND f.is_price_outlier = FALSE
GROUP BY d.year, d.month, pt.property_type_name
HAVING COUNT(*) >= 10
ORDER BY d.year, d.month;
```

**Chart:** multi-line chart (1 line/loại hình theo tháng).

---

## Bảng tổng hợp ưu tiên

| # | KPI | Nhóm | Độ "ăn điểm" | Phụ thuộc coverage | Chart gợi ý |
|---|-----|------|--------------|--------------------|-------------|
| A1 | Giá TB/median theo phường × loại hình | Giá–khu vực | ⭐⭐⭐ | price | Heatmap / bảng |
| A2 | Top 10 phường đắt–rẻ | Giá–khu vực | ⭐⭐⭐ | price | Horizontal bar |
| A3 | Price/m² theo phường | Giá–khu vực | ⭐⭐⭐ | area (một phần) | Bản đồ tô màu |
| A4 | Phân bố giá theo loại hình | Giá–khu vực | ⭐⭐ | price | Boxplot |
| B1 | Cơ cấu nguồn cung × phân khúc | Cấu trúc | ⭐⭐ | — | Stacked bar / treemap |
| B2 | Giá vs diện tích | Cấu trúc | ⭐⭐ | area | Scatter + trendline |
| B3 | Khoảng giá hợp lý p25–p75 | Cấu trúc | ⭐⭐⭐ | price | Error-bar / bảng tra |
| C1 | Premium giá theo tiện ích | Tiện ích | ⭐⭐⭐ | amenity flags | Grouped bar |
| C2 | Furnishing vs giá | Tiện ích | ⭐⭐ | furnishing | Line/bar |
| D1 | Số tin mới theo thời gian | Thời gian | ⭐ | **posted_at** | Line |
| D2 | Trend median giá theo tháng | Thời gian | ⭐⭐ | **posted_at** | Multi-line |

**Đề xuất chọn cho báo cáo (nếu phải gọn):** A1, A2, A3, B3, C1 — đủ trả lời trọn vẹn bài toán gốc ("giá hợp lý theo khu vực") + có 1 phân tích khác biệt (tiện ích) mà ít đồ án làm.

---

## 3 việc nên fix ở pipeline để KPI vững hơn

1. **Mang `duplicate_group_id` lên `fct_listings`** (hiện chỉ có ở Silver) → tránh đếm trùng cross-source trong mọi KPI count/average. Đây là lỗi lệch số liệu nghiêm trọng nhất hiện tại.
2. **Thêm cột nhóm cụm phường** (vd `area_cluster`) vào `dim_location` để fallback khi 1 phường < 10 tin — nếu không, KPI theo phường sẽ rỗng ở nhiều khu do địa giới 2 cấp khá mảnh.
3. **Kiểm tra & ghi log coverage `posted_at` và `area_m2`** trong dashboard Quality → quyết định KPI nhóm D có làm được không, và đặt nhãn coverage cho A3 (price/m²).

---

## Định hướng Dashboard (tab "Phân tích" trên web)

> Quyết định kiến trúc (đã chốt): **Cách 2 — chart native trong Next.js** (không nhúng Streamlit iframe).
> Web có 2 tab: **Tra cứu** (map Leaflet + filter + popup) và **Phân tích** (dashboard insights, tương tác được).
> Tab Phân tích vẽ chart bằng **Recharts hoặc Chart.js** ngay trong React, lấy data qua endpoint FastAPI đọc Gold layer.
>
> ⚠️ **Lệch với kế hoạch gốc cần cập nhật:** `KE_HOACH_DU_AN.md` hiện ghi `dashboard.tsx` là "Embedded Streamlit" (iframe) và liệt kê Streamlit Cloud trong bảng deployment. Theo cách 2, **bỏ Streamlit khỏi stack** — giảm 1 dịch vụ, không vượt free tier (FastAPI vẫn trên Render, Next.js trên Vercel). Cần sửa lại mục 3.4, 8, 9, 11, 12 của kế hoạch cho khớp.

### Các view trong tab Phân tích

Đã prototype demo (HTML tương tác) các view sau — bản thật sẽ port thành component React:

| View | Mô tả | KPI nguồn | Chart |
|------|-------|-----------|-------|
| Metric cards | Tổng tin, giá median, giá/m², phường đắt/rẻ nhất — cập nhật theo filter | A1, A3 | Stat cards |
| Top phường theo giá | Bar ngang xếp hạng phường theo median, đổi theo loại hình | A1, A2 | Horizontal bar |
| **So sánh 2 phường** | Chọn phường A/B → ra ngay "rẻ/đắt hơn X%", giá/m², DT TB | A1, A3 | Card đối chiếu |
| Phân bố khoảng giá | Histogram số tin theo bậc giá (<2tr, 2-3tr...) | A4 | Bar |
| Premium tiện ích | Median giá: có vs không có điều hoà/khép kín/máy giặt/giờ tự do | C1 | Grouped bar |
| Bảng giá hợp lý | p25 – median – p75 từng phường để tra cứu | B3 | Bảng |
| **Boxplot dao động giá** | Hộp p25–p75 + median + râu min–max theo loại hình | A4 | Boxplot |
| **Bản đồ nhiệt giá** | Tô màu phường theo median; bản thật dùng Leaflet + GeoJSON ranh giới phường | A1, A3 | Choropleth / grid heatmap |

Các view có thể bổ sung sau (đã liệt kê khi trao đổi): **Value score** (xếp hạng phường "đáng tiền" = giá thấp + tiện ích cao + DT tốt), **radar so sánh đa tiêu chí** nhiều phường cùng lúc, **treemap cơ cấu thị trường**, **trend giá theo thời gian** (khi đủ `posted_at`).

### Bộ lọc tương tác (dùng chung)

Tab Phân tích nên có filter: loại hình (phòng trọ / chung cư mini / chung cư / tất cả), giá tối đa (slider), diện tích tối thiểu (slider). Mọi chart + metric cập nhật realtime theo filter. Ưu điểm cách 2: filter này **có thể chia sẻ state với tab Tra cứu** (cùng codebase Next.js) — điều iframe Streamlit không làm được.

### Ghi chú triển khai (làm sau)

- **Endpoint FastAPI cần thêm** (ngoài 2 endpoint map/stats trong kế hoạch): `/api/stats/by-ward` (median/p25/p75 theo phường × loại hình), `/api/stats/amenity-premium`, `/api/stats/price-distribution`, `/api/stats/compare?wards=A,B`. Tất cả query Gold layer, có thể cache 5–10 phút để Render free không bị gọi liên tục — hoặc dựng sẵn bảng `gold.price_stats_by_ward` (đã có trong schema) và đọc thẳng.
- **Choropleth thật**: cần GeoJSON ranh giới phường Hà Nội (địa giới 2 cấp mới từ 01/07/2025) — kiểm tra nguồn dữ liệu ranh giới có sẵn không; nếu chưa có thể dùng grid heatmap như prototype.
- **Chưa code** — phần này hiện chỉ là demo + định hướng. Sẽ cải tiến sau.

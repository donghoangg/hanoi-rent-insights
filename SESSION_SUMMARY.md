# Tóm tắt session — Xây dựng Website HanoiRent Insights

> Mục đích file này: ghi lại toàn bộ những gì đã làm ở session xây website, để
> **session sau bắt tay vào DEPLOY** (Render + Vercel) ngay mà không cần dò lại.

---

## 1. Đã làm gì trong session này

Trước session: pipeline dữ liệu (scraper, ETL, dbt, dashboard Streamlit) đã xong;
hai thư mục `backend/` và `frontend/` **trống** → session này xây cả hai = phần website.

### 1.1. Backend — FastAPI (`backend/`)
- Kết nối **trực tiếp tầng Gold** trên Supabase qua `DATABASE_URL` (psycopg2 pool, read-only).
- Tự đọc `.env` theo thứ tự `(".env", "../.env")` → khi chạy `cd backend && uvicorn ...`
  nó lấy luôn `.env` gốc repo (đã có `DATABASE_URL`), **không cần tạo `backend/.env`**.
- Các endpoint:
  - `GET /api/listings/map` — tin cho bản đồ (lọc giá/diện tích/phường/loại hình/tiện ích + bbox)
  - `GET /api/stats/summary` — KPI sidebar
  - `GET /api/stats/analytics` — gói dữ liệu dashboard (1 lần gọi)
  - `GET /api/filters/options` — phường, loại hình, range giá/diện tích
  - `GET /health` — ping DB (dùng cho Render health check)
  - `GET /docs` — Swagger tự sinh
- Đã thêm dữ liệu cho dashboard: **histogram giá**, **histogram diện tích**, **độ phổ biến tiện ích**.

### 1.2. Frontend — Next.js 14 + Tailwind + TS (`frontend/`)
- **Trang Bản đồ** (`/`): React-Leaflet + marker clustering, marker hiện nhãn giá
  (màu theo phân khúc), jitter ±100m, popup style Booking ("Xem tin gốc" mở tab mới).
- **Trang Phân tích** (`/dashboard`): dashboard BI-style render native bằng **Recharts**
  (histogram giá/diện tích, xếp hạng phường rẻ/đắt, cơ cấu loại hình donut, khoảng giá
  theo loại hình, scatter giá–diện tích, premium tiện ích, độ phổ biến tiện ích, phân khúc giá).
- **Trang Giới thiệu** (`/about`).
- API client cấu hình qua `NEXT_PUBLIC_API_URL` (mặc định `http://localhost:8000`).

### 1.3. Hai sửa lỗi/cải tiến quan trọng đã xử lý
1. **Chủ quyền biển đảo**: đổi tile nền OpenStreetMap.org → **Carto Voyager** (miễn phí,
   không API key) + vẽ nhãn cố định **"Quần đảo Hoàng Sa / Trường Sa (Việt Nam)"** đè lên
   đúng toạ độ. Xử lý trong `MapView.tsx` + CSS `.sovereignty-label` trong `globals.css`.
2. **Dashboard**: sửa các chart trống (boxplot/pie/scatter), thêm KPI mới, nâng cấp BI-style
   (lưới nền, nhãn số trên cột, màu nhất quán).

---

## 2. Trạng thái hiện tại (tính tới cuối session)

- **Backend** chạy OK trên máy: `uvicorn app.main:app --reload --port 8000` →
  `/health` trả `{"status":"ok","database":true}`. Đã xác nhận `/api/stats/analytics`
  trả **đầy đủ dữ liệu thật** (phong_tro 1148, chung_cu 233, nha_nguyen_can 212...).
- **Frontend** build pass (`npm run build` → Compiled successfully, 4 route).
- Việc cuối còn dang dở: sau khi sửa dashboard, **cần chạy lại `npm run dev` + hard refresh
  (Ctrl+Shift+R)** để thấy bản chart mới. (Dữ liệu backend đã đúng, chỉ là Next.js cần
  biên dịch lại bản frontend mới.)

### Lưu ý kỹ thuật quan trọng
- **Cài thêm `pydantic-settings`**: venv gốc cài từ `requirements.txt` cũ nên thiếu gói này.
  Đã thêm vào `requirements.txt`. Nếu môi trường mới: `pip install -r requirements.txt` là đủ.
- **Ghi file frontend hay bị cắt cụt** khi `npm run dev` đang chạy (file-watcher khoá file).
  → Khi sửa file frontend, **nên tắt `npm run dev`** trước, sửa xong bật lại.
- `dim_property_type.sql` (dbt) đã sửa codes `room/apartment/house` → `phong_tro/
  chung_cu/nha_nguyen_can/can_ho_dich_vu/khac` cho khớp Silver, kèm nhãn tiếng Việt.
  **ĐÃ chạy lại `dbt run`** (user thực hiện) → `fct_listings.property_type_key` giờ
  được điền đúng (trước đây NULL do join trượt), dim có nhãn VN chuẩn, dbt tests
  `relationships` xanh. Dashboard không đổi (vì `listings_for_map.property_type` vốn
  đã đúng), nhưng star schema giờ sạch hơn — điểm cộng cho báo cáo.

---

## 3. KẾ HOẠCH SESSION SAU — DEPLOY lên web thật

Mục tiêu: có **public URL** cho cả backend (Render) và frontend (Vercel), free tier.

### Bước 0 — Chuẩn bị repo
- Repo GitHub: `https://github.com/donghoangg/hanoi-rent-insights.git` (branch `main`).
- **Commit & push** thư mục `backend/` và `frontend/` lên GitHub (hiện đang là untracked).
- Kiểm tra `.gitignore` không vô tình bỏ qua `backend/` hay `frontend/`.
- **KHÔNG commit** `.env` thật (chứa mật khẩu DB). Chỉ commit `.env.example`.
  `backend/.gitignore` và `frontend/.gitignore` đã loại `.env`/`node_modules`/`.next`.

### Bước 1 — Backend lên Render
- Tạo Web Service từ repo (Render đọc `backend/render.yaml`), hoặc thủ công:
  - Root Directory: `backend`
  - Build: `pip install -r requirements.txt`
  - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  - Health Check Path: `/health`
- Env vars trên Render:
  - `DATABASE_URL` = chuỗi Supabase (nên dùng **connection pooling**, port 6543 nếu có)
  - `GOLD_SCHEMA` = `gold`
  - `CORS_ORIGINS` = (điền sau khi có URL Vercel ở Bước 2)
- Lấy URL, ví dụ `https://hanoirent-api.onrender.com` → test `/health`, `/docs`.
- Lưu ý: Render free "ngủ" sau ~15 phút; request đầu sau đó mất ~30–50s để dậy.

### Bước 2 — Frontend lên Vercel
- Add New Project từ repo, Root Directory: `frontend` (Vercel tự nhận Next.js).
- Env var: `NEXT_PUBLIC_API_URL` = URL Render ở Bước 1.
- Deploy → lấy URL, ví dụ `https://hanoirent.vercel.app`.

### Bước 3 — Nối CORS
- Quay lại Render, đặt `CORS_ORIGINS` = URL Vercel, **redeploy** backend.
- Mở URL Vercel kiểm tra: bản đồ load tin, popup mở tin gốc, tab Phân tích vẽ chart.

### Checklist nghiệm thu sau deploy
- [ ] `https://<render>/health` → ok
- [ ] `https://<render>/api/filters/options` → có dữ liệu
- [ ] `https://<vercel>` → bản đồ hiện marker giá + nhãn Hoàng Sa/Trường Sa (zoom out)
- [ ] Tab Phân tích → tất cả chart có dữ liệu
- [ ] Không lỗi CORS trong Console (F12)

### Rủi ro/điểm cần lưu khi deploy
- **CORS**: lỗi hay gặp nhất — nhớ set `CORS_ORIGINS` đúng URL Vercel (kèm https, không dấu / cuối).
- **Supabase connection**: Render dùng `DATABASE_URL` qua pooler; nếu lỗi SSL, thêm `?sslmode=require`.
- **Cold start Render**: lần đầu vào web có thể chậm ~30–50s (backend dậy). Có thể set cron ping `/health`.
- **Build Vercel**: nếu lỗi font Google (đã thấy warning lúc build local) → vô hại, vẫn build được.

---

## 4. Tài liệu liên quan đã có
- `WEBSITE.md` — hướng dẫn chạy local + deploy chi tiết (đọc kèm file này).
- `backend/render.yaml` — blueprint Render.
- `backend/.env.example`, `frontend/.env.local.example` — mẫu biến môi trường.
- `KE_HOACH_DU_AN.md`, `docs/BAO_CAO_PHAN_3.md` — kế hoạch & thiết kế tổng thể.

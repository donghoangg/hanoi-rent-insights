# HanoiRent Insights — Website (Backend FastAPI + Frontend Next.js)

Phần website của đồ án: bản đồ tra cứu nhà cho thuê (Leaflet) và dashboard
phân tích thị trường (Recharts). Dữ liệu đọc trực tiếp từ tầng **Gold**
(`gold.listings_for_map`, `gold.fct_listings`...) trên Supabase.

```
frontend (Next.js, Vercel)  ──HTTP──►  backend (FastAPI, Render)  ──SQL──►  Supabase (Gold)
```

---

## 1. Kiến trúc thư mục

```
backend/                       # FastAPI
├── app/
│   ├── main.py                # khởi tạo app, CORS, lifespan (DB pool), /health
│   ├── config.py              # đọc .env (DATABASE_URL, CORS_ORIGINS, GOLD_SCHEMA)
│   ├── database.py            # psycopg2 ThreadedConnectionPool (read-only)
│   ├── schemas.py             # Pydantic models
│   └── routers/
│       ├── listings.py        # GET /api/listings/map
│       └── stats.py           # GET /api/stats/summary | /analytics | /filters/options
├── requirements.txt
├── render.yaml                # blueprint deploy Render
└── .env.example

frontend/                      # Next.js 14 (app router) + TailwindCSS + TS strict
├── src/
│   ├── app/
│   │   ├── layout.tsx         # khung + NavBar
│   │   ├── page.tsx           # trang Bản đồ
│   │   ├── dashboard/page.tsx # trang Phân tích
│   │   └── about/page.tsx     # Giới thiệu
│   ├── components/
│   │   ├── MapView.tsx        # Leaflet + cluster + marker giá + popup
│   │   ├── FilterSidebar.tsx  # bộ lọc dùng chung 2 trang
│   │   ├── DashboardCharts.tsx# các biểu đồ Recharts
│   │   ├── KpiCard.tsx
│   │   └── NavBar.tsx
│   └── lib/
│       ├── api.ts             # client gọi backend
│       ├── types.ts           # interface khớp response
│       ├── format.ts          # formatVND...
│       └── labels.ts          # nhãn + màu loại hình / tiện ích
├── package.json
└── .env.local.example
```

---

## 2. API (backend)

| Method & Endpoint | Mô tả | Tham số chính |
|---|---|---|
| `GET /api/listings/map` | Tin cho bản đồ | `min_price,max_price,min_area,max_area,districts[],property_types[],amenities[],north,south,east,west` |
| `GET /api/stats/summary` | KPI sidebar | (cùng bộ lọc, trừ amenities) |
| `GET /api/stats/analytics` | Gói dữ liệu dashboard | (cùng bộ lọc) |
| `GET /api/filters/options` | Phường, loại hình, range giá/diện tích | — |
| `GET /health` | Health check (ping DB) | — |
| `GET /docs` | Swagger UI tự sinh | — |

Bộ lọc nhiều giá trị truyền dạng lặp param: `?districts=Quan%20Hoa&districts=Mỹ%20Đình%201`.

--- 

## 3. Chạy local

### 3.1. Backend (cổng 8000)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Tạo backend/.env (xem .env.example). Tối thiểu cần DATABASE_URL.
# Có thể copy DATABASE_URL từ .env gốc của dự án.
cp .env.example .env        # rồi điền DATABASE_URL

uvicorn app.main:app --reload --port 8000
```

Mở http://localhost:8000/docs để thử API. Kiểm tra nhanh:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/api/filters/options"
```

### 3.2. Frontend (cổng 3000)

```bash
cd frontend
npm install

cp .env.local.example .env.local   # mặc định NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Mở http://localhost:3000 — trang **Bản đồ**. Tab **Phân tích** là dashboard.

> Lưu ý: backend phải chạy trước thì frontend mới có dữ liệu. Nếu thấy báo lỗi
> tải dữ liệu, kiểm tra `NEXT_PUBLIC_API_URL` và CORS (`CORS_ORIGINS` ở backend
> phải chứa `http://localhost:3000`).

---

## 4. Deploy (free tier)

### 4.1. Backend → Render

1. Push repo lên GitHub.
2. Trên **Render** → **New +** → **Blueprint** → chọn repo (Render đọc
   `backend/render.yaml`). Hoặc tạo **Web Service** thủ công:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/health`
3. Khai báo **Environment Variables**:
   - `DATABASE_URL` — chuỗi kết nối Supabase (nên dùng **connection pooling**).
   - `GOLD_SCHEMA` = `gold`
   - `CORS_ORIGINS` = URL Vercel của frontend (điền sau khi có ở bước 4.2),
     ví dụ `https://hanoirent.vercel.app`.
4. Deploy → lấy URL service, ví dụ `https://hanoirent-api.onrender.com`.
   Kiểm tra `…/health` và `…/docs`.

> Render free "ngủ" sau ~15 phút không dùng; request đầu tiên sau đó mất
> ~30–50s để dậy. Có thể dùng cron uptime ping `/health` để giữ thức.

### 4.2. Frontend → Vercel

1. Trên **Vercel** → **Add New Project** → import repo.
2. **Root Directory**: `frontend` (Vercel tự nhận Next.js).
3. **Environment Variables**:
   - `NEXT_PUBLIC_API_URL` = URL Render ở bước 4.1
     (ví dụ `https://hanoirent-api.onrender.com`).
4. Deploy → lấy URL, ví dụ `https://hanoirent.vercel.app`.
5. **Quay lại Render**, cập nhật `CORS_ORIGINS` = URL Vercel này, rồi
   redeploy backend (để trình duyệt không bị chặn CORS).

---

## 5. Quyết định thiết kế (để ghi vào báo cáo)

- **Backend đọc thẳng Gold layer** (`listings_for_map` đã denormalized: chỉ
  tin có toạ độ, `price_status='ok'`, không outlier, đã tính sẵn
  `price_segment`) → query nhanh, không cần join ở API.
- **Dashboard render native bằng Recharts** trong React (không nhúng iframe
  Streamlit) để giao diện đồng nhất với bản đồ — đúng như mô tả ở
  `docs/BAO_CAO_PHAN_3.md` mục 3.7.
- **Marker thêm jitter ±~100m** (deterministic theo `listing_key`) vì geocoding
  chỉ chính xác cấp phường; xử lý ở frontend (`MapView.tsx`), không lưu DB.
- **Không có trang chi tiết riêng**: click marker → popup → nút "Xem tin gốc"
  mở tab mới sang website nguồn (style Booking.com).
- Logic phân tích (ngưỡng ≥10 tin/phường để xếp hạng, ≥15 tin mỗi nhóm khi so
  premium tiện ích, diện tích hợp lệ 5–500 m²) **đồng bộ** với trang Streamlit
  `analytics/dashboard/pages/3_Phan_tich.py` để hai nơi cho cùng con số.
```

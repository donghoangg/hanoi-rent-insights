"""HanoiRent Insights — FastAPI backend.

API đọc trực tiếp tầng Gold (gold.listings_for_map) trên Supabase PostgreSQL.
Hai nhóm endpoint:
  - /api/listings/map        → marker cho bản đồ Leaflet (frontend trang Map)
  - /api/stats/*, /api/filters → KPI + phân tích (frontend trang Dashboard)

Chạy local:
    cd backend
    uvicorn app.main:app --reload --port 8000
Docs Swagger tự sinh tại http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import close_pool, init_pool, ping
from .routers import listings, stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hanoirent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi tạo DB pool lúc start, đóng lúc shutdown."""
    init_pool()
    logger.info("Backend HanoiRent đã sẵn sàng.")
    yield
    close_pool()


app = FastAPI(
    title="HanoiRent Insights API",
    description="API tra cứu & phân tích nhà cho thuê Hà Nội (tầng Gold).",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — cho phép frontend Next.js gọi.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(listings.router)
app.include_router(stats.router)


@app.get("/", tags=["meta"])
def root():
    """Thông tin nhanh về API."""
    return {
        "name": "HanoiRent Insights API",
        "docs": "/docs",
        "endpoints": [
            "/api/listings/map",
            "/api/stats/summary",
            "/api/stats/analytics",
            "/api/filters/options",
            "/health",
        ],
    }


@app.get("/health", tags=["meta"])
def health():
    """Health check — kiểm tra kết nối DB (dùng cho Render/uptime)."""
    db_ok = ping()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}

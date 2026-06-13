"""
Tầng nguồn dữ liệu cho trang Phân tích thị trường.

Mục tiêu: tách phần LẤY DỮ LIỆU ra khỏi phần VẼ CHART, để dashboard chạy
được ở 2 chế độ mà không phải sửa code chart:

    1. PRODUCTION  — đọc thẳng từ Gold layer trên Supabase (qua db.query).
                     Tự bật khi có biến môi trường DATABASE_URL.
    2. PROTOTYPE   — đọc từ silver_listings_export.csv (dữ liệu thật đã export).
                     Tự bật khi KHÔNG có DATABASE_URL (vd: chạy demo offline,
                     hoặc môi trường không nối được DB).

Cả 2 chế độ trả về CÙNG một DataFrame chuẩn hoá (cùng tên cột), nên các hàm
KPI ở phía sau không cần quan tâm dữ liệu đến từ đâu.

Lý do thiết kế:
  - price_per_m2 trong silver hiện đang rỗng → luôn TỰ TÍNH lại từ price/area.
  - furnishing_level hiện rỗng 100% → không dùng làm chiều phân tích.
  - posted_at chỉ ~38% coverage → KPI theo thời gian để riêng, có cảnh báo.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

# Cột boolean tiện ích — dùng chung cho Nhóm C
AMENITY_COLS = [
    "has_air_conditioner",
    "has_water_heater",
    "has_fridge",
    "has_washing_machine",
    "has_furniture",
    "has_wifi",
    "has_kitchen",
    "is_self_contained",
    "good_security",
    "near_market",
]

# Nhãn tiếng Việt cho tiện ích (hiển thị trên chart)
AMENITY_LABELS = {
    "has_air_conditioner": "Điều hoà",
    "has_water_heater": "Bình nóng lạnh",
    "has_fridge": "Tủ lạnh",
    "has_washing_machine": "Máy giặt",
    "has_furniture": "Nội thất",
    "has_wifi": "Wifi",
    "has_kitchen": "Bếp",
    "is_self_contained": "Khép kín",
    "good_security": "An ninh tốt",
    "near_market": "Gần chợ",
}

# Nhãn tiếng Việt cho loại hình
PROPERTY_TYPE_LABELS = {
    "phong_tro": "Phòng trọ",
    "chung_cu": "Chung cư",
    "nha_nguyen_can": "Nhà nguyên căn",
    "can_ho_dich_vu": "Căn hộ dịch vụ",
    "khac": "Khác",
}

# Giới hạn diện tích hợp lý để loại bản ghi lỗi (vd area_m2 = 30000)
AREA_MIN_M2 = 5
AREA_MAX_M2 = 500


def _truthy(series: pd.Series) -> pd.Series:
    """Chuẩn hoá cột boolean (CSV lưu 'True'/'False' dạng chuỗi) → bool thật."""
    return series.astype(str).str.lower().isin(["true", "t", "1"])


def using_database() -> bool:
    """True nếu có DATABASE_URL → chế độ production (Supabase Gold)."""
    return bool(os.environ.get("DATABASE_URL"))


def _find_csv() -> Path | None:
    """Tìm silver_listings_export.csv ở repo root (đi lên từ thư mục dashboard)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "silver_listings_export.csv"
        if candidate.exists():
            return candidate
    return None


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Chuẩn hoá kiểu dữ liệu + tính cột phái sinh, dùng chung cho cả 2 nguồn."""
    df = df.copy()

    # Số
    for col in ["price_vnd", "area_m2", "bedrooms", "bathrooms", "latitude", "longitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Boolean tiện ích + cờ
    for col in AMENITY_COLS + ["is_price_outlier", "is_negotiable", "landlord_shared"]:
        if col in df.columns:
            df[col] = _truthy(df[col])

    # Nhãn loại hình
    if "property_type" in df.columns:
        df["property_type_label"] = (
            df["property_type"].map(PROPERTY_TYPE_LABELS).fillna(df["property_type"])
        )

    # TỰ TÍNH price_per_m2 (cột gốc đang rỗng) — chỉ trên diện tích hợp lệ
    area_ok = df["area_m2"].between(AREA_MIN_M2, AREA_MAX_M2)
    df["price_per_m2_calc"] = (df["price_vnd"] / df["area_m2"]).where(area_ok)

    # Cờ diện tích hợp lệ (dùng để lọc các KPI theo m²)
    df["area_valid"] = area_ok

    # posted_at → datetime (coverage thấp, để None nếu thiếu)
    if "posted_at" in df.columns:
        df["posted_at"] = pd.to_datetime(df["posted_at"], errors="coerce")

    return df


@st.cache_data(ttl=600, show_spinner="Đang tải dữ liệu thị trường...")
def load_listings() -> pd.DataFrame:
    """
    Trả về DataFrame listing đã chuẩn hoá.

    Production: SELECT từ gold.fct_listings JOIN các dim (qua db.query).
    Prototype : đọc silver_listings_export.csv.
    """
    if using_database():
        # Lazy import để chế độ prototype không cần psycopg2/db.py
        from db import query

        sql = """
            SELECT
                f.listing_key            AS listing_id,
                s.source_name,
                f.source_id,
                f.source_url,
                f.title,
                f.price_vnd,
                f.area_m2,
                f.bedrooms,
                f.bathrooms,
                pt.property_type_code    AS property_type,
                l.ward,
                l.province,
                f.latitude,
                f.longitude,
                f.geocode_status,
                f.has_air_conditioner,
                f.has_water_heater,
                f.has_fridge,
                f.has_washing_machine,
                f.has_furniture,
                f.has_wifi,
                f.has_kitchen,
                f.is_self_contained,
                f.good_security,
                f.near_market,
                f.price_status,
                f.is_price_outlier,
                f.posted_at
            FROM gold.fct_listings f
            LEFT JOIN gold.dim_location      l  ON f.location_key      = l.location_key
            LEFT JOIN gold.dim_property_type pt ON f.property_type_key = pt.property_type_key
            LEFT JOIN gold.dim_source        s  ON f.source_key        = s.source_key
        """
        rows = query(sql)
        df = pd.DataFrame(rows)
    else:
        csv = _find_csv()
        if csv is None:
            raise FileNotFoundError(
                "Không tìm thấy silver_listings_export.csv và cũng không có "
                "DATABASE_URL. Hãy đặt DATABASE_URL để nối Supabase, hoặc đảm bảo "
                "file CSV nằm ở thư mục gốc dự án."
            )
        df = pd.read_csv(csv)

    return _normalize(df)


def data_source_label() -> str:
    """Nhãn hiển thị nguồn dữ liệu hiện tại (cho caption trên trang)."""
    if using_database():
        return "Gold layer (Supabase) — dữ liệu trực tiếp"
    csv = _find_csv()
    name = csv.name if csv else "CSV"
    return f"Bản export {name} — chế độ demo offline"


# ----------------------------------------------------------------------
# Hàm lọc giá "sạch" — quy ước xuyên suốt: chỉ tính KPI giá trên tin
# price_status='ok' VÀ không phải outlier (theo KPI_DINH_HUONG.md mục 0).
# ----------------------------------------------------------------------
def clean_price(df: pd.DataFrame) -> pd.DataFrame:
    """Lọc về tập tin có giá đáng tin để tính KPI giá."""
    mask = (df.get("price_status", "ok") == "ok") & (~df["is_price_outlier"])
    return df[mask]

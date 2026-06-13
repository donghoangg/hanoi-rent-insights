"""Router /api/listings — dữ liệu tin đăng cho bản đồ.

Truy vấn gold.listings_for_map (đã denormalized): chỉ tin có lat/lng hợp lệ,
price_status='ok', không outlier. Hỗ trợ lọc theo giá, diện tích, phường,
loại hình, tiện ích và bounding box (viewport map).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from ..config import get_settings
from ..database import query
from ..schemas import Listing

router = APIRouter(prefix="/api/listings", tags=["listings"])

# Map tên tham số tiện ích (query) → tên cột trong DB.
# Chỉ cho phép các cột boolean này để tránh SQL injection qua tên cột.
AMENITY_COLUMNS = {
    "has_air_conditioner",
    "has_water_heater",
    "has_fridge",
    "has_washing_machine",
    "has_furniture",
    "has_wifi",
    "has_kitchen",
    "is_self_contained",
    "free_hours",
    "landlord_shared",
    "good_security",
    "near_market",
}

# Các cột SELECT cho bản đồ.
_SELECT_COLS = """
    listing_key, title, price_vnd, area_m2, price_per_m2, bedrooms,
    property_type, price_segment, province, ward, latitude, longitude,
    source_name, source_url, thumbnail_url, posted_at,
    has_air_conditioner, has_water_heater, has_fridge, has_washing_machine,
    has_furniture, has_wifi, has_kitchen, is_self_contained, free_hours,
    landlord_shared, good_security, near_market
"""


@router.get("/map", response_model=list[Listing], summary="Tin đăng cho bản đồ")
def get_listings_for_map(
    min_price: Optional[int] = Query(None, description="Giá tối thiểu (VND/tháng)"),
    max_price: Optional[int] = Query(None, description="Giá tối đa (VND/tháng)"),
    min_area: Optional[float] = Query(None, description="Diện tích tối thiểu (m²)"),
    max_area: Optional[float] = Query(None, description="Diện tích tối đa (m²)"),
    districts: Optional[list[str]] = Query(
        None, description="Danh sách phường (lặp param: districts=A&districts=B)"
    ),
    property_types: Optional[list[str]] = Query(
        None, description="Danh sách mã loại hình"
    ),
    amenities: Optional[list[str]] = Query(
        None, description="Tiện ích bắt buộc TRUE (vd has_air_conditioner)"
    ),
    # Bounding box viewport (tuỳ chọn, tối ưu khi map đã zoom).
    north: Optional[float] = Query(None),
    south: Optional[float] = Query(None),
    east: Optional[float] = Query(None),
    west: Optional[float] = Query(None),
    limit: int = Query(8000, ge=1, le=20000, description="Giới hạn số tin trả về"),
):
    """Trả về danh sách tin matching filter để hiển thị marker trên bản đồ."""
    schema = get_settings().gold_schema

    where: list[str] = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
    params: list[object] = []

    if min_price is not None:
        where.append("price_vnd >= %s")
        params.append(min_price)
    if max_price is not None:
        where.append("price_vnd <= %s")
        params.append(max_price)
    if min_area is not None:
        where.append("area_m2 >= %s")
        params.append(min_area)
    if max_area is not None:
        where.append("area_m2 <= %s")
        params.append(max_area)
    if districts:
        where.append("ward = ANY(%s)")
        params.append(list(districts))
    if property_types:
        where.append("property_type = ANY(%s)")
        params.append(list(property_types))

    # Bounding box (chỉ áp khi đủ 4 cạnh).
    if None not in (north, south, east, west):
        where.append("latitude BETWEEN %s AND %s")
        params.extend([south, north])
        where.append("longitude BETWEEN %s AND %s")
        params.extend([west, east])

    # Tiện ích: mỗi tiện ích yêu cầu cột = TRUE. Whitelist tên cột.
    if amenities:
        for a in amenities:
            if a in AMENITY_COLUMNS:
                where.append(f"{a} = TRUE")

    where_sql = " AND ".join(where)
    sql = f"""
        SELECT {_SELECT_COLS}
        FROM {schema}.listings_for_map
        WHERE {where_sql}
        LIMIT %s
    """
    params.append(limit)

    rows = query(sql, tuple(params))
    return rows

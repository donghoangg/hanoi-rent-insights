"""Pydantic schemas — định dạng dữ liệu trả về cho frontend.

Bám sát cột của gold.listings_for_map và các truy vấn thống kê.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class Listing(BaseModel):
    """Một tin đăng để render lên bản đồ (1 dòng gold.listings_for_map)."""

    listing_key: int
    title: Optional[str] = None
    price_vnd: Optional[int] = None
    area_m2: Optional[float] = None
    price_per_m2: Optional[float] = None
    bedrooms: Optional[int] = None
    property_type: Optional[str] = None
    price_segment: Optional[str] = None  # 'thap' | 'trung_binh' | 'cao'
    province: Optional[str] = None
    ward: Optional[str] = None
    latitude: float
    longitude: float
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    posted_at: Optional[date] = None

    # 12 cờ tiện ích
    has_air_conditioner: Optional[bool] = None
    has_water_heater: Optional[bool] = None
    has_fridge: Optional[bool] = None
    has_washing_machine: Optional[bool] = None
    has_furniture: Optional[bool] = None
    has_wifi: Optional[bool] = None
    has_kitchen: Optional[bool] = None
    is_self_contained: Optional[bool] = None
    free_hours: Optional[bool] = None
    landlord_shared: Optional[bool] = None
    good_security: Optional[bool] = None
    near_market: Optional[bool] = None


class SummaryStats(BaseModel):
    """Thống kê tổng quan cho sidebar."""

    total_listings: int
    median_price_vnd: Optional[float] = None
    p25_price_vnd: Optional[float] = None
    p75_price_vnd: Optional[float] = None
    median_price_per_m2: Optional[float] = None
    ward_count: int


class WardOption(BaseModel):
    """Một phường trong danh sách filter (kèm số tin để sắp xếp/lọc)."""

    ward: str
    count: int


class PropertyTypeOption(BaseModel):
    """Một loại hình trong danh sách filter."""

    code: str
    count: int


class FilterOptions(BaseModel):
    """Toàn bộ lựa chọn cho filter sidebar."""

    wards: list[WardOption]
    property_types: list[PropertyTypeOption]
    price_min_vnd: int
    price_max_vnd: int
    area_min_m2: float
    area_max_m2: float


# ---- Analytics (trang Dashboard) ----------------------------------------


class WardPrice(BaseModel):
    """Giá trung vị theo phường (cho bảng xếp hạng + giá/m²)."""

    ward: str
    count: int
    median_price_vnd: float
    median_price_per_m2: Optional[float] = None


class PropertyTypePrice(BaseModel):
    """Phân bố giá theo loại hình (cho boxplot)."""

    property_type: str
    count: int
    min_price: float
    q1_price: float
    median_price: float
    q3_price: float
    max_price: float


class TypeShare(BaseModel):
    """Cơ cấu nguồn cung theo loại hình (cho pie)."""

    property_type: str
    count: int


class ScatterPoint(BaseModel):
    """Một điểm giá–diện tích (cho scatter)."""

    area_m2: float
    price_vnd: int
    property_type: Optional[str] = None


class AmenityPremium(BaseModel):
    """Phần chênh giá khi có 1 tiện ích (so với không có), trong cùng loại hình."""

    amenity: str
    pct_diff: float
    vnd_diff: float
    n_with: int
    n_without: int


class SegmentShare(BaseModel):
    """Cơ cấu phân khúc giá theo loại hình (thấp / trung bình / cao)."""

    property_type: str
    segment: str  # 'thap' | 'trung_binh' | 'cao'
    count: int



class HistogramBin(BaseModel):
    """Một cột histogram (giá hoặc diện tích)."""

    label: str          # nhãn hiển thị, vd "3–4 tr" hoặc "20–30 m²"
    lower: float        # cận dưới (để sort)
    count: int


class AmenityPrevalence(BaseModel):
    """Độ phổ biến của một tiện ích: % tin có tiện ích đó."""

    amenity: str
    pct: float          # 0–100
    count: int


class AnalyticsResponse(BaseModel):
    """Gói toàn bộ dữ liệu cho trang Dashboard trong 1 lần gọi."""

    summary: SummaryStats
    ward_prices: list[WardPrice]
    type_prices: list[PropertyTypePrice]
    type_shares: list[TypeShare]
    scatter: list[ScatterPoint]
    amenity_premiums: list[AmenityPremium]
    segment_shares: list[SegmentShare]
    price_histogram: list[HistogramBin]
    area_histogram: list[HistogramBin]
    amenity_prevalence: list[AmenityPrevalence]

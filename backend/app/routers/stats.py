"""Router /api/stats và /api/filters — thống kê cho sidebar + trang Dashboard.

Mọi truy vấn đọc gold.listings_for_map (đã loại outlier, chỉ price ok). Logic
phân tích bám theo trang Streamlit 3_Phan_tich.py để hai nơi cho kết quả nhất quán:
  - Xếp hạng phường: chỉ phường có ≥10 tin (median ổn định).
  - Giá/m²: chỉ tính trên tin có diện tích hợp lệ (5–500 m²).
  - Premium tiện ích: so trong cùng loại hình, mỗi nhóm ≥15 tin.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from ..config import get_settings
from ..database import query, query_one
from ..schemas import (
    AmenityPremium,
    AmenityPrevalence,
    AnalyticsResponse,
    HistogramBin,
    FilterOptions,
    PropertyTypeOption,
    PropertyTypePrice,
    ScatterPoint,
    SegmentShare,
    SummaryStats,
    TypeShare,
    WardOption,
    WardPrice,
)

router = APIRouter(tags=["stats"])

# Tiện ích đưa vào phân tích premium (nhãn VN xử lý ở frontend).
ANALYTICS_AMENITIES = [
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

# Diện tích hợp lệ để tính giá/m² (đồng bộ data_source.py).
AREA_MIN, AREA_MAX = 5, 500


def _T() -> str:
    """Tên bảng map đầy đủ schema."""
    return f"{get_settings().gold_schema}.listings_for_map"


def _where_filters(
    min_price, max_price, min_area, max_area, districts, property_types
) -> tuple[str, list]:
    """Dựng mệnh đề WHERE dùng chung cho summary & analytics."""
    where = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
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
    return " AND ".join(where), params


# ---------------------------------------------------------------------------
# /api/filters/options — dữ liệu cho filter sidebar
# ---------------------------------------------------------------------------
@router.get("/api/filters/options", response_model=FilterOptions)
def get_filter_options():
    """Danh sách phường, loại hình, khoảng giá/diện tích để khởi tạo filter."""
    t = _T()

    wards = query(
        f"""
        SELECT ward, COUNT(*) AS count
        FROM {t}
        WHERE ward IS NOT NULL
        GROUP BY ward
        HAVING COUNT(*) >= 1
        ORDER BY ward
        """
    )
    types = query(
        f"""
        SELECT property_type AS code, COUNT(*) AS count
        FROM {t}
        WHERE property_type IS NOT NULL
        GROUP BY property_type
        ORDER BY count DESC
        """
    )
    bounds = query_one(
        f"""
        SELECT
            COALESCE(MIN(price_vnd), 0)                              AS price_min_vnd,
            COALESCE(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY price_vnd), 0)::bigint
                                                                     AS price_max_vnd,
            COALESCE(MIN(area_m2), 0)                                AS area_min_m2,
            COALESCE(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY area_m2), 0)
                                                                     AS area_max_m2
        FROM {t}
        WHERE price_vnd IS NOT NULL
        """
    ) or {}

    return FilterOptions(
        wards=[WardOption(**w) for w in wards],
        property_types=[PropertyTypeOption(**p) for p in types],
        price_min_vnd=int(bounds.get("price_min_vnd") or 0),
        price_max_vnd=int(bounds.get("price_max_vnd") or 0),
        area_min_m2=float(bounds.get("area_min_m2") or 0),
        area_max_m2=float(bounds.get("area_max_m2") or 0),
    )


# ---------------------------------------------------------------------------
# /api/stats/summary — KPI cho sidebar / dashboard
# ---------------------------------------------------------------------------
@router.get("/api/stats/summary", response_model=SummaryStats)
def get_summary(
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    districts: Optional[list[str]] = Query(None),
    property_types: Optional[list[str]] = Query(None),
):
    """Tổng số tin, giá trung vị, p25–p75, giá/m² trung vị, số phường."""
    t = _T()
    where_sql, params = _where_filters(
        min_price, max_price, min_area, max_area, districts, property_types
    )
    row = query_one(
        f"""
        SELECT
            COUNT(*)                                                   AS total_listings,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY price_vnd)     AS median_price_vnd,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_vnd)     AS p25_price_vnd,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_vnd)     AS p75_price_vnd,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (
                ORDER BY price_per_m2
            ) FILTER (WHERE area_m2 BETWEEN %s AND %s)                  AS median_price_per_m2,
            COUNT(DISTINCT ward)                                       AS ward_count
        FROM {t}
        WHERE {where_sql}
        """,
        tuple([AREA_MIN, AREA_MAX, *params]),
    ) or {}
    return SummaryStats(
        total_listings=int(row.get("total_listings") or 0),
        median_price_vnd=row.get("median_price_vnd"),
        p25_price_vnd=row.get("p25_price_vnd"),
        p75_price_vnd=row.get("p75_price_vnd"),
        median_price_per_m2=row.get("median_price_per_m2"),
        ward_count=int(row.get("ward_count") or 0),
    )


# ---------------------------------------------------------------------------
# /api/stats/analytics — gói dữ liệu cho trang Dashboard (1 lần gọi)
# ---------------------------------------------------------------------------
@router.get("/api/stats/analytics", response_model=AnalyticsResponse)
def get_analytics(
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    districts: Optional[list[str]] = Query(None),
    property_types: Optional[list[str]] = Query(None),
    scatter_limit: int = Query(2000, ge=100, le=8000),
):
    """Trả toàn bộ số liệu cho dashboard: xếp hạng phường, boxplot, pie,
    scatter, premium tiện ích, phân khúc giá."""
    t = _T()
    where_sql, base_params = _where_filters(
        min_price, max_price, min_area, max_area, districts, property_types
    )

    # 1) Summary (tái dùng logic ở trên).
    summary = get_summary(
        min_price, max_price, min_area, max_area, districts, property_types
    )

    # 2) Giá trung vị theo phường (≥10 tin) + giá/m².
    ward_prices = query(
        f"""
        SELECT
            ward,
            COUNT(*)                                               AS count,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_vnd) AS median_price_vnd,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2)
                FILTER (WHERE area_m2 BETWEEN %s AND %s)           AS median_price_per_m2
        FROM {t}
        WHERE {where_sql} AND ward IS NOT NULL
        GROUP BY ward
        HAVING COUNT(*) >= 10
        ORDER BY median_price_vnd
        """,
        tuple([AREA_MIN, AREA_MAX, *base_params]),
    )

    # 3) Phân bố giá theo loại hình (min/Q1/median/Q3/max) — cho box.
    type_prices = query(
        f"""
        SELECT
            property_type,
            COUNT(*)                                                AS count,
            MIN(price_vnd)::float                                    AS min_price,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_vnd)  AS q1_price,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY price_vnd)  AS median_price,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_vnd)  AS q3_price,
            MAX(price_vnd)::float                                    AS max_price
        FROM {t}
        WHERE {where_sql} AND property_type IS NOT NULL
        GROUP BY property_type
        ORDER BY count DESC
        """,
        tuple(base_params),
    )

    # 4) Cơ cấu loại hình (pie).
    type_shares = query(
        f"""
        SELECT property_type, COUNT(*) AS count
        FROM {t}
        WHERE {where_sql} AND property_type IS NOT NULL
        GROUP BY property_type
        ORDER BY count DESC
        """,
        tuple(base_params),
    )

    # 5) Scatter giá–diện tích (lấy mẫu để nhẹ).
    scatter = query(
        f"""
        SELECT area_m2, price_vnd, property_type
        FROM {t}
        WHERE {where_sql}
          AND area_m2 BETWEEN %s AND %s
          AND price_vnd IS NOT NULL
        ORDER BY random()
        LIMIT %s
        """,
        tuple([*base_params, AREA_MIN, AREA_MAX, scatter_limit]),
    )

    # 6) Phân khúc giá theo loại hình (đã tính sẵn price_segment trong bảng).
    segment_shares = query(
        f"""
        SELECT property_type, price_segment AS segment, COUNT(*) AS count
        FROM {t}
        WHERE {where_sql}
          AND property_type IS NOT NULL
          AND price_segment IS NOT NULL
        GROUP BY property_type, price_segment
        ORDER BY property_type, price_segment
        """,
        tuple(base_params),
    )

    # 7) Premium tiện ích: trên TOÀN tập đã lọc (gộp loại hình), mỗi phía ≥15.
    #    Dùng 1 query tổng hợp: với mỗi cột, median giá khi TRUE và khi FALSE.
    amen_aggs = []
    for col in ANALYTICS_AMENITIES:
        amen_aggs.append(
            f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_vnd) "
            f"FILTER (WHERE {col} = TRUE)  AS {col}__with"
        )
        amen_aggs.append(
            f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_vnd) "
            f"FILTER (WHERE {col} = FALSE OR {col} IS NULL) AS {col}__without"
        )
        amen_aggs.append(
            f"COUNT(*) FILTER (WHERE {col} = TRUE)  AS {col}__n_with"
        )
        amen_aggs.append(
            f"COUNT(*) FILTER (WHERE {col} = FALSE OR {col} IS NULL) AS {col}__n_without"
        )
    amen_row = query_one(
        f"SELECT {', '.join(amen_aggs)} FROM {t} WHERE {where_sql}",
        tuple(base_params),
    ) or {}

    amenity_premiums: list[AmenityPremium] = []
    for col in ANALYTICS_AMENITIES:
        n_with = int(amen_row.get(f"{col}__n_with") or 0)
        n_without = int(amen_row.get(f"{col}__n_without") or 0)
        med_with = amen_row.get(f"{col}__with")
        med_without = amen_row.get(f"{col}__without")
        if n_with >= 15 and n_without >= 15 and med_with and med_without:
            diff = float(med_with) - float(med_without)
            pct = 100 * diff / float(med_without) if med_without else 0.0
            amenity_premiums.append(
                AmenityPremium(
                    amenity=col,
                    pct_diff=round(pct, 1),
                    vnd_diff=round(diff, 0),
                    n_with=n_with,
                    n_without=n_without,
                )
            )
    amenity_premiums.sort(key=lambda x: x.pct_diff)

    # 8) Histogram phân bố GIÁ (bins 1 triệu, gộp đuôi >=10tr).
    price_rows = query(
        f"""
        SELECT width_bucket(price_vnd, 0, 10000000, 10) AS b, COUNT(*) AS c
        FROM {t}
        WHERE {where_sql} AND price_vnd IS NOT NULL
        GROUP BY b ORDER BY b
        """,
        tuple(base_params),
    )
    price_histogram = []
    for r in price_rows:
        b = int(r["b"])
        c = int(r["c"])
        if b <= 0:
            label, lo = "< 1 tr", 0.0
        elif b >= 11:
            label, lo = "≥ 10 tr", 10.0
        else:
            label, lo = f"{b - 1}–{b} tr", float(b - 1)
        price_histogram.append(HistogramBin(label=label, lower=lo, count=c))

    # 9) Histogram phân bố DIỆN TÍCH (bins 10 m², 0–100, gộp đuôi >=100).
    area_rows = query(
        f"""
        SELECT width_bucket(area_m2, 0, 100, 10) AS b, COUNT(*) AS c
        FROM {t}
        WHERE {where_sql} AND area_m2 BETWEEN %s AND %s
        GROUP BY b ORDER BY b
        """,
        tuple([*base_params, AREA_MIN, AREA_MAX]),
    )
    area_histogram = []
    for r in area_rows:
        b = int(r["b"])
        c = int(r["c"])
        if b >= 11:
            label, lo = "≥ 100 m²", 100.0
        elif b <= 0:
            label, lo = "< 10 m²", 0.0
        else:
            label, lo = f"{(b - 1) * 10}–{b * 10} m²", float((b - 1) * 10)
        area_histogram.append(HistogramBin(label=label, lower=lo, count=c))

    # 10) Độ phổ biến tiện ích (% tin có mỗi tiện ích).
    prev_aggs = [f"COUNT(*) FILTER (WHERE {c} = TRUE) AS {c}__n" for c in ANALYTICS_AMENITIES]
    prev_aggs.append("COUNT(*) AS total")
    prev_row = query_one(
        f"SELECT {', '.join(prev_aggs)} FROM {t} WHERE {where_sql}",
        tuple(base_params),
    ) or {}
    total_n = int(prev_row.get("total") or 0) or 1
    amenity_prevalence = []
    for c in ANALYTICS_AMENITIES:
        n = int(prev_row.get(f"{c}__n") or 0)
        amenity_prevalence.append(
            AmenityPrevalence(amenity=c, pct=round(100 * n / total_n, 1), count=n)
        )
    amenity_prevalence.sort(key=lambda x: x.pct, reverse=True)

    return AnalyticsResponse(
        summary=summary,
        ward_prices=[WardPrice(**w) for w in ward_prices],
        type_prices=[PropertyTypePrice(**p) for p in type_prices],
        type_shares=[TypeShare(**s) for s in type_shares],
        scatter=[ScatterPoint(**s) for s in scatter],
        amenity_premiums=amenity_premiums,
        segment_shares=[SegmentShare(**s) for s in segment_shares],
        price_histogram=price_histogram,
        area_histogram=area_histogram,
        amenity_prevalence=amenity_prevalence,
    )

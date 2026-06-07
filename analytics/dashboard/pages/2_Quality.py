"""
Trang Data Quality — kiểm tra chất lượng dữ liệu Silver layer.

Sections:
  1. KPI tổng quan: tổng tin, outlier %, duplicate %, geocode ok %
  2. Outlier: phân bố giá theo property_type (box-plot style), bảng ngưỡng IQR
  3. Duplicate: số cặp trùng theo source, bảng mẫu
  4. Completeness: % null theo từng cột quan trọng
  5. Validity: phân bố price_status, area hợp lệ

Nút "Chạy Quality Check" ở sidebar để trigger silver_quality.py trực tiếp.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import query

# ------------------------------------------------------------------
st.set_page_config(page_title="Data Quality", page_icon="🔍", layout="wide")
st.title("🔍 Data Quality — Silver Layer")

# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.header("Controls")

    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.subheader("Chạy Quality Check")
    dry_run = st.checkbox("Dry run (chỉ xem, không UPDATE)", value=True)
    skip_outlier   = st.checkbox("Bỏ qua outlier detection",   value=False)
    skip_duplicate = st.checkbox("Bỏ qua duplicate detection", value=False)

    run_btn = st.button("▶ Chạy silver_quality.py", use_container_width=True, type="primary")

# ------------------------------------------------------------------
# Chạy quality check nếu bấm nút
# ------------------------------------------------------------------
if run_btn:
    cmd = [sys.executable, "-m", "etl.silver_quality"]
    if dry_run:
        cmd.append("--dry-run")
    if skip_outlier:
        cmd.append("--skip-outlier")
    if skip_duplicate:
        cmd.append("--skip-duplicate")

    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )

    with st.spinner("Đang chạy quality check..."):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            env={**os.environ},
        )

    if result.returncode == 0:
        st.success("✅ Quality check hoàn thành!")
        with st.expander("Log output"):
            st.code(result.stdout, language="text")
        st.cache_data.clear()
        st.rerun()
    else:
        st.error("❌ Lỗi khi chạy quality check")
        st.code(result.stderr, language="text")

# ------------------------------------------------------------------
# Queries
# ------------------------------------------------------------------

@st.cache_data(ttl=60)
def get_kpi():
    return query("""
        SELECT
            COUNT(*)                                                      AS total,
            SUM(CASE WHEN is_price_outlier THEN 1 ELSE 0 END)            AS outliers,
            SUM(CASE WHEN duplicate_group_id IS NOT NULL THEN 1 ELSE 0 END) AS duplicates,
            SUM(CASE WHEN geocode_status = 'ok' THEN 1 ELSE 0 END)       AS geocoded,
            SUM(CASE WHEN price_vnd IS NOT NULL THEN 1 ELSE 0 END)       AS has_price,
            SUM(CASE WHEN ward IS NOT NULL THEN 1 ELSE 0 END)            AS has_ward
        FROM silver.listings
    """)


@st.cache_data(ttl=60)
def get_price_distribution():
    """Phân bố giá theo property_type — dùng để vẽ histogram."""
    return query("""
        SELECT
            COALESCE(property_type, 'khac')  AS property_type,
            source_name,
            price_vnd,
            is_price_outlier
        FROM silver.listings
        WHERE price_vnd IS NOT NULL
          AND price_status = 'ok'
          AND price_vnd BETWEEN 500000 AND 100000000
        ORDER BY property_type, price_vnd
    """)


@st.cache_data(ttl=60)
def get_outlier_by_group():
    return query("""
        SELECT
            COALESCE(property_type, 'khac') AS property_type,
            source_name,
            COUNT(*)                         AS total,
            SUM(CASE WHEN is_price_outlier THEN 1 ELSE 0 END) AS outliers,
            ROUND(100.0 * SUM(CASE WHEN is_price_outlier THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0), 1)  AS outlier_pct,
            MIN(CASE WHEN NOT is_price_outlier THEN price_vnd END) AS p_min,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY
                CASE WHEN NOT is_price_outlier THEN price_vnd END)::BIGINT AS q1,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
                CASE WHEN NOT is_price_outlier THEN price_vnd END)::BIGINT AS median,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY
                CASE WHEN NOT is_price_outlier THEN price_vnd END)::BIGINT AS q3,
            MAX(CASE WHEN NOT is_price_outlier THEN price_vnd END) AS p_max
        FROM silver.listings
        WHERE price_vnd IS NOT NULL AND price_status = 'ok'
        GROUP BY property_type, source_name
        ORDER BY property_type, source_name
    """)


@st.cache_data(ttl=60)
def get_duplicate_stats():
    return query("""
        SELECT
            a.source_name AS source_a,
            b.source_name AS source_b,
            COUNT(*)       AS pair_count
        FROM silver.listings a
        JOIN silver.listings b
            ON a.duplicate_group_id = b.duplicate_group_id
            AND a.duplicate_group_id IS NOT NULL
            AND a.listing_id < b.listing_id
        GROUP BY a.source_name, b.source_name
        ORDER BY pair_count DESC
    """)


@st.cache_data(ttl=60)
def get_duplicate_samples():
    return query("""
        SELECT
            a.duplicate_group_id,
            a.source_name AS source_a,
            a.title       AS title_a,
            a.price_vnd   AS price_a,
            a.area_m2     AS area_a,
            a.ward,
            b.source_name AS source_b,
            b.title       AS title_b,
            b.price_vnd   AS price_b,
            b.area_m2     AS area_b
        FROM silver.listings a
        JOIN silver.listings b
            ON a.duplicate_group_id = b.duplicate_group_id
            AND a.duplicate_group_id IS NOT NULL
            AND a.listing_id < b.listing_id
        ORDER BY a.duplicate_group_id
        LIMIT 20
    """)


@st.cache_data(ttl=60)
def get_completeness():
    return query("""
        SELECT
            COUNT(*)                                                           AS total,
            ROUND(100.0 * SUM(CASE WHEN price_vnd   IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS null_price_pct,
            ROUND(100.0 * SUM(CASE WHEN area_m2     IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS null_area_pct,
            ROUND(100.0 * SUM(CASE WHEN ward        IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS null_ward_pct,
            ROUND(100.0 * SUM(CASE WHEN latitude    IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS null_lat_pct,
            ROUND(100.0 * SUM(CASE WHEN bedrooms    IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS null_bedrooms_pct,
            ROUND(100.0 * SUM(CASE WHEN property_type IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS null_proptype_pct,
            ROUND(100.0 * SUM(CASE WHEN thumbnail_status = 'ok' THEN 1 ELSE 0 END) / COUNT(*), 1) AS thumbnail_ok_pct
        FROM silver.listings
    """)


@st.cache_data(ttl=60)
def get_price_status():
    return query("""
        SELECT
            source_name,
            price_status,
            COUNT(*) AS cnt
        FROM silver.listings
        GROUP BY source_name, price_status
        ORDER BY source_name, price_status
    """)


# ------------------------------------------------------------------
# Section 1: KPI tổng quan
# ------------------------------------------------------------------
st.subheader("📊 Tổng quan")

kpi_rows = get_kpi()
if kpi_rows:
    k = kpi_rows[0]
    total       = int(k["total"]      or 0)
    outliers    = int(k["outliers"]   or 0)
    duplicates  = int(k["duplicates"] or 0)
    geocoded    = int(k["geocoded"]   or 0)
    has_price   = int(k["has_price"]  or 0)
    has_ward    = int(k["has_ward"]   or 0)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Tổng tin Silver", f"{total:,}")
    c2.metric(
        "Outlier giá",
        f"{outliers:,}",
        delta=f"{100*outliers/max(total,1):.1f}%",
        delta_color="inverse",
    )
    c3.metric(
        "Duplicate",
        f"{duplicates:,}",
        delta=f"{100*duplicates/max(total,1):.1f}%",
        delta_color="inverse",
    )
    c4.metric(
        "Geocoded OK",
        f"{geocoded:,}",
        delta=f"{100*geocoded/max(total,1):.1f}%",
    )
    c5.metric(
        "Có giá",
        f"{has_price:,}",
        delta=f"{100*has_price/max(total,1):.1f}%",
    )

st.divider()

# ------------------------------------------------------------------
# Section 2: Outlier Detection
# ------------------------------------------------------------------
st.subheader("⚠️ Outlier Giá")

# Bảng ngưỡng IQR — full width
outlier_rows = get_outlier_by_group()
if outlier_rows:
    df_out = pd.DataFrame(outlier_rows)
    df_out["q1_m"]     = (df_out["q1"]     / 1e6).round(2)
    df_out["median_m"] = (df_out["median"] / 1e6).round(2)
    df_out["q3_m"]     = (df_out["q3"]     / 1e6).round(2)
    st.dataframe(
        df_out[["property_type", "source_name", "total", "outliers",
                "outlier_pct", "q1_m", "median_m", "q3_m"]].rename(columns={
            "property_type": "Loại hình",
            "source_name":   "Nguồn",
            "total":         "Tổng",
            "outliers":      "Outlier",
            "outlier_pct":   "% Outlier",
            "q1_m":          "Q1 (tr.đ)",
            "median_m":      "Median (tr.đ)",
            "q3_m":          "Q3 (tr.đ)",
        }),
        use_container_width=True,
        hide_index=True,
    )

# Histogram phân bố giá — theo từng property_type, tabs riêng
price_rows = get_price_distribution()
if price_rows:
    df_price = pd.DataFrame(price_rows)
    df_price["price_m"] = (df_price["price_vnd"] / 1e6).round(2)
    df_price["status"]  = df_price["is_price_outlier"].map(
        {True: "Outlier", False: "Bình thường"}
    )

    prop_types = sorted(df_price["property_type"].unique().tolist())
    tabs = st.tabs(prop_types)
    for tab, pt in zip(tabs, prop_types):
        with tab:
            df_pt = df_price[df_price["property_type"] == pt]
            chart = (
                alt.Chart(df_pt)
                .mark_bar(opacity=0.75)
                .encode(
                    x=alt.X("price_m:Q", bin=alt.Bin(maxbins=50),
                             title="Giá (triệu VND/tháng)"),
                    y=alt.Y("count():Q", title="Số tin"),
                    color=alt.Color(
                        "status:N",
                        scale=alt.Scale(domain=["Bình thường", "Outlier"],
                                        range=["#4C78A8", "#E45756"]),
                        legend=alt.Legend(title=""),
                    ),
                    tooltip=["status:N", "count():Q",
                             alt.Tooltip("price_m:Q", bin=alt.Bin(maxbins=50),
                                         title="Giá (tr.đ)")],
                )
                .properties(height=300)
            )
            st.altair_chart(chart, use_container_width=True)

st.divider()

# ------------------------------------------------------------------
# Section 3: Duplicate Detection
# ------------------------------------------------------------------
st.subheader("🔁 Duplicate Cross-source")

dup_stats = get_duplicate_stats()
if not dup_stats:
    st.info("Chưa có dữ liệu duplicate — chạy quality check trước.")
else:
    df_dup = pd.DataFrame(dup_stats)
    c1, c2 = st.columns([1, 2])
    with c1:
        st.dataframe(
            df_dup.rename(columns={
                "source_a":   "Nguồn A",
                "source_b":   "Nguồn B",
                "pair_count": "Số cặp trùng",
            }),
            use_container_width=True,
            hide_index=True,
        )

    with c2:
        dup_samples = get_duplicate_samples()
        if dup_samples:
            df_samples = pd.DataFrame(dup_samples)
            df_samples["price_a_m"] = (df_samples["price_a"] / 1e6).round(2)
            df_samples["price_b_m"] = (df_samples["price_b"] / 1e6).round(2)
            st.caption("Mẫu cặp tin trùng (20 đầu tiên)")
            st.dataframe(
                df_samples[["duplicate_group_id", "ward",
                             "source_a", "title_a", "price_a_m", "area_a",
                             "source_b", "title_b", "price_b_m", "area_b"]].rename(columns={
                    "duplicate_group_id": "Group ID",
                    "ward":      "Phường",
                    "source_a":  "Nguồn A",
                    "title_a":   "Tiêu đề A",
                    "price_a_m": "Giá A (tr)",
                    "area_a":    "DT A",
                    "source_b":  "Nguồn B",
                    "title_b":   "Tiêu đề B",
                    "price_b_m": "Giá B (tr)",
                    "area_b":    "DT B",
                }),
                use_container_width=True,
                hide_index=True,
            )

st.divider()

# ------------------------------------------------------------------
# Section 4: Completeness
# ------------------------------------------------------------------
st.subheader("📋 Completeness — Tỷ lệ thiếu dữ liệu")

comp_rows = get_completeness()
if comp_rows:
    c = comp_rows[0]
    null_data = {
        "Cột": ["Giá (price_vnd)", "Diện tích (area_m2)", "Phường (ward)",
                 "Toạ độ (latitude)", "Số phòng ngủ", "Loại hình"],
        "% Null": [
            float(c["null_price_pct"]    or 0),
            float(c["null_area_pct"]     or 0),
            float(c["null_ward_pct"]     or 0),
            float(c["null_lat_pct"]      or 0),
            float(c["null_bedrooms_pct"] or 0),
            float(c["null_proptype_pct"] or 0),
        ],
    }
    df_null = pd.DataFrame(null_data).sort_values("% Null", ascending=False)

    # Màu theo ngưỡng
    def bar_color(pct):
        if pct > 40:
            return "#E45756"
        elif pct > 20:
            return "#F58518"
        return "#54A24B"

    chart = (
        alt.Chart(df_null)
        .mark_bar()
        .encode(
            x=alt.X("% Null:Q", scale=alt.Scale(domain=[0, 100]), title="% Null"),
            y=alt.Y("Cột:N", sort="-x"),
            color=alt.Color(
                "% Null:Q",
                scale=alt.Scale(domain=[0, 20, 40, 100],
                                range=["#54A24B", "#F58518", "#E45756", "#E45756"]),
                legend=None,
            ),
            tooltip=["Cột", "% Null"],
        )
        .properties(height=220)
    )
    ref_20 = alt.Chart(pd.DataFrame({"x": [20]})).mark_rule(
        strokeDash=[4, 4], color="orange"
    ).encode(x="x:Q")
    ref_40 = alt.Chart(pd.DataFrame({"x": [40]})).mark_rule(
        strokeDash=[4, 4], color="red"
    ).encode(x="x:Q")

    st.altair_chart(chart + ref_20 + ref_40, use_container_width=True)
    st.caption("Đường cam = ngưỡng 20%, đường đỏ = ngưỡng 40%")

    # Thumbnail OK rate
    thumb_ok = float(c["thumbnail_ok_pct"] or 0)
    st.metric("Thumbnail OK", f"{thumb_ok:.1f}%")

st.divider()

# ------------------------------------------------------------------
# Section 5: Validity — price_status
# ------------------------------------------------------------------
st.subheader("✅ Validity — Price Status")

price_status_rows = get_price_status()
if price_status_rows:
    df_ps = pd.DataFrame(price_status_rows)
    chart = (
        alt.Chart(df_ps)
        .mark_bar()
        .encode(
            x=alt.X("source_name:N", title="Nguồn"),
            y=alt.Y("cnt:Q", title="Số tin"),
            color=alt.Color(
                "price_status:N",
                scale=alt.Scale(
                    domain=["ok", "suspect", "missing"],
                    range=["#54A24B", "#F58518", "#E45756"],
                ),
                legend=alt.Legend(title="Price Status"),
            ),
            tooltip=["source_name", "price_status", "cnt"],
        )
        .properties(height=250)
    )
    st.altair_chart(chart, use_container_width=True)

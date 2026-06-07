"""
Trang Monitoring — theo dõi quá trình cào dữ liệu.

KPIs hiển thị:
  - Lần cào cuối (last scrape time) theo từng nguồn
  - Tổng tin hợp lệ (bronze.listings_raw)
  - Tỉ lệ pass / quarantine
  - Bảng các run gần nhất

Charts:
  - Tổng tin theo nguồn qua từng ngày (stacked bar)
  - Pass rate theo từng run (line chart)
  - Số tin quarantine theo nguồn (area chart)
  - Missing values theo cột silver (bar chart)
  - Phân bố property_type (donut)
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import altair as alt

# Import db helper từ thư mục cha
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import query

# ──────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="Monitoring — HanoiRent",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Monitoring — Giám sát cào dữ liệu")

# Tự động refresh khi mở trang (không cần F5)
# Nút manual refresh luôn hiển thị ở sidebar
with st.sidebar:
    st.header("⚙️ Tuỳ chọn")
    if st.button("🔄 Làm mới dữ liệu", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    n_runs = st.slider("Số run hiển thị", min_value=10, max_value=200, value=50, step=10)
    sources = st.multiselect(
        "Nguồn dữ liệu",
        options=["nhatot", "mogi"],
        default=["nhatot", "mogi"],
    )

# ──────────────────────────────────────────────
# Queries (cache 60s để tránh hit DB liên tục)
# ──────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def load_ingestion_monitor() -> pd.DataFrame:
    rows = query("SELECT * FROM bronze.v_ingestion_monitor ORDER BY source_name")
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def load_recent_runs(limit: int, sources: list[str]) -> pd.DataFrame:
    placeholders = ", ".join(["%s"] * len(sources)) if sources else "''"
    sql = f"""
        SELECT
            run_id,
            source_name,
            spider_name,
            started_at AT TIME ZONE 'Asia/Ho_Chi_Minh' AS started_at,
            finished_at AT TIME ZONE 'Asia/Ho_Chi_Minh' AS finished_at,
            duration_sec,
            total_scraped,
            pass_count,
            quarantine_count,
            duplicate_count,
            error_count,
            pass_rate_pct,
            status
        FROM bronze.scrape_runs
        WHERE source_name IN ({placeholders})
        ORDER BY started_at DESC
        LIMIT %s
    """
    rows = query(sql, tuple(sources) + (limit,))
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def load_daily_trend(sources: list[str]) -> pd.DataFrame:
    """Tổng tin pass + quarantine theo ngày và nguồn."""
    placeholders = ", ".join(["%s"] * len(sources)) if sources else "''"
    sql = f"""
        SELECT
            DATE(started_at AT TIME ZONE 'Asia/Ho_Chi_Minh') AS run_date,
            source_name,
            SUM(pass_count)       AS pass_count,
            SUM(quarantine_count) AS quarantine_count,
            SUM(total_scraped)    AS total_scraped,
            AVG(pass_rate_pct)    AS avg_pass_rate
        FROM bronze.scrape_runs
        WHERE status = 'finished'
          AND source_name IN ({placeholders})
        GROUP BY run_date, source_name
        ORDER BY run_date
    """
    rows = query(sql, tuple(sources))
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def load_silver_missing() -> pd.DataFrame:
    """Đếm % missing values cho các cột quan trọng trong silver.listings."""
    sql = """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN price_vnd    IS NULL THEN 1 ELSE 0 END) AS miss_price,
            SUM(CASE WHEN area_m2      IS NULL THEN 1 ELSE 0 END) AS miss_area,
            SUM(CASE WHEN ward         IS NULL THEN 1 ELSE 0 END) AS miss_ward,
            SUM(CASE WHEN latitude     IS NULL THEN 1 ELSE 0 END) AS miss_lat,
            SUM(CASE WHEN property_type IS NULL THEN 1 ELSE 0 END) AS miss_proptype,
            SUM(CASE WHEN bedrooms     IS NULL THEN 1 ELSE 0 END) AS miss_bedrooms,
            SUM(CASE WHEN posted_at    IS NULL THEN 1 ELSE 0 END) AS miss_posted_at
        FROM silver.listings
    """
    rows = query(sql)
    if not rows:
        return pd.DataFrame()
    row = rows[0]
    total = row["total"] or 1
    cols = {
        "Giá (price_vnd)":      row["miss_price"],
        "Diện tích (area_m2)":  row["miss_area"],
        "Phường (ward)":        row["miss_ward"],
        "Toạ độ (lat/lng)":     row["miss_lat"],
        "Loại hình":            row["miss_proptype"],
        "Số phòng ngủ":         row["miss_bedrooms"],
        "Ngày đăng":            row["miss_posted_at"],
    }
    return pd.DataFrame([
        {"column": k, "missing_count": v, "missing_pct": round(100 * v / total, 1)}
        for k, v in cols.items()
    ])


@st.cache_data(ttl=60, show_spinner=False)
def load_property_type_dist() -> pd.DataFrame:
    sql = """
        SELECT property_type, COUNT(*) AS count
        FROM silver.listings
        WHERE property_type IS NOT NULL
        GROUP BY property_type
        ORDER BY count DESC
    """
    rows = query(sql)
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

def _fmt_vnd(x) -> str:
    if x is None:
        return "—"
    x = int(x)
    if x >= 1_000_000:
        return f"{x/1_000_000:.1f}M"
    if x >= 1_000:
        return f"{x/1_000:.0f}K"
    return str(x)


def _status_badge(s: str) -> str:
    mapping = {
        "finished": "🟢 finished",
        "running":  "🟡 running",
        "failed":   "🔴 failed",
    }
    return mapping.get(s, s)


# ──────────────────────────────────────────────
# Section 1: KPI cards
# ──────────────────────────────────────────────

st.subheader("📌 Tổng quan")

try:
    df_monitor = load_ingestion_monitor()
except Exception as exc:
    st.error(f"Không thể kết nối database: {exc}")
    st.stop()

if df_monitor.empty:
    st.info("Chưa có dữ liệu. Hãy chạy spider lần đầu.")
else:
    # Mỗi nguồn 1 hàng riêng, 5 cột — tránh bị tràn
    for _, row in df_monitor.iterrows():
        src = row["source_name"].upper()
        last = row.get("last_scraped")
        last_str = pd.Timestamp(last).strftime("%d/%m %H:%M") if last else "—"
        pass_rate = row['pass_rate_pct'] or 0

        st.markdown(f"**{src}**")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Tổng hợp lệ",  f"{int(row['pass_count']):,}")
        c2.metric("Quarantine",    f"{int(row['quarantine_count']):,}")
        c3.metric("Pass rate",     f"{pass_rate:.1f}%")
        c4.metric("Tổng scraped",  f"{int(row['total_count']):,}")
        c5.metric("Lần cuối cào",  last_str)

st.divider()

# ──────────────────────────────────────────────
# Section 2: Bảng run gần nhất
# ──────────────────────────────────────────────

st.subheader("🗂️ Lịch sử scraping runs")

try:
    df_runs = load_recent_runs(n_runs, sources)
except Exception as exc:
    st.warning(f"Không load được scrape_runs: {exc}")
    df_runs = pd.DataFrame()

if df_runs.empty:
    st.info("Chưa có run nào được ghi lại. Hãy chạy spider với BronzePipeline enabled.")
else:
    # Format bảng hiển thị
    df_display = df_runs[[
        "run_id", "source_name", "started_at", "duration_sec",
        "total_scraped", "pass_count", "quarantine_count",
        "duplicate_count", "error_count", "pass_rate_pct", "status",
    ]].copy()
    df_display["status"] = df_display["status"].apply(_status_badge)
    df_display["started_at"] = pd.to_datetime(df_display["started_at"]).dt.strftime("%d/%m %H:%M")
    df_display["duration_sec"] = df_display["duration_sec"].apply(
        lambda x: f"{float(x):.0f}s" if x is not None else "—"
    )
    df_display["pass_rate_pct"] = df_display["pass_rate_pct"].apply(
        lambda x: f"{float(x):.1f}%" if x is not None else "—"
    )

    st.dataframe(
        df_display.rename(columns={
            "run_id":          "ID",
            "source_name":     "Nguồn",
            "started_at":      "Bắt đầu",
            "duration_sec":    "Thời gian",
            "total_scraped":   "Scraped",
            "pass_count":      "Pass",
            "quarantine_count":"Quar.",
            "duplicate_count": "Dup.",
            "error_count":     "Lỗi",
            "pass_rate_pct":   "Rate",
            "status":          "Trạng thái",
        }),
        use_container_width=True,
        hide_index=True,
        height=350,
        column_config={
            "ID":         st.column_config.NumberColumn(width="small"),
            "Nguồn":      st.column_config.TextColumn(width="small"),
            "Bắt đầu":    st.column_config.TextColumn(width="medium"),
            "Thời gian":  st.column_config.TextColumn(width="small"),
            "Scraped":    st.column_config.NumberColumn(width="small"),
            "Pass":       st.column_config.NumberColumn(width="small"),
            "Quar.":      st.column_config.NumberColumn(width="small"),
            "Dup.":       st.column_config.NumberColumn(width="small"),
            "Lỗi":        st.column_config.NumberColumn(width="small"),
            "Rate":       st.column_config.TextColumn(width="small"),
            "Trạng thái": st.column_config.TextColumn(width="medium"),
        },
    )

st.divider()

# ──────────────────────────────────────────────
# Section 3: Trend charts
# ──────────────────────────────────────────────

st.subheader("📈 Xu hướng theo ngày")

try:
    df_daily = load_daily_trend(sources)
except Exception as exc:
    st.warning(f"Không load được daily trend: {exc}")
    df_daily = pd.DataFrame()

if not df_daily.empty:
    df_daily["run_date"] = pd.to_datetime(df_daily["run_date"])

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Tổng tin scraped theo ngày (pass vs quarantine)**")
        df_melt = df_daily.melt(
            id_vars=["run_date", "source_name"],
            value_vars=["pass_count", "quarantine_count"],
            var_name="type",
            value_name="count",
        )
        df_melt["type"] = df_melt["type"].map({
            "pass_count":       "Pass ✅",
            "quarantine_count": "Quarantine 🚫",
        })
        df_melt["label"] = df_melt["source_name"] + " — " + df_melt["type"]

        chart_bar = (
            alt.Chart(df_melt)
            .mark_bar(opacity=0.85)
            .encode(
                x=alt.X("run_date:T", title="Ngày", axis=alt.Axis(format="%d/%m")),
                y=alt.Y("count:Q", title="Số tin", stack="zero"),
                color=alt.Color("label:N", title="Nguồn / Loại"),
                tooltip=[
                    alt.Tooltip("run_date:T", title="Ngày", format="%d/%m/%Y"),
                    alt.Tooltip("label:N", title="Loại"),
                    alt.Tooltip("count:Q", title="Số tin"),
                ],
            )
            .properties(height=300)
            .interactive()
        )
        st.altair_chart(chart_bar, use_container_width=True)

    with col2:
        st.markdown("**Pass rate trung bình theo ngày (%)**")
        chart_line = (
            alt.Chart(df_daily)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X("run_date:T", title="Ngày", axis=alt.Axis(format="%d/%m")),
                y=alt.Y("avg_pass_rate:Q", title="Pass rate (%)", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("source_name:N", title="Nguồn"),
                tooltip=[
                    alt.Tooltip("run_date:T", title="Ngày", format="%d/%m/%Y"),
                    alt.Tooltip("source_name:N", title="Nguồn"),
                    alt.Tooltip("avg_pass_rate:Q", title="Pass rate (%)", format=".1f"),
                ],
            )
            .properties(height=300)
            .interactive()
        )
        st.altair_chart(chart_line, use_container_width=True)

st.divider()

# ──────────────────────────────────────────────
# Section 4: Silver data quality
# ──────────────────────────────────────────────

st.subheader("🔍 Chất lượng dữ liệu Silver")

col3, col4 = st.columns([3, 2])

with col3:
    st.markdown("**% Thiếu dữ liệu theo cột (silver.listings)**")
    try:
        df_missing = load_silver_missing()
    except Exception as exc:
        st.warning(f"Không load được silver stats: {exc}")
        df_missing = pd.DataFrame()

    if not df_missing.empty:
        chart_missing = (
            alt.Chart(df_missing)
            .mark_bar(color="#e45756")
            .encode(
                x=alt.X("missing_pct:Q", title="% thiếu", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("column:N", title="", sort="-x"),
                tooltip=[
                    alt.Tooltip("column:N", title="Cột"),
                    alt.Tooltip("missing_count:Q", title="Số tin thiếu"),
                    alt.Tooltip("missing_pct:Q", title="% thiếu", format=".1f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(chart_missing, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu Silver.")

with col4:
    st.markdown("**Phân bố loại hình bất động sản**")
    try:
        df_proptype = load_property_type_dist()
    except Exception as exc:
        st.warning(f"Không load được phân bố property_type: {exc}")
        df_proptype = pd.DataFrame()

    if not df_proptype.empty:
        chart_donut = (
            alt.Chart(df_proptype)
            .mark_arc(innerRadius=60)
            .encode(
                theta=alt.Theta("count:Q"),
                color=alt.Color(
                    "property_type:N",
                    title="Loại hình",
                    scale=alt.Scale(scheme="tableau10"),
                ),
                tooltip=[
                    alt.Tooltip("property_type:N", title="Loại hình"),
                    alt.Tooltip("count:Q", title="Số tin"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(chart_donut, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu Silver.")

st.divider()

# ──────────────────────────────────────────────
# Section 5: Summary table (bảng tổng hợp run mới nhất)
# ──────────────────────────────────────────────

st.subheader("📋 Tóm tắt run mới nhất theo nguồn")

try:
    df_latest_sql = query("""
        SELECT DISTINCT ON (source_name)
            source_name,
            run_id,
            started_at AT TIME ZONE 'Asia/Ho_Chi_Minh' AS started_at,
            total_scraped,
            pass_count,
            quarantine_count,
            duplicate_count,
            error_count,
            pass_rate_pct,
            duration_sec,
            status
        FROM bronze.scrape_runs
        ORDER BY source_name, started_at DESC
    """)
    df_latest = pd.DataFrame(df_latest_sql)
except Exception as exc:
    st.warning(f"Lỗi: {exc}")
    df_latest = pd.DataFrame()

if not df_latest.empty:
    df_latest["started_at"] = pd.to_datetime(df_latest["started_at"]).dt.strftime("%d/%m/%Y %H:%M")
    df_latest["duration_sec"] = df_latest["duration_sec"].apply(
        lambda x: f"{float(x):.0f}s" if x is not None else "—"
    )
    df_latest["pass_rate_pct"] = df_latest["pass_rate_pct"].apply(
        lambda x: f"{float(x):.1f}%" if x is not None else "—"
    )
    st.dataframe(
        df_latest.rename(columns={
            "source_name":     "Nguồn",
            "run_id":          "Run ID",
            "started_at":      "Thời gian chạy",
            "total_scraped":   "Tổng scraped",
            "pass_count":      "Pass ✅",
            "quarantine_count":"Quarantine 🚫",
            "duplicate_count": "Duplicate ⚠️",
            "error_count":     "Lỗi ❌",
            "pass_rate_pct":   "Pass rate",
            "duration_sec":    "Thời gian",
            "status":          "Trạng thái",
        }),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Chưa có run nào hoàn thành.")

# Footnote
st.caption(
    f"Cập nhật lúc {datetime.now(timezone.utc).astimezone().strftime('%H:%M:%S %d/%m/%Y')} — "
    "Cache 60 giây. Nhấn '🔄 Làm mới dữ liệu' để lấy dữ liệu mới nhất."
)

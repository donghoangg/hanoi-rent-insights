"""
Trang Phân tích thị trường — dành cho NGƯỜI ĐI THUÊ.

Khác với 2 trang Monitoring/Quality (phục vụ vận hành pipeline), trang này
hướng tới người dùng cuối: giúp họ NẮM MẶT BẰNG GIÁ theo khu vực để SO SÁNH
khi chọn nhà. Đặt cạnh bản đồ tìm nhà của web app (nhúng iframe).

Bố cục kiểu "analytics dashboard" (gần Power BI):
  - Thanh bộ lọc đồng bộ trên cùng (loại hình, quận/phường, khoảng giá, diện tích)
  - Hàng KPI cards: số tin, giá trung vị, giá/m², khoảng giá phổ biến
  - Lưới biểu đồ:
        A. Giá theo khu vực   — xếp hạng phường, giá/m², boxplot theo loại hình
        B. Cấu trúc thị trường — cơ cấu loại hình & phân khúc, scatter giá–diện tích
        C. Tiện ích            — phần chênh giá khi có từng tiện ích

Nguồn dữ liệu: data_source.load_listings() (tự chọn Supabase hoặc CSV).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data_source import (  # noqa: E402
    AMENITY_COLS,
    AMENITY_LABELS,
    clean_price,
    data_source_label,
    load_listings,
)

# ======================================================================
# Cấu hình trang + theme màu (nhất quán toàn trang, kiểu BI)
# ======================================================================
st.set_page_config(page_title="Phân tích thị trường", page_icon="📊", layout="wide")

# Bảng màu dùng chung
ACCENT = "#2563eb"        # xanh chủ đạo
ACCENT_SOFT = "#93c5fd"
GOOD = "#16a34a"          # rẻ / tốt
BAD = "#dc2626"           # đắt
SEQ = px.colors.sequential.Blues
PROP_COLORS = {
    "Phòng trọ": "#2563eb",
    "Chung cư": "#7c3aed",
    "Nhà nguyên căn": "#0891b2",
    "Căn hộ dịch vụ": "#db2777",
    "Khác": "#94a3b8",
}

PLOTLY_LAYOUT = dict(
    margin=dict(l=10, r=10, t=40, b=10),
    height=340,
    font=dict(family="Inter, system-ui, sans-serif", size=12),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    title=dict(font=dict(size=14)),
)


def fmt_vnd(v: float) -> str:
    """Định dạng tiền gọn: 4.000.000 → '4,0 tr'."""
    if v is None or pd.isna(v):
        return "—"
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f} tr".replace(".", ",")
    if v >= 1_000:
        return f"{v/1_000:.0f}k"
    return f"{v:.0f}"


# CSS nhẹ cho KPI card (Streamlit không có sẵn card đẹp)
st.markdown(
    """
    <style>
      .kpi-card{
        background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);
        border:1px solid #334155;border-radius:14px;padding:16px 18px;
      }
      .kpi-label{color:#94a3b8;font-size:12px;font-weight:600;
        text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;}
      .kpi-value{color:#f8fafc;font-size:26px;font-weight:700;line-height:1.1;}
      .kpi-sub{color:#64748b;font-size:12px;margin-top:2px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def kpi_card(col, label: str, value: str, sub: str = ""):
    col.markdown(
        f"""<div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""",
        unsafe_allow_html=True,
    )


# ======================================================================
# Tải dữ liệu
# ======================================================================
st.title("📊 Phân tích thị trường thuê nhà Hà Nội")
st.caption(
    f"Nguồn: {data_source_label()} · Dùng để tra mặt bằng giá theo khu vực "
    "trước khi quyết định thuê."
)

try:
    df_all = load_listings()
except Exception as e:  # noqa: BLE001
    st.error(f"Không tải được dữ liệu: {e}")
    st.stop()

if df_all.empty:
    st.warning("Chưa có dữ liệu để phân tích.")
    st.stop()

# ======================================================================
# THANH BỘ LỌC ĐỒNG BỘ (áp dụng cho toàn trang) — đặt ở sidebar
# ======================================================================
with st.sidebar:
    st.header("🔎 Bộ lọc")
    if st.button("🔄 Làm mới dữ liệu", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()

    # Loại hình
    types_available = (
        df_all["property_type_label"].dropna().value_counts().index.tolist()
    )
    sel_types = st.multiselect(
        "Loại hình", types_available, default=types_available
    )

    # Quận/phường (ward) — chỉ hiện ward đủ mẫu để đỡ nhiễu
    ward_counts = df_all["ward"].value_counts()
    wards_enough = ward_counts[ward_counts >= 5].index.tolist()
    sel_wards = st.multiselect(
        "Phường/khu vực (để trống = tất cả)",
        sorted(wards_enough),
        default=[],
        help="Chỉ liệt kê phường có từ 5 tin trở lên.",
    )

    # Khoảng giá (triệu/tháng)
    price_clean = clean_price(df_all)
    pmax = float(np.nanpercentile(price_clean["price_vnd"], 99)) / 1_000_000
    price_range = st.slider(
        "Khoảng giá (triệu/tháng)",
        0.0, round(pmax, 1), (0.0, round(pmax, 1)), step=0.5,
    )

    # Khoảng diện tích
    area_valid = df_all[df_all["area_valid"]]
    amax = float(np.nanpercentile(area_valid["area_m2"], 99))
    area_range = st.slider(
        "Diện tích (m²)", 0, int(amax), (0, int(amax)), step=5
    )

# Áp bộ lọc
mask = pd.Series(True, index=df_all.index)
if sel_types:
    mask &= df_all["property_type_label"].isin(sel_types)
if sel_wards:
    mask &= df_all["ward"].isin(sel_wards)
mask &= df_all["price_vnd"].between(
    price_range[0] * 1_000_000, price_range[1] * 1_000_000
)
mask &= df_all["area_m2"].between(area_range[0], area_range[1]) | df_all["area_m2"].isna()

df = df_all[mask]
dfp = clean_price(df)  # tập tin giá sạch sau lọc

if dfp.empty:
    st.warning("Không có tin nào khớp bộ lọc. Hãy nới điều kiện ở thanh bên trái.")
    st.stop()

# ======================================================================
# HÀNG KPI CARDS
# ======================================================================
n_listings = len(df)
median_price = dfp["price_vnd"].median()
ppm = dfp.loc[dfp["area_valid"], "price_per_m2_calc"].median()
p25, p75 = dfp["price_vnd"].quantile([0.25, 0.75])

c1, c2, c3, c4 = st.columns(4)
kpi_card(c1, "Số tin khớp lọc", f"{n_listings:,}".replace(",", "."),
         f"{dfp['ward'].nunique()} phường")
kpi_card(c2, "Giá thuê trung vị", fmt_vnd(median_price), "đồng/tháng")
kpi_card(c3, "Giá theo m²", f"{fmt_vnd(ppm)}/m²" if pd.notna(ppm) else "—",
         "trung vị")
kpi_card(c4, "Khoảng giá phổ biến", f"{fmt_vnd(p25)} – {fmt_vnd(p75)}",
         "p25–p75")

st.divider()

# ======================================================================
# Đặt nội dung theo TAB để gần cảm giác dashboard nhiều trang của BI
# ======================================================================
tab_a, tab_b, tab_c = st.tabs(
    ["💰 Giá theo khu vực", "🏗️ Cấu trúc thị trường", "✨ Tiện ích & giá"]
)

# ----------------------------------------------------------------------
# TAB A — GIÁ THEO KHU VỰC (lõi: trả lời "thuê ở đâu giá bao nhiêu")
# ----------------------------------------------------------------------
with tab_a:
    st.markdown("##### Xếp hạng phường theo giá — chọn loại hình để so công bằng")

    # Loại hình để xếp hạng (so cùng loại mới có nghĩa)
    rank_type = st.radio(
        "Loại hình xếp hạng",
        sorted(dfp["property_type_label"].dropna().unique()),
        horizontal=True,
        key="rank_type",
    )
    sub = dfp[dfp["property_type_label"] == rank_type]

    # Ngưỡng mẫu tối thiểu/phường: ≥10 (chuẩn KPI). Nếu loại hình ít tin khiến
    # không phường nào đạt, hạ xuống ≥5 để vẫn xếp hạng được (có ghi chú).
    min_n = 10
    g = (
        sub.groupby("ward")
        .agg(so_tin=("price_vnd", "size"), median_price=("price_vnd", "median"))
        .query("so_tin >= @min_n")
        .sort_values("median_price")
    )
    if len(g) < 2:
        min_n = 5
        g = (
            sub.groupby("ward")
            .agg(so_tin=("price_vnd", "size"), median_price=("price_vnd", "median"))
            .query("so_tin >= @min_n")
            .sort_values("median_price")
        )

    left, right = st.columns(2)

    with left:
        if len(g) >= 2:
            top_cheap = g.head(10).copy()
            top_cheap["nhan"] = top_cheap["median_price"].apply(fmt_vnd)
            fig = px.bar(
                top_cheap, x="median_price", y=top_cheap.index, orientation="h",
                text="nhan", color_discrete_sequence=[GOOD],
                labels={"median_price": "Giá trung vị (đ/tháng)", "y": ""},
                title=f"10 phường RẺ nhất · {rank_type}",
            )
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_layout(**PLOTLY_LAYOUT, yaxis=dict(categoryorder="total descending"))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Chưa đủ phường (≥10 tin) cho loại hình này để xếp hạng.")

    with right:
        if len(g) >= 2:
            top_exp = g.tail(10).iloc[::-1].copy()
            top_exp["nhan"] = top_exp["median_price"].apply(fmt_vnd)
            fig = px.bar(
                top_exp, x="median_price", y=top_exp.index, orientation="h",
                text="nhan", color_discrete_sequence=[BAD],
                labels={"median_price": "Giá trung vị (đ/tháng)", "y": ""},
                title=f"10 phường ĐẮT nhất · {rank_type}",
            )
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_layout(**PLOTLY_LAYOUT, yaxis=dict(categoryorder="total ascending"))
            st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"Chỉ tính phường có ≥{min_n} tin {rank_type.lower()} để median ổn định "
        f"({len(g)} phường đạt). Đã loại tin giá bất thường (outlier)."
    )

    st.divider()
    cL, cR = st.columns(2)

    # Giá/m² theo phường (top 12 đắt nhất theo m²)
    with cL:
        st.markdown("**Giá theo m² — phường đắt nhất/m²**")
        gm = (
            dfp[dfp["area_valid"]]
            .groupby("ward")
            .agg(so_tin=("price_per_m2_calc", "size"),
                 ppm=("price_per_m2_calc", "median"))
            .query("so_tin >= 10")
            .sort_values("ppm", ascending=False)
            .head(12)
        )
        if not gm.empty:
            gm = gm.iloc[::-1]
            gm["nhan"] = (gm["ppm"] / 1000).round().astype(int).astype(str) + "k"
            fig = px.bar(
                gm, x="ppm", y=gm.index, orientation="h", text="nhan",
                color="ppm", color_continuous_scale=SEQ,
                labels={"ppm": "đồng/m²/tháng", "y": ""},
            )
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_layout(**PLOTLY_LAYOUT, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Chưa đủ dữ liệu diện tích để tính giá/m².")

    # Boxplot giá theo loại hình (độ dao động)
    with cR:
        st.markdown("**Phân bố giá theo loại hình**")
        fig = px.box(
            dfp, x="property_type_label", y="price_vnd", color="property_type_label",
            color_discrete_map=PROP_COLORS, points=False,
            labels={"property_type_label": "", "price_vnd": "Giá (đ/tháng)"},
        )
        fig.update_layout(**PLOTLY_LAYOUT, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Hộp càng cao = giá càng dao động, dễ thương lượng.")

# ----------------------------------------------------------------------
# TAB B — CẤU TRÚC & PHÂN KHÚC THỊ TRƯỜNG
# ----------------------------------------------------------------------
with tab_b:
    cL, cR = st.columns(2)

    # Cơ cấu nguồn cung theo loại hình
    with cL:
        st.markdown("**Cơ cấu nguồn cung theo loại hình**")
        comp = df["property_type_label"].value_counts().reset_index()
        comp.columns = ["loai", "so_tin"]
        fig = px.pie(
            comp, names="loai", values="so_tin", hole=0.5,
            color="loai", color_discrete_map=PROP_COLORS,
        )
        fig.update_traces(textinfo="percent+label", textfont_size=12)
        fig.update_layout(**PLOTLY_LAYOUT, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Cơ cấu phân khúc giá (rẻ / trung bình / cao theo p33-p67 mỗi loại hình)
    with cR:
        st.markdown("**Phân khúc giá theo loại hình**")
        seg = dfp.copy()

        def _segment(grp):
            lo, hi = grp["price_vnd"].quantile([0.33, 0.67])
            return pd.cut(
                grp["price_vnd"], [-np.inf, lo, hi, np.inf],
                labels=["Bình dân", "Trung cấp", "Cao cấp"],
            )

        seg["phan_khuc"] = (
            seg.groupby("property_type_label", group_keys=False).apply(_segment)
        )
        cnt = (
            seg.groupby(["property_type_label", "phan_khuc"], observed=True)
            .size().reset_index(name="so_tin")
        )
        fig = px.bar(
            cnt, x="property_type_label", y="so_tin", color="phan_khuc",
            color_discrete_map={"Bình dân": GOOD, "Trung cấp": ACCENT_SOFT, "Cao cấp": BAD},
            labels={"property_type_label": "", "so_tin": "Số tin", "phan_khuc": "Phân khúc"},
            barmode="stack",
        )
        fig.update_layout(**PLOTLY_LAYOUT, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Phân khúc chia theo p33/p67 trong từng loại hình.")

    st.divider()
    st.markdown("**Tương quan Giá – Diện tích** (mỗi điểm là một tin)")
    sc = dfp[dfp["area_valid"]]
    if not sc.empty:
        fig = px.scatter(
            sc, x="area_m2", y="price_vnd", color="property_type_label",
            color_discrete_map=PROP_COLORS, opacity=0.55,
            trendline="ols", trendline_scope="overall",
            labels={"area_m2": "Diện tích (m²)", "price_vnd": "Giá (đ/tháng)",
                    "property_type_label": "Loại hình"},
        )
        fig.update_layout(**PLOTLY_LAYOUT, height=420,
                          legend=dict(orientation="h", y=-0.18))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Đường xu hướng cho thấy mức tăng giá theo diện tích. Điểm nằm dưới "
            "đường = rẻ hơn mặt bằng cùng diện tích (đáng cân nhắc)."
        )
    else:
        st.info("Chưa đủ dữ liệu diện tích hợp lệ để vẽ scatter.")

# ----------------------------------------------------------------------
# TAB C — TIỆN ÍCH & GIÁ (phần chênh giá khi có từng tiện ích)
# ----------------------------------------------------------------------
with tab_c:
    st.markdown(
        "##### Có tiện ích thì giá chênh bao nhiêu? "
        "(so giá trung vị tin CÓ vs KHÔNG có tiện ích đó)"
    )

    # So sánh trong cùng 1 loại hình để công bằng
    amen_type = st.radio(
        "Xét trên loại hình", sorted(dfp["property_type_label"].dropna().unique()),
        horizontal=True, key="amen_type",
    )
    base = dfp[dfp["property_type_label"] == amen_type]

    rows = []
    for col in AMENITY_COLS:
        if col not in base.columns:
            continue
        has = base[base[col]]["price_vnd"]
        no = base[~base[col]]["price_vnd"]
        if len(has) >= 15 and len(no) >= 15:  # đủ mẫu hai phía
            diff = has.median() - no.median()
            pct = 100 * diff / no.median() if no.median() else 0
            rows.append({
                "tien_ich": AMENITY_LABELS.get(col, col),
                "chenh_pct": pct, "chenh_vnd": diff,
                "n_co": len(has),
            })

    if rows:
        prem = pd.DataFrame(rows).sort_values("chenh_pct")
        prem["mau"] = np.where(prem["chenh_pct"] >= 0, BAD, GOOD)
        prem["nhan"] = prem["chenh_pct"].apply(lambda x: f"{x:+.0f}%")
        fig = go.Figure(go.Bar(
            x=prem["chenh_pct"], y=prem["tien_ich"], orientation="h",
            marker_color=prem["mau"], text=prem["nhan"], textposition="outside",
            hovertemplate="%{y}: %{x:.0f}%<extra></extra>",
        ))
        fig.update_layout(
            **{**PLOTLY_LAYOUT, "height": 420},
            xaxis_title="% chênh giá trung vị so với tin không có tiện ích",
            yaxis_title="",
        )
        fig.add_vline(x=0, line_width=1, line_color="#64748b")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Trên {amen_type.lower()}. Chỉ xét tiện ích có ≥15 tin ở cả hai nhóm. "
            "Lưu ý: đây là tương quan, chưa loại ảnh hưởng của khu vực/diện tích — "
            "đọc như gợi ý, không phải nhân quả tuyệt đối."
        )
    else:
        st.info(
            f"Chưa đủ mẫu để so tiện ích trên {amen_type.lower()}. "
            "Thử chọn loại hình khác hoặc nới bộ lọc."
        )

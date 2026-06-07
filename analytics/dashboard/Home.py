"""
HanoiRent Insights — Streamlit Dashboard
Entry point: chạy `streamlit run analytics/dashboard/Home.py`
"""

import streamlit as st

st.set_page_config(
    page_title="HanoiRent Insights",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏠 HanoiRent Insights")
st.markdown(
    """
    Dashboard phân tích thị trường thuê nhà Hà Nội.

    Dùng menu bên trái để chuyển trang:
    - **Monitoring** — Theo dõi quá trình cào dữ liệu (scraping runs, pass rate, quarantine)
    - **Quality** — Kiểm tra chất lượng dữ liệu Silver (outlier, duplicate, completeness)
    """
)

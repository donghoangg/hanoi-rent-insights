"""
ETL: Bronze → Silver

Đọc từ bronze.listings_raw, transform, upsert vào silver.listings.

Nguồn hỗ trợ: nhatot, mogi
Geocoding: nhatot dùng lat/lng sẵn có từ provider; mogi dùng Nominatim.

Chạy:
    python -m etl.bronze_to_silver
    python -m etl.bronze_to_silver --source nhatot     # chỉ xử lý 1 source
    python -m etl.bronze_to_silver --limit 500         # giới hạn số tin (debug)
    python -m etl.bronze_to_silver --batch-size 50     # batch size (mặc định 100)
"""

from __future__ import annotations

import argparse
import logging
import os
import re

from dotenv import load_dotenv
load_dotenv()
import time
from dataclasses import dataclass, field
from typing import Optional

import psycopg2
import psycopg2.extras
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from geopy.geocoders import Nominatim

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("bronze_to_silver")

# =============================================================
# Constants
# =============================================================

MIN_PRICE = 500_000       # 500k VND/tháng
MAX_PRICE = 100_000_000   # 100 triệu VND/tháng

BATCH_SIZE = 100

# Centroid từng phường phổ biến Hà Nội (fallback geocoding).
# Lat/lng lấy từ trung tâm hành chính phường trên OSM.
WARD_CENTROIDS: dict[str, tuple[float, float]] = {
    # Cầu Giấy
    "Dịch Vọng":          (21.0369, 105.7889),
    "Dịch Vọng Hậu":      (21.0394, 105.7820),
    "Mai Dịch":           (21.0362, 105.7720),
    "Nghĩa Đô":           (21.0424, 105.8001),
    "Nghĩa Tân":          (21.0450, 105.8045),
    "Quan Hoa":           (21.0388, 105.7959),
    "Trung Hoà":          (21.0088, 105.7962),
    "Yên Hoà":            (21.0202, 105.7920),
    # Đống Đa
    "Cát Linh":           (21.0282, 105.8368),
    "Hàng Bột":           (21.0272, 105.8412),
    "Khâm Thiên":         (21.0237, 105.8429),
    "Kim Liên":           (21.0220, 105.8451),
    "Láng Hạ":            (21.0200, 105.8274),
    "Láng Thượng":        (21.0258, 105.8200),
    "Nam Đồng":           (21.0199, 105.8396),
    "Ngã Tư Sở":          (21.0137, 105.8302),
    "Ô Chợ Dừa":          (21.0253, 105.8355),
    "Phương Liên":        (21.0160, 105.8439),
    "Phương Mai":         (21.0131, 105.8468),
    "Quốc Tử Giám":       (21.0292, 105.8355),
    "Thịnh Quang":        (21.0170, 105.8245),
    "Thổ Quan":           (21.0251, 105.8433),
    "Trung Liệt":         (21.0133, 105.8344),
    "Trung Phụng":        (21.0196, 105.8358),
    "Trung Tự":           (21.0160, 105.8471),
    "Văn Chương":         (21.0262, 105.8395),
    "Văn Miếu":           (21.0278, 105.8345),
    "Khương Thượng":      (21.0105, 105.8372),
    # Thanh Xuân
    "Hạ Đình":            (20.9938, 105.8214),
    "Khương Đình":        (20.9999, 105.8204),
    "Khương Mai":         (21.0040, 105.8263),
    "Khương Trung":       (21.0013, 105.8236),
    "Kim Giang":          (20.9906, 105.8285),
    "Nhân Chính":         (21.0040, 105.8140),
    "Phương Liệt":        (21.0063, 105.8368),
    "Thanh Xuân Bắc":     (21.0096, 105.8176),
    "Thanh Xuân Nam":     (21.0012, 105.8149),
    "Thanh Xuân Trung":   (21.0053, 105.8140),
    "Thượng Đình":        (20.9965, 105.8163),
    # Hoàng Mai
    "Định Công":          (20.9819, 105.8414),
    "Đại Kim":            (20.9740, 105.8501),
    "Giáp Bát":           (20.9871, 105.8501),
    "Hoàng Liệt":         (20.9713, 105.8431),
    "Hoàng Văn Thụ":      (20.9938, 105.8417),
    "Lĩnh Nam":           (20.9700, 105.8810),
    "Mai Động":           (20.9969, 105.8657),
    "Tân Mai":            (20.9910, 105.8551),
    "Thanh Trì":          (20.9655, 105.8466),
    "Thịnh Liệt":         (20.9820, 105.8607),
    "Trần Phú":           (20.9888, 105.8355),
    "Tương Mai":          (20.9869, 105.8557),
    "Vĩnh Hưng":          (20.9797, 105.8732),
    "Yên Sở":             (20.9628, 105.8693),
    "Văn Điển":           (20.9558, 105.8440),
    # Hà Đông
    "Biên Giang":         (20.9350, 105.7438),
    "Dương Nội":          (20.9694, 105.7500),
    "Hà Cầu":             (20.9656, 105.7758),
    "Kiến Hưng":          (20.9569, 105.7711),
    "La Khê":             (20.9668, 105.7630),
    "Mộ Lao":             (20.9703, 105.7809),
    "Nguyễn Trãi":        (20.9726, 105.7747),
    "Phú La":             (20.9623, 105.7772),
    "Phú Lãm":            (20.9430, 105.7705),
    "Phú Lương":          (20.9544, 105.7827),
    "Phúc La":            (20.9598, 105.7836),
    "Quang Trung":        (20.9759, 105.7866),
    "Văn Quán":           (20.9773, 105.7920),
    "Vạn Phúc":           (20.9700, 105.7561),
    "Yên Nghĩa":          (20.9454, 105.7630),
    # Tây Hồ
    "Bưởi":               (21.0534, 105.8240),
    "Nhật Tân":           (21.0840, 105.8420),
    "Phú Thượng":         (21.0974, 105.8483),
    "Quảng An":           (21.0638, 105.8388),
    "Tứ Liên":            (21.0738, 105.8448),
    "Xuân La":            (21.0700, 105.8201),
    "Yên Phụ":            (21.0512, 105.8494),
    "Thụy Khuê":          (21.0481, 105.8288),
    # Ba Đình
    "Cống Vị":            (21.0358, 105.8368),
    "Điện Biên":          (21.0368, 105.8417),
    "Đội Cấn":            (21.0438, 105.8286),
    "Giảng Võ":           (21.0290, 105.8267),
    "Kim Mã":             (21.0330, 105.8288),
    "Liễu Giai":          (21.0395, 105.8284),
    "Ngọc Hà":            (21.0418, 105.8369),
    "Ngọc Khánh":         (21.0302, 105.8203),
    "Phúc Xá":            (21.0462, 105.8510),
    "Quán Thánh":         (21.0411, 105.8457),
    "Thành Công":         (21.0240, 105.8200),
    "Trúc Bạch":          (21.0445, 105.8478),
    "Vĩnh Phúc":          (21.0418, 105.8256),
    # Hai Bà Trưng
    "Bách Khoa":          (21.0041, 105.8488),
    "Bạch Đằng":          (21.0112, 105.8600),
    "Bạch Mai":           (21.0086, 105.8491),
    "Cầu Dền":            (21.0089, 105.8437),
    "Đồng Nhân":          (21.0109, 105.8548),
    "Đồng Tâm":           (21.0041, 105.8583),
    "Lê Đại Hành":        (21.0134, 105.8489),
    "Minh Khai":          (21.0011, 105.8602),
    "Nguyễn Du":          (21.0209, 105.8494),
    "Phố Huế":            (21.0192, 105.8530),
    "Phương Liên":        (21.0160, 105.8439),
    "Quỳnh Lôi":          (21.0025, 105.8566),
    "Quỳnh Mai":          (21.0060, 105.8544),
    "Thanh Lương":        (21.0001, 105.8654),
    "Thanh Nhàn":         (21.0061, 105.8567),
    "Trương Định":        (21.0000, 105.8508),
    "Vĩnh Tuy":           (21.0026, 105.8674),
    # Long Biên
    "Bồ Đề":              (21.0400, 105.8900),
    "Cự Khối":            (21.0217, 105.9188),
    "Đức Giang":          (21.0540, 105.8818),
    "Gia Thụy":           (21.0538, 105.8970),
    "Giang Biên":         (21.0700, 105.9104),
    "Long Biên":          (21.0482, 105.8898),
    "Ngọc Lâm":           (21.0475, 105.8890),
    "Ngọc Thụy":          (21.0551, 105.8733),
    "Phúc Đồng":          (21.0596, 105.9018),
    "Phúc Lợi":           (21.0656, 105.9072),
    "Sài Đồng":           (21.0560, 105.9100),
    "Thạch Bàn":          (21.0325, 105.9134),
    "Thượng Thanh":       (21.0695, 105.9018),
    "Việt Hưng":          (21.0618, 105.9002),
    # Nam Từ Liêm
    "Cầu Diễn":           (21.0402, 105.7629),
    "Đại Mỗ":             (20.9934, 105.7513),
    "Mễ Trì":             (21.0030, 105.7832),
    "Mỹ Đình 1":          (21.0274, 105.7762),
    "Mỹ Đình 2":          (21.0232, 105.7727),
    "Phú Đô":             (21.0079, 105.7593),
    "Phương Canh":        (21.0307, 105.7538),
    "Tây Mỗ":             (20.9982, 105.7596),
    "Trung Văn":          (21.0065, 105.7831),
    "Xuân Phương":        (21.0368, 105.7534),
    # Bắc Từ Liêm
    "Cổ Nhuế 1":          (21.0621, 105.7731),
    "Cổ Nhuế 2":          (21.0725, 105.7710),
    "Đông Ngạc":          (21.0837, 105.7924),
    "Đức Thắng":          (21.0766, 105.8003),
    "Liên Mạc":           (21.1017, 105.7782),
    "Minh Khai":          (21.0690, 105.7819),
    "Phú Diễn":           (21.0524, 105.7628),
    "Phúc Diễn":          (21.0597, 105.7580),
    "Tây Tựu":            (21.0921, 105.7615),
    "Thượng Cát":         (21.1049, 105.7894),
    "Thụy Phương":        (21.0914, 105.8030),
    "Xuân Đỉnh":          (21.0768, 105.7924),
    "Xuân Tảo":           (21.0693, 105.7825),
    # Hoàn Kiếm
    "Chương Dương":       (21.0360, 105.8613),
    "Cửa Đông":           (21.0335, 105.8520),
    "Cửa Nam":            (21.0269, 105.8465),
    "Đồng Xuân":          (21.0384, 105.8494),
    "Hàng Bạc":           (21.0334, 105.8505),
    "Hàng Bài":           (21.0261, 105.8514),
    "Hàng Bồ":            (21.0351, 105.8481),
    "Hàng Buồm":          (21.0363, 105.8510),
    "Hàng Gai":           (21.0326, 105.8491),
    "Hàng Mã":            (21.0378, 105.8479),
    "Hàng Trống":         (21.0310, 105.8498),
    "Lý Thái Tổ":         (21.0289, 105.8502),
    "Phan Chu Trinh":     (21.0253, 105.8508),
    "Phúc Tân":           (21.0406, 105.8567),
    "Tràng Tiền":         (21.0258, 105.8547),
    "Trần Hưng Đạo":      (21.0230, 105.8528),
    "Hàng Đào":           (21.0340, 105.8495),
}

# Province normalize: các alias → chuẩn
# Tên quận/huyện Hà Nội — dùng để filter khi tách ward từ địa chỉ text.
# Địa chỉ dạng "phố, phường, quận, Hà Nội" — nếu không có prefix "quận"
# thì vẫn cần nhận ra và bỏ qua phần tử này khi tìm ward.
HANOI_DISTRICT_NAMES = {
    "ba đình", "hoàn kiếm", "hai bà trưng", "đống đa", "tây hồ",
    "cầu giấy", "thanh xuân", "hoàng mai", "long biên", "nam từ liêm",
    "bắc từ liêm", "hà đông", "sóc sơn", "đông anh", "gia lâm",
    "thanh trì", "mê linh", "thạch thất", "quốc oai", "hoài đức",
    "chương mỹ", "đan phượng", "ba vì", "phúc thọ", "thường tín",
    "thanh oai", "mỹ đức", "ứng hòa", "phú xuyên", "sơn tây",
}

PROVINCE_ALIASES = {
    "tp hà nội": "Hà Nội",
    "thành phố hà nội": "Hà Nội",
    "ha noi": "Hà Nội",
    "hanoi": "Hà Nội",
    "hn": "Hà Nội",
}

# Amenity patterns: key → (positive_regex, negative_lookaround_prefix)
# negative_prefix: nếu match với prefix này ngay trước keyword → bỏ qua
AMENITY_PATTERNS: dict[str, str] = {
    # Khớp với các cột boolean trong silver.listings
    "has_air_conditioner":  r"điều ho[àa]|máy lạnh|air[\s\-]?con",
    "has_water_heater":     r"nóng lạnh|bình nóng lạnh|máy nước nóng",
    "has_fridge":           r"tủ lạnh",
    "has_washing_machine":  r"máy giặt",
    "has_furniture":        r"giường|tủ|nội thất|đầy đủ đồ|có đồ|full đồ",
    "has_wifi":             r"wifi|wi[\s\-]fi|internet miễn phí|mạng miễn phí",
    "has_kitchen":          r"bếp riêng|nhà bếp|nấu ăn|bếp nấu|tủ bếp|kệ bếp",
    "is_self_contained":    r"khép kín|wc riêng|nhà vệ sinh riêng|toilet riêng|phòng tắm riêng",
    "free_hours":           r"giờ (giấc )?tự do|tự do giờ giấc|ra vào tự do|không giờ giấc",
    "landlord_shared":      r"chung chủ|ở cùng chủ|chủ nhà ở|có chủ ở",
    "good_security":        r"bảo vệ 24|an ninh 24|camera an ninh|cổng từ|có bảo vệ|an ninh tốt",
    "near_market":          r"gần chợ|cạnh chợ|gần siêu thị|cạnh siêu thị",
}

# Regex để detect negation trước keyword (trong vòng 40 ký tự trước match)
NEGATION_RE = re.compile(r"không\s*(có)?|cấm|không\s+cho\s+phép|không\s+được|k\s+có|ko\s+có")


# =============================================================
# Dataclass: SilverRow — đại diện 1 row sẽ upsert vào silver
# =============================================================

@dataclass
class SilverRow:
    source_name: str
    source_id: str
    source_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    price_vnd: Optional[int] = None
    area_m2: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    property_type: Optional[str] = None
    furnishing_level: Optional[str] = None
    address: Optional[str] = None
    province: Optional[str] = "Hà Nội"
    ward: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocode_source: Optional[str] = None
    # amenities — tên khớp với cột boolean trong silver.listings
    has_air_conditioner: bool = False
    has_water_heater: bool = False
    has_fridge: bool = False
    has_washing_machine: bool = False
    has_furniture: bool = False
    has_wifi: bool = False
    has_kitchen: bool = False
    is_self_contained: bool = False
    free_hours: bool = False
    landlord_shared: bool = False
    good_security: bool = False
    near_market: bool = False
    # thumbnail
    original_thumbnail_url: Optional[str] = None
    thumbnail_status: str = "pending"
    # quality
    price_status: str = "ok"
    posted_at: Optional[str] = None


# =============================================================
# Geocoder wrapper
# =============================================================

class GeocoderWrapper:
    """
    Wrapper quanh Nominatim với cache DB.
    Fallback xuống ward centroid nếu Nominatim fail.
    """

    def __init__(self, conn: psycopg2.extensions.connection):
        self._conn = conn
        self._geolocator = Nominatim(user_agent="hanoi-rent-insights-etl/1.0")
        self._mem_cache: dict[str, tuple[Optional[float], Optional[float], str]] = {}
        self._load_db_cache()

    def _load_db_cache(self):
        """Load toàn bộ cache từ DB vào memory để tránh query lặp."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT address_key, latitude, longitude, status FROM silver.geocode_cache")
            for row in cur.fetchall():
                self._mem_cache[row[0]] = (row[1], row[2], row[3])
        logger.info("Geocode cache loaded: %d entries", len(self._mem_cache))

    def _cache_key(self, address: str) -> str:
        """Normalize address thành key ổn định."""
        return re.sub(r"\s+", " ", address.lower().strip())

    def _save_to_db(self, key: str, lat: Optional[float], lng: Optional[float], src: str):
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO silver.geocode_cache (address_key, latitude, longitude, status, provider)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (address_key) DO NOTHING
                """,
                (key, lat, lng, "success" if lat is not None else "failed", src),
            )
        self._conn.commit()

    def geocode(self, address: str, ward: Optional[str] = None) -> tuple[Optional[float], Optional[float], str]:
        """
        Trả về (lat, lng, source).
        source: 'nominatim' | 'ward_centroid' | 'failed'
        """
        key = self._cache_key(address)

        # 1. Kiểm tra memory cache
        if key in self._mem_cache:
            return self._mem_cache[key]

        # 2. Thử Nominatim với địa chỉ đầy đủ
        lat, lng, src = self._try_nominatim(address + ", Hà Nội, Việt Nam")

        # 3. Nếu fail, thử với ward + Hà Nội
        if lat is None and ward:
            ward_key = self._cache_key(ward + ", Hà Nội")
            if ward_key in self._mem_cache:
                lat, lng, src = self._mem_cache[ward_key]
            else:
                lat, lng, src = self._try_nominatim(ward + ", Hà Nội, Việt Nam")
                if lat is not None:
                    # Cache riêng cho ward-level query
                    self._mem_cache[ward_key] = (lat, lng, src)
                    self._save_to_db(ward_key, lat, lng, src)

        # 4. Fallback: ward centroid hardcode
        if lat is None and ward:
            centroid = self._lookup_ward_centroid(ward)
            if centroid:
                lat, lng, src = centroid[0], centroid[1], "ward_centroid"

        result = (lat, lng, src or "failed")
        self._mem_cache[key] = result
        self._save_to_db(key, lat, lng, result[2])
        return result

    def _try_nominatim(self, query: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
        """Gọi Nominatim, rate-limit 1 req/s. Trả (lat, lng, 'nominatim') hoặc (None, None, None)."""
        time.sleep(1.1)  # Nominatim ToS: max 1 req/giây
        try:
            location = self._geolocator.geocode(
                query,
                exactly_one=True,
                timeout=10,
                language="vi",
                country_codes="vn",
            )
            if location:
                return location.latitude, location.longitude, "nominatim"
        except (GeocoderTimedOut, GeocoderServiceError) as exc:
            logger.warning("Nominatim error for '%s': %s", query[:60], exc)
        except Exception as exc:
            logger.error("Unexpected geocoder error: %s", exc)
        return None, None, None

    def _lookup_ward_centroid(self, ward: str) -> Optional[tuple[float, float]]:
        """Tìm centroid từ WARD_CENTROIDS, thử các biến thể tên."""
        ward_clean = _normalize_ward(ward)
        if ward_clean in WARD_CENTROIDS:
            return WARD_CENTROIDS[ward_clean]
        # Thử không dấu hoặc tên rút gọn
        for known_ward, coords in WARD_CENTROIDS.items():
            if known_ward.lower() in ward_clean.lower() or ward_clean.lower() in known_ward.lower():
                return coords
        return None


# =============================================================
# Normalize helpers
# =============================================================

def _normalize_province(raw: Optional[str]) -> str:
    if not raw:
        return "Hà Nội"
    normalized = raw.strip()
    alias = PROVINCE_ALIASES.get(normalized.lower())
    if alias:
        return alias
    # Strip tiền tố "TP.", "Thành phố "
    normalized = re.sub(r"^(tp\.?\s*|thành\s+phố\s+)", "", normalized, flags=re.IGNORECASE).strip()
    return normalized or "Hà Nội"


def _normalize_ward(raw: Optional[str]) -> Optional[str]:
    """Bỏ tiền tố 'Phường', 'Xã', 'P.', strip, title case."""
    if not raw:
        return None
    cleaned = re.sub(
        r"^(phường\s+|xã\s+|thị\s+trấn\s+|p\.\s*|tt\s+)",
        "",
        raw.strip(),
        flags=re.IGNORECASE,
    ).strip()
    # Title case chuẩn (giữ dấu tiếng Việt)
    return cleaned if cleaned else None


def _normalize_price(raw) -> tuple[Optional[int], str]:
    """
    Parse giá → (price_vnd, price_status).
    price_status: 'ok' | 'suspect' | 'missing'
    """
    if raw is None:
        return None, "missing"
    try:
        price = int(float(str(raw).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None, "missing"

    if price == 0:
        return None, "missing"
    if price < MIN_PRICE or price > MAX_PRICE:
        return price, "suspect"
    return price, "ok"


def _parse_area(raw) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", ".").strip())
    except (ValueError, TypeError):
        return None


def _parse_int(raw) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


# =============================================================
# Amenity extractor
# =============================================================

def _extract_amenities(title: Optional[str], description: Optional[str]) -> dict[str, bool]:
    """
    Quét title + description để xác định các boolean amenity.
    Xử lý negation: nếu trong 40 ký tự trước match có 'không', 'cấm',... → bỏ qua.
    """
    text = ((title or "") + " " + (description or "")).lower()
    results = {}
    for amenity_key, pattern in AMENITY_PATTERNS.items():
        matched = False
        for m in re.finditer(pattern, text, re.IGNORECASE):
            # Lấy đoạn trước match để kiểm tra negation
            prefix_start = max(0, m.start() - 40)
            prefix = text[prefix_start:m.start()]
            if NEGATION_RE.search(prefix):
                continue  # Bị phủ định → bỏ qua match này
            matched = True
            break
        results[amenity_key] = matched
    return results


# =============================================================
# Source-specific parsers
# =============================================================

# Nhatot: category code → property_type (mirror từ spider)
_NHATOT_CATEGORY_MAP: dict[str, str] = {
    "1050": "phong_tro",
    "1010": "chung_cu",
    "1020": "nha_nguyen_can",
}
_NHATOT_HOUSE_TYPE_MAP: dict[int, str] = {
    5: "can_ho_dich_vu",
    7: "can_ho_dich_vu",
}

# Mogi: prop_type_text → property_type
_MOGI_PROP_TYPE_MAP: dict[str, str] = {
    "phòng trọ":          "phong_tro",
    "nhà trọ":            "phong_tro",
    "chung cư":           "chung_cu",
    "căn hộ":             "chung_cu",
    "căn hộ dịch vụ":    "can_ho_dich_vu",
    "nhà nguyên căn":     "nha_nguyen_can",
    "nhà riêng":          "nha_nguyen_can",
    "biệt thự":           "nha_nguyen_can",
}


def _map_nhatot_property_type(raw_payload: dict) -> Optional[str]:
    """Suy ra property_type từ category + house_type trong raw_payload nhatot."""
    category   = str(raw_payload.get("category") or "")
    house_type = raw_payload.get("house_type")
    base = _NHATOT_CATEGORY_MAP.get(category, "phong_tro")
    if house_type is not None:
        override = _NHATOT_HOUSE_TYPE_MAP.get(int(house_type))
        if override:
            return override
    return base


def _map_mogi_property_type(raw_payload: dict) -> Optional[str]:
    """Map prop_type_text từ raw_payload mogi → property_type chuẩn."""
    text = (raw_payload.get("prop_type_text") or "").lower().strip()
    if not text:
        return None
    for key, val in _MOGI_PROP_TYPE_MAP.items():
        if key in text:
            return val
    # Fallback: tìm trong URL
    url = (raw_payload.get("url") or "").lower()
    if "phong-tro" in url or "nha-tro" in url:
        return "phong_tro"
    if "can-ho" in url or "chung-cu" in url:
        return "chung_cu"
    if "nha-nguyen-can" in url or "nha-rieng" in url:
        return "nha_nguyen_can"
    return None


def _parse_nhatot(raw_payload: dict) -> dict:
    """
    Parse raw_payload từ nhatot spider.
    Spider đã xử lý hầu hết fields — chỉ cần đọc ra và chuẩn hoá thêm.
    """
    return {
        "title":           raw_payload.get("subject") or raw_payload.get("title"),
        "description":     raw_payload.get("body") or raw_payload.get("description"),
        "price_vnd_raw":   raw_payload.get("price") or raw_payload.get("price_vnd"),
        "area_m2":         raw_payload.get("size") or raw_payload.get("area"),
        "bedrooms":        raw_payload.get("rooms") or raw_payload.get("room"),
        "bathrooms":       raw_payload.get("toilets") or raw_payload.get("toilet"),
        "property_type":   raw_payload.get("property_type") or _map_nhatot_property_type(raw_payload),
        "furnishing_level":raw_payload.get("furnishing_level"),
        "address":         raw_payload.get("address"),
        "province":        raw_payload.get("region_name"),
        "ward":            raw_payload.get("ward_name"),
        # Nhatot cung cấp lat/lng trực tiếp từ provider
        "latitude":        raw_payload.get("_lat") or raw_payload.get("latitude"),
        "longitude":       raw_payload.get("_lng") or raw_payload.get("longitude"),
        "geocode_source":  "provider" if (raw_payload.get("_lat") or raw_payload.get("latitude")) else None,
        "posted_at":       raw_payload.get("posted_at") or raw_payload.get("list_time"),
        "source_url":      raw_payload.get("url") or raw_payload.get("source_url"),
    }


def _parse_mogi(raw_payload: dict) -> dict:
    """
    Parse raw_payload từ mogi spider.
    raw_payload chứa price_text, area_text thô + address, description, source_url.
    Giá cần parse lại từ price_text.
    """

    def _parse_mogi_price(text: Optional[str]) -> Optional[int]:
        """Parse giá từ text Mogi: '2.5 triệu/tháng', '2,500,000 đ/tháng'..."""
        if not text:
            return None
        t = text.lower().strip()

        multiplier = 1
        if "tỷ" in t:
            multiplier = 1_000_000_000
        elif any(w in t for w in ("triệu", "tr/", " tr", "tr.")):
            multiplier = 1_000_000
        elif "nghìn" in t or "ngàn" in t:
            multiplier = 1_000

        nums = re.findall(r"[\d]+(?:[.,][\d]+)?", t)
        if not nums:
            return None
        # Lấy số đầu tiên, xử lý dấu phẩy/chấm
        num_str = nums[0].replace(",", ".")
        try:
            val = float(num_str)
        except ValueError:
            return None

        result = int(val * multiplier)
        # Nếu multiplier=1 và giá có vẻ nhỏ (nhập thiếu đơn vị)
        if multiplier == 1:
            if 0 < result < 1_000:
                result *= 1_000_000
            elif 0 < result < 100_000:
                result *= 1_000
        return result if result > 0 else None

    def _parse_mogi_area(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        m = re.search(r"([\d]+(?:[.,][\d]+)?)\s*m", text.replace(",", "."))
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    price_raw = _parse_mogi_price(raw_payload.get("price_text"))
    area_raw = _parse_mogi_area(raw_payload.get("area_text"))

    return {
        "title":            raw_payload.get("title"),
        "description":      raw_payload.get("description"),
        "price_vnd_raw":    price_raw,
        "area_m2":          area_raw,
        "bedrooms":         None,   # Mogi không có trong raw_payload (parse từ detail page)
        "bathrooms":        None,
        "property_type":    raw_payload.get("property_type") or _map_mogi_property_type(raw_payload),
        "furnishing_level": None,
        "address":          raw_payload.get("address"),
        "province":         None,   # sẽ extract từ address
        "ward":             None,   # sẽ extract từ address
        "latitude":         None,   # cần geocode
        "longitude":        None,
        "geocode_source":   None,
        "posted_at":        None,
        "source_url":       raw_payload.get("url") or raw_payload.get("source_url"),
    }


def _extract_address_parts(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Tách province và ward từ địa chỉ text dạng 'số nhà, phố, phường, [quận,] tỉnh'.
    Trả (province, ward).
    """
    if not address:
        return "Hà Nội", None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return "Hà Nội", None

    province = _normalize_province(parts[-1])

    ward = None
    for part in parts:
        low = part.lower()
        if re.match(r"(phường|xã|p\.|tt |thị trấn)", low):
            ward = _normalize_ward(part)
            break
    # Fallback: phần tử áp cuối nếu không tìm được ward keyword
    if not ward and len(parts) >= 2:
        # Duyệt từ phần tử áp cuối trở về trước, bỏ qua tên quận/huyện
        for candidate in reversed(parts[:-1]):
            low = candidate.lower().strip()
            # Bỏ qua nếu có prefix quận/huyện hoặc tên quận trong danh sách
            if re.match(r"(quận|huyện|q\.|h\.)", low):
                continue
            if low in HANOI_DISTRICT_NAMES:
                continue
            ward = _normalize_ward(candidate)
            break

    return province, ward


# =============================================================
# Thumbnail picker
# =============================================================

def _fetch_thumbnails_batch(
    conn: psycopg2.extensions.connection,
    keys: list[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """
    Batch query thumbnail order=0 cho danh sách (source_name, source_id).
    Trả dict: (source_name, source_id) → image_url
    """
    if not keys:
        return {}
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            SELECT b.source_name, b.source_id, b.image_url
            FROM bronze.listing_images_raw b
            JOIN (VALUES %s) AS v(sn, sid) ON b.source_name = v.sn AND b.source_id = v.sid
            WHERE b.image_order = 0
            """,
            keys,
        )
        return {(row[0], row[1]): row[2] for row in cur.fetchall()}


# =============================================================
# Bronze reader
# =============================================================

def _read_bronze_batch(
    conn: psycopg2.extensions.connection,
    source_name: Optional[str],
    limit: int,
) -> list[dict]:
    """
    Đọc batch từ bronze.listings_raw, chỉ lấy những tin CHƯA có trong silver
    (tránh re-process khi chạy lại — idempotent).
    Không dùng OFFSET vì sau mỗi batch upsert, các row đã xử lý biến khỏi
    LEFT JOIN WHERE IS NULL, nên query luôn trả về "top N còn lại".
    """
    where_source = "AND b.source_name = %s" if source_name else ""
    params: list = []
    if source_name:
        params.append(source_name)
    params.append(limit)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT b.id, b.source_name, b.source_id, b.source_url,
                   b.raw_payload, b.scraped_at
            FROM bronze.listings_raw b
            LEFT JOIN silver.listings s
                ON b.source_name = s.source_name AND b.source_id = s.source_id
            WHERE s.listing_id IS NULL
              {where_source}
            ORDER BY b.id
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


# =============================================================
# Upsert silver
# =============================================================

_UPSERT_SQL = """
INSERT INTO silver.listings (
    source_name, source_id, source_url,
    title, description,
    price_vnd, area_m2, bedrooms, bathrooms,
    property_type, furnishing_level,
    address, province, ward,
    latitude, longitude, geocode_status,
    has_air_conditioner, has_water_heater, has_fridge, has_washing_machine,
    has_furniture, has_wifi, has_kitchen, is_self_contained,
    free_hours, landlord_shared, good_security, near_market,
    original_thumbnail_url, thumbnail_status,
    price_status, posted_at,
    created_at, updated_at
)
VALUES %s
ON CONFLICT (source_name, source_id) DO UPDATE SET
    title                  = EXCLUDED.title,
    description            = EXCLUDED.description,
    price_vnd              = EXCLUDED.price_vnd,
    area_m2                = EXCLUDED.area_m2,
    bedrooms               = EXCLUDED.bedrooms,
    bathrooms              = EXCLUDED.bathrooms,
    property_type          = EXCLUDED.property_type,
    furnishing_level       = EXCLUDED.furnishing_level,
    address                = EXCLUDED.address,
    province               = EXCLUDED.province,
    ward                   = EXCLUDED.ward,
    latitude               = EXCLUDED.latitude,
    longitude              = EXCLUDED.longitude,
    geocode_status         = EXCLUDED.geocode_status,
    has_air_conditioner    = EXCLUDED.has_air_conditioner,
    has_water_heater       = EXCLUDED.has_water_heater,
    has_fridge             = EXCLUDED.has_fridge,
    has_washing_machine    = EXCLUDED.has_washing_machine,
    has_furniture          = EXCLUDED.has_furniture,
    has_wifi               = EXCLUDED.has_wifi,
    has_kitchen            = EXCLUDED.has_kitchen,
    is_self_contained      = EXCLUDED.is_self_contained,
    free_hours             = EXCLUDED.free_hours,
    landlord_shared        = EXCLUDED.landlord_shared,
    good_security          = EXCLUDED.good_security,
    near_market            = EXCLUDED.near_market,
    original_thumbnail_url = EXCLUDED.original_thumbnail_url,
    thumbnail_status       = CASE
        WHEN silver.listings.thumbnail_status = 'success' THEN 'success'
        ELSE EXCLUDED.thumbnail_status
    END,
    price_status           = EXCLUDED.price_status,
    posted_at              = EXCLUDED.posted_at,
    updated_at             = NOW()
"""

def _row_to_tuple(r: SilverRow):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    # geocode_status: map geocode_source → enum value của schema
    # Lưu ý: khi đọc từ DB cache, geocode_source có thể là status value ('success','failed')
    # thay vì provider name ('nominatim','provider') — cần handle cả 2 trường hợp
    geocode_src_map = {
        "provider":      "success",
        "nominatim":     "success",
        "ward_centroid": "centroid",
        "centroid":      "centroid",   # đọc từ cache
        "success":       "success",    # đọc từ cache
        "failed":        "failed",
        None:            "pending",
    }
    geocode_status = geocode_src_map.get(r.geocode_source, "pending")
    return (
        r.source_name, r.source_id, r.source_url,
        r.title, r.description,
        r.price_vnd, r.area_m2, r.bedrooms, r.bathrooms,
        r.property_type, r.furnishing_level,
        r.address, r.province, r.ward,
        r.latitude, r.longitude, geocode_status,
        r.has_air_conditioner, r.has_water_heater, r.has_fridge, r.has_washing_machine,
        r.has_furniture, r.has_wifi, r.has_kitchen, r.is_self_contained,
        r.free_hours, r.landlord_shared, r.good_security, r.near_market,
        r.original_thumbnail_url, r.thumbnail_status,
        r.price_status, r.posted_at,
        now, now,
    )


def _upsert_batch(conn: psycopg2.extensions.connection, rows: list[SilverRow]):
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            _UPSERT_SQL,
            [_row_to_tuple(r) for r in rows],
        )
    conn.commit()


# =============================================================
# Main transform logic
# =============================================================

def _transform_one(bronze_row: dict, geocoder: GeocoderWrapper) -> Optional[SilverRow]:
    """
    Transform 1 bronze row → SilverRow.
    Trả None nếu không thể tạo row hợp lệ.
    """
    source_name: str = bronze_row["source_name"]
    source_id: str = bronze_row["source_id"]
    raw_payload: dict = bronze_row.get("raw_payload") or {}

    # 1. Parse theo source
    if source_name == "nhatot":
        parsed = _parse_nhatot(raw_payload)
    elif source_name == "mogi":
        parsed = _parse_mogi(raw_payload)
    else:
        logger.warning("Unknown source '%s' — skip %s", source_name, source_id)
        return None

    # 2. Chuẩn hoá giá
    price_vnd, price_status = _normalize_price(parsed.get("price_vnd_raw"))

    # 3. Parse area + int fields
    area_m2 = _parse_area(parsed.get("area_m2"))
    bedrooms = _parse_int(parsed.get("bedrooms"))
    bathrooms = _parse_int(parsed.get("bathrooms"))

    # 4. Chuẩn hoá địa chỉ
    address = (parsed.get("address") or "").strip() or None
    province_raw = parsed.get("province")
    ward_raw = parsed.get("ward")

    if province_raw or ward_raw:
        province = _normalize_province(province_raw)
        ward = _normalize_ward(ward_raw)
    else:
        # Mogi: tách từ địa chỉ text
        province, ward = _extract_address_parts(address)

    # 5. Geocoding
    lat = parsed.get("latitude")
    lng = parsed.get("longitude")
    geocode_source = parsed.get("geocode_source")

    if lat is None or lng is None:
        # Chỉ geocode nếu có địa chỉ hoặc ward
        if address or ward:
            query_address = address or (ward + ", Hà Nội")
            lat, lng, geocode_source = geocoder.geocode(query_address, ward=ward)
        else:
            geocode_source = "failed"

    # Validate lat/lng hợp lệ cho Hà Nội (bounding box xấp xỉ)
    if lat is not None and lng is not None:
        if not (20.5 < float(lat) < 21.5 and 105.3 < float(lng) < 106.1):
            logger.debug("Lat/lng out of Hanoi bbox for %s:%s — set to None", source_name, source_id)
            lat, lng, geocode_source = None, None, "failed"

    # 6. Amenities
    amenities = _extract_amenities(parsed.get("title"), parsed.get("description"))

    # 7. posted_at — đảm bảo là string ISO date hoặc None
    posted_at_raw = parsed.get("posted_at")
    posted_at = None
    if posted_at_raw:
        posted_at_str = str(posted_at_raw).strip()
        # Nếu là unix timestamp ms
        if re.match(r"^\d{13}$", posted_at_str):
            try:
                from datetime import datetime, timezone
                posted_at = datetime.fromtimestamp(int(posted_at_str) / 1000, tz=timezone.utc).date().isoformat()
            except Exception:
                pass
        elif re.match(r"^\d{4}-\d{2}-\d{2}", posted_at_str):
            posted_at = posted_at_str[:10]
        # Nếu định dạng khác → để None (không đoán mò)

    return SilverRow(
        source_name=source_name,
        source_id=source_id,
        source_url=parsed.get("source_url") or bronze_row.get("source_url"),
        title=parsed.get("title"),
        description=parsed.get("description"),
        price_vnd=price_vnd,
        area_m2=area_m2,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type=parsed.get("property_type"),
        furnishing_level=parsed.get("furnishing_level"),
        address=address,
        province=province,
        ward=ward,
        latitude=float(lat) if lat is not None else None,
        longitude=float(lng) if lng is not None else None,
        geocode_source=geocode_source,
        price_status=price_status,
        posted_at=posted_at,
        **amenities,
    )


# =============================================================
# ETL runner
# =============================================================

def run(
    database_url: str,
    source_name: Optional[str] = None,
    limit: Optional[int] = None,
    batch_size: int = BATCH_SIZE,
):
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    logger.info("Connected to database")

    geocoder = GeocoderWrapper(conn)

    total_processed = 0
    total_inserted = 0
    total_skipped = 0

    while True:
        effective_limit = batch_size
        if limit is not None:
            effective_limit = min(batch_size, limit - total_processed)
            if effective_limit <= 0:
                break

        bronze_rows = _read_bronze_batch(conn, source_name, effective_limit)
        if not bronze_rows:
            break

        # Batch fetch thumbnails cho tất cả row trong batch
        keys = [(r["source_name"], r["source_id"]) for r in bronze_rows]
        thumbnails = _fetch_thumbnails_batch(conn, keys)

        silver_rows: list[SilverRow] = []
        for bronze_row in bronze_rows:
            try:
                row = _transform_one(bronze_row, geocoder)
            except Exception as exc:
                logger.error(
                    "Transform error %s:%s — %s",
                    bronze_row.get("source_name"), bronze_row.get("source_id"), exc,
                )
                total_skipped += 1
                continue

            if row is None:
                total_skipped += 1
                continue

            # Gắn thumbnail
            thumb_url = thumbnails.get((row.source_name, row.source_id))
            if thumb_url:
                row.original_thumbnail_url = thumb_url
                row.thumbnail_status = "pending"
            else:
                row.thumbnail_status = "failed"

            silver_rows.append(row)

        if silver_rows:
            try:
                _upsert_batch(conn, silver_rows)
                total_inserted += len(silver_rows)
                logger.info(
                    "Batch total_processed=%d: %d upserted, %d skipped",
                    total_processed, len(silver_rows), len(bronze_rows) - len(silver_rows),
                )
            except Exception as exc:
                conn.rollback()
                logger.error("Upsert batch failed at total_processed=%d: %s", total_processed, exc)
                total_skipped += len(silver_rows)

        total_processed += len(bronze_rows)

    conn.close()
    logger.info(
        "Done — processed: %d, inserted/updated: %d, skipped: %d",
        total_processed, total_inserted, total_skipped,
    )


# =============================================================
# CLI entry point
# =============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bronze → Silver ETL")
    parser.add_argument("--source", choices=["nhatot", "mogi"], help="Chỉ xử lý 1 source")
    parser.add_argument("--limit", type=int, help="Giới hạn số tin xử lý (debug)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"Batch size (mặc định {BATCH_SIZE})")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("Thiếu biến môi trường DATABASE_URL")

    run(
        database_url=db_url,
        source_name=args.source,
        limit=args.limit,
        batch_size=args.batch_size,
    )

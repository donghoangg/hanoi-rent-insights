# scraper/spiders/nhatot_spider.py
"""
Spider cào tin đăng nhà/phòng cho thuê tại Hà Nội từ Nhatot.com (Chợ Tốt).

Nhatot cung cấp API JSON public — không cần Playwright.
API endpoint: https://gateway.chotot.com/v1/public/ad-listing

Chiến lược:
1. Gọi API listing (có phân trang) với 3 category cho thuê:
   - cg=1050 (Phòng trọ)           → type="u"
   - cg=1010 (Căn hộ/Chung cư)     → type="u", st=u
   - cg=1020 (Nhà nguyên căn)      → type="u", st=u
2. Với mỗi ad_id, gọi API detail để lấy đầy đủ thông tin + ảnh
3. Guard: bỏ qua bất kỳ listing nào có type != "u" (chỉ lấy cho thuê)
4. Parse → RentingItem → Pipeline

Chạy thử:
    scrapy crawl nhatot -s CLOSESPIDER_ITEMCOUNT=50
Chạy thật:
    scrapy crawl nhatot
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Generator
from urllib.parse import urlencode

import scrapy
from scrapy.http import Response

from ..items import RentingItem

# ──────────────────────────────────────────────────────────────
# Các category code cho thuê trên Nhatot (Chợ Tốt)
# cg=1050: Phòng trọ/Nhà trọ
# cg=1010: Căn hộ/Chung cư cho thuê
# cg=1020: Nhà nguyên căn cho thuê
# Tham số st=u: "use" = cho thuê (phân biệt với st=s = bán)
# ──────────────────────────────────────────────────────────────
RENTAL_CATEGORIES = [
    {"cg": "1050", "st": "u"},   # Phòng trọ / Nhà trọ
    {"cg": "1010", "st": "u"},   # Căn hộ / Chung cư
    {"cg": "1020", "st": "u"},   # Nhà nguyên căn / Biệt thự
]

# Mapping category code → property_type chuẩn nội bộ
CATEGORY_TO_PROPERTY_TYPE = {
    "1050": "phong_tro",         # Phòng trọ / Nhà trọ
    "1010": "chung_cu",          # Căn hộ / Chung cư
    "1020": "nha_nguyen_can",    # Nhà nguyên căn
}

# Mapping house_type (sub-type) để phân biệt chi tiết hơn
# house_type trong API: 1=nhà nguyên căn, 2=biệt thự, 5=căn hộ dịch vụ
HOUSE_TYPE_MAP = {
    5: "can_ho_dich_vu",
    7: "can_ho_dich_vu",
}

# Mapping furnishing_rent → tên chuẩn nội bộ
FURNISHING_MAP = {
    0: "bare",       # Không nội thất
    1: "partial",    # Nội thất cơ bản
    2: "full",       # Đầy đủ nội thất
    3: "luxury",     # Nội thất cao cấp
}

# Mapping quận Hà Nội (area_v2 code → tên quận)
DISTRICT_MAP = {
    "12100": "Ba Đình",
    "12101": "Hoàn Kiếm",
    "12102": "Hai Bà Trưng",
    "12103": "Đống Đa",
    "12104": "Tây Hồ",
    "12105": "Cầu Giấy",
    "12106": "Thanh Xuân",
    "12107": "Hoàng Mai",
    "12108": "Long Biên",
    "12109": "Nam Từ Liêm",
    "12110": "Bắc Từ Liêm",
    "12111": "Hà Đông",
    "12070": "Sóc Sơn",
    "12071": "Đông Anh",
    "12072": "Gia Lâm",
    "12073": "Thanh Trì",
    "12074": "Mê Linh",
    "12075": "Đống Đa",
    "12076": "Cầu Giấy",
    "12077": "Thanh Xuân",
    "12078": "Hoàng Mai",
    "12079": "Long Biên",
    "12080": "Hoàng Mai",
    "12081": "Long Biên",
    "12082": "Gia Lâm",
    "12083": "Đông Anh",
    "12084": "Sóc Sơn",
    "12085": "Mê Linh",
    "12086": "Hà Đông",
    "12087": "Ba Đình",
    "12088": "Hoàn Kiếm",
    "12089": "Hai Bà Trưng",
    "12090": "Đống Đa",
    "12091": "Thạch Thất",
    "12092": "Chương Mỹ",
    "12093": "Thường Tín",
    "12094": "Thanh Oai",
    "12095": "Ứng Hòa",
    "12096": "Mỹ Đức",
    "12097": "Phú Xuyên",
    "12098": "Đan Phượng",
    "12099": "Hoài Đức",
    "12121": "Nam Từ Liêm",
    "12122": "Bắc Từ Liêm",
    "12123": "Tây Hồ",
    "12124": "Ba Đình",
    "12125": "Cầu Giấy",
    "12126": "Hoàn Kiếm",
    "12127": "Ba Vì",
}


class NhatotSpider(scrapy.Spider):
    name = "nhatot"
    allowed_domains = ["gateway.chotot.com", "www.nhatot.com"]

    # ── API endpoints ──────────────────────────────────────────
    LIST_API = "https://gateway.chotot.com/v1/public/ad-listing"
    DETAIL_API = "https://gateway.chotot.com/v2/public/ad-listing/{ad_id}"

    # Số tin mỗi trang (max Nhatot cho phép)
    PAGE_SIZE = 50
    MAX_PAGES = 100   # Tối đa ~5000 tin mỗi category (50 * 100)

    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 3,
    }

    def __init__(self, max_pages: int = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if max_pages:
            self.MAX_PAGES = int(max_pages)

    # ── Entry point ─────────────────────────────────────────────
    def start_requests(self):
        """Bắt đầu từ trang 1 của từng category cho thuê."""
        for cat in RENTAL_CATEGORIES:
            yield self._make_list_request(cg=cat["cg"], st=cat["st"], page=1)

    # ── List page ───────────────────────────────────────────────
    def _make_list_request(self, cg: str, st: str, page: int) -> scrapy.Request:
        params = {
            "region_v2": "12000",   # Hà Nội
            "cg": cg,
            "st": st,               # "u" = cho thuê
            "limit": self.PAGE_SIZE,
            "page": page,
        }
        url = f"{self.LIST_API}?{urlencode(params)}"
        return scrapy.Request(
            url=url,
            callback=self.parse_list,
            meta={"cg": cg, "st": st, "page": page},
            headers={"Accept": "application/json"},
        )

    def parse_list(self, response: Response) -> Generator:
        """Parse trang list → yield request cho từng detail."""
        cg = response.meta["cg"]
        st = response.meta["st"]
        page = response.meta["page"]

        try:
            data = response.json()
        except Exception:
            self.logger.error("Failed JSON list page %d cg=%s: %s", page, cg, response.url)
            return

        ads = data.get("ads", [])
        if not ads:
            self.logger.info("No more ads at page %d cg=%s — stopping", page, cg)
            return

        self.logger.info("cg=%s page %d — %d ads found", cg, page, len(ads))

        for ad in ads:
            # Guard sơ bộ ở list: chỉ xử lý listing cho thuê
            if ad.get("type") not in ("u", None, ""):
                continue

            ad_id = str(ad.get("list_id") or ad.get("ad_id") or "")
            if not ad_id:
                continue

            detail_url = self.DETAIL_API.format(ad_id=ad_id)
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                meta={"ad_id": ad_id, "list_data": ad, "cg": cg},
                headers={"Accept": "application/json"},
                priority=1,
            )

        # Phân trang tiếp theo
        if page < self.MAX_PAGES and len(ads) == self.PAGE_SIZE:
            yield self._make_list_request(cg=cg, st=st, page=page + 1)

    # ── Detail page ─────────────────────────────────────────────
    def parse_detail(self, response: Response) -> Generator:
        """Parse API detail → yield RentingItem."""
        try:
            data = response.json()
        except Exception:
            self.logger.error("Failed JSON detail: %s", response.url)
            return

        # Nhatot v2 detail API trả {"ad": {...}}
        ad = data.get("ad") or {}
        if not ad:
            # Fallback: một số endpoint trả thẳng object hoặc {"ads": [...]}
            ads_list = data.get("ads")
            if isinstance(ads_list, list) and ads_list:
                ad = ads_list[0]
            else:
                ad = data

        # ── GUARD: Chỉ lấy listing cho thuê (type="u") ───────
        listing_type = ad.get("type") or response.meta.get("list_data", {}).get("type")
        if listing_type == "s":
            self.logger.debug("Skip sale listing: %s", response.meta["ad_id"])
            return

        ad_id = str(response.meta["ad_id"])
        list_data: dict = response.meta.get("list_data", {})
        cg = response.meta.get("cg", "1050")

        # ── Extract fields ──────────────────────────────────────
        price_vnd = self._extract_price(ad, list_data)
        district = self._extract_district(ad, list_data)
        ward = self._extract_ward(ad, list_data)
        property_type = self._extract_property_type(ad, list_data, cg)
        furnishing_level = self._extract_furnishing(ad, list_data)
        thumbnail_url, image_urls = self._extract_images(ad)
        posted_at = self._extract_posted_at(ad, list_data)
        area_m2 = self._extract_area(ad, list_data)
        bedrooms = self._extract_int(ad, ["rooms", "room"])
        bathrooms = self._extract_int(ad, ["toilets", "toilet"])

        title = (
            ad.get("subject")
            or ad.get("title")
            or list_data.get("subject")
            or ""
        ).strip()

        description = (
            ad.get("body")
            or ad.get("description")
            or ""
        ).strip()

        address = self._extract_address(ad, list_data)
        source_url = (
            ad.get("url")
            or f"https://www.nhatot.com/{ad_id}.htm"
        )

        # GPS coordinates (Nhatot cung cấp trực tiếp — không cần geocoding)
        latitude = ad.get("latitude") or list_data.get("latitude")
        longitude = ad.get("longitude") or list_data.get("longitude")

        # Merge raw payload: list data + detail data + GPS
        raw = {**list_data, **ad}
        if latitude:
            raw["_lat"] = latitude
        if longitude:
            raw["_lng"] = longitude

        item = RentingItem(
            source_name="nhatot",
            source_id=ad_id,
            source_url=source_url,
            title=title,
            description=description,
            price_vnd=price_vnd,
            area_m2=area_m2,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            property_type=property_type,
            furnishing_level=furnishing_level,
            address=address,
            district=district,
            ward=ward,
            thumbnail_url=thumbnail_url,
            image_urls=image_urls,
            posted_at=posted_at,
            raw_payload=raw,
        )

        yield item

    # ── Helpers ─────────────────────────────────────────────────

    def _extract_price(self, ad: dict, list_data: dict) -> int | None:
        """Lấy giá VND/tháng. Nhatot lưu nguyên VND (e.g. 2800000 = 2.8 triệu)."""
        raw = (
            ad.get("price")
            or ad.get("price_vnd")
            or list_data.get("price")
        )
        if raw is None:
            return None
        try:
            price = int(float(str(raw).replace(",", "").replace(".", "").strip()))
            # Normalize: nếu < 1000 thì đơn vị triệu, nếu < 100_000 thì đơn vị nghìn
            if 0 < price < 1_000:
                price = price * 1_000_000
            elif 0 < price < 100_000:
                price = price * 1_000
            return price
        except (ValueError, TypeError):
            return None

    def _extract_area(self, ad: dict, list_data: dict) -> float | None:
        raw = ad.get("size") or ad.get("area") or list_data.get("size")
        if raw is None:
            return None
        try:
            return float(str(raw).replace(",", ".").strip())
        except (ValueError, TypeError):
            return None

    def _extract_district(self, ad: dict, list_data: dict) -> str | None:
        # Ưu tiên tên text từ area_name
        area_name = ad.get("area_name") or list_data.get("area_name")
        if area_name and isinstance(area_name, str):
            return area_name.strip()
        # Fallback: tra bảng area_v2 code
        area_code = str(ad.get("area_v2") or ad.get("area") or list_data.get("area_v2") or "")
        return DISTRICT_MAP.get(area_code)

    def _extract_ward(self, ad: dict, list_data: dict) -> str | None:
        ward = ad.get("ward_name") or list_data.get("ward_name")
        if ward and isinstance(ward, str):
            return ward.strip()
        return None

    def _extract_property_type(self, ad: dict, list_data: dict, cg: str) -> str:
        """
        Xác định property_type từ category code + house_type.
        cg=1050 → phong_tro
        cg=1010 → chung_cu (hoặc can_ho_dich_vu nếu house_type=5)
        cg=1020 → nha_nguyen_can
        """
        base_type = CATEGORY_TO_PROPERTY_TYPE.get(
            str(ad.get("category") or cg),
            "phong_tro"
        )
        # Tinh chỉnh dựa trên house_type
        house_type = ad.get("house_type") or list_data.get("house_type")
        if house_type is not None:
            override = HOUSE_TYPE_MAP.get(int(house_type))
            if override:
                return override
        return base_type

    def _extract_furnishing(self, ad: dict, list_data: dict) -> str | None:
        """
        Rental listings dùng `furnishing_rent` (không phải furnishing_sell).
        furnishing_rent: 0=bare, 1=partial, 2=full, 3=luxury
        """
        val = ad.get("furnishing_rent")
        if val is None:
            val = list_data.get("furnishing_rent")
        if val is None:
            return None
        try:
            return FURNISHING_MAP.get(int(val))
        except (ValueError, TypeError):
            return None

    def _extract_images(self, ad: dict) -> tuple[str | None, list[str]]:
        """Trả về (thumbnail_url, [all_image_urls])."""
        images = ad.get("images") or []
        image_urls = []
        for img in images:
            if isinstance(img, str) and img.startswith("http"):
                image_urls.append(img)
            elif isinstance(img, dict):
                url = img.get("name") or img.get("url") or img.get("src") or ""
                if url and url.startswith("http"):
                    image_urls.append(url)

        # Fallback thumbnail từ image_thumbnails hoặc thumbnail_image
        thumbnail = (
            ad.get("thumbnail_image")
            or (image_urls[0] if image_urls else None)
        )
        return thumbnail, image_urls

    def _extract_posted_at(self, ad: dict, list_data: dict) -> str | None:
        """Convert Unix timestamp (ms) → ISO date string."""
        ts = (
            ad.get("list_time")
            or ad.get("orig_list_time")
            or list_data.get("list_time")
        )
        if not ts:
            return None
        try:
            # Nhatot dùng milliseconds
            ts_int = int(ts)
            if ts_int > 1e12:
                ts_int = ts_int // 1000
            dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
            return dt.date().isoformat()
        except (ValueError, TypeError, OSError):
            return str(ts)

    def _extract_address(self, ad: dict, list_data: dict) -> str:
        """Ghép địa chỉ từ số nhà + tên phố + phường + quận."""
        parts = []
        street_number = ad.get("street_number") or list_data.get("street_number")
        street_name = ad.get("street_name") or list_data.get("street_name")
        ward_name = ad.get("ward_name") or list_data.get("ward_name")
        area_name = ad.get("area_name") or list_data.get("area_name")

        if street_number and str(street_number).strip():
            parts.append(str(street_number).strip())
        if street_name and str(street_name).strip():
            parts.append(str(street_name).strip())
        if ward_name and str(ward_name).strip():
            parts.append(str(ward_name).strip())
        if area_name and str(area_name).strip():
            parts.append(str(area_name).strip())

        return ", ".join(parts) if parts else ""

    def _extract_int(self, ad: dict, keys: list[str]) -> int | None:
        for key in keys:
            val = ad.get(key)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
        return None

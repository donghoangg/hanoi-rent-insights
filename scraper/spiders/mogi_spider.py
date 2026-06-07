# scraper/spiders/mogi_spider.py
"""
Spider cào tin đăng nhà/phòng cho thuê tại Hà Nội từ Mogi.vn.

Mogi.vn dùng HTML server-side render — không cần Playwright.
Chiến lược:
1. Crawl các trang danh sách cho thuê (3 loại: phòng trọ, nhà, căn hộ) với phân trang
2. Extract URL từng tin đăng
3. Request detail page → parse HTML → RentingItem
4. Guard: chỉ xử lý listing có URL slug chứa "cho-thue" hoặc "thue"

Chạy thử:
    scrapy crawl mogi -s CLOSESPIDER_ITEMCOUNT=50
"""

import re
from datetime import datetime, date
from typing import Generator

import scrapy
from scrapy.http import Response

from ..items import RentingItem

# ──────────────────────────────────────────────────────────────
# Các URL cho thuê trên Mogi.vn — chỉ lấy tin cho thuê Hà Nội
# ──────────────────────────────────────────────────────────────
RENTAL_LIST_URLS = [
    "https://mogi.vn/ha-noi/thue-phong-tro-nha-tro?cp={page}",  # Phòng trọ / nhà trọ
]

# Slug prefix → dấu hiệu là tin cho thuê (guard)
RENTAL_URL_KEYWORDS = ("cho-thue", "thue-phong", "phong-tro", "thue-phong-tro", "thue-nha-tro", "thue-phong-tro-khu-nha-tro")

# Slug → property_type mapping (dùng cho URL-based detection)
SLUG_TO_PROPERTY_TYPE = {
    "cho-thue-phong-tro": "phong_tro",
    "phong-tro": "phong_tro",
    "nha-tro": "phong_tro",
    "cho-thue-nha": "nha_nguyen_can",
    "nha-cho-thue": "nha_nguyen_can",
    "cho-thue-can-ho": "chung_cu",
    "can-ho-cho-thue": "chung_cu",
    "can-ho-dich-vu": "can_ho_dich_vu",
}

PROPERTY_TYPE_MAP = {
    "phòng trọ":          "phong_tro",
    "nhà trọ":            "phong_tro",
    "chung cư":           "chung_cu",
    "căn hộ":             "chung_cu",
    "căn hộ dịch vụ":    "can_ho_dich_vu",
    "nhà nguyên căn":    "nha_nguyen_can",
    "nhà riêng":          "nha_nguyen_can",
    "nhà phố":            "nha_nguyen_can",
    "biệt thự":           "biet_thu",
}

# Tên quận Hà Nội để normalize
# [DEPRECATED] Danh sách quận cũ — giữ tạm để ánh xạ địa danh cũ→mới ở tầng Silver.
# Theo địa giới 2 cấp (01/07/2025) không còn dùng quận.
HANOI_DISTRICTS = [
    "Ba Đình", "Hoàn Kiếm", "Hai Bà Trưng", "Đống Đa", "Tây Hồ",
    "Cầu Giấy", "Thanh Xuân", "Hoàng Mai", "Long Biên", "Nam Từ Liêm",
    "Bắc Từ Liêm", "Hà Đông", "Sóc Sơn", "Đông Anh", "Gia Lâm",
    "Thanh Trì", "Mê Linh", "Thạch Thất", "Quốc Oai", "Hoài Đức",
    "Chương Mỹ", "Đan Phượng", "Ba Vì", "Phúc Thọ", "Thường Tín",
    "Thanh Oai", "Mỹ Đức", "Ứng Hòa", "Phú Xuyên", "Sơn Tây",
]


class MogiSpider(scrapy.Spider):
    name = "mogi"
    allowed_domains = ["mogi.vn"]

    MAX_PAGES = 80   # ~4000 tin mỗi loại (50 tin/trang × 80 trang)

    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    }

    def __init__(self, max_pages: int = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if max_pages:
            self.MAX_PAGES = int(max_pages)

    # ── Entry point ─────────────────────────────────────────────
    async def start(self):
        """Bắt đầu từ trang 1 của từng category cho thuê."""
        for url_template in RENTAL_LIST_URLS:
            yield scrapy.Request(
                url=url_template.format(page=1),
                callback=self.parse_list,
                meta={"page": 1, "url_template": url_template},
            )

    # ── List page ───────────────────────────────────────────────
    def parse_list(self, response: Response) -> Generator:
        """Parse trang danh sách Mogi → yield request chi tiết."""
        current_page = response.meta["page"]
        url_template = response.meta["url_template"]

        # Selector các card tin đăng
        listings = response.css("ul.props li")
        if not listings:
            # Fallback selector cũ
            listings = response.css("ul.prop-list li.prop-item")

        if not listings:
            self.logger.warning("No listings on page %d — check selectors: %s", current_page, response.url)
            return

        self.logger.info("Mogi page %d — %d listings [%s]", current_page, len(listings), response.url)

        for listing in listings:
            detail_url = listing.css("a.link-overlay::attr(href)").get()
            if not detail_url:
                detail_url = listing.css("a::attr(href)").get()
            if not detail_url:
                continue

            if not detail_url.startswith("http"):
                detail_url = f"https://mogi.vn{detail_url}"

            # Guard sơ bộ: URL phải chứa từ khóa cho thuê
            # (tạm bỏ để debug số lượng detail request)
            # if not any(kw in detail_url for kw in RENTAL_URL_KEYWORDS):
            #     self.logger.debug("Skip non-rental URL: %s", detail_url)
            #     continue

            # Extract preview data từ list để có fallback nếu detail chậm
            preview = {
                "title": listing.css("h2.prop-title::text, h3.prop-title::text").get("").strip(),
                "price_text": listing.css("div.price::text, strong.price::text").get("").strip(),
                "area_text": listing.css("span.area::text, ul.prop-attr li::text").get("").strip(),
                "location_text": listing.css("div.prop-addr::text").get("").strip(),
            }

            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                meta={"preview": preview},
                priority=1,
            )

        # Phân trang
        next_page = current_page + 1
        if next_page <= self.MAX_PAGES and len(listings) > 0:
            yield scrapy.Request(
                url=url_template.format(page=next_page),
                callback=self.parse_list,
                meta={"page": next_page, "url_template": url_template},
            )

    # ── Detail page ─────────────────────────────────────────────
    def parse_detail(self, response: Response) -> Generator:
        """Parse trang chi tiết một tin Mogi → yield RentingItem."""
        preview: dict = response.meta.get("preview", {})

        # Source ID từ URL (vd: /cho-thue-phong-tro/12345678.html → 12345678)
        source_id = self._extract_source_id(response.url)
        if not source_id:
            self.logger.warning("Cannot extract source_id from: %s", response.url)
            return

        # ── Title ────────────────────────────────────────────────
        title = (
            response.css("div.title h1::text").get()
            or response.css("h1.prop-title::text").get()
            or response.css("h1[itemprop='name']::text").get()
            or preview.get("title")
            or ""
        ).strip()

        # ── Giá ─────────────────────────────────────────────────
        price_text = (
            response.css("div.price::text").get()
            or response.css("strong.price::text").get()
            or response.css("[itemprop='price']::text").get()
            or preview.get("price_text")
            or ""
        )
        price_vnd = self._parse_price(price_text)

        # ── Diện tích ────────────────────────────────────────────
        area_text = (
            response.css("div.info-attrs li:contains('Diện tích') span::text").get()
            or response.css("span.info-item:contains('Diện tích') strong::text").get()
            or preview.get("area_text")
            or ""
        )
        area_m2 = self._parse_area(area_text)

        # ── Loại hình ────────────────────────────────────────────
        prop_type_text = (
            response.css("div.info-attrs li:contains('Loại') span::text").get()
            or response.css("span.info-item:contains('Loại') strong::text").get()
            or response.css("a.prop-type::text").get()
            or ""
        ).strip().lower()
        property_type = self._map_property_type(prop_type_text, response.url)

        # ── Nội thất ────────────────────────────────────────────
        furnishing_text = (
            response.css("div.info-attrs li:contains('Nội thất') span::text").get()
            or response.css("span.info-item:contains('Nội thất') strong::text").get()
            or ""
        ).strip().lower()
        furnishing_level = self._map_furnishing(furnishing_text)

        # ── Phòng ngủ / phòng tắm ────────────────────────────────
        bedrooms = self._parse_int(
            response.css("div.info-attrs li:contains('Phòng ngủ') span::text").get()
            or response.css("span.info-item:contains('Phòng ngủ') strong::text").get()
        )
        bathrooms = self._parse_int(
            response.css("div.info-attrs li:contains('Phòng tắm') span::text").get()
            or response.css("span.info-item:contains('Phòng tắm') strong::text").get()
            or response.css("span.info-item:contains('Toilet') strong::text").get()
        )

        # ── Địa chỉ ─────────────────────────────────────────────
        address = (
            response.css("div.address::text").get()
            or response.css("div.prop-address span::text").get()
            or response.css("[itemprop='address']::text").get()
            or ""
        ).strip()
        province = self._extract_province(address)
        ward = self._extract_ward(address)

        # ── Ảnh ──────────────────────────────────────────────────
        image_urls = response.css(
            "div#gallery div.media-item img::attr(src), "
            "div#top-media div.owl-item img::attr(src), "
            "div.gallery img::attr(src)"
        ).getall()
        image_urls = [u for u in image_urls if u and u.startswith("http")]
        thumbnail_url = image_urls[0] if image_urls else None

        # ── Mô tả ────────────────────────────────────────────────
        description = " ".join(
            response.css("div.info-content-body *::text, div.prop-description *::text").getall()
        ).strip()

        # ── Ngày đăng ────────────────────────────────────────────
        posted_at = self._extract_posted_at(response)

        # ── Raw payload ──────────────────────────────────────────
        raw_payload = {
            "url": response.url,
            "title": title,
            "price_text": price_text,
            "area_text": area_text,
            "address": address,
            "description": description,
            "prop_type_text": prop_type_text,
            "property_type": property_type,   # đã map sẵn, ETL đọc trực tiếp
            "image_count": len(image_urls),
            "scraped_at": datetime.utcnow().isoformat(),
        }

        yield RentingItem(
            source_name="mogi",
            source_id=source_id,
            source_url=response.url,
            title=title,
            description=description,
            price_vnd=price_vnd,
            area_m2=area_m2,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            property_type=property_type,
            furnishing_level=furnishing_level,
            address=address,
            province=province,
            ward=ward,
            thumbnail_url=thumbnail_url,
            image_urls=image_urls,
            posted_at=posted_at,
            raw_payload=raw_payload,
        )

    # ── Helpers ─────────────────────────────────────────────────

    def _extract_source_id(self, url: str) -> str | None:
        # Mogi URL patterns:
        # Mới: /quan-thanh-xuan/thue-phong-tro/.../cho-thue-...-id22662490
        # Cũ:  /cho-thue-phong-tro/ha-noi/12345678.html
        match = re.search(r"-id(\d{5,12})(?:/|\?|$)", url)
        if match:
            return match.group(1)
        match = re.search(r"/(\d{7,12})(?:\.html)?(?:\?|$)", url)
        return match.group(1) if match else None

    def _parse_price(self, text: str) -> int | None:
        if not text:
            return None
        text = text.lower().strip()

        # Dạng "2.5 triệu/tháng", "2,500,000 đ/tháng"
        # Loại bỏ chữ
        text = re.sub(r"[^\d.,]", "", text)
        text = text.replace(",", "")

        try:
            val = float(text.replace(".", "", text.count(".") - 1) if text.count(".") > 1 else text)
        except ValueError:
            return None

        # Nếu giá < 1000 → đơn vị triệu → nhân 1 triệu
        if val < 1_000:
            val *= 1_000_000
        elif val < 100_000:
            val *= 1_000

        return int(val)

    def _parse_area(self, text: str) -> float | None:
        if not text:
            return None
        match = re.search(r"([\d.,]+)\s*m?²?", text.replace(",", "."))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _map_property_type(self, text: str, url: str = "") -> str:
        """Xác định property_type từ text loại hình + URL slug."""
        text_lower = text.lower()
        for keyword, prop_type in PROPERTY_TYPE_MAP.items():
            if keyword in text_lower:
                return prop_type
        # Fallback: tra URL slug
        for slug, prop_type in SLUG_TO_PROPERTY_TYPE.items():
            if slug in url:
                return prop_type
        return "phong_tro"

    def _map_furnishing(self, text: str) -> str | None:
        """Map text nội thất → furnishing_level chuẩn nội bộ."""
        if not text:
            return None
        text = text.lower()
        if any(w in text for w in ("cao cấp", "luxury", "sang trọng")):
            return "luxury"
        if any(w in text for w in ("đầy đủ", "full", "nội thất đầy")):
            return "full"
        if any(w in text for w in ("cơ bản", "basic", "một phần", "partial")):
            return "partial"
        if any(w in text for w in ("không", "trống", "bare", "none")):
            return "bare"
        return "partial"  # Mogi thường liệt kê nội thất có sẵn

    def _extract_province(self, address: str) -> str | None:
        """
        Cấp tỉnh (Tỉnh/TP) theo địa giới 2 cấp — phần tử cuối của địa chỉ.
        Spider này cào ha-noi nên mặc định 'Hà Nội' nếu không tách được.
        """
        if not address:
            return "Hà Nội"
        parts = [p.strip() for p in address.split(",") if p.strip()]
        return parts[-1] if parts else "Hà Nội"

    def _extract_ward(self, address: str) -> str | None:
        """
        Cấp xã (Phường/Xã). Ưu tiên phần có từ khoá phường/xã/thị trấn.
        Ánh xạ địa danh cũ→mới (2 cấp) xử lý tiếp ở tầng Silver.
        """
        if not address:
            return None
        parts = [p.strip() for p in address.split(",") if p.strip()]
        for part in parts:
            low = part.lower()
            if low.startswith("phường") or low.startswith("xã") \
               or low.startswith("p.") or low.startswith("thị trấn") \
               or low.startswith("tt "):
                return part
        # Fallback: phần thứ 2 từ cuối nếu ngắn gọn
        if len(parts) >= 2 and len(parts[-2].split()) <= 5:
            return parts[-2]
        return None

    def _parse_int(self, text: str | None) -> int | None:
        if not text:
            return None
        match = re.search(r"\d+", text)
        return int(match.group()) if match else None

    def _extract_posted_at(self, response: Response) -> str | None:
        # Thử các pattern phổ biến
        date_text = (
            response.css("span.post-date::text").get()
            or response.css("time::attr(datetime)").get()
            or response.css("[itemprop='datePosted']::attr(content)").get()
            or response.css("div.date-post::text").get()
        )
        if not date_text:
            return None

        date_text = date_text.strip()

        # ISO format
        if re.match(r"\d{4}-\d{2}-\d{2}", date_text):
            return date_text[:10]

        # "dd/mm/yyyy"
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_text)
        if match:
            d, m, y = match.groups()
            try:
                return date(int(y), int(m), int(d)).isoformat()
            except ValueError:
                pass

        return date_text

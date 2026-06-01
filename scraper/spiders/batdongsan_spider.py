# scraper/spiders/batdongsan_spider.py
"""
Spider cào tin đăng nhà cho thuê Hà Nội từ Batdongsan.com.vn.

Batdongsan là trang SPA/React — dùng scrapy-playwright để render JS.

Chiến lược:
- Dùng Playwright chỉ cho trang DANH SÁCH (cần JS để load tin)
- Parse dữ liệu từ JSON trong <script id="__NEXT_DATA__"> (Next.js hydration data)
  → Nếu không tìm thấy, fallback sang CSS selector
- Trang DETAIL: thử fetch bằng HTTP thuần trước (nhanh hơn),
  nếu 403 thì fallback sang Playwright

Chạy thử:
    scrapy crawl batdongsan -s CLOSESPIDER_ITEMCOUNT=30
Chạy đầy đủ:
    scrapy crawl batdongsan

LƯU Ý: Spider này dùng Playwright nên cần cài:
    pip install scrapy-playwright
    playwright install chromium
"""

import json
import re
from datetime import datetime, date, timezone, timedelta
from typing import Any, Generator

import scrapy
from scrapy.http import Response
from scrapy_playwright.page import PageMethod

from ..items import RentingItem

# ──────────────────────────────────────────────────────────────
# URL cấu hình — chỉ lấy tin CHO THUÊ tại Hà Nội
# Dùng nhiều URL category để đảm bảo bao phủ đủ loại hình
# ──────────────────────────────────────────────────────────────
RENTAL_LIST_URLS = [
    "https://batdongsan.com.vn/cho-thue-phong-tro-ha-noi?sortValue=1&pageIndex={page}",
    "https://batdongsan.com.vn/cho-thue-chung-cu-ha-noi?sortValue=1&pageIndex={page}",
    "https://batdongsan.com.vn/cho-thue-nha-rieng-ha-noi?sortValue=1&pageIndex={page}",
    "https://batdongsan.com.vn/cho-thue-nha-dat-ha-noi?sortValue=1&pageIndex={page}",
]

# Từ khóa trong URL để nhận biết tin cho thuê (guard)
RENTAL_URL_KEYWORDS = ("cho-thue",)

PROPERTY_TYPE_MAP = {
    "phòng trọ":          "phong_tro",
    "nhà trọ":            "phong_tro",
    "chung cư":           "chung_cu",
    "căn hộ":             "chung_cu",
    "căn hộ dịch vụ":    "can_ho_dich_vu",
    "mini":               "can_ho_dich_vu",
    "nhà riêng":          "nha_nguyen_can",
    "nhà nguyên căn":    "nha_nguyen_can",
    "nhà phố":            "nha_nguyen_can",
    "biệt thự":           "biet_thu",
    "văn phòng":          "van_phong",
    "shophouse":          "shophouse",
}

HANOI_DISTRICTS = [
    "Ba Đình", "Hoàn Kiếm", "Hai Bà Trưng", "Đống Đa", "Tây Hồ",
    "Cầu Giấy", "Thanh Xuân", "Hoàng Mai", "Long Biên", "Nam Từ Liêm",
    "Bắc Từ Liêm", "Hà Đông", "Sóc Sơn", "Đông Anh", "Gia Lâm",
    "Thanh Trì", "Mê Linh", "Thạch Thất", "Quốc Oai", "Hoài Đức",
    "Chương Mỹ", "Đan Phượng", "Ba Vì", "Phúc Thọ", "Thường Tín",
    "Thanh Oai", "Mỹ Đức", "Ứng Hòa", "Phú Xuyên", "Sơn Tây",
]


class BatdongsanSpider(scrapy.Spider):
    name = "batdongsan"
    allowed_domains = ["batdongsan.com.vn"]

    MAX_PAGES = 100   # 20 tin/trang × 100 = ~2000 tin
    custom_settings = {
        "DOWNLOAD_DELAY": 2.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_HANDLERS": {
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
    }

    def __init__(self, max_pages: int = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if max_pages:
            self.MAX_PAGES = int(max_pages)

    # ── Entry point ─────────────────────────────────────────────
    async def start(self):
        """Bắt đầu từ trang 1 của từng category cho thuê."""
        for url_template in RENTAL_LIST_URLS:
            yield self._make_list_request(url_template=url_template, page=1)

    # ── List page (Playwright) ───────────────────────────────────
    def _make_list_request(self, url_template: str, page: int) -> scrapy.Request:
        url = url_template.format(page=page)
        return scrapy.Request(
            url=url,
            callback=self.parse_list,
            meta={
                "page": page,
                "url_template": url_template,
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    # Đợi danh sách tin đăng load
                    PageMethod("wait_for_selector", "div.js__card, article.re__card-full", timeout=20_000),
                    # Scroll xuống để lazy-load ảnh (optional)
                    PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight / 2)"),
                    PageMethod("wait_for_timeout", 1000),
                ],
                "errback": self.handle_playwright_error,
            },
        )

    async def parse_list(self, response: Response) -> Generator:
        """Parse danh sách tin BDS → yield request chi tiết."""
        page = response.meta["page"]
        url_template = response.meta["url_template"]

        # Đóng Playwright page sau khi parse xong (tiết kiệm memory)
        playwright_page = response.meta.get("playwright_page")
        if playwright_page:
            await playwright_page.close()

        # ── Ưu tiên: parse __NEXT_DATA__ (Next.js hydration) ───
        listing_urls = []
        next_data = self._extract_next_data(response)
        if next_data:
            listing_urls = self._extract_urls_from_next_data(next_data)
            self.logger.info("Page %d — %d URLs from __NEXT_DATA__ [%s]", page, len(listing_urls), response.url)

        # ── Fallback: CSS selectors ─────────────────────────────
        if not listing_urls:
            listing_urls = self._extract_urls_from_html(response)
            self.logger.info("Page %d — %d URLs from HTML selectors [%s]", page, len(listing_urls), response.url)

        if not listing_urls:
            self.logger.warning("Page %d — no listings found: %s", page, response.url)
            return

        for url in listing_urls:
            if not url.startswith("http"):
                url = f"https://batdongsan.com.vn{url}"

            # Guard: chỉ request URL có chứa "cho-thue"
            if not any(kw in url for kw in RENTAL_URL_KEYWORDS):
                self.logger.debug("Skip non-rental URL: %s", url)
                continue

            yield scrapy.Request(
                url=url,
                callback=self.parse_detail,
                meta={
                    "playwright": False,  # Thử không dùng Playwright trước
                    "use_playwright_fallback": True,
                },
                priority=1,
            )

        # Phân trang
        next_page = page + 1
        if next_page <= self.MAX_PAGES and len(listing_urls) > 0:
            yield self._make_list_request(url_template=url_template, page=next_page)

    # ── Detail page ─────────────────────────────────────────────
    def parse_detail(self, response: Response) -> Generator:
        """Parse trang chi tiết 1 tin BDS — chỉ lấy tin cho thuê."""
        # Guard: URL phải chứa "cho-thue"
        if not any(kw in response.url for kw in RENTAL_URL_KEYWORDS):
            self.logger.debug("Skip non-rental detail URL: %s", response.url)
            return

        # Nếu bị block (403/empty) và chưa thử Playwright
        if response.status in (403, 404):
            if response.meta.get("use_playwright_fallback") and not response.meta.get("tried_playwright"):
                self.logger.info("Retrying with Playwright: %s", response.url)
                yield scrapy.Request(
                    url=response.url,
                    callback=self.parse_detail,
                    meta={
                        "playwright": True,
                        "playwright_page_methods": [
                            PageMethod("wait_for_selector", "h1.re__pr-title, h1.title-detail", timeout=20_000),
                        ],
                        "tried_playwright": True,
                        "use_playwright_fallback": False,
                    },
                    dont_filter=True,
                )
            return

        # ── __NEXT_DATA__ (path nhanh nhất) ─────────────────────
        next_data = self._extract_next_data(response)
        if next_data:
            item = self._parse_item_from_next_data(next_data, response.url)
            if item:
                yield item
                return

        # ── Fallback HTML parsing ────────────────────────────────
        item = self._parse_item_from_html(response)
        if item:
            yield item

    # ── __NEXT_DATA__ parsers ───────────────────────────────────

    def _extract_next_data(self, response: Response) -> dict | None:
        script = response.css("script#__NEXT_DATA__::text").get()
        if not script:
            return None
        try:
            return json.loads(script)
        except json.JSONDecodeError:
            return None

    def _extract_urls_from_next_data(self, data: dict) -> list[str]:
        """Trích xuất URLs tin đăng từ Next.js page props."""
        urls = []
        try:
            # Tìm sâu trong props.pageProps
            page_props = (
                data.get("props", {})
                    .get("pageProps", {})
            )
            # Batdongsan Next.js thường có field "listProduct" hoặc "seoData"
            product_list = (
                page_props.get("listProduct")
                or page_props.get("data", {}).get("items")
                or []
            )
            for item in product_list:
                url = item.get("detailUrl") or item.get("url") or item.get("slug")
                if url:
                    urls.append(url)
        except (AttributeError, TypeError):
            pass
        return urls

    def _extract_urls_from_html(self, response: Response) -> list[str]:
        """Fallback: lấy URLs từ HTML selectors."""
        selectors = [
            "div.js__card a.js__product-link-for-product-id::attr(href)",
            "article.re__card-full a.re__card-full-title::attr(href)",
            "div.search-productItem a.title::attr(href)",
            "ul.product-list li a.p-title::attr(href)",
        ]
        urls = []
        for sel in selectors:
            found = response.css(sel).getall()
            if found:
                urls.extend(found)
                break
        return [u for u in urls if u and "/cho-thue" in u]

    def _parse_item_from_next_data(self, data: dict, url: str) -> RentingItem | None:
        """Parse RentingItem từ __NEXT_DATA__ của trang detail."""
        try:
            page_props = data.get("props", {}).get("pageProps", {})

            # Batdongsan detail thường có productDetail hoặc seoDetail
            detail = (
                page_props.get("productDetail")
                or page_props.get("detail")
                or page_props.get("data")
            )
            if not detail:
                return None

            source_id = str(
                detail.get("productCode")
                or detail.get("id")
                or detail.get("code")
                or self._extract_source_id(url)
                or ""
            )
            if not source_id:
                return None

            title = (detail.get("title") or detail.get("name") or "").strip()
            description = (detail.get("description") or detail.get("body") or "").strip()

            # Giá
            price_vnd = self._parse_price_bds(
                detail.get("formattedPrice")
                or detail.get("price")
                or detail.get("priceText")
            )

            # Diện tích
            area_m2 = self._parse_area(str(detail.get("area") or detail.get("acreage") or ""))

            # Phòng
            bedrooms = detail.get("bedroom") or detail.get("rooms")
            bathrooms = detail.get("bathroom") or detail.get("toilets")

            # Loại hình
            prop_type_text = (
                detail.get("categoryTitle")
                or detail.get("typeTitle")
                or ""
            ).lower()
            property_type = self._map_property_type(prop_type_text)

            # Nội thất
            furnishing_text = (
                detail.get("furniture")
                or detail.get("furnishing")
                or detail.get("interiorStatus")
                or ""
            )
            furnishing_level = self._map_furnishing(str(furnishing_text).lower())

            # Địa chỉ
            address = (
                detail.get("fullAddress")
                or detail.get("address")
                or ""
            ).strip()
            # Địa giới 2 cấp: province (tỉnh/TP) + ward (phường/xã), bỏ quận
            province = (
                detail.get("cityName")
                or detail.get("provinceName")
                or self._extract_province(address)
            )
            ward = detail.get("wardName") or self._extract_ward(address)

            # Ảnh
            images_raw = detail.get("images") or detail.get("photos") or []
            image_urls = []
            for img in images_raw:
                if isinstance(img, str):
                    image_urls.append(img)
                elif isinstance(img, dict):
                    img_url = img.get("url") or img.get("src") or img.get("path") or ""
                    if img_url:
                        image_urls.append(img_url)
            image_urls = [u for u in image_urls if u.startswith("http")]
            thumbnail_url = image_urls[0] if image_urls else None

            # Ngày đăng
            posted_at = self._parse_date(
                detail.get("postedDate") or detail.get("startDate")
            )

            return RentingItem(
                source_name="batdongsan",
                source_id=source_id,
                source_url=url,
                title=title,
                description=description,
                price_vnd=price_vnd,
                area_m2=area_m2,
                bedrooms=int(bedrooms) if bedrooms else None,
                bathrooms=int(bathrooms) if bathrooms else None,
                property_type=property_type,
                furnishing_level=furnishing_level,
                address=address,
                province=province,
                ward=ward,
                thumbnail_url=thumbnail_url,
                image_urls=image_urls,
                posted_at=posted_at,
                raw_payload=detail,
            )
        except Exception as exc:
            self.logger.error("parse_item_from_next_data failed: %s", exc)
            return None

    # ── HTML fallback parser ─────────────────────────────────────
    def _parse_item_from_html(self, response: Response) -> RentingItem | None:
        """Parse trang detail bằng CSS/XPath selectors khi không có __NEXT_DATA__."""
        source_id = self._extract_source_id(response.url)
        if not source_id:
            return None

        title = (
            response.css("h1.re__pr-title::text").get()
            or response.css("h1.title-detail::text").get()
            or response.css("h1::text").get()
            or ""
        ).strip()

        price_text = (
            response.css("span.re__pr-price-value::text").get()
            or response.css("b.price::text").get()
            or response.css("[data-price]::attr(data-price)").get()
            or ""
        )
        price_vnd = self._parse_price_bds(price_text)

        area_text = (
            response.css("div.re__pr-short-info-item:contains('Diện tích') span.value::text").get()
            or response.css("span[data-area]::attr(data-area)").get()
            or ""
        )
        area_m2 = self._parse_area(area_text)

        bedrooms = self._parse_int_text(
            response.css("div.re__pr-short-info-item:contains('Phòng ngủ') span.value::text").get()
        )
        bathrooms = self._parse_int_text(
            response.css("div.re__pr-short-info-item:contains('Toilet') span.value::text").get()
        )

        prop_type_text = (
            response.css("span.re__pr-category::text").get()
            or ""
        ).strip().lower()
        property_type = self._map_property_type(prop_type_text)

        furnishing_text = (
            response.css(
                "div.re__pr-short-info-item:contains('Nội thất') span.value::text, "
                "div.re__pr-specs-content-item:contains('Nội thất') span.re__pr-specs-content-item-value::text"
            ).get()
            or ""
        ).strip().lower()
        furnishing_level = self._map_furnishing(furnishing_text)

        address = (
            response.css("span.re__pr-address-value::text").get()
            or response.css("div.re__pr-address span::text").get()
            or ""
        ).strip()
        province = self._extract_province(address)
        ward = self._extract_ward(address)

        description = " ".join(
            response.css("div.re__section-body div.re__detail-content *::text").getall()
        ).strip()

        image_urls = response.css(
            "div.re__pr-gallery img::attr(src), "
            "div.gallery img::attr(data-src)"
        ).getall()
        image_urls = [u for u in image_urls if u and u.startswith("http")]
        thumbnail_url = image_urls[0] if image_urls else None

        posted_at = self._parse_date(
            response.css("span.re__pr-short-info-item:contains('Ngày đăng') span.value::text").get()
        )

        if not title and not price_vnd:
            self.logger.warning("Sparse detail page — likely JS not rendered: %s", response.url)
            return None

        return RentingItem(
            source_name="batdongsan",
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
            raw_payload={
                "url": response.url,
                "title": title,
                "price_text": price_text,
                "scraped_at": datetime.utcnow().isoformat(),
            },
        )

    # ── Error handler ────────────────────────────────────────────
    async def handle_playwright_error(self, failure):
        self.logger.error("Playwright error: %s | %s", failure.value, failure.request.url)

    # ── Helpers ─────────────────────────────────────────────────

    def _extract_source_id(self, url: str) -> str | None:
        # BDS URL pattern: /cho-thue-chung-cu/ha-noi/pr12345678
        match = re.search(r"pr(\d{6,12})(?:\.html)?(?:\?|$|/)", url)
        if match:
            return match.group(1)
        # Fallback: lấy số dài cuối URL
        match = re.search(r"(\d{7,12})(?:\.html)?$", url)
        return match.group(1) if match else None

    def _parse_price_bds(self, text: Any) -> int | None:
        if not text:
            return None
        text = str(text).lower().strip()

        # Đã là số nguyên
        if isinstance(text, int):
            return text if text > 0 else None

        # Dạng "2.5 triệu/tháng", "2,500,000 đ/tháng", "25 tr/tháng"
        # Detect đơn vị
        multiplier = 1
        if "tỷ" in text or "ty" in text:
            multiplier = 1_000_000_000
        elif "triệu" in text or "trieu" in text or " tr" in text:
            multiplier = 1_000_000
        elif "nghìn" in text or "nghin" in text or " ng" in text:
            multiplier = 1_000

        # Lấy số
        nums = re.findall(r"[\d,./]+", text)
        if not nums:
            return None
        num_str = nums[0].replace(",", "").strip(".")
        try:
            val = float(num_str)
            result = int(val * multiplier)
            return result if result > 0 else None
        except ValueError:
            return None

    def _parse_area(self, text: str) -> float | None:
        if not text:
            return None
        match = re.search(r"([\d,./]+)\s*m", text.replace(",", "."))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _map_property_type(self, text: str) -> str:
        text = text.lower()
        for keyword, prop_type in PROPERTY_TYPE_MAP.items():
            if keyword in text:
                return prop_type
        return "phong_tro"

    def _map_furnishing(self, text: str) -> str | None:
        """Map text nội thất → furnishing_level chuẩn nội bộ."""
        if not text:
            return None
        if any(w in text for w in ("cao cấp", "luxury", "sang trọng", "đầy đủ cao")):
            return "luxury"
        if any(w in text for w in ("đầy đủ", "full", "nội thất đầy", "hoàn chỉnh")):
            return "full"
        if any(w in text for w in ("cơ bản", "basic", "một phần", "partial")):
            return "partial"
        if any(w in text for w in ("không", "trống", "bare", "none", "chưa")):
            return "bare"
        if text.strip():
            return "partial"  # Có mention nội thất nhưng không rõ → partial
        return None

    def _extract_province(self, address: str) -> str | None:
        """Cấp tỉnh (Tỉnh/TP) — phần tử cuối của địa chỉ; mặc định Hà Nội."""
        if not address:
            return "Hà Nội"
        parts = [p.strip() for p in address.split(",") if p.strip()]
        return parts[-1] if parts else "Hà Nội"

    def _extract_ward(self, address: str) -> str | None:
        """Cấp xã (Phường/Xã). Ánh xạ địa danh cũ→mới xử lý ở tầng Silver."""
        if not address:
            return None
        parts = [p.strip() for p in address.split(",") if p.strip()]
        for part in parts:
            low = part.lower()
            if low.startswith("phường") or low.startswith("xã") \
               or low.startswith("p.") or low.startswith("thị trấn") \
               or low.startswith("tt "):
                return part
        if len(parts) >= 2 and len(parts[-2].split()) <= 5:
            return parts[-2]
        return None

    def _parse_int_text(self, text: str | None) -> int | None:
        if not text:
            return None
        match = re.search(r"\d+", text)
        return int(match.group()) if match else None

    def _parse_date(self, text: Any) -> str | None:
        """
        Chuẩn hoá ngày đăng về dạng ISO 'YYYY-MM-DD'.
        Hỗ trợ: ISO sẵn, timestamp (ms/s), 'dd/mm/yyyy', và ngày tương đối
        kiểu 'Hôm nay' / 'Hôm qua' / 'N ngày trước' (trừ từ ngày hiện tại).
        """
        if not text:
            return None
        text = str(text).strip()

        # ISO 8601
        if re.match(r"\d{4}-\d{2}-\d{2}", text):
            return text[:10]

        # Timestamp milliseconds
        if re.match(r"^\d{13}$", text):
            try:
                dt = datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
                return dt.date().isoformat()
            except Exception:
                pass

        # Timestamp seconds
        if re.match(r"^\d{10}$", text):
            try:
                dt = datetime.fromtimestamp(int(text), tz=timezone.utc)
                return dt.date().isoformat()
            except Exception:
                pass

        low = text.lower()

        # Ngày tương đối
        if "hôm nay" in low:
            return date.today().isoformat()
        if "hôm qua" in low:
            return (date.today() - timedelta(days=1)).isoformat()
        m = re.search(r"(\d+)\s*ngày\s*trước", low)
        if m:
            return (date.today() - timedelta(days=int(m.group(1)))).isoformat()
        m = re.search(r"(\d+)\s*tuần\s*trước", low)
        if m:
            return (date.today() - timedelta(weeks=int(m.group(1)))).isoformat()

        # dd/mm/yyyy
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if m:
            d, mth, y = m.groups()
            try:
                return date(int(y), int(mth), int(d)).isoformat()
            except ValueError:
                pass

        return None

# scraper/spiders/batdongsan_spider.py
"""
*** DISABLED — Batdongsan.com.vn dùng Cloudflare Bot Management cấp enterprise.
Mọi phương pháp automation (Playwright, undetected-chromedriver, Selenium + remote debugging)
đều bị block. Spider này được giữ lại để tham khảo nhưng không chạy trong production.
Nguồn dữ liệu thay thế: mogi.vn và nhatot.com. ***

Spider cào tin đăng nhà cho thuê Hà Nội từ Batdongsan.com.vn.

Batdongsan dùng Cloudflare anti-bot → dùng undetected-chromedriver để bypass.

Chiến lược:
- Dùng undetected-chromedriver để render list page (bypass anti-bot)
- Lấy cookies từ UC driver → dùng requests để fetch detail page (nhanh hơn)
- Parse dữ liệu từ JSON trong <script id="__NEXT_DATA__"> (Next.js hydration)
  → Nếu không tìm thấy, fallback sang CSS selector

Chạy thử:
    scrapy crawl batdongsan -s CLOSESPIDER_ITEMCOUNT=30
Chạy đầy đủ:
    scrapy crawl batdongsan
"""

import json
import re
import time
import threading
from datetime import datetime, date, timezone, timedelta
from typing import Any, Generator

import requests as req_lib
import scrapy
from scrapy.http import HtmlResponse
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

from ..items import RentingItem

# ──────────────────────────────────────────────────────────────
# URL cấu hình — chỉ lấy tin CHO THUÊ tại Hà Nội
# ──────────────────────────────────────────────────────────────
RENTAL_LIST_URLS = [
    "https://batdongsan.com.vn/cho-thue-phong-tro-ha-noi?sortValue=1&pageIndex={page}",
    "https://batdongsan.com.vn/cho-thue-chung-cu-ha-noi?sortValue=1&pageIndex={page}",
    "https://batdongsan.com.vn/cho-thue-nha-rieng-ha-noi?sortValue=1&pageIndex={page}",
    "https://batdongsan.com.vn/cho-thue-nha-dat-ha-noi?sortValue=1&pageIndex={page}",
]

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


class BatdongsanSpider(scrapy.Spider):
    name = "batdongsan"
    allowed_domains = ["batdongsan.com.vn"]

    MAX_PAGES = 100   # 20 tin/trang × 100 = ~2000 tin
    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        # Không dùng Playwright nữa
        "DOWNLOAD_HANDLERS": {},
    }

    def __init__(self, max_pages: int = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if max_pages:
            self.MAX_PAGES = int(max_pages)
        self._driver = None
        self._driver_lock = threading.Lock()
        self._session = None   # requests.Session với cookies từ UC

    # ── Driver lifecycle ────────────────────────────────────────
    def _get_driver(self):
        """Kết nối vào Chrome thật đang chạy với --remote-debugging-port=9222."""
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            options = Options()
            options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
            self._driver = webdriver.Chrome(options=options)
            self._driver.implicitly_wait(10)
            self.logger.info("Connected to existing Chrome (remote debugging)")
        return self._driver

    def _get_session(self) -> req_lib.Session:
        """Tạo requests.Session với cookies từ UC driver."""
        driver = self._get_driver()
        session = req_lib.Session()
        session.headers.update({
            "User-Agent": driver.execute_script("return navigator.userAgent"),
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://batdongsan.com.vn/",
        })
        for cookie in driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        return session

    def closed(self, reason):
        """Đóng driver khi spider kết thúc."""
        if self._driver:
            try:
                self._driver.quit()
                self.logger.info("Browser closed")
            except Exception:
                pass

    # ── Entry point ─────────────────────────────────────────────
    async def start(self):
        """Dùng UC driver để fetch list page đầu tiên của mỗi category."""
        for url_template in RENTAL_LIST_URLS:
            url = url_template.format(page=1)
            html = self._fetch_with_uc(url)
            if html:
                response = HtmlResponse(url=url, body=html, encoding="utf-8")
                for item_or_request in self.parse_list(response, page=1, url_template=url_template):
                    yield item_or_request

    # ── UC fetch ────────────────────────────────────────────────
    def _fetch_with_uc(self, url: str, wait_selector: str = None) -> str | None:
        """
        Dùng undetected-chromedriver để load trang, trả về HTML sau khi render.
        """
        with self._driver_lock:
            driver = self._get_driver()
            try:
                driver.get(url)
                # Đợi trang load xong
                if wait_selector:
                    try:
                        WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                        )
                    except TimeoutException:
                        self.logger.warning("Selector '%s' not found on %s", wait_selector, url)
                else:
                    # Đợi DOM content loaded + thêm buffer
                    WebDriverWait(driver, 20).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    time.sleep(2)

                # Scroll để kích hoạt lazy-load
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2)")
                time.sleep(1)

                html = driver.page_source
                self.logger.info("UC fetched: %s (%d chars)", url[:80], len(html))
                return html

            except Exception as exc:
                self.logger.error("UC fetch error on %s: %s", url[:80], exc)
                return None

    # ── List page ───────────────────────────────────────────────
    def parse_list(self, response: HtmlResponse, page: int = 1, url_template: str = "") -> Generator:
        """Parse danh sách tin BDS → yield request chi tiết."""

        # Ưu tiên: parse __NEXT_DATA__
        listing_urls = []
        next_data = self._extract_next_data(response)
        if next_data:
            listing_urls = self._extract_urls_from_next_data(next_data)
            self.logger.info("Page %d — %d URLs from __NEXT_DATA__ [%s]", page, len(listing_urls), response.url)

        # Fallback: CSS selectors
        if not listing_urls:
            listing_urls = self._extract_urls_from_html(response)
            self.logger.info("Page %d — %d URLs from HTML [%s]", page, len(listing_urls), response.url)

        if not listing_urls:
            body_snippet = response.text[:2000]
            self.logger.warning("Page %d — no listings found: %s\nHTML:\n%s", page, response.url, body_snippet)
            return

        # Cập nhật session cookies sau khi đã vào được trang
        self._session = self._get_session()

        for url in listing_urls:
            if not url.startswith("http"):
                url = f"https://batdongsan.com.vn{url}"
            if not any(kw in url for kw in RENTAL_URL_KEYWORDS):
                continue
            yield scrapy.Request(
                url=url,
                callback=self.parse_detail,
                meta={"dont_merge_cookies": True},
                priority=1,
            )

        # Phân trang
        next_page = page + 1
        if next_page <= self.MAX_PAGES and listing_urls:
            next_url = url_template.format(page=next_page)
            html = self._fetch_with_uc(next_url)
            if html:
                next_response = HtmlResponse(url=next_url, body=html, encoding="utf-8")
                yield from self.parse_list(next_response, page=next_page, url_template=url_template)

    # ── Detail page ─────────────────────────────────────────────
    def parse_detail(self, response) -> Generator:
        """Parse trang chi tiết — dùng requests+session nếu Scrapy bị block."""
        if not any(kw in response.url for kw in RENTAL_URL_KEYWORDS):
            return

        # Nếu Scrapy bị 403, dùng session từ UC
        if response.status == 403 and self._session:
            self.logger.info("Scrapy 403 → dùng requests session: %s", response.url)
            try:
                r = self._session.get(response.url, timeout=15)
                if r.status_code == 200:
                    response = HtmlResponse(
                        url=response.url, body=r.content, encoding="utf-8"
                    )
                else:
                    self.logger.warning("Session also failed %d: %s", r.status_code, response.url)
                    return
            except Exception as exc:
                self.logger.error("Session fetch error: %s", exc)
                return

        # Parse __NEXT_DATA__ (path nhanh)
        next_data = self._extract_next_data(response)
        if next_data:
            item = self._parse_item_from_next_data(next_data, response.url)
            if item:
                yield item
                return

        # Fallback HTML
        item = self._parse_item_from_html(response)
        if item:
            yield item

    # ── __NEXT_DATA__ parsers ───────────────────────────────────

    def _extract_next_data(self, response) -> dict | None:
        script = response.css("script#__NEXT_DATA__::text").get()
        if not script:
            return None
        try:
            return json.loads(script)
        except json.JSONDecodeError:
            return None

    def _extract_urls_from_next_data(self, data: dict) -> list[str]:
        urls = []
        try:
            page_props = data.get("props", {}).get("pageProps", {})
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

    def _extract_urls_from_html(self, response) -> list[str]:
        selectors = [
            "div[class*='product-item'] a[href*='cho-thue']::attr(href)",
            "div[class*='listing'] a[href*='cho-thue']::attr(href)",
            "a[data-product-id][href*='cho-thue']::attr(href)",
            "div.js__card a.js__product-link-for-product-id::attr(href)",
            "article.re__card-full a.re__card-full-title::attr(href)",
            "a[href*='/cho-thue-']::attr(href)",
        ]
        for sel in selectors:
            found = response.css(sel).getall()
            if found:
                return [u for u in found if "/cho-thue" in u]
        return []

    def _parse_item_from_next_data(self, data: dict, url: str) -> RentingItem | None:
        try:
            page_props = data.get("props", {}).get("pageProps", {})
            detail = (
                page_props.get("productDetail")
                or page_props.get("detail")
                or page_props.get("data")
            )
            if not detail:
                return None

            source_id = str(
                detail.get("productCode") or detail.get("id") or detail.get("code")
                or self._extract_source_id(url) or ""
            )
            if not source_id:
                return None

            title = (detail.get("title") or detail.get("name") or "").strip()
            description = (detail.get("description") or detail.get("body") or "").strip()
            price_vnd = self._parse_price_bds(
                detail.get("formattedPrice") or detail.get("price") or detail.get("priceText")
            )
            area_m2 = self._parse_area(str(detail.get("area") or detail.get("acreage") or ""))
            bedrooms = detail.get("bedroom") or detail.get("rooms")
            bathrooms = detail.get("bathroom") or detail.get("toilets")
            prop_type_text = (detail.get("categoryTitle") or detail.get("typeTitle") or "").lower()
            property_type = self._map_property_type(prop_type_text)
            furnishing_text = (
                detail.get("furniture") or detail.get("furnishing")
                or detail.get("interiorStatus") or ""
            )
            furnishing_level = self._map_furnishing(str(furnishing_text).lower())
            address = (detail.get("fullAddress") or detail.get("address") or "").strip()
            province = (
                detail.get("cityName") or detail.get("provinceName")
                or self._extract_province(address)
            )
            ward = detail.get("wardName") or self._extract_ward(address)
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
            posted_at = self._parse_date(detail.get("postedDate") or detail.get("startDate"))

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

    def _parse_item_from_html(self, response) -> RentingItem | None:
        source_id = self._extract_source_id(response.url)
        if not source_id:
            return None

        title = (
            response.css("h1.re__pr-title::text").get()
            or response.css("h1.title-detail::text").get()
            or response.css("h1::text").get() or ""
        ).strip()

        price_text = (
            response.css("span.re__pr-price-value::text").get()
            or response.css("b.price::text").get()
            or response.css("[data-price]::attr(data-price)").get() or ""
        )
        price_vnd = self._parse_price_bds(price_text)

        area_text = (
            response.css("div.re__pr-short-info-item:contains('Diện tích') span.value::text").get()
            or response.css("span[data-area]::attr(data-area)").get() or ""
        )
        area_m2 = self._parse_area(area_text)

        bedrooms = self._parse_int_text(
            response.css("div.re__pr-short-info-item:contains('Phòng ngủ') span.value::text").get()
        )
        bathrooms = self._parse_int_text(
            response.css("div.re__pr-short-info-item:contains('Toilet') span.value::text").get()
        )

        prop_type_text = (response.css("span.re__pr-category::text").get() or "").strip().lower()
        property_type = self._map_property_type(prop_type_text)

        furnishing_text = (
            response.css(
                "div.re__pr-short-info-item:contains('Nội thất') span.value::text,"
                "div.re__pr-specs-content-item:contains('Nội thất') span.re__pr-specs-content-item-value::text"
            ).get() or ""
        ).strip().lower()
        furnishing_level = self._map_furnishing(furnishing_text)

        address = (
            response.css("span.re__pr-address-value::text").get()
            or response.css("div.re__pr-address span::text").get() or ""
        ).strip()
        province = self._extract_province(address)
        ward = self._extract_ward(address)

        description = " ".join(
            response.css("div.re__section-body div.re__detail-content *::text").getall()
        ).strip()

        image_urls = response.css(
            "div.re__pr-gallery img::attr(src), div.gallery img::attr(data-src)"
        ).getall()
        image_urls = [u for u in image_urls if u and u.startswith("http")]
        thumbnail_url = image_urls[0] if image_urls else None

        posted_at = self._parse_date(
            response.css("span.re__pr-short-info-item:contains('Ngày đăng') span.value::text").get()
        )

        if not title and not price_vnd:
            self.logger.warning("Sparse page — likely not rendered: %s", response.url)
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

    # ── Helpers ─────────────────────────────────────────────────

    def _extract_source_id(self, url: str) -> str | None:
        match = re.search(r"pr(\d{6,12})(?:\.html)?(?:\?|$|/)", url)
        if match:
            return match.group(1)
        match = re.search(r"(\d{7,12})(?:\.html)?$", url)
        return match.group(1) if match else None

    def _parse_price_bds(self, text: Any) -> int | None:
        if not text:
            return None
        text = str(text).lower().strip()
        multiplier = 1
        if "tỷ" in text or "ty" in text:
            multiplier = 1_000_000_000
        elif "triệu" in text or "trieu" in text or " tr" in text:
            multiplier = 1_000_000
        elif "nghìn" in text or "nghin" in text or " ng" in text:
            multiplier = 1_000
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
            return "partial"
        return None

    def _extract_province(self, address: str) -> str | None:
        if not address:
            return "Hà Nội"
        parts = [p.strip() for p in address.split(",") if p.strip()]
        return parts[-1] if parts else "Hà Nội"

    def _extract_ward(self, address: str) -> str | None:
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
        if not text:
            return None
        text = str(text).strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", text):
            return text[:10]
        if re.match(r"^\d{13}$", text):
            try:
                dt = datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
                return dt.date().isoformat()
            except Exception:
                pass
        if re.match(r"^\d{10}$", text):
            try:
                dt = datetime.fromtimestamp(int(text), tz=timezone.utc)
                return dt.date().isoformat()
            except Exception:
                pass
        low = text.lower()
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
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if m:
            d, mth, y = m.groups()
            try:
                return date(int(y), int(mth), int(d)).isoformat()
            except ValueError:
                pass
        return None

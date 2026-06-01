# scraper/settings.py
"""
Cấu hình Scrapy cho HanoiRent Insights.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Project ---
BOT_NAME = "hanoi_rent_insights"
SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

# --- Tuân thủ robots.txt (có thể tắt nếu cần nhưng ghi rõ lý do) ---
ROBOTSTXT_OBEY = False  # Các site bất động sản VN thường không có robots.txt hợp lệ

# --- Rate limiting & politeness ---
DOWNLOAD_DELAY = float(os.getenv("SCRAPER_DELAY", "2"))
RANDOMIZE_DOWNLOAD_DELAY = True          # Delay thực tế = 0.5x – 1.5x DOWNLOAD_DELAY
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# --- AutoThrottle (tự điều chỉnh tốc độ dựa trên response time) ---
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0
AUTOTHROTTLE_DEBUG = False

# --- Retry ---
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429, 403]

# --- Timeout ---
DOWNLOAD_TIMEOUT = 30

# --- HTTP Cache (phát triển/debug) ---
# Bật khi debug để không cào lại mỗi lần chạy
HTTPCACHE_ENABLED = False
HTTPCACHE_EXPIRATION_SECS = 3600
HTTPCACHE_DIR = ".scrapy/httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [403, 404, 429, 500, 502, 503]

# --- Default headers ---
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}

# --- User Agent mặc định (sẽ được override bởi middleware) ---
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

# --- Middlewares ---
DOWNLOADER_MIDDLEWARES = {
    # Tắt built-in UserAgent, bật custom rotation
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    "scraper.middlewares.RandomUserAgentMiddleware": 400,
    # Custom retry (bổ sung thêm logic)
    "scraper.middlewares.SmartRetryMiddleware": 550,
}

# DOWNLOAD_HANDLERS: Playwright chỉ được kích hoạt khi spider tự set
# meta={"playwright": True} trong Request. Không route toàn bộ qua Playwright
# vì các spider dùng JSON API (nhatot, mogi) không cần browser.
# Spider nào cần Playwright thì tự override trong custom_settings:
#   DOWNLOAD_HANDLERS = {
#       "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
#   }
DOWNLOAD_HANDLERS = {}

# --- Playwright config ---
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "args": [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ],
}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30_000  # ms

# --- Item Pipelines ---
ITEM_PIPELINES = {
    "scraper.pipelines.ValidationPipeline":  100,
    "scraper.pipelines.DuplicatesPipeline":  200,
    "scraper.pipelines.BronzePipeline":      300,
}

# --- Database (đọc từ .env) ---
DATABASE_URL = os.getenv("DATABASE_URL")

# --- Logging ---
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# --- Feed exports (tùy chọn, dùng khi debug) ---
# FEEDS = {
#     "output/%(name)s_%(time)s.jsonl": {"format": "jsonlines", "encoding": "utf8"},
# }

# --- Twisted async reactor (cần cho Playwright) ---
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

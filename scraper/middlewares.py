# scraper/middlewares.py
"""
Scrapy Downloader Middlewares cho HanoiRent Insights.
- RandomUserAgentMiddleware: xoay vòng User-Agent để tránh bị chặn
- SmartRetryMiddleware: retry với backoff tuỳ chỉnh
"""

import random
import time
import logging

from scrapy import signals
from scrapy.downloadermiddlewares.retry import RetryMiddleware, get_retry_request
from scrapy.utils.response import response_status_message

logger = logging.getLogger(__name__)

USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Firefox Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Chrome Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
]


class RandomUserAgentMiddleware:
    """Thay thế built-in UserAgentMiddleware — gán ngẫu nhiên UA cho mỗi request."""

    def __init__(self, crawler):
        self._agents = USER_AGENTS
        self._crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware

    def spider_opened(self, spider):
        logger.debug(
            "RandomUserAgentMiddleware enabled — %d agents available",
            len(self._agents),
        )

    def process_request(self, request, **kwargs):
        agent = random.choice(self._agents)
        request.headers["User-Agent"] = agent
        logger.debug("UA → %s | %s", agent[:60], request.url[:80])


class SmartRetryMiddleware(RetryMiddleware):
    """
    Mở rộng RetryMiddleware với exponential backoff cho 429
    và random sleep cho 403/503.
    """

    BACKOFF_BASE = 5
    MAX_BACKOFF = 60

    def process_response(self, request, response, **kwargs):
        spider = self._crawler.spider if hasattr(self, '_crawler') else None

        if response.status == 429:
            retry_count = request.meta.get("retry_times", 0)
            backoff = min(self.BACKOFF_BASE * (2 ** retry_count), self.MAX_BACKOFF)
            logger.warning(
                "429 Too Many Requests — sleeping %.1fs before retry #%d | %s",
                backoff, retry_count + 1, request.url[:80],
            )
            time.sleep(backoff)
            reason = response_status_message(response.status)
            retry_req = get_retry_request(request, spider=spider, reason=reason)
            return retry_req or response

        if response.status in (403, 503):
            retry_count = request.meta.get("retry_times", 0)
            if retry_count < self.max_retry_times:
                delay = random.uniform(3, 8)
                logger.warning(
                    "HTTP %d — sleeping %.1fs before retry #%d | %s",
                    response.status, delay, retry_count + 1, request.url[:80],
                )
                time.sleep(delay)
                reason = response_status_message(response.status)
                retry_req = get_retry_request(request, spider=spider, reason=reason)
                return retry_req or response

        return super().process_response(request, response, **kwargs)

    def process_exception(self, request, exception, **kwargs):
        logger.warning(
            "Exception %s on %s — attempting retry",
            type(exception).__name__, request.url[:80],
        )
        return super().process_exception(request, exception, **kwargs)

    @classmethod
    def from_crawler(cls, crawler):
        middleware = super().from_crawler(crawler)
        middleware._crawler = crawler
        return middleware

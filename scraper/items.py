# scraper/items.py
"""
Scrapy Items cho HanoiRent Insights.
Mỗi RentingItem đại diện cho 1 tin đăng nhà cho thuê.
"""

import scrapy


class RentingItem(scrapy.Item):
    # --- Định danh nguồn ---
    source_name = scrapy.Field()      # str: 'nhatot' | 'batdongsan' | 'mogi'
    source_id   = scrapy.Field()      # str: ID gốc trên website nguồn
    source_url  = scrapy.Field()      # str: URL đầy đủ của tin

    # --- Thông tin chính ---
    title           = scrapy.Field()  # str
    description     = scrapy.Field()  # str
    price_vnd       = scrapy.Field()  # int: giá VND/tháng
    area_m2         = scrapy.Field()  # float: diện tích m²
    bedrooms        = scrapy.Field()  # int | None
    bathrooms       = scrapy.Field()  # int | None
    property_type   = scrapy.Field()  # str: 'phong_tro' | 'chung_cu' | 'nha_nguyen_can' | 'can_ho_dich_vu'
    furnishing_level = scrapy.Field() # str | None: 'bare' | 'partial' | 'full' | 'luxury'

    # --- Địa chỉ ---
    address     = scrapy.Field()      # str: địa chỉ đầy đủ thô
    district    = scrapy.Field()      # str: tên quận đã chuẩn hoá
    ward        = scrapy.Field()      # str | None: tên phường

    # --- Ảnh ---
    thumbnail_url   = scrapy.Field()  # str | None: URL ảnh đầu tiên (thumbnail)
    image_urls      = scrapy.Field()  # list[str]: tất cả URL ảnh (dùng trong pipeline)

    # --- Thời gian ---
    posted_at   = scrapy.Field()      # str | None: ngày đăng dạng ISO hoặc text gốc

    # --- NLP-extracted fields (điền ở Silver ETL stage) ---
    amenities   = scrapy.Field()      # list[str] | None: ['dieu_hoa', 'tu_lanh', ...]

    # --- Raw payload (lưu vào bronze) ---
    raw_payload = scrapy.Field()      # dict: toàn bộ data thô gốc

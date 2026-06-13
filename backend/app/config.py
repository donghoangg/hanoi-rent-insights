"""Cấu hình ứng dụng backend — đọc từ biến môi trường / .env.

Backend kết nối trực tiếp tầng Gold trên Supabase (PostgreSQL) qua DATABASE_URL.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Biến cấu hình cho backend.

    Ưu tiên đọc file .env ở thư mục gốc dự án (hoặc backend/.env).
    """

    # Chuỗi kết nối PostgreSQL (Supabase). Bắt buộc để chạy production.
    # Ví dụ: postgresql://postgres.xxx:password@aws-1-...:5432/postgres
    database_url: str = ""

    # Tên schema Gold trên DB.
    gold_schema: str = "gold"

    # Danh sách origin được phép gọi API (frontend). Phân tách bằng dấu phẩy.
    # Mặc định cho phép localhost (dev) — production set qua biến môi trường.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(
        # Tìm .env ở backend/.env trước, rồi tới .env gốc repo.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Tách cors_origins thành list; '*' để mở cho mọi origin (demo)."""
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Trả về Settings (cache 1 lần cho cả vòng đời process)."""
    return Settings()

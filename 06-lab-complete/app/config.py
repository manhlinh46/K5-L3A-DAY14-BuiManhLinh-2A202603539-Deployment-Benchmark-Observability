"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

  • PORT, ENVIRONMENT, AGENT_API_KEY, REDIS_URL,
    RATE_LIMIT_PER_MINUTE, DAILY_BUDGET_USD, LOG_LEVEL
  • Không hard-code secret: AGENT_API_KEY mặc định rỗng → mọi request /ask bị 401
    cho tới khi đặt biến môi trường.
  • Danh sách đầy đủ nằm trong .env.example.
"""
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass
class Settings:
    port: int = field(default_factory=lambda: _int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Secret — chỉ đọc từ env, không có giá trị mặc định thật
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _float("DAILY_BUDGET_USD", 1.0))


settings = Settings()

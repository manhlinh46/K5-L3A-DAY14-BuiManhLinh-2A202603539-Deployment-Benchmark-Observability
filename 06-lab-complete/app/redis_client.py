"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • redis.from_url() chỉ tạo connection pool, KHÔNG kết nối ngay → app vẫn khởi động
    được khi Redis chưa sẵn sàng (container chạy một mình, /health vẫn 200).
  • Timeout ngắn (1–2 s) để /ready và /ask trả lỗi nhanh thay vì treo khi mất Redis.
  • redis_healthy() dùng cho GET /ready.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=2,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False

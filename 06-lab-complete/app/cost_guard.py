"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, key theo ngày UTC: cost:YYYY-MM-DD
  • Tổng chi phí trong ngày ≥ DAILY_BUDGET_USD → HTTP 402
  • Key tự hết hạn sau 2 ngày → không phải dọn tay; sang ngày mới là budget reset.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

KEY_TTL_SECONDS = 2 * 24 * 3600


def _today_key() -> str:
    return "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_cost() -> float:
    return float(r.get(_today_key()) or 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spent = current_cost()
    budget = settings.daily_budget_usd
    if spent >= budget:
        raise HTTPException(
            status_code=402,
            detail={"error": "Daily budget exceeded", "spent_usd": round(spent, 6),
                    "budget_usd": budget, "resets_at": "00:00 UTC"},
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    key = _today_key()
    pipe = r.pipeline(transaction=True)
    pipe.incrbyfloat(key, cost)          # atomic → nhiều worker cộng đồng thời không mất số
    pipe.expire(key, KEY_TTL_SECONDS)
    pipe.execute()
    return cost

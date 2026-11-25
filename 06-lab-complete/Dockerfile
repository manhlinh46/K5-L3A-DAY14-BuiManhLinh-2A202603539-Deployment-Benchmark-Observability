# ============================================================
# Production Dockerfile — multi-stage
#   Stage 1 (builder): tạo virtualenv /opt/venv và cài dependencies
#   Stage 2 (runtime): chỉ copy /opt/venv + code, chạy bằng user non-root
# Không cần apt-get: mọi package trong requirements.txt đều có wheel dựng sẵn.
# ============================================================

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements TRƯỚC code → layer pip install được cache khi chỉ sửa code
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# User non-root — container bị chiếm quyền cũng không có quyền root
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app

EXPOSE 8000

# Docker tự gọi /health; fail 3 lần liên tiếp → container "unhealthy"
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=3)" || exit 1

# `exec` → uvicorn thay thế shell, trở thành PID 1 và nhận SIGTERM trực tiếp khi `docker stop`.
# ${PORT:-8000}: Railway/Render cấp PORT qua env, local mặc định 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]

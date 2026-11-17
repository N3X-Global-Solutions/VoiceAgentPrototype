# Voice Agent Studio: one image with the FastAPI/Pipecat backend serving the built React UI.

# ---------------------------------------------------------------- 1. build the UI
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- 2. backend + UI
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    DATA_DIR=/app/data \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend
# Dependencies first, so code changes don't reinstall them.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3

COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Run as a non-root user; /app/data holds the SQLite DB and is a volume.
RUN useradd --system --uid 10001 --home /app app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data
USER app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"7860\")}/api/healthz', timeout=4)"

# One worker on purpose: live calls (WebRTC peers, phone WebSockets) live in this process.
# --proxy-headers trusts X-Forwarded-Proto from Caddy so the session cookie is marked Secure.
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"${HOST:-127.0.0.1}\" --port \"${PORT:-7860}\" --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]

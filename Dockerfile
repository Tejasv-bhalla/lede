# Lede in one container: the React app is built first, then served by the API on one origin.

# ── 1. build the web app ────────────────────────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx vite build --logLevel warn

# ── 2. the API, serving the built app ───────────────────────────────────────
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY --from=web /web/dist /app/web/dist

RUN useradd --create-home lede
USER lede

# Render (and most hosts) pass the port in $PORT. Secrets come from the host's environment;
# no .env file is baked into the image.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

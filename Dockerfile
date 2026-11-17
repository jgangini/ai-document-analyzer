FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build/frontend

COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci

COPY apps/frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS backend-builder
WORKDIR /build/backend

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY apps/backend/requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.11-slim-bookworm AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        nginx \
        curl \
        libgomp1 \
        libglib2.0-0 \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf

COPY --from=backend-builder /install /usr/local
COPY apps/backend /app/apps/backend
COPY apps/__init__.py /app/apps/__init__.py
COPY --from=frontend-builder /build/frontend/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/ai-document-analyzer.conf
COPY docker/start.sh /app/docker/start.sh

RUN chmod +x /app/docker/start.sh \
    && mkdir -p \
        /app/apps/backend/data \
        /app/apps/backend/wallet \
        /app/apps/backend/keys \
        /app/apps/backend/logs \
    && touch /app/apps/backend/logs/runtime_trace.jsonl

EXPOSE 80

VOLUME ["/app/apps/backend/data", "/app/apps/backend/wallet", "/app/apps/backend/keys", "/app/apps/backend/logs"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl --fail http://127.0.0.1/api/health || exit 1

CMD ["/app/docker/start.sh"]

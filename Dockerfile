# --- Etapa 1: build del frontend ---
FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Etapa 2: backend + estáticos ---
FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/app ./app
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

ENV PATH="/app/backend/.venv/bin:$PATH" \
    SOLVENTO_CACHE_DB_PATH=/data/pvgis_cache.db
RUN mkdir /data
VOLUME /data

EXPOSE 8000
# HOST/PORT se pueden sobreescribir al arrancar el contenedor
CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]

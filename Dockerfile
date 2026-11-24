# Spark — Multi-stage Dockerfile
# Builds frontend, installs backend deps, runs FastAPI on port 8000.

# ──────────────────────────────────────────────────────────────
# Stage 1: Frontend build
# ──────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ──────────────────────────────────────────────────────────────
# Stage 2: Backend runtime
# ──────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for tzdata (IANA zones on Debian) and Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libjpeg62-turbo \
    libwebp7 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Data directory (mounted at runtime for persistence)
RUN mkdir -p /app/data

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Create app at import time (initializes DB, seeds mock workspace)
ENV PYTHONPATH=/app/backend
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# Multi-stage build for chess-trainer web server
# Works with both Podman (podman build) and Docker (docker build)

# ── Builder stage ────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev, web extras only)
RUN uv sync --frozen --no-dev --extra web --no-install-project

# Copy application source and assets
COPY src/ src/
COPY assets/ assets/

# Install the project itself
RUN uv sync --frozen --no-dev --extra web

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

# Create non-root user
RUN groupadd -g 1000 chess && \
    useradd -u 1000 -g chess -m chess

# Create data directory for volume mount
RUN mkdir /data && chown chess:chess /data

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Put the venv on PATH so `chess-trainer` CLI is available
ENV PATH="/app/.venv/bin:$PATH"

# Application defaults
ENV CHESS_TRAINER_WEB_HOST=0.0.0.0 \
    CHESS_TRAINER_WEB_PORT=8000 \
    CHESS_TRAINER_AUTH_ENABLED=true \
    CHESS_TRAINER_AUTH_DATABASE_PATH=/data/auth.db \
    CHESS_TRAINER_DATA_DIR=/data

EXPOSE 8000

USER chess
WORKDIR /data

CMD ["chess-trainer", "web"]

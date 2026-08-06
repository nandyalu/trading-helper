FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY TradingAgents/ ./TradingAgents/
# --locked fails the build if uv.lock is out of sync with pyproject.toml,
# instead of silently installing a stale resolution. Non-editable path
# dependency (see pyproject.toml's [tool.uv.sources]): this is a production
# image, and an editable install would leave tradingagents pointing back at
# this build-stage path, which doesn't exist in the final stage below.
RUN uv sync --locked --no-dev

# Docs are built in their own stage so zensical and its dependencies never
# reach the runtime image — only the static site/ output does.
FROM python:3.14-slim AS docsbuilder

RUN pip install --no-cache-dir zensical

WORKDIR /docs-build
COPY zensical.toml ./
COPY docs/ ./docs/
RUN python -m zensical build

# Same idea as docsbuilder: Node/npm and the whole Angular toolchain never
# reach the runtime image, only the static production build output does.
FROM node:22-slim AS frontendbuilder

WORKDIR /frontend-build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents
WORKDIR /app

COPY --chown=appuser:appuser bot/ ./bot/
# Static docs site, served at /docs by bot/app.py.
COPY --from=docsbuilder --chown=appuser:appuser /docs-build/site ./site/
# Angular production build, served at the container's web root by
# bot/app.py (with an index.html fallback for client-side routes).
COPY --from=frontendbuilder --chown=appuser:appuser /frontend-build/dist/frontend/browser ./web/
# Owned by appuser *before* the VOLUME instruction so a freshly created named
# volume inherits appuser ownership instead of defaulting to root.
RUN mkdir -p /app/data && chown appuser:appuser /app/data
VOLUME ["/app/data"]

USER appuser

# Idempotent: every start/redeploy just confirms the DB is already at head.
ENTRYPOINT ["sh", "-c", "python -m alembic -c bot/alembic.ini upgrade head && python -m bot.main"]

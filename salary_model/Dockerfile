# syntax=docker/dockerfile:1.7
# Multi-stage build for the salary-model FastAPI service.
#
# Stage 1 (builder): use uv to materialize the virtual environment from pyproject + lock,
# leaving artifacts/ and data/ out of the image.
# Stage 2 (runtime): non-root, minimal Python base, copy only the venv + source.

ARG PYTHON_VERSION=3.12

# ── Builder ──────────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for cacheable layer
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev || \
    uv sync --no-install-project --no-dev

# Now copy source and build the project itself
COPY src ./src
COPY README.md ./README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    SALARY_MODEL_DATA_DIR=/data \
    SALARY_MODEL_ARTIFACTS_DIR=/artifacts

RUN groupadd --system --gid 1001 app \
 && useradd --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --chown=app:app pyproject.toml ./pyproject.toml

# Persist mount points for data and trained bundles
RUN install -d -o app -g app /data /artifacts /reports

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3).status==200 else 1)"

CMD ["uvicorn", "salary_model.api.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

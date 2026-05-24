# syntax=docker/dockerfile:1.7
# job-crawler — single image runs both the API and the per-source crawlers.
#
# Build:   make build-image
# Run API: docker run --rm -p 8080:8080 -e JCDB_DSN=... localhost/job-crawler:latest api
# Run job: docker run --rm -e JCDB_DSN=... localhost/job-crawler:latest crawler greenhouse
#
# Multi-stage uv build keeps the final image small (~150 MB).

# ---------------------------------------------------------------------------
# Build stage — install deps into a venv with uv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

# uv: deterministic, fast resolver. Pulled from the official tagged release.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

# Copy only the metadata first so dep installation can cache.
COPY pyproject.toml README.md ./
COPY src ./src

# Install into /opt/venv with both the API and crawler extras.
RUN uv venv /opt/venv && \
    VIRTUAL_ENV=/opt/venv uv pip install --no-cache -e ".[api,crawler]"


# ---------------------------------------------------------------------------
# Runtime stage — slim image, non-root, read-only root FS friendly
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Minimal runtime needs: libpq for psycopg's binary wheels is already
# bundled. We add `tini` for clean signal handling in k8s pods.
RUN apt-get update && apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10001 app && useradd -u 10001 -g 10001 -s /usr/sbin/nologin -M app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src /app/src
COPY db_schema.sql /app/db_schema.sql
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /app
USER 10001:10001

EXPOSE 8080

# tini reaps zombies + forwards signals so uvicorn / cli get clean shutdown.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["api"]

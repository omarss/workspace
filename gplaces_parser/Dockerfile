# ---- stage 1: build wheels --------------------------------------------------
FROM python:3.12-slim AS build

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip build \
 && pip wheel --wheel-dir=/wheels .

# ---- stage 2: runtime (API only; scraper runs on the host) -----------------
FROM python:3.12-slim

# Non-root user; API never needs root at runtime.
RUN useradd --system --uid 10001 --create-home gplaces

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels gplaces-parser \
 && rm -rf /wheels

USER gplaces

EXPOSE 8000

# Tiny HTTP healthcheck — matches /v1/health in routes.py.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u, sys; \
                 sys.exit(0 if u.urlopen('http://127.0.0.1:8000/v1/health', timeout=2).status == 200 else 1)"

CMD ["gplaces", "serve"]

# Web worker image — includes Playwright and Chromium
FROM node:20-slim AS base

WORKDIR /app

# System deps for Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libxshmfence1 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@latest --activate

# Install deps
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Install Chromium via Playwright
RUN npx playwright install chromium

# Build
COPY tsconfig.json ./
COPY src/ ./src/
RUN pnpm build

# Runtime config
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
ENV NODE_ENV=production

ENTRYPOINT ["node", "dist/cli/main.js"]

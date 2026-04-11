# CLI-only image — lightweight, no browser or Android tooling
FROM node:20-slim AS base

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Install dependencies
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --prod

# Build
COPY tsconfig.json ./
COPY src/ ./src/
RUN pnpm install --frozen-lockfile && pnpm build && rm -rf src node_modules/.cache

# Production image
FROM node:20-slim AS production

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY --from=base /app/package.json /app/pnpm-lock.yaml ./
COPY --from=base /app/dist/ ./dist/
COPY --from=base /app/node_modules/ ./node_modules/

ENTRYPOINT ["node", "dist/cli/main.js"]

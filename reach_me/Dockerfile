# syntax=docker/dockerfile:1

FROM docker.io/oven/bun:1.3.5-alpine AS builder

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY tsconfig.json tsconfig.build.json nest-cli.json ./
COPY src ./src
COPY test ./test

RUN bun run build

FROM docker.io/oven/bun:1.3.5-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production

# Create a non-root user
RUN addgroup -S app && adduser -S app -G app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

COPY --from=builder /app/dist ./dist

USER app
EXPOSE 3000

CMD ["bun", "dist/main.js"]

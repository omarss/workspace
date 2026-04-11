# Android worker image — includes adb and UiAutomator tooling
# NOTE: This image provides the control plane only.
# The actual Android virtual device (Cuttlefish/Emulator) runs on the host
# or in a separate VM with KVM access.
FROM node:20-slim AS base

WORKDIR /app

# Install adb and supporting tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@latest --activate

# Install deps
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Build
COPY tsconfig.json ./
COPY src/ ./src/
RUN pnpm build

ENV NODE_ENV=production

# adb server must connect to the host's Android device/emulator
# Set ADB_SERVER_SOCKET or use --serial to target a specific device
ENTRYPOINT ["node", "dist/cli/main.js"]

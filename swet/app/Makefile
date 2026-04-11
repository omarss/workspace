.PHONY: setup dev build lint test test-cov test-e2e clean

# Install dependencies
setup:
	pnpm install

# Run development server
dev:
	pnpm dev

# Production build
build:
	pnpm build

# Lint and type-check
lint:
	pnpm lint

# Run unit tests
test:
	pnpm test

# Run tests with coverage
test-cov:
	pnpm test:cov

# Run E2E tests
test-e2e:
	pnpm test:e2e

# Clean build artifacts
clean:
	rm -rf .next node_modules coverage

.PHONY: dev dev-be dev-fe db db-stop test lint clean setup

# Start PostgreSQL
db:
	docker compose up -d postgres
	@echo "Waiting for PostgreSQL to be ready..."
	@until docker compose exec postgres pg_isready -U swet > /dev/null 2>&1; do sleep 1; done
	@echo "PostgreSQL is ready."

db-stop:
	docker compose down

# Setup everything from scratch
setup: db
	$(MAKE) -C backend setup
	$(MAKE) -C app setup

# Development
dev:
	$(MAKE) dev-be & $(MAKE) dev-fe & wait

dev-be:
	$(MAKE) -C backend dev

dev-fe:
	$(MAKE) -C app dev

# Testing
test:
	$(MAKE) -C backend test
	$(MAKE) -C app test

test-be:
	$(MAKE) -C backend test

test-fe:
	$(MAKE) -C app test

# Linting
lint:
	$(MAKE) -C backend lint
	$(MAKE) -C app lint

# Clean
clean:
	$(MAKE) -C backend clean
	$(MAKE) -C app clean

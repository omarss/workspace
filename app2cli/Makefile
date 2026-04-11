.PHONY: build lint lint-fix test typecheck check audit clean dev shell install

# install dependencies
install:
	pnpm install

# build the project
build:
	pnpm build

# lint with zero warnings tolerance
lint:
	pnpm lint

# lint and auto-fix
lint-fix:
	pnpm lint:fix

# run tests
test:
	pnpm test

# typecheck without emitting
typecheck:
	pnpm typecheck

# lint + typecheck + test (run before every commit)
check:
	pnpm check

# deterministic repo audit (includes build verification)
audit:
	pnpm audit:repo

# clean build artifacts
clean:
	pnpm clean

# run cli in development mode (pass args after --)
# usage: make dev -- web snapshot https://example.com
dev:
	pnpm tsx src/cli/main.ts $(filter-out $@,$(MAKECMDGOALS))

# start interactive shell
shell:
	pnpm tsx src/cli/main.ts shell

# catch-all to allow passing args to dev
%:
	@:

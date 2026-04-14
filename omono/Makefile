# Omono — convenience wrappers around Gradle. All day-to-day build/test/run
# operations should go through here so they stay consistent across machines,
# CI, and AI agents (per the project conventions).

GRADLEW := ./gradlew

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: wrapper
wrapper: ## Regenerate the Gradle wrapper (requires system gradle)
	gradle wrapper --gradle-version=9.3.1 --distribution-type=bin

.PHONY: clean
clean: ## Remove all build outputs
	$(GRADLEW) clean

.PHONY: build
build: ## Assemble debug APK for all modules
	$(GRADLEW) assembleDebug

.PHONY: release
release: ## Assemble release APK (signed via app/keystore.properties or debug)
	$(GRADLEW) assembleRelease
	@echo
	@echo "  APK: app/build/outputs/apk/release/app-release.apk"

.PHONY: release-keystore
release-keystore: ## Generate a personal release keystore (interactive)
	@if [ -f app/keystore.properties ]; then \
		echo "app/keystore.properties already exists — refusing to overwrite."; \
		exit 1; \
	fi
	@mkdir -p $$HOME/.android
	keytool -genkeypair -v \
		-keystore $$HOME/.android/omono-release.jks \
		-keyalg RSA -keysize 4096 -validity 10000 \
		-alias omono
	@echo
	@echo "Now create app/keystore.properties with:"
	@echo "  storeFile=$$HOME/.android/omono-release.jks"
	@echo "  storePassword=<your store password>"
	@echo "  keyAlias=omono"
	@echo "  keyPassword=<your key password>"

.PHONY: publish
publish: ## Upload the release APK to OMONO_RELEASE_HOST (rsync target)
	@./scripts/publish.sh

.PHONY: lint
lint: ## Run Android lint on debug variant
	$(GRADLEW) lintDebug

.PHONY: test
test: ## Run JVM + Robolectric unit tests
	$(GRADLEW) testDebugUnitTest

.PHONY: connected-test
connected-test: ## Run instrumentation tests on a connected device/emulator
	$(GRADLEW) connectedDebugAndroidTest

.PHONY: check
check: ## Run full verification (lint + tests)
	$(GRADLEW) check

.PHONY: install
install: ## Install debug APK on the connected device
	$(GRADLEW) installDebug

.PHONY: uninstall
uninstall: ## Uninstall the debug build from the connected device
	$(GRADLEW) uninstallDebug

.PHONY: deps
deps: ## Print the dependency graph for :app
	$(GRADLEW) :app:dependencies

.PHONY: tasks
tasks: ## List all Gradle tasks
	$(GRADLEW) tasks --all

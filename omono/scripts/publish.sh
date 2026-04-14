#!/usr/bin/env bash
# Publish a release APK to the homelab nginx host so Obtainium can pick it up.
#
# Required env:
#   OMONO_RELEASE_HOST  rsync target, e.g. user@homelab:/srv/nginx/omono/
#
# Optional env:
#   OMONO_RELEASE_URL   public URL of the directory (printed for Obtainium setup)
#
# Usage: scripts/publish.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${OMONO_RELEASE_HOST:-}" ]]; then
    echo "OMONO_RELEASE_HOST is not set." >&2
    echo "Example: OMONO_RELEASE_HOST=user@homelab:/srv/nginx/omono/ make publish" >&2
    exit 1
fi

# Read versionName from the app module without invoking Gradle. Quick and
# deterministic for a single-line declaration.
VERSION=$(grep -oP 'versionName = "\K[^"]+' app/build.gradle.kts)
if [[ -z "$VERSION" ]]; then
    echo "Could not determine versionName from app/build.gradle.kts" >&2
    exit 1
fi

APK_SOURCE="app/build/outputs/apk/release/app-release.apk"
if [[ ! -f "$APK_SOURCE" ]]; then
    echo "Release APK not found at $APK_SOURCE — run 'make release' first." >&2
    exit 1
fi

VERSIONED="omono-${VERSION}.apk"
LATEST="omono-latest.apk"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

cp "$APK_SOURCE" "$TMP_DIR/$VERSIONED"
cp "$APK_SOURCE" "$TMP_DIR/$LATEST"

# A tiny JSON manifest helps Obtainium's "HTML directory" source resolve
# the latest version reliably without scraping filenames.
cat >"$TMP_DIR/latest.json" <<JSON
{
  "version": "${VERSION}",
  "apk": "${VERSIONED}",
  "latest": "${LATEST}"
}
JSON

echo "==> Uploading ${VERSIONED} + ${LATEST} to ${OMONO_RELEASE_HOST}"
rsync -av --progress "$TMP_DIR/" "${OMONO_RELEASE_HOST}"

echo
echo "==> Published omono ${VERSION}"
if [[ -n "${OMONO_RELEASE_URL:-}" ]]; then
    echo "    Latest:    ${OMONO_RELEASE_URL%/}/${LATEST}"
    echo "    Versioned: ${OMONO_RELEASE_URL%/}/${VERSIONED}"
    echo "    Manifest:  ${OMONO_RELEASE_URL%/}/latest.json"
    echo
    echo "    In Obtainium, add a new app with source 'Direct APK link' and URL:"
    echo "      ${OMONO_RELEASE_URL%/}/${LATEST}"
fi

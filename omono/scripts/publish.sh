#!/usr/bin/env bash
# Publish a release APK so Obtainium can pick it up.
#
# Defaults target the homelab apps host on this machine — override the
# env vars to push elsewhere.
#
# Env (all optional unless overriding):
#   OMONO_RELEASE_HOST  rsync target. Local path or user@host:/path.
#                      default: /srv/apps
#   OMONO_RELEASE_URL   public base URL (used for the "Done" message).
#                      default: https://apps.omarss.net
#
# Usage: scripts/publish.sh
set -euo pipefail

cd "$(dirname "$0")/.."

OMONO_RELEASE_HOST="${OMONO_RELEASE_HOST:-/srv/apps}"
OMONO_RELEASE_URL="${OMONO_RELEASE_URL:-https://apps.omarss.net}"

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

# Filename layout matches the apps.omarss.net nginx vhost:
#   {app}.latest.apk      ← Obtainium target, short-cached
#   {app}.{version}.apk   ← rollback / pinning, immutable
VERSIONED="omono.${VERSION}.apk"
LATEST="omono.latest.apk"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

cp "$APK_SOURCE" "$TMP_DIR/$VERSIONED"
cp "$APK_SOURCE" "$TMP_DIR/$LATEST"

# Tiny manifest sidecar, useful for tooling that wants to read the
# current version without parsing the APK.
cat >"$TMP_DIR/omono.latest.json" <<JSON
{
  "version": "${VERSION}",
  "apk": "${VERSIONED}",
  "latest": "${LATEST}"
}
JSON

echo "==> Uploading ${VERSIONED} + ${LATEST} to ${OMONO_RELEASE_HOST}"
rsync -av --progress "$TMP_DIR/" "${OMONO_RELEASE_HOST%/}/"

echo
echo "==> Published omono ${VERSION}"
echo "    Latest:    ${OMONO_RELEASE_URL%/}/${LATEST}"
echo "    Versioned: ${OMONO_RELEASE_URL%/}/${VERSIONED}"
echo "    Manifest:  ${OMONO_RELEASE_URL%/}/omono.latest.json"
echo
echo "    In Obtainium, add a new app with source 'Direct APK link' and URL:"
echo "      ${OMONO_RELEASE_URL%/}/${LATEST}"

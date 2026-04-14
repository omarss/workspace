#!/usr/bin/env bash
# Publish a release APK to the apps host so Obtainium can pick it up.
#
# Usually called by ./scripts/release.sh, which sets RELEASE_VERSION and
# CHANGELOG_FILE. Can also be called standalone after `make release`
# (a debug-/manual-built APK) — it'll fall back to the build file's
# versionName and an empty changelog.
#
# Env (all optional):
#   OMONO_RELEASE_HOST  rsync target. Local path or user@host:/path.
#                       default: /srv/apps
#   OMONO_RELEASE_URL   public base URL for the success message.
#                       default: https://apps.omarss.net
#   RELEASE_VERSION     version string to publish. Default: parsed from
#                       app/build.gradle.kts.
#   CHANGELOG_FILE      path to a file with one bullet per line. Default
#                       empty (no entries).
set -euo pipefail

cd "$(dirname "$0")/.."

OMONO_RELEASE_HOST="${OMONO_RELEASE_HOST:-/srv/apps}"
OMONO_RELEASE_URL="${OMONO_RELEASE_URL:-https://apps.omarss.net}"

if [[ -n "${RELEASE_VERSION:-}" ]]; then
    VERSION=$RELEASE_VERSION
else
    VERSION=$(grep -oP 'versionName = "\K[^"]+' app/build.gradle.kts)
fi
if [[ -z "$VERSION" ]]; then
    echo "Could not determine version" >&2
    exit 1
fi

APK_SOURCE="app/build/outputs/apk/release/app-release.apk"
if [[ ! -f "$APK_SOURCE" ]]; then
    echo "Release APK not found at $APK_SOURCE — run 'make release' first." >&2
    exit 1
fi

VERSIONED="omono.${VERSION}.apk"
LATEST="omono.latest.apk"

# Per-file rsync (no temp dir, no `-a`). The previous version staged
# both files in mktemp -d and rsync'd the directory with -a — which
# also propagated mktemp's 700 mode onto /srv/apps, locking nginx
# out with a 403. --no-perms / --no-owner / --no-group keep file
# attributes minimal so the destination dir mode is never touched.
RSYNC_OPTS=(-t --no-perms --no-owner --no-group --info=progress2)
DEST="${OMONO_RELEASE_HOST%/}"

echo "==> Uploading ${VERSIONED} to ${DEST}"
rsync "${RSYNC_OPTS[@]}" "$APK_SOURCE" "${DEST}/${VERSIONED}"
echo "==> Uploading ${LATEST} to ${DEST}"
rsync "${RSYNC_OPTS[@]}" "$APK_SOURCE" "${DEST}/${LATEST}"

# Ask the apps host to merge the new release into manifest.json.
# If we're publishing locally and update-apps-manifest is on PATH,
# call it directly. Otherwise SSH to the remote.
update_manifest_local() {
    update-apps-manifest \
        --app omono \
        --name omono \
        --description "Background speed monitor" \
        --version "$VERSION" \
        --apk "$VERSIONED" \
        ${CHANGELOG_FILE:+--changelog-file "$CHANGELOG_FILE"}
}

update_manifest_remote() {
    local host_part="${OMONO_RELEASE_HOST%%:*}"
    local remote_changelog=""
    if [[ -n "${CHANGELOG_FILE:-}" && -f "$CHANGELOG_FILE" ]]; then
        remote_changelog=/tmp/omono-changelog.$$.txt
        scp -q "$CHANGELOG_FILE" "${host_part}:${remote_changelog}"
    fi
    ssh "$host_part" "update-apps-manifest \
        --app omono \
        --name omono \
        --description 'Background speed monitor' \
        --version '$VERSION' \
        --apk '$VERSIONED' \
        ${remote_changelog:+--changelog-file '$remote_changelog'} \
        && ${remote_changelog:+rm -f '$remote_changelog'}"
}

echo "==> Updating manifest.json"
if [[ "$OMONO_RELEASE_HOST" == *:* ]]; then
    update_manifest_remote
else
    if command -v update-apps-manifest >/dev/null 2>&1; then
        update_manifest_local
    else
        echo "    update-apps-manifest not found on PATH; skipping manifest update." >&2
        echo "    (run 'sudo make -C homelab apply-apps-host' to install it)" >&2
    fi
fi

echo
echo "==> Published omono ${VERSION}"
echo "    Index:     ${OMONO_RELEASE_URL%/}/"
echo "    Latest:    ${OMONO_RELEASE_URL%/}/${LATEST}"
echo "    Versioned: ${OMONO_RELEASE_URL%/}/${VERSIONED}"
echo "    Manifest:  ${OMONO_RELEASE_URL%/}/manifest.json"
echo
echo "    In Obtainium, add a new app with source 'Direct APK link' and URL:"
echo "      ${OMONO_RELEASE_URL%/}/${LATEST}"

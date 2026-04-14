#!/usr/bin/env bash
# Atomically merge a release into /srv/apps/manifest.json.
#
# Installed to /usr/local/bin/update-apps-manifest by setup-apps-host.sh
# so any project's publish flow can call it without depending on the
# homelab repo being checked out.
#
# Usage:
#   update-apps-manifest \
#     --app omono \
#     --name "Omono" \
#     --description "Background speed monitor" \
#     --version 0.1.0 \
#     --apk omono.0.1.0.apk \
#     --changelog-file /tmp/changelog.txt
#
# changelog-file is one bullet per line (raw, no leading dash).
set -euo pipefail

MANIFEST=/srv/apps/manifest.json
APP=
NAME=
DESCRIPTION=
VERSION=
APK=
CHANGELOG_FILE=

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app) APP=$2; shift 2 ;;
        --name) NAME=$2; shift 2 ;;
        --description) DESCRIPTION=$2; shift 2 ;;
        --version) VERSION=$2; shift 2 ;;
        --apk) APK=$2; shift 2 ;;
        --changelog-file) CHANGELOG_FILE=$2; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

for required in APP VERSION APK; do
    if [[ -z "${!required}" ]]; then
        echo "Missing --${required,,}" >&2
        exit 1
    fi
done

if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required but not installed" >&2
    exit 1
fi

APK_PATH="/srv/apps/${APK}"
if [[ ! -f "$APK_PATH" ]]; then
    echo "APK not found at ${APK_PATH} — rsync it first" >&2
    exit 1
fi

SIZE=$(stat -c '%s' "$APK_PATH")
# SHA-256 is recorded so the index page can display it for verification.
# Users who care can `sha256sum omono.latest.apk | grep $sha` to confirm
# the file they downloaded matches what the manifest claims.
SHA256=$(sha256sum "$APK_PATH" | awk '{print $1}')
RELEASED_AT=$(date -u -Iseconds | sed 's/+00:00/Z/')
NOW=$RELEASED_AT

# Build the changelog JSON array. jq --rawfile reads the file as a single
# string; we split on newlines and drop blanks.
CHANGELOG_JSON='[]'
if [[ -n "$CHANGELOG_FILE" && -f "$CHANGELOG_FILE" ]]; then
    CHANGELOG_JSON=$(jq --rawfile raw "$CHANGELOG_FILE" -n \
        '$raw | split("\n") | map(select(length > 0))')
fi

# Seed the manifest if missing.
if [[ ! -f "$MANIFEST" ]]; then
    echo '{"apps":{}}' > "$MANIFEST"
fi

NEW_RELEASE=$(jq -n \
    --arg version "$VERSION" \
    --arg apk "$APK" \
    --arg released_at "$RELEASED_AT" \
    --arg sha256 "$SHA256" \
    --argjson size "$SIZE" \
    --argjson changelog "$CHANGELOG_JSON" \
    '{version:$version, apk:$apk, released_at:$released_at, size_bytes:$size, sha256:$sha256, changelog:$changelog}')

# Merge:
#   - update or insert apps[$app]
#   - prepend the new release (deduping by version, newest first)
#   - refresh latest pointer
#   - bump generated_at
TMP=$(mktemp)
jq \
    --arg app "$APP" \
    --arg name "${NAME:-$APP}" \
    --arg description "$DESCRIPTION" \
    --arg now "$NOW" \
    --argjson release "$NEW_RELEASE" \
    '
    .generated_at = $now
    | .apps //= {}
    | .apps[$app] //= {name: $name, description: $description, releases: []}
    | .apps[$app].name = $name
    | (if $description != "" then .apps[$app].description = $description else . end)
    | .apps[$app].releases = (
        [$release] + (.apps[$app].releases // [])
        | unique_by(.version)
        | sort_by(.version | split(".") | map(tonumber? // 0))
        | reverse
      )
    | .apps[$app].latest = .apps[$app].releases[0]
    ' "$MANIFEST" > "$TMP"

mv "$TMP" "$MANIFEST"
chmod 644 "$MANIFEST"
echo "Updated $MANIFEST: $APP @ $VERSION"

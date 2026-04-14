#!/usr/bin/env bash
# Auto-bump versionName + versionCode in app/build.gradle.kts based on
# conventional commits since the last `omono/v*` tag.
#
# Bump rules:
#   - any commit message with `BREAKING CHANGE` or `<type>!:`  → major
#   - any commit message starting with `feat`                  → minor
#   - otherwise                                                → patch
#
# First-ever release (no tags) keeps the current versionName and just
# bumps versionCode.
#
# Prints the resolved new version to stdout. Exits 1 with no output if
# there's nothing new to release.
set -euo pipefail

cd "$(dirname "$0")/.."

BUILD_FILE=app/build.gradle.kts
TAG_PREFIX="omono/v"

current_version=$(grep -oP 'versionName = "\K[^"]+' "$BUILD_FILE")
current_code=$(grep -oP 'versionCode = \K\d+' "$BUILD_FILE")
if [[ -z "$current_version" || -z "$current_code" ]]; then
    echo "Could not parse versionName/versionCode from $BUILD_FILE" >&2
    exit 2
fi

# Sort tags by semver components, take the highest. `git tag -l --sort`
# sorts lexically; `version:refname` sorts semver-aware.
last_tag=$(git tag -l "${TAG_PREFIX}*" --sort=-version:refname | head -1)

if [[ -z "$last_tag" ]]; then
    new_version="$current_version"
    new_code=$((current_code + 1))
else
    # Range: last release → HEAD, restricted to omono/ paths.
    range="${last_tag}..HEAD"
    commits=$(git log --pretty='%B%n---%n' "$range" -- . 2>/dev/null || true)
    if [[ -z "${commits// }" ]]; then
        echo "Nothing new to release since $last_tag" >&2
        exit 1
    fi

    bump=patch
    while IFS= read -r line; do
        if [[ "$line" =~ BREAKING\ CHANGE ]] || [[ "$line" =~ ^[a-z]+(\(.*\))?!: ]]; then
            bump=major
            break
        elif [[ "$line" =~ ^feat(\(.*\))?: ]] && [[ "$bump" != major ]]; then
            bump=minor
        fi
    done <<<"$commits"

    last_version="${last_tag#$TAG_PREFIX}"
    IFS='.' read -r major minor patch <<<"$last_version"
    case "$bump" in
        major) major=$((major + 1)); minor=0; patch=0 ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        patch) patch=$((patch + 1)) ;;
    esac
    new_version="${major}.${minor}.${patch}"
    new_code=$((current_code + 1))
fi

# Rewrite the build file. Use a temp file + mv for atomicity so a
# half-edit can't poison subsequent steps.
TMP=$(mktemp)
sed -e "s/versionName = \"${current_version}\"/versionName = \"${new_version}\"/" \
    -e "s/versionCode = ${current_code}/versionCode = ${new_code}/" \
    "$BUILD_FILE" > "$TMP"
mv "$TMP" "$BUILD_FILE"

echo "$new_version"

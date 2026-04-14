#!/usr/bin/env bash
# One-shot release orchestrator.
#
# Steps (any failure aborts the rest):
#   1. Refuse if there's a dirty working tree (we're about to commit).
#   2. Auto-bump versionName + versionCode from conventional commits.
#   3. Generate the changelog (raw lines, written to a tempfile).
#   4. Stage + commit the version bump.
#   5. Tag the commit `omono/v${VERSION}`.
#   6. Build the release APK.
#   7. Publish (rsync + manifest update on the apps host).
#   8. Push origin main + the new tag.
#
# Override the publish target with OMONO_RELEASE_HOST / OMONO_RELEASE_URL.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! git diff --quiet -- . || ! git diff --cached --quiet -- .; then
    echo "Refusing to release: working tree has uncommitted changes." >&2
    echo "Commit or stash them first." >&2
    exit 1
fi

echo "==> Computing next version"
NEW_VERSION=$(./scripts/bump-version.sh)
echo "    new version: ${NEW_VERSION}"

echo "==> Generating changelog"
CHANGELOG_FILE=$(mktemp)
trap 'rm -f "$CHANGELOG_FILE"' EXIT
./scripts/changelog.sh > "$CHANGELOG_FILE"
if [[ ! -s "$CHANGELOG_FILE" ]]; then
    echo "Empty changelog — refusing to release. Commit something first." >&2
    exit 1
fi
echo "    $(wc -l < "$CHANGELOG_FILE") changelog entries"

echo "==> Committing version bump"
# Run from repo root so the path is correct regardless of cwd.
REPO_ROOT=$(git rev-parse --show-toplevel)
git -C "$REPO_ROOT" add omono/app/build.gradle.kts
git -C "$REPO_ROOT" commit -m "release omono v${NEW_VERSION}"

echo "==> Tagging omono/v${NEW_VERSION}"
git -C "$REPO_ROOT" tag "omono/v${NEW_VERSION}"

echo "==> Building release APK"
./gradlew assembleRelease

echo "==> Publishing"
CHANGELOG_FILE="$CHANGELOG_FILE" RELEASE_VERSION="$NEW_VERSION" ./scripts/publish.sh

echo "==> Pushing origin main + tag"
git -C "$REPO_ROOT" push origin main
git -C "$REPO_ROOT" push origin "omono/v${NEW_VERSION}"

echo
echo "==> Released omono v${NEW_VERSION}"

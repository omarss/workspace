#!/usr/bin/env bash
# Print the changelog (one bullet per line, raw conventional-commit form)
# for commits since the last `omono/v*` tag that touched omono/.
#
# If no tag exists, print every omono/ commit so the first release has
# meaningful history.
set -euo pipefail

cd "$(dirname "$0")/.."

TAG_PREFIX="omono/v"
last_tag=$(git tag -l "${TAG_PREFIX}*" --sort=-version:refname | head -1)

if [[ -n "$last_tag" ]]; then
    range="${last_tag}..HEAD"
else
    range="HEAD"
fi

# %s gives just the subject line. We deliberately keep the conventional
# commit prefix so the index page can colour-code feat/fix/break.
git log --pretty='%s' "$range" -- . 2>/dev/null \
    | grep -v '^$' \
    || true

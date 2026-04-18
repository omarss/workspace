#!/usr/bin/env bash
# Print commit subjects since the last `gplaces/v*` tag that touched
# gplaces_parser/, one per line. Used by `make release` to build the
# message body for the release commit + tag annotation.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

last_tag="$(git tag --list 'gplaces/v*' --sort=-v:refname | head -n1 || true)"
if [[ -z "$last_tag" ]]; then
    git log --pretty=format:'%s' -- gplaces_parser/
else
    git log "$last_tag"..HEAD --pretty=format:'%s' -- gplaces_parser/
fi

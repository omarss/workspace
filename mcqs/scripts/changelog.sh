#!/usr/bin/env bash
# Print commit subjects since the last `mcqs/v*` tag that touched mcqs/,
# one per line.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

last_tag="$(git tag --list 'mcqs/v*' --sort=-v:refname | head -n1 || true)"
if [[ -z "$last_tag" ]]; then
    git log --pretty=format:'%s' -- mcqs/
else
    git log "$last_tag"..HEAD --pretty=format:'%s' -- mcqs/
fi

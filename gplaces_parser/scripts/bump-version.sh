#!/usr/bin/env bash
# Parse the last `gplaces/v*` tag, classify the bump from conventional-
# commit prefixes since that tag, rewrite pyproject.toml's version, and
# print the new version on stdout. Exits 0 with "keep" + no write if
# there are no commits touching gplaces_parser/ since the last tag.
#
# Classification:
#   any `BREAKING CHANGE` / `!:` / `major:` → major
#   else if any `feat:`                     → minor
#   else                                    → patch
#
# Overridable with BUMP=major|minor|patch in the environment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
PYPROJECT="$ROOT/pyproject.toml"

cd "$REPO_ROOT"

last_tag="$(git tag --list 'gplaces/v*' --sort=-v:refname | head -n1 || true)"
if [[ -z "$last_tag" ]]; then
    # No prior tag — start from the version in pyproject.toml itself.
    current="$(grep -E '^version\s*=' "$PYPROJECT" | head -1 | sed -E 's/^version\s*=\s*"([^"]+)".*$/\1/')"
    commits=""
else
    current="${last_tag#gplaces/v}"
    commits="$(git log "$last_tag"..HEAD --pretty=format:'%s%n%b' -- gplaces_parser/ 2>/dev/null || true)"
fi

if [[ -z "$commits" && -n "$last_tag" ]]; then
    # Nothing changed on gplaces_parser/ since the last tag — bail without a release.
    echo "KEEP $current" >&2
    exit 1
fi

bump="${BUMP:-}"
if [[ -z "$bump" ]]; then
    if grep -qE '(BREAKING CHANGE|^[a-z]+!:|^major:)' <<<"$commits"; then
        bump=major
    elif grep -qE '^(feat|feature)[(:]' <<<"$commits"; then
        bump=minor
    else
        bump=patch
    fi
fi

IFS=. read -r major minor patch <<<"$current"
case "$bump" in
    major) major=$((major + 1)); minor=0; patch=0 ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    patch) patch=$((patch + 1)) ;;
    *) echo "unknown bump '$bump' — expected major|minor|patch" >&2; exit 2 ;;
esac
new="${major}.${minor}.${patch}"

# Rewrite pyproject.toml in-place. Only touch the first `version = "..."`
# under [project] so we don't accidentally bump tool configs elsewhere.
python3 - "$PYPROJECT" "$new" <<'PY'
import sys, re, pathlib
path, new = sys.argv[1], sys.argv[2]
src = pathlib.Path(path).read_text(encoding="utf-8")
# Match `version = "X.Y.Z"` anywhere in the [project] table (project table
# is the first table header that starts with [project]). Simple approach:
# replace only the FIRST occurrence — acceptable because pyproject.toml
# has at most one project version at top.
src2, n = re.subn(r'(?m)^(version\s*=\s*)"[^"]+"', rf'\1"{new}"', src, count=1)
if n != 1:
    print(f"could not find version line in {path}", file=sys.stderr)
    sys.exit(3)
pathlib.Path(path).write_text(src2, encoding="utf-8")
PY

echo "$new"

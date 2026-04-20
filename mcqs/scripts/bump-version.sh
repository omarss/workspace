#!/usr/bin/env bash
# Parse the last `mcqs/v*` tag, classify the bump from conventional-
# commit prefixes since that tag, rewrite pyproject.toml's version, and
# print the new version on stdout. Exits 1 + "keep" if there are no
# commits touching mcqs/ since the last tag.
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

last_tag="$(git tag --list 'mcqs/v*' --sort=-v:refname | head -n1 || true)"
if [[ -z "$last_tag" ]]; then
    current="$(grep -E '^version\s*=' "$PYPROJECT" | head -1 | sed -E 's/^version\s*=\s*"([^"]+)".*$/\1/')"
    commits=""
else
    current="${last_tag#mcqs/v}"
    commits="$(git log "$last_tag"..HEAD --pretty=format:'%s%n%b' -- mcqs/ 2>/dev/null || true)"
fi

if [[ -z "$commits" && -n "$last_tag" ]]; then
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

python3 - "$PYPROJECT" "$new" <<'PY'
import sys, re, pathlib
path, new = sys.argv[1], sys.argv[2]
src = pathlib.Path(path).read_text(encoding="utf-8")
src2, n = re.subn(r'(?m)^(version\s*=\s*)"[^"]+"', rf'\1"{new}"', src, count=1)
if n != 1:
    print(f"could not find version line in {path}", file=sys.stderr)
    sys.exit(3)
pathlib.Path(path).write_text(src2, encoding="utf-8")
PY

echo "$new"

"""Title normalization — `"Sr SWE"` → `"Senior Software Engineer"`.

A small dictionary plus a couple of rewrite rules. Improves both search
ranking (titles compare better post-norm) and the cluster verdict's
de-dup confidence.
"""

from __future__ import annotations

import re
from typing import Final

# Word-level seniority expansions. Order matters: longer keys first.
_SENIORITY: Final[dict[str, str]] = {
    "sr.": "Senior", "sr": "Senior", "snr": "Senior",
    "jr.": "Junior", "jr": "Junior",
    "lvl": "Level",
    "vp": "Vice President",
    "svp": "Senior Vice President",
    "evp": "Executive Vice President",
    "exec": "Executive",
    "asst": "Assistant",
    "assoc": "Associate",
    "mgr": "Manager",
    "supr": "Supervisor",
    "spec": "Specialist",
    "dir": "Director",
    "coord": "Coordinator",
}

# Domain-level expansions.
_ABBREV: Final[dict[str, str]] = {
    "swe": "Software Engineer",
    "sde": "Software Engineer",
    "se": "Software Engineer",
    "qa": "Quality Assurance",
    "sdet": "Software Development Engineer in Test",
    "pm": "Product Manager",
    "tpm": "Technical Program Manager",
    "em": "Engineering Manager",
    "ml": "Machine Learning",
    "ai": "AI",
    "ds": "Data Scientist",
    "de": "Data Engineer",
    "ux": "UX",
    "ui": "UI",
    "sre": "Site Reliability Engineer",
    "devops": "DevOps",
    "fsd": "Full-Stack Developer",
    "fse": "Full-Stack Engineer",
    "fe": "Frontend",
    "be": "Backend",
    "ba": "Business Analyst",
    "hrbp": "HR Business Partner",
    "kyc": "KYC",
    "aml": "AML",
}

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\b[\w.&-]+\b")


def normalize_title(title: str | None) -> str | None:
    """Return a normalised, title-cased variant of `title`.

    `None` in / `None` out. Empty string returns `None`. Long titles
    are preserved verbatim aside from token-level substitutions, so
    we never lose information.
    """
    if not title or not title.strip():
        return None

    def replace(match: re.Match[str]) -> str:
        tok = match.group(0)
        low = tok.lower()
        # Strip a trailing comma so "Sr.," gets handled.
        if low in _SENIORITY:
            return _SENIORITY[low]
        if low in _ABBREV:
            return _ABBREV[low]
        return tok

    expanded = _TOKEN_RE.sub(replace, title)

    # Trim repeated whitespace + Title-case the result for readability.
    cleaned = " ".join(expanded.split())
    # Title-case but preserve ALL-CAPS tokens (e.g. "API", "SAP") and
    # already-title-cased words (e.g. "Saudi", "Aramco").
    out: list[str] = []
    for word in cleaned.split(" "):
        if not word:
            continue
        if (word.isupper() and len(word) <= 5) or any(c.isupper() for c in word[1:]):
            out.append(word)
        else:
            out.append(word.capitalize())
    return " ".join(out)

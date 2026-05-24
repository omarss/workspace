"""Tiny pure-Python text utilities used by the cluster repos.

Kept dependency-free so the DB lib stays portable and importable in any
Python context.
"""

from __future__ import annotations


def is_arabic_dominant(text: str | None) -> bool:
    """True when more than half of the letters in `text` are Arabic.

    Used by `JobsRepo.create_from_posting` + `recompute_canonical` to route
    a posting's `title` / `description` to `title_ar` / `description_ar`
    when the source posted in Arabic, and to `title_en` / `description_en`
    otherwise. Mixed-script strings fall on the side of the dominant script.
    """
    if not text:
        return False
    arabic = 0
    latin = 0
    for ch in text:
        cp = ord(ch)
        if (
            0x0600 <= cp <= 0x06FF       # Arabic
            or 0x0750 <= cp <= 0x077F    # Arabic Supplement
            or 0xFB50 <= cp <= 0xFDFF    # Arabic Presentation Forms-A
            or 0xFE70 <= cp <= 0xFEFF    # Arabic Presentation Forms-B
        ):
            arabic += 1
        elif ch.isalpha():
            latin += 1
    return arabic > latin and arabic > 0

"""Tiny script-detection helpers used to route bilingual postings to the
right column in the DB.

`is_arabic_dominant(text)` returns True when more than half of the letters
in `text` belong to the Arabic Unicode block (U+0600..U+06FF + U+0750..U+077F
+ presentation forms). This is the simplest signal that correctly classifies
"مهندس برمجيات" (Arabic), "Senior Engineer" (English), and mixed strings
like "Engineer / مهندس" (called English here, which is the right behaviour
because the canonical text should go in the field most users will see).
"""

from __future__ import annotations


def is_arabic_dominant(text: str | None) -> bool:
    if not text:
        return False
    arabic = 0
    latin = 0
    for ch in text:
        cp = ord(ch)
        if (0x0600 <= cp <= 0x06FF) or (0x0750 <= cp <= 0x077F) or (0xFB50 <= cp <= 0xFDFF) or (0xFE70 <= cp <= 0xFEFF):
            arabic += 1
        elif ch.isalpha():
            latin += 1
    return arabic > latin and arabic > 0

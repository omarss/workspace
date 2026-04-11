"""Arabic text normalization for Quran text matching."""

import re

TASHKEEL = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7-\u06E8\u06EA-\u06ED]"
)
TATWEEL = "\u0640"


def normalize(text: str) -> str:
    """Normalize Arabic text by removing diacritics and normalizing letter variants."""
    text = TASHKEEL.sub("", text)
    text = text.replace(TATWEEL, "")
    # Alef variants -> plain alef
    for c in "إأآٱ":
        text = text.replace(c, "ا")
    text = text.replace("ة", "ه")  # taa marbuta -> haa
    text = text.replace("ى", "ي")  # alef maqsura -> yaa
    text = text.replace("ؤ", "و")  # waw hamza -> waw
    text = text.replace("ئ", "ي")  # yaa hamza -> yaa
    text = re.sub(r"\s+", " ", text).strip()
    return text

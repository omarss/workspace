"""Arabic-English synonym groups + query expansion.

The tsvector indexes are built with `ar_normalize()` on both sides, so
harakat / alef-variant mismatches are already folded. What's left is
semantic equivalence — a user typing `coffee` should also match
`قهوة` / `كوفي` / `كافيه`, and `مكتبة` should also hit `library` /
`books`.

Rather than managing Postgres synonym dictionary files (which require
shipping text files into $SHAREDIR), we expand at the app layer:

    raw query:      "coffee books"
    normalized:     "coffee books"
    tokenized:      ["coffee", "books"]
    per-token OR:   "(coffee|قهوة|كوفي|كافيه) & (books|library|مكتبة|كتب)"
    → to_tsquery

Each token is looked up in SYNONYMS; if it's part of a group, all
group members OR together; if not, the token passes through verbatim.
All members are themselves `ar_normalize`d so the tsquery matches
against the stored (normalized) tsvector cleanly.
"""

from __future__ import annotations

import re

# Each group lists one concept in every spelling / language users
# realistically type. Order inside a group doesn't matter.
SYNONYM_GROUPS: list[list[str]] = [
    # coffee shops
    ["coffee", "cafe", "caffe", "coffee shop",
     "قهوة", "كوفي", "كافيه", "كافي", "مقهى", "مقاهي"],
    # restaurants
    ["restaurant", "restaurants", "dining",
     "مطعم", "مطاعم", "مطبخ"],
    # fast food
    ["fast food", "burger", "shawarma",
     "وجبات سريعة", "برجر", "شاورما"],
    # bakery
    ["bakery", "patisserie", "bread",
     "مخبز", "مخابز", "حلويات", "باتيسري", "خبز"],
    # grocery / supermarket
    ["grocery", "supermarket", "market",
     "سوبر ماركت", "سوبرماركت", "بقالة", "تموينات", "هايبر"],
    # mall
    ["mall", "shopping mall", "shopping center",
     "مول", "مجمع", "مركز تسوق"],
    # fuel / petrol / gas station
    ["fuel", "petrol", "gas station", "gas",
     "محطة وقود", "بنزين", "وقود", "محطة"],
    # ev charger
    ["ev", "ev charger", "ev charging", "charger", "electric car",
     "شاحن", "شاحن كهربائي", "سيارة كهربائية"],
    # car wash
    ["car wash", "wash",
     "غسيل سيارات", "مغسلة سيارات", "غسيل"],
    # pharmacy
    ["pharmacy", "drugstore", "medicine",
     "صيدلية", "صيدليات", "دواء"],
    # hospital — full-size facilities
    ["hospital",
     "مستشفى", "مستشفيات"],
    # clinic — small/medium medical practices + polyclinics
    ["clinic", "medical center", "polyclinic", "medical complex",
     "عيادة", "عيادات", "مجمع طبي", "مركز طبي"],
    # gym
    ["gym", "fitness", "workout",
     "نادي رياضي", "جيم", "نادي", "لياقة"],
    # park
    ["park", "garden",
     "حديقة", "حدائق", "منتزه"],
    # bank
    ["bank", "banking",
     "بنك", "بنوك", "مصرف"],
    # atm
    ["atm", "cash machine",
     "صراف آلي", "صراف", "ماكينة"],
    # mosque — include the Friday-mosque term too
    ["mosque", "masjid", "grand mosque", "friday mosque",
     "مسجد", "مساجد", "جامع", "جوامع"],
    # transit — stations of every mode the Riyadh city zone has
    ["bus station", "bus", "saptco",
     "محطة حافلات", "حافلات", "موقف باص", "باصات"],
    ["metro", "metro station", "subway",
     "محطة مترو", "مترو", "محطات المترو"],
    ["train", "train station", "railway", "railway station", "rail", "sar",
     "محطة قطار", "قطار", "محطة سكة حديد", "سكة حديد", "القطار"],
    ["taxi", "taxi stand",
     "موقف سيارات أجرة", "تاكسي", "سيارة أجرة"],
    # salon / barber
    ["salon", "barber", "barbershop", "haircut",
     "حلاق", "حلاقة", "صالون"],
    # laundry
    ["laundry", "dry cleaner", "cleaners",
     "مغسلة", "مغاسل", "تنظيف ملابس"],
    # post office
    ["post office", "post", "shipping",
     "مكتب بريد", "بريد", "شحن"],
    # library + book-cafe hybrids
    ["library", "books", "reading", "book cafe",
     "مكتبة", "مكتبات", "كتب", "كافيه مكتبة", "مطالعة"],
    # juice — fresh juice bars, including the Saudi sugarcane-juice stalls
    ["juice", "juices", "juice bar", "fresh juice", "sugarcane", "sugarcane juice",
     "عصير", "عصائر", "عصائر طازجة", "عصير قصب", "قصب"],
    # cuisine sub-types
    ["seafood", "fish", "sea food",
     "سي فود", "اسماك", "أسماك", "مطاعم أسماك", "بحري"],
    ["healthy", "healthy food", "salad", "salads",
     "صحي", "أكل صحي", "طعام صحي", "سلطة", "سلطات"],
    ["italian", "italian food", "italian restaurant",
     "ايطالي", "إيطالي", "مطاعم إيطالية", "مطبخ إيطالي"],
    ["sushi", "japanese",
     "سوشي", "ساشيمي", "مطاعم يابانية", "ياباني"],
    ["burger", "burgers",
     "برجر", "برغر", "همبرجر"],
    ["pizza", "pizzeria",
     "بيتزا", "بيزا"],
    ["shawarma",
     "شاورما", "شوارما", "شواورما"],
    ["kabsa",
     "كبسة", "كبسه"],
    ["mandi", "madhbi",
     "مندي", "مضبي"],
    ["steak", "steakhouse",
     "ستيك", "ستيك هاوس", "لحوم"],
    ["dessert", "desserts",
     "حلويات", "حلى"],
    ["ice cream", "icecream",
     "آيس كريم", "ايس كريم", "بوظة", "مثلجات"],
    ["breakfast", "brunch",
     "فطور", "الفطور", "إفطار"],
    ["indian", "indian food", "indian restaurant",
     "مطاعم هندية", "هندي", "برياني"],
    ["asian", "asian food", "chinese", "thai", "vietnamese",
     "مطاعم آسيوية", "آسيوي", "صيني", "تايلندي"],
    # museum + cultural / heritage
    ["museum", "national museum", "art museum", "gallery",
     "متحف", "متاحف", "معرض", "المتحف الوطني"],
    ["cultural", "cultural site", "heritage", "heritage site",
     "landmark", "historic", "historic site", "monument",
     "معلم", "معالم", "تراث", "تراثي", "موقع تراثي", "معلم ثقافي"],
    # brunch — distinct from traditional Saudi breakfast (فطور) and
    # from all-day fast breakfast spots; these are the sit-down café types
    ["brunch", "brunch cafe", "all-day brunch", "all day brunch",
     "برانش", "برانش كافيه"],
    # american coffee — filter/drip/pour-over/specialty third-wave. Maps
    # both the literal "american coffee" term and the specialty-coffee
    # families that typically serve it.
    ["american coffee", "filter coffee", "drip coffee", "pour over",
     "pour-over", "v60", "chemex", "specialty coffee", "third wave",
     "قهوة أمريكية", "قهوة مقطرة", "قهوة مختصة", "فلتر"],
]

# Precompute a word → group-members map for cheap lookup. We normalise
# both the key and the values with `_ar_normalize` so a user typing
# `قهوه` (colloquial ha-for-ta-marbuta) matches `قهوة` (formal).
# Must match the SQL `ar_normalize()` character set bit-for-bit so the
# tsquery we build in Python hits the tsvector the trigger produced.
_AR_DIACRITICS_RE = re.compile("[\u064b-\u065f\u0670\u0640]")
_AR_FOLD = str.maketrans("أإآٱىة", "اااييه")


def _ar_normalize(s: str) -> str:
    return _AR_DIACRITICS_RE.sub("", s).translate(_AR_FOLD).strip().lower()


_INDEX: dict[str, frozenset[str]] = {}
for _group in SYNONYM_GROUPS:
    _norm_group = frozenset(_ar_normalize(m) for m in _group if m.strip())
    for _member in _norm_group:
        _INDEX[_member] = _norm_group


def expand(token: str) -> list[str]:
    """Return the group the token belongs to (normalised), or `[token]`.

    Single words OR multi-word entries both work: if the user typed
    `coffee shop` and that appears in the group, the full phrase hits
    the group; if they typed just `coffee`, the same group wins too.
    """
    t = _ar_normalize(token)
    group = _INDEX.get(t)
    if group:
        return sorted(group)
    return [t]


# tsquery grammar note: `to_tsquery` needs operators between tokens;
# a multi-word synonym member like `coffee shop` must be quoted with
# `<->` phrase-search syntax or split by `&`. Simpler: tokenize
# multi-word synonyms with `&` (AND within the phrase) so
# `coffee shop` becomes `coffee & shop`.
_WORD_RE = re.compile(r"[^\s]+")


def to_tsquery_or(token_or_phrase: str) -> str:
    """Convert a synonym member (possibly multi-word) to a tsquery fragment.

    `"coffee"`         →  `coffee`
    `"coffee shop"`    →  `(coffee & shop)`
    """
    words = _WORD_RE.findall(token_or_phrase)
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return "(" + " & ".join(words) + ")"


# Greedy phrase match — try spans up to 4 tokens. Covers every
# multi-word synonym member we define today ("american coffee", "book
# cafe", "قهوة أمريكية", "shopping mall", "pour over"...).
_MAX_PHRASE_TOKENS = 4


def build_tsquery(q: str) -> str:
    """Turn a user query into a tsquery string with synonym expansion.

    Walk the normalised tokens left-to-right. At each position, try the
    longest phrase (up to 4 tokens) that matches a synonym group —
    expand that group to an `(a | b | c)` OR-block and advance. If no
    phrase hits, fall back to single-token lookup (and pass-through).
    Conjoin the resulting parts with `&`.

    Handles both single-word (`coffee`, `قهوة`) and multi-word
    (`american coffee`, `قهوة أمريكية`) synonyms without the caller
    having to disambiguate.
    """
    normalised = _ar_normalize(q)
    tokens = [t for t in normalised.split() if t]
    if not tokens:
        return normalised

    conj_parts: list[str] = []
    i = 0
    while i < len(tokens):
        matched = False
        # Try the longest phrase first, shrinking down to single token.
        for span in range(min(_MAX_PHRASE_TOKENS, len(tokens) - i), 0, -1):
            phrase = " ".join(tokens[i : i + span])
            group = _INDEX.get(phrase)
            if group:
                fragments = [to_tsquery_or(m) for m in sorted(group) if m]
                fragments = [f for f in fragments if f]
                if not fragments:
                    continue
                if len(fragments) == 1:
                    conj_parts.append(fragments[0])
                else:
                    conj_parts.append("(" + " | ".join(fragments) + ")")
                i += span
                matched = True
                break
        if not matched:
            # No phrase hit — pass this single token through verbatim.
            conj_parts.append(tokens[i])
            i += 1
    return " & ".join(conj_parts) if conj_parts else normalised

"""Heuristic detection of posting restrictions: Saudi-only and gender-only.

Pure functions — no I/O, no globals. Safe to call on every parse.
The phrase lists are intentionally small and conservative; false positives
are worse here than false negatives (the cluster verdict reflects them).
"""

from __future__ import annotations

import re
from typing import Final

from job_crawler_db import ExperienceLevel, GenderPreference

# ---------------------------------------------------------------------------
# Saudi-only detection
# ---------------------------------------------------------------------------
# English: phrase must explicitly restrict to Saudi nationals/citizens.
# Arabic:  للسعوديين فقط (literally "for Saudis only"), سعوديين فقط, etc.
# We require the "only" qualifier so a posting that merely *prefers* Saudis
# is not mis-flagged.

_SA_ONLY_EN_PHRASES: tuple[str, ...] = (
    "saudi nationals only",
    "saudis only",
    "saudi national only",
    "saudi citizens only",
    "only saudi nationals",
    "open to saudi nationals only",
    "open to saudis only",
    "for saudi nationals only",
    "only for saudi nationals",
    "saudi only",
)

_SA_ONLY_AR_PHRASES: tuple[str, ...] = (
    "للسعوديين فقط",
    "للسعوديات فقط",
    "للسعوديين والسعوديات فقط",
    "للسعودي فقط",
    "السعوديين فقط",
    "سعوديي الجنسية فقط",
    "للجنسية السعودية فقط",
)


def detect_saudi_only(text: str | None) -> bool:
    """True when `text` explicitly restricts the role to Saudi nationals."""
    if not text:
        return False
    lower = text.casefold()
    if any(p in lower for p in _SA_ONLY_EN_PHRASES):
        return True
    return any(p in text for p in _SA_ONLY_AR_PHRASES)


# ---------------------------------------------------------------------------
# Gender preference detection
# ---------------------------------------------------------------------------
# Same conservative principle. Single-gender restrictions are common in SA
# retail / hospitality / education roles.

_FEMALE_EN_PHRASES: tuple[str, ...] = (
    "female candidates only", "females only", "for females only",
    "open to females only", "open to female candidates only",
    "female only", "women only", "for women only",
    "this position is for females",
)
_MALE_EN_PHRASES: tuple[str, ...] = (
    "male candidates only", "males only", "for males only",
    "open to males only", "open to male candidates only",
    "male only", "men only", "for men only",
    "this position is for males",
)
_FEMALE_AR_PHRASES: tuple[str, ...] = (
    "للنساء فقط", "للإناث فقط", "للسيدات فقط",
    "للمتقدمات فقط", "للمرشحات فقط",
)
_MALE_AR_PHRASES: tuple[str, ...] = (
    "للرجال فقط", "للذكور فقط",
    "للمتقدمين فقط", "للمرشحين فقط",
)


# A loose word-boundary regex catches inflected forms like
# "Female Customer Service Representatives only" without false-positive
# matching of "female" inside e.g. "femaleness" or random tokens.
_FEMALE_LOOSE: Final = re.compile(
    r"\b(female|women)\b[^.!?]{0,40}\bonly\b",
    re.IGNORECASE,
)
_MALE_LOOSE: Final = re.compile(
    r"\b(male|men)\b[^.!?]{0,40}\bonly\b",
    re.IGNORECASE,
)


def detect_gender_preference(text: str | None) -> GenderPreference:
    """Return the gender restriction declared in `text`, or `any` when none."""
    if not text:
        return GenderPreference.any
    lower = text.casefold()
    # Use word-bounded match so "male" doesn't match the "male" inside
    # "female" (a real bug if you `in`-check raw substrings).
    female = (
        _any_word(lower, _FEMALE_EN_PHRASES)
        or any(p in text for p in _FEMALE_AR_PHRASES)
        or bool(_FEMALE_LOOSE.search(text))
    )
    male = (
        _any_word(lower, _MALE_EN_PHRASES)
        or any(p in text for p in _MALE_AR_PHRASES)
        or bool(_MALE_LOOSE.search(text))
    )
    if female and not male:
        return GenderPreference.female_only
    if male and not female:
        return GenderPreference.male_only
    # If both fire (e.g. "no preference between male only / female only…"),
    # treat as no restriction — better than picking the wrong one.
    return GenderPreference.any


def _any_word(text: str, phrases: tuple[str, ...]) -> bool:
    """True when any of `phrases` appears in `text` with leading + trailing
    word boundaries. Prevents `male` matching inside `female`."""
    return any(re.search(rf"\b{re.escape(p)}\b", text) for p in phrases)


# ---------------------------------------------------------------------------
# Experience-level detection
# ---------------------------------------------------------------------------
# Maps title / body keywords to the closest `ExperienceLevel` enum value.
# Each tier is mutually exclusive in the title; if the title carries no
# signal, the body's first-paragraph keywords are checked as a fallback.
# Conservative: when two tiers fire (e.g. "Senior Engineer / Lead Role")
# we return None and let the value stay NULL.

# Downgrade modifiers ALWAYS win — "Associate Product Manager" is a
# junior PM, not a manager. Scan these first; only fall through to the
# rank-ordered patterns when no downgrade is present.
_EXP_LEVEL_DOWNGRADE_PATTERNS: Final[tuple[tuple[ExperienceLevel, re.Pattern[str]], ...]] = (
    (ExperienceLevel.junior, re.compile(r"\b(junior|jr\.?|associate)\b", re.IGNORECASE)),
    (ExperienceLevel.entry,  re.compile(r"\b(entry[- ]level|intern|graduate|trainee|fresh(er)?)\b", re.IGNORECASE)),
)

# Highest-rank wins among non-downgrade modifiers. "Senior Engineering
# Manager" is a manager because manager is a higher rank than senior.
_EXP_LEVEL_RANK_PATTERNS: Final[tuple[tuple[ExperienceLevel, re.Pattern[str]], ...]] = (
    (ExperienceLevel.executive, re.compile(r"\b(chief|cxo|cto|cfo|ceo|coo|cmo|cpo|vp)\b", re.IGNORECASE)),
    (ExperienceLevel.director,  re.compile(r"\b(director|head of)\b", re.IGNORECASE)),
    (ExperienceLevel.manager,   re.compile(r"\b(manager|supervisor)\b", re.IGNORECASE)),
    (ExperienceLevel.lead,      re.compile(r"\b(lead|principal|staff)\b", re.IGNORECASE)),
    (ExperienceLevel.senior,    re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE)),
)


def detect_experience_level(
    title: str | None,
    description: str | None = None,
) -> ExperienceLevel | None:
    """Return the strongest experience-level signal in the title.

    Order of checks (first-match-wins per group):
      1. Downgrade modifiers (associate / junior / intern / graduate)
         on the title — these ALWAYS win, so "Associate PM" → junior,
         "Graduate Engineer" → entry.
      2. Highest-rank pattern in the title (executive > director >
         manager > lead > senior) — so "Senior Engineering Manager"
         is a manager.
      3. Same two passes on the first 500 chars of the description as
         a fallback when the title is silent.
    """
    sources = (title, (description or "")[:500])
    for src in sources:
        if not src:
            continue
        for level, pattern in _EXP_LEVEL_DOWNGRADE_PATTERNS:
            if pattern.search(src):
                return level
        for level, pattern in _EXP_LEVEL_RANK_PATTERNS:
            if pattern.search(src):
                return level
    return None


# ---------------------------------------------------------------------------
# Arabic-required detection
# ---------------------------------------------------------------------------
# Conservative — only fires when "Arabic" appears alongside a "required /
# native / fluent / mandatory" qualifier. Real postings always couch the
# language requirement explicitly, so loose substring matching ("Arabic"
# alone) would false-positive on the half of SA postings that merely
# mention "Arabic speakers welcome" as a preference.

_REQ_ARABIC_EN_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bnative\s+arabic\b", re.IGNORECASE),
    re.compile(r"\barabic\s+(speaker|native)\b", re.IGNORECASE),
    re.compile(r"\bfluen(t|cy)\s+in\s+arabic\b", re.IGNORECASE),
    re.compile(r"\barabic\s+is\s+(required|mandatory|a\s+must)\b", re.IGNORECASE),
    re.compile(r"\b(must|should|need to)\s+speak\s+arabic\b", re.IGNORECASE),
    re.compile(r"\barabic\s+language\s+(required|skills?|proficiency)\b", re.IGNORECASE),
    re.compile(r"\bproficien(t|cy)\s+in\s+arabic\b", re.IGNORECASE),
    re.compile(r"\bbilingual\s+\(?(arabic|english\s*[/,]\s*arabic|arabic\s*[/,]\s*english)\)?", re.IGNORECASE),
)

_REQ_ARABIC_AR_PHRASES: Final[tuple[str, ...]] = (
    "إتقان اللغة العربية",
    "إجادة اللغة العربية",
    "اللغة العربية مطلوبة",
    "متحدث باللغة العربية",
    "متحدثة باللغة العربية",
    "اللغة الأم العربية",
)


def detect_requires_arabic(text: str | None) -> bool | None:
    """True when the role explicitly requires Arabic fluency.

    Returns None when the text doesn't mention Arabic at all (so the
    cluster stays NULL rather than getting an explicit False on every
    Arabic-silent description — which would be misleading on a Saudi
    board). Returns True only when a phrase explicitly qualifies the
    language as required.
    """
    if not text:
        return None
    if any(p.search(text) for p in _REQ_ARABIC_EN_RES):
        return True
    if any(p in text for p in _REQ_ARABIC_AR_PHRASES):
        return True
    # Mentions Arabic at all? Return None (unknown) — there's a signal,
    # but not enough to call it required. Otherwise return None too
    # (truly silent on the topic). Both paths converge to None.
    return None


# ---------------------------------------------------------------------------
# Visa sponsorship detection
# ---------------------------------------------------------------------------
# Two-state: explicit yes (sponsorship offered) → True; explicit no
# (must have own visa / iqama transfer required) → False; silent → None.

_VISA_YES_EN_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bvisa\s+sponsorship\b", re.IGNORECASE),
    re.compile(r"\bwe\s+(will\s+)?sponsor\s+(your\s+)?(work\s+)?visas?\b", re.IGNORECASE),
    re.compile(r"\bsponsor(s|ed|ship)?\s+(work|employment|h-?1b|gcc)\s*visas?\b", re.IGNORECASE),
    re.compile(r"\biqama\s+(will\s+be\s+)?provided\b", re.IGNORECASE),
    re.compile(r"\bemployer\s+(provides?|sponsors?)\s+(visa|iqama)\b", re.IGNORECASE),
)

_VISA_NO_EN_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(must\s+have|requires?)\s+(transferable\s+)?iqama\b", re.IGNORECASE),
    re.compile(r"\bno\s+visa\s+sponsorship\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+offer\s+(visa\s+)?sponsorship\b", re.IGNORECASE),
    re.compile(r"\bown\s+(valid\s+)?iqama\b", re.IGNORECASE),
    re.compile(r"\b(iqama|residence\s+permit)\s+(transferable|transfer)\b", re.IGNORECASE),
)


def detect_visa_sponsorship(text: str | None) -> bool | None:
    """Three-state visa-sponsorship signal.

    Returns True when the posting explicitly offers sponsorship, False
    when it requires the candidate to bring their own iqama / residence,
    and None when silent (or contradictory).

    Implementation note: the YES regexes catch the substring "visa
    sponsorship" in isolation, but the NO regex "no visa sponsorship"
    contains that same substring. To avoid every NO match also firing a
    YES match, we drop YES spans that are fully contained inside a NO
    span before deciding. True contradictions (one YES somewhere AND
    one NO elsewhere) still resolve to None.
    """
    if not text:
        return None
    yes_spans = [m.span() for p in _VISA_YES_EN_RES for m in p.finditer(text)]
    no_spans = [m.span() for p in _VISA_NO_EN_RES for m in p.finditer(text)]
    yes_real = [
        y for y in yes_spans
        if not any(n[0] <= y[0] and y[1] <= n[1] for n in no_spans)
    ]
    if yes_real and no_spans:
        return None  # signals truly contradict each other
    if yes_real:
        return True
    if no_spans:
        return False
    return None


# ---------------------------------------------------------------------------
# Hybrid days-per-week detection
# ---------------------------------------------------------------------------
# Captures patterns like:
#   "3 days in office", "4 days a week onsite", "2 days remote / 3 in office",
#   "hybrid (3 days office)", "in-office 4 days per week"
# Returns the in-office day count (1..6). Conservative: ignores ambiguous
# phrases like "few days a week" or vague "couple of days".

_NUMBER_WORDS: Final[dict[str, int]] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
}

# Numeric or word-form number followed by a "day(s)" + an in-office cue
# within ~30 chars. The cue list intentionally excludes "remote" so we
# don't mis-classify "2 days remote" as 2 in-office days.
_HYBRID_DAYS_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(\d|one|two|three|four|five|six)\s*(?:-|to)?\s*\d?\s*"
        r"days?\b[^.!?]{0,30}\b(in[- ]?office|in[- ]?the[- ]?office|"
        r"onsite|on[- ]?site|at\s+the\s+office|in[- ]?person)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(in[- ]?office|onsite|on[- ]?site|in[- ]?person)\b[^.!?]{0,30}"
        r"\b(\d|one|two|three|four|five|six)\s+days?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhybrid\b[^.!?]{0,20}\(?\s*(\d|one|two|three|four|five|six)\s+days?",
        re.IGNORECASE,
    ),
)


def _coerce_day_count(token: str) -> int | None:
    token = token.lower()
    if token.isdigit():
        n = int(token)
        return n if 1 <= n <= 6 else None
    return _NUMBER_WORDS.get(token)


def detect_hybrid_days_per_week(text: str | None) -> int | None:
    """Return the in-office day count for hybrid roles, or None.

    Range clamped to 1..6 — five-day full-time onsite is rarely described
    as "hybrid", and seven-day office is implausible. A NULL means the
    text didn't explicitly state how many days are in-office.
    """
    if not text:
        return None
    for pattern in _HYBRID_DAYS_RES:
        m = pattern.search(text)
        if m is None:
            continue
        for group in m.groups():
            if group is None:
                continue
            value = _coerce_day_count(group)
            if value is not None:
                return value
    return None


# ---------------------------------------------------------------------------
# Remote country restriction detection
# ---------------------------------------------------------------------------
# Looks for explicit "must be based in / resident of X" phrasings and
# returns the 2-letter country code (lowercase). Defaults to None when
# the text is silent OR when multiple countries match (ambiguous).

# Map country name → ISO 3166 alpha-2 (lowercase). Limited to GCC + a
# handful of remote-hiring hubs we've seen in postings.
_COUNTRY_NAME_TO_CODE: Final[dict[str, str]] = {
    "saudi arabia": "sa", "ksa": "sa",
    "united arab emirates": "ae", "uae": "ae",
    "bahrain": "bh",
    "kuwait": "kw",
    "qatar": "qa",
    "oman": "om",
    "egypt": "eg",
    "jordan": "jo",
    "lebanon": "lb",
    "india": "in",
    "pakistan": "pk",
    "philippines": "ph",
    "turkey": "tr",
    "united kingdom": "gb", "uk": "gb",
    "united states": "us", "usa": "us",
}

_REMOTE_RESTRICTION_RE: Final = re.compile(
    r"\b(?:must\s+(?:be\s+)?(?:resid(?:e|ent)|based|located)\s+(?:in\s+)?|"
    r"(?:residing|based|located)\s+in\s+|"
    r"open\s+to\s+(?:candidates\s+in\s+|residents\s+of\s+)|"
    r"remote\s+(?:from|in|within)\s+)"
    r"(?:the\s+)?"  # optional definite article — "based in *the* UAE"
    r"(?P<country>"
    r"saudi arabia|ksa|united arab emirates|uae|bahrain|kuwait|qatar|oman|"
    r"egypt|jordan|lebanon|india|pakistan|philippines|turkey|"
    r"united kingdom|uk|united states|usa)\b",
    re.IGNORECASE,
)


def detect_remote_country_restriction(text: str | None) -> str | None:
    """Return the 2-letter country code a remote role is restricted to.

    Conservative: returns None when ambiguous (multiple distinct
    countries matched) or when the text is silent on the restriction.
    Case-insensitive matching; output is always lowercase.
    """
    if not text:
        return None
    codes = {
        _COUNTRY_NAME_TO_CODE[m.group("country").lower()]
        for m in _REMOTE_RESTRICTION_RE.finditer(text)
    }
    if len(codes) == 1:
        return next(iter(codes))
    return None


# ---------------------------------------------------------------------------
# Relocation-assistance detection
# ---------------------------------------------------------------------------
# Three-state: explicit yes (relocation assistance offered) → True;
# explicit no (must be local / no relocation) → False; silent → None.

_RELOCATION_YES_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\brelocation\s+(assistance|support|package|allowance|bonus|benefits?)\b", re.IGNORECASE),
    # Allow filler words between "help/assist/provide/cover" and "relocate" —
    # "We will help you relocate", "We can assist with your relocation", etc.
    re.compile(r"\bwe\s+(?:will\s+|can\s+)?(?:help|assist|provide|cover)\b[^.!?]{0,20}\brelocat(?:e|ion|ing)\b", re.IGNORECASE),
    re.compile(r"\boffer\s+relocation\b", re.IGNORECASE),
    re.compile(r"\brelocation\s+(?:is\s+)?(?:offered|provided|available|included)\b", re.IGNORECASE),
)

# NO patterns are written to extend their span past the qualifying word
# ("no relocation provided", "no relocation assistance") so the
# span-overlap math drops the inner YES match cleanly. Without the
# trailing `\w+` consumer, "no relocation" would stop at "relocation"
# and the YES "relocation provided" pattern would extend past it,
# producing a contradiction instead of a clear False.
_RELOCATION_NO_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bno\s+relocation(?:\s+\w+){0,3}\b", re.IGNORECASE),
    re.compile(r"\brelocation\s+(?:is\s+)?not\s+(offered|provided|available)\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+(offer|provide|include)\s+relocation\b", re.IGNORECASE),
    re.compile(r"\b(must\s+be|currently)\s+(local|locally\s+based)\b", re.IGNORECASE),
)


def detect_relocation_assistance(text: str | None) -> bool | None:
    """Three-state relocation-assistance signal.

    Returns True when the posting explicitly offers relocation help,
    False when it requires the candidate to already be local, and None
    when silent. Uses the same span-overlap logic as visa-sponsorship
    so "no relocation" doesn't fire both YES and NO patterns.
    """
    if not text:
        return None
    yes_spans = [m.span() for p in _RELOCATION_YES_RES for m in p.finditer(text)]
    no_spans = [m.span() for p in _RELOCATION_NO_RES for m in p.finditer(text)]
    yes_real = [
        y for y in yes_spans
        if not any(n[0] <= y[0] and y[1] <= n[1] for n in no_spans)
    ]
    if yes_real and no_spans:
        return None
    if yes_real:
        return True
    if no_spans:
        return False
    return None


# ---------------------------------------------------------------------------
# Job-category classification
# ---------------------------------------------------------------------------
# Ordered (specificity-first) list of (code, pattern). The first pattern
# that matches the title (or, as a fallback, the first 500 chars of the
# description) wins. Codes match the taxonomy seeded by
# `discover/manual_seed._ensure_reference`.
#
# Order matters: specific subcategories MUST come before catch-alls so
# "Mechanical Engineer" maps to engineering_mechanical, not a generic
# "engineer" bucket. "Sr. Software Engineer" maps to
# software_engineering before any "engineer" fallback.
#
# Patterns are intentionally written with word boundaries so the classifier
# is whitespace/punctuation-robust. Arabic title keywords are added inline
# where they're meaningfully different from translations of the English
# keywords.

_CATEGORY_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    # --- Tech / engineering subspecialties (specific first) ------------
    ("software_engineering", re.compile(
        r"\b(software\s+engineer|software\s+developer|swe|"
        r"backend|front[- ]?end|full[- ]?stack|web\s+developer|"
        r"mobile\s+developer|ios\s+developer|android\s+developer|"
        r"\.net\s+developer|java\s+(developer|engineer)|"
        r"python\s+(developer|engineer)|"
        r"node\s+(developer|engineer)|node\.?js\s+(developer|engineer)|"
        r"ruby\s+(developer|engineer)|php\s+(developer|engineer)|"
        r"(kotlin|scala|swift|go(?:lang)?|c\#)\s+(developer|engineer)|"
        r"programmer|qa\s+engineer|"
        r"quality\s+assurance\s+engineer|sdet|"
        r"مهندس\s+برمجيات|مطور)\b",
        re.IGNORECASE),
    ),
    ("data_analytics", re.compile(
        r"\b(data\s+(engineer|analyst|scientist|architect|specialist|officer)|"
        r"business\s+intelligence|bi\s+(developer|analyst)|"
        r"machine\s+learning\s+engineer|ml\s+engineer|"
        r"ai\s+engineer|ai\s+researcher|"
        r"analytics\s+engineer|business\s+analyst|"
        r"credit\s+risk\s+data\s+specialist|"
        r"محلل\s+بيانات|عالم\s+بيانات)\b",
        re.IGNORECASE),
    ),
    ("cybersecurity", re.compile(
        r"\b(security\s+(engineer|analyst|consultant|architect)|"
        r"information\s+security|infosec|cyber\s*security|"
        r"penetration\s+test|pen\s*tester|soc\s+analyst|"
        r"vulnerability\s+(analyst|manager)|"
        r"الأمن\s+السيبراني|أمن\s+المعلومات)\b",
        re.IGNORECASE),
    ),
    ("it_infrastructure", re.compile(
        r"\b(devops|sre|site\s+reliability|"
        r"systems?\s+administrator|sys\s*admin|sysops|"
        r"network\s+(engineer|administrator|technician)|"
        r"cloud\s+(engineer|architect)|aws\s+engineer|azure\s+engineer|"
        r"platform\s+engineer|kubernetes\s+engineer|"
        r"it\s+(support|technician|helpdesk|administrator)|help\s*desk|"
        r"noc\s+(engineer|operator|analyst)|"
        r"wired\s*/?\s*wireless\s+technician|"
        r"electronic\s+device\s+(maintenance\s+)?technician|"
        r"desktop\s+(and\s+laptop\s+)?(repairman|technician|support)|"
        r"operational\s+technology\s+engineer|"
        r"تقنية\s+المعلومات|دعم\s+فني)\b",
        re.IGNORECASE),
    ),
    ("product_management", re.compile(
        r"\b(product\s+(manager|owner|director|lead)|"
        r"technical\s+product\s+manager|"
        r"مدير\s+منتج)\b",
        re.IGNORECASE),
    ),
    ("design_creative", re.compile(
        r"\b(ui\s+designer|ux\s+designer|ui/ux|product\s+designer|"
        r"graphic\s+designer|graphic\s+artist|"
        r"art\s+director|creative\s+director|"
        r"motion\s+designer|video\s+editor|photographer|"
        r"interior\s+designer|fashion\s+designer|"
        r"(embroidery|textile|jewel(le)?ry|industrial|"
        r"furniture|set|exhibition)\s+designer|"
        r"content\s*/?\s*reel\s+creator|reel\s+creator|"
        r"head\s+of\s+media|"
        r"مصمم\s+(جرافيك|واجهات|منتج))\b",
        re.IGNORECASE),
    ),
    ("engineering_civil", re.compile(
        r"\b(civil\s+(engineer|procurement\s+engineer)|"
        r"structural\s+(engineer|coordinator)|"
        r"geotechnical\s+engineer|surveyor|survey\s+(manager|engineer)|"
        r"site\s+engineer|"
        r"highway\s+engineer|transportation\s+engineer|"
        r"bim\s+(engineer|modeler|coordinator|manager)|"
        r"infrastructure\s*/?\s*utilities\s+engineer|"
        r"(?:lead\s+)?infrastructure\s+engineer|"
        r"utilities\s+engineer|"
        r"مهندس\s+مدني|مهندس\s+إنشائي)\b",
        re.IGNORECASE),
    ),
    ("engineering_mechanical", re.compile(
        r"\b(mechanical\s+(engineer|designer|design\s+engineer)|"
        r"automotive\s+engineer|maintenance\s+engineer|"
        r"مهندس\s+ميكانيكي)\b",
        re.IGNORECASE),
    ),
    ("engineering_electrical", re.compile(
        r"\b(electrical\s+(engineer|technician|design\s+engineer)|"
        r"electronics\s+engineer|"
        r"power\s+engineer|control\s+systems\s+engineer|"
        r"elevator\s+electrical\s+technician|"
        r"solar\s+(pv|panel)\s+engineer|"
        r"e\s*&\s*i\s+(commissioning\s+)?engineer|"
        r"instrumentation\s+(technician|engineer)|"
        r"industrial\s+electrician|electrician|"
        r"مهندس\s+كهرباء)\b",
        re.IGNORECASE),
    ),
    ("engineering_chemical", re.compile(
        r"\b(chemical\s+engineer|process\s+engineer|"
        r"petroleum\s+engineer|reservoir\s+engineer|drilling\s+engineer|"
        r"petrochemical\s+engineer|"
        r"cathodic\s+protection\s+engineer|"
        r"rig\s+(company\s+man|superintendent|manager)|"
        r"مهندس\s+كيميائي|مهندس\s+بترول)\b",
        re.IGNORECASE),
    ),
    ("engineering_mep", re.compile(
        r"\b(mep\s+(engineer|technician|manager|coordinator)|"
        r"hvac\s+(engineer|technician)|"
        r"refrigeration\s+(engineer|technician)|"
        r"plumbing\s+(engineer|technician)|fire\s+alarm\s+technician|"
        r"tendering\s+engineer\s*[-]\s*mep|"
        r"(?:assistant\s+)?ac\s+technician|air[- ]?conditioning\s+technician|"
        r"مهندس\s+تكييف|فني\s+تبريد)\b",
        re.IGNORECASE),
    ),
    ("architecture", re.compile(
        r"\b(architect|architectural\s+(engineer|technical|"
        r"technical\s+office\s+engineer)|"
        r"(?:enterprise|solution|technical|cloud|data)?\s*architecture\s+lead|"
        r"urban\s+planner|landscape\s+architect|"
        r"interior\s+architect|"
        r"مهندس\s+معماري|معماري)\b",
        re.IGNORECASE),
    ),
    # --- Commercial / support functions -------------------------------
    ("finance_accounting", re.compile(
        r"\b(accountant|chief\s+accountant|senior\s+accountant|"
        r"manager\s+of\s+accounts|accounts\s+manager|"
        r"treasury\s+(accountant|manager|specialist|analyst)|"
        r"financial\s+(analyst|controller|manager|planner|specialist|"
        r"officer|coordinator)|"
        r"corporate\s+financial\s+(specialist|analyst|manager|officer)|"
        r"audit(or|ing)?\b|internal\s+audit|tax\s+(manager|specialist|"
        r"accountant|consultant)|"
        r"finance\s+(manager|director|lead|specialist|officer|analyst)|"
        r"cost\s+engineer|"
        r"debt\s+collector|collections\s+(officer|specialist)|"
        r"controller|cfo|"
        r"محاسب|مدير\s+مالي)\b",
        re.IGNORECASE),
    ),
    ("sales_business_dev", re.compile(
        r"\b(sales\s+(executive|representative|manager|engineer|associate|"
        r"assistant|"
        r"director|consultant|specialist|coordinator|partner|"
        r"supervisor|advisor|professional)|"
        r"sales\s*man|sales\s+girl|sales\s+lady|"
        r"account\s+(executive|manager|director|supervisor)|"
        r"business\s+development|business\s+developer|"
        r"key\s+account|territory\s+manager|"
        r"horeca\s+sales|b2b\s+sales|inside\s+sales|outside\s+sales|"
        r"commercial\s+(director|manager|lead)|"
        r"(?:regional\s+)?aftersales\s+(manager|coordinator|director|supervisor)|"
        r"laminated\s+glass\s+sales|"
        r"(?:part[- ]?time\s+)?(?:freelance\s+)?sales\s+partner|"
        r"e[- ]?commerce\s+(manager|specialist|director)|"
        r"sales\s*/\s*commercial|trainee\s*[-]\s*sales|"
        r"presales\s+engineer|pre[- ]?sales\s+engineer|"
        r"sme\s+relationship\s+(officer|manager)|"
        r"relationship\s+(officer|manager)\b|"
        r"senior\s+project\s+sales|"
        r"مبيعات|مندوب\s+مبيعات|تطوير\s+الأعمال)\b",
        re.IGNORECASE),
    ),
    ("marketing", re.compile(
        r"\b(marketing\s+(manager|director|executive|specialist|coordinator|"
        r"analyst|consultant|lead|communications)|"
        r"marketing\s+communications|"
        r"brand\s+(manager|director|specialist)|"
        r"digital\s+marketing|content\s+(manager|writer|strategist|creator)|"
        r"social\s+media\s+(manager|specialist|executive|designer)|"
        r"seo\s+specialist|sem\s+specialist|"
        r"performance\s+(media\s+buying|marketing)\s+(team\s+leader|manager|"
        r"specialist|lead)|"
        r"media\s+buying\s+(team\s+leader|manager|specialist)|"
        r"growth\s+(marketer|hacker|manager)|"
        r"public\s+relations|pr\s+(manager|specialist)|"
        r"event\s+(executive|manager|coordinator|specialist)|"
        r"corporate\s+(affairs|communications)\s+(manager|director|specialist)|"
        r"تسويق|مدير\s+تسويق)\b",
        re.IGNORECASE),
    ),
    ("hr_recruitment", re.compile(
        r"\b(human\s+resources|"
        r"hr\s+(manager|director|executive|specialist|coordinator|"
        r"business\s+partner|generalist)|"
        r"recruit(er|ment|ing)|"
        r"talent\s+(acquisition|partner|specialist)|"
        r"people\s+(operations|partner)|"
        r"learning\s+and\s+development|l&d\s+(manager|specialist)|"
        r"compensation\s+and\s+benefits|c&b\s+(manager|specialist)|"
        r"organi[sz]ational\s+development|"
        r"od\s+(specialist|manager|consultant)|"
        r"training\s+(and|&)\s+od\s+specialist|"
        r"sap\s+(?:human\s+capital|hcm|sf|successfactors)\s+(?:management\s+)?manager|"
        r"موارد\s+بشرية|توظيف)\b",
        re.IGNORECASE),
    ),
    ("legal_compliance", re.compile(
        r"\b(lawyer|"
        r"legal\s+(counsel|advisor|manager|consultant|director)|"
        r"attorney|paralegal|"
        r"compliance\s+(officer|manager|analyst|specialist)|"
        r"corporate\s+governance(\s+manager)?|"
        r"قانوني|مستشار\s+قانوني)\b",
        re.IGNORECASE),
    ),
    ("operations_supply_chain", re.compile(
        r"\b(operations\s+(manager|director|executive|specialist|coordinator|"
        r"analyst|officer|supervisor|assistant)|"
        r"supply\s+chain\s+(manager|analyst|specialist|engineer|coordinator)|"
        r"manager\s+of\s+supply\s+chain|"
        r"logistics\s+(manager|coordinator|specialist|analyst|supervisor)|"
        r"warehouse\s+(manager|supervisor|associate|operator)|"
        r"(?:store|stock)\s*keeper|stockroom\s+(clerk|assistant)|"
        r"forklift\s+operator|"
        r"inventory\s+(manager|coordinator|specialist|controller|analyst)|"
        r"procurement\s+(manager|officer|specialist|director|"
        r"intern|trainee|coordinator|associate|assistant|analyst)|"
        r"buyer|sourcing\s+(manager|specialist)|"
        r"planning\s+(manager|engineer)|"
        r"project\s+(manager|engineer|coordinator|director|lead|"
        r"scheduler|controls?\s+engineer|controls?\s+specialist)|"
        r"qc\s+(officer|inspector|engineer|manager|supervisor)|"
        r"qa\s+(officer|inspector|manager|supervisor)|"
        r"quality\s+(assurance|control|qc/qa|qa/qc)[^.!?]{0,30}\b"
        r"(officer|inspector|manager|supervisor|engineer)|"
        r"cost\s+estimator|collection\s+supervisor|"
        r"sheet\s+metal\s+supervisor|"
        r"عمليات|سلسلة\s+التوريد|مشتريات|"
        r"مدير\s+مشروع|مهندس\s+مشروع)\b",
        re.IGNORECASE),
    ),
    ("customer_service", re.compile(
        r"\b(customer\s+(service|support|experience|success)\s+"
        r"(representative|agent|specialist|manager|associate|executive|"
        r"coordinator)|"
        r"call\s+center\s+(agent|representative|supervisor|manager)|"
        r"contact\s+center\s+(agent|representative)|"
        r"client\s+services\s+(specialist|manager)|"
        r"خدمة\s+العملاء|مركز\s+اتصال)\b",
        re.IGNORECASE),
    ),
    ("healthcare", re.compile(
        r"\b(doctor|physician|nurse|pharmacist|dentist|"
        r"general\s+practitioner|specialist\s+doctor|consultant\s+doctor|"
        r"radiologist|cardiologist|anesthesiologist|surgeon|"
        r"ent\s+(specialist|consultant|doctor)|"
        r"oncologist|neurologist|dermatologist|orthopedic|pediatrician|"
        r"medical\s+(director|officer|representative|technician)|"
        r"clinical\s+(specialist|coordinator|pharmacist)|"
        r"laboratory\s+technician|lab\s+technician|"
        r"physiotherapist|nutritionist|midwife|paramedic|"
        r"healthcare\s+(specialist|manager|coordinator)|"
        r"faculty\s+member\s+in\s+(nursing|medical|respiratory|dental|pharmacy)|"
        r"طبيب|ممرض|صيدلي)\b",
        re.IGNORECASE),
    ),
    ("education_academic", re.compile(
        r"\b(teacher|"
        r"professor|associate\s+professor|assistant\s+professor|"
        r"instructor|lecturer|tutor|"
        r"academic\s+(director|coordinator|advisor)|"
        r"dean|provost|"
        r"faculty\s+member|"
        r"curriculum\s+(developer|designer|specialist)|"
        r"(mathematics|maths|english|arabic|science|physics|chemistry|"
        r"biology|computer|coding|arduino|programming|robotics)\s+trainer|"
        r"معلم|أستاذ|محاضر|عضو\s+هيئة\s+تدريس)\b",
        re.IGNORECASE),
    ),
    ("hospitality", re.compile(
        r"\b(chef|sous\s+chef|head\s+chef|executive\s+chef|line\s+cook|cook|"
        r"barista|waiter|waitress|server|host(?:ess)?|"
        r"front\s+(desk|office)\s+(agent|supervisor|manager|employee)|"
        r"guest\s+(relations|services)\s+(officer|agent|manager|coordinator)|"
        r"hotel\s+(manager|director|supervisor)|"
        r"restaurant\s+(manager|supervisor)|"
        r"housekeeping\s+(supervisor|attendant)|"
        r"hospitality\s+(revenues?|operations?)\s+(manager|director|"
        r"supervisor|coordinator)|"
        r"lifeguard|personal\s+butler|butler\b|"
        r"bartender|sommelier|food\s+and\s+beverage|"
        r"f&b\s+(manager|supervisor)|"
        r"camp\s+(boss|manager)|"
        r"hair\s+stylist|makeup\s+artist|make[- ]?up\s+artist|"
        r"بارستا|طاهٍ|نادل)\b",
        re.IGNORECASE),
    ),
    ("retail", re.compile(
        r"\b(retail\s+(manager|supervisor|associate|sales\s+associate|"
        r"merchandising\s+manager|merchandiser)|"
        r"national\s+(grocery\s+)?retail\s+merchandising\s+manager|"
        r"store\s+(manager|supervisor|associate)|"
        r"shop\s+(manager|assistant)|"
        r"cashier|merchandiser|visual\s+merchandiser|"
        r"stock\s+(controller|keeper)|"
        r"mystery\s+shopper|"
        r"مدير\s+معرض|بائع|محاسب\s+صندوق)\b",
        re.IGNORECASE),
    ),
    ("construction", re.compile(
        r"\b(construction\s+(manager|engineer|supervisor|foreman)|"
        r"project\s+manager\s*(?:-)?\s*construction|"
        r"foreman|site\s+supervisor|site\s+(foreman|inspector)|"
        r"steel\s+fixer|carpenter|mason|"
        r"rigger\b|scaffolder|"
        r"بناء|تشييد|رئيس\s+ورشة)\b",
        re.IGNORECASE),
    ),
    ("transport_logistics", re.compile(
        r"\b(driver|truck\s+driver|delivery\s+(driver|rider)|"
        r"ride[- ]?hailing\s+driver|chauffeur|"
        r"dispatcher|fleet\s+(manager|coordinator)|"
        r"freight\s+(coordinator|forwarder)|"
        r"customs\s+(officer|broker)|"
        r"سائق|مرسل)\b",
        re.IGNORECASE),
    ),
    ("manufacturing_production", re.compile(
        r"\b(production\s+(manager|supervisor|engineer|operator|planner|"
        r"technician)|"
        r"manufacturing\s+(engineer|supervisor|technician|manager)|"
        r"assembly\s+(line\s+worker|operator|technician)|"
        r"machine\s+operator|cnc\s+(operator|machinist)|"
        r"diesel\s+pump.*\bmaintenance|injection\s+technician|"
        r"maintenance\s+(technician|manager)|"
        r"food\s+inspector|food\s+safety\s+inspector|"
        r"sheet\s+metal\s+(supervisor|worker|fabricator))\b",
        re.IGNORECASE),
    ),
    ("hse_safety", re.compile(
        r"\b(hse\s+(engineer|officer|coordinator|trainer|manager|specialist)|"
        r"safety\s+(engineer|officer|supervisor|manager|coordinator|guard)|"
        r"health\s+and\s+safety|"
        r"environmental\s+(specialist|engineer|consultant|coordinator)|"
        r"\behss?(\s+|/)?\s*(manager|engineer|officer|coordinator|specialist)|"
        r"الصحة\s+والسلامة|مهندس\s+سلامة)\b",
        re.IGNORECASE),
    ),
    ("administrative", re.compile(
        r"\b(administrative\s+(assistant|coordinator|officer|manager)|"
        r"executive\s+(assistant|secretary)|"
        r"office\s+(manager|administrator|coordinator)|"
        r"receptionist|secretary|personal\s+assistant|"
        r"data\s+entry\s+(operator|clerk)|"
        r"(?:language\s+)?translator|interpreter|"
        r"government\s+relations[^.!?]{0,40}\b(officer|specialist|manager|coordinator)|"
        r"سكرتير|مساعد\s+إداري|مترجم)\b",
        re.IGNORECASE),
    ),
    ("consulting", re.compile(
        r"\b(consultants?|strategy\s+(consultants?|advisors?)|"
        r"management\s+consultants?|business\s+consultants?|"
        r"advisors?|advisory\s+(manager|director))\b",
        re.IGNORECASE),
    ),
)


def detect_category_code(
    title: str | None,
    description: str | None = None,
) -> str | None:
    """Classify a posting into one of the seeded `job_categories` codes.

    Specificity-first: patterns are ordered so the most specific match
    wins (e.g. "Mechanical Engineer" → `engineering_mechanical` rather
    than falling through to a generic engineering bucket). The title is
    the primary signal — if the title is silent, the first 500 chars of
    the description are scanned as a fallback.

    Returns None when no pattern matches confidently. The classifier is
    intentionally conservative — a None at the cluster level is better
    than a wrong category that pollutes search facets.
    """
    sources = (title, (description or "")[:500])
    for src in sources:
        if not src:
            continue
        for code, pattern in _CATEGORY_PATTERNS:
            if pattern.search(src):
                return code
    return None

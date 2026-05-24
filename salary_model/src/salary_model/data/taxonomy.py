"""Title and level normalization.

Two stages:

1. **Rules + alias dictionary.** Fast, deterministic. Covers the bulk of clean inputs.
2. **Embedding fallback.** Optional; only loaded when a title cannot be resolved by
   rules. Uses multilingual e5 so Arabic titles work without separate handling.

The synthetic dataset already emits canonical family / level codes, so embeddings are
not on the critical path for training-time. They matter at API time when callers send
free-form titles. The fallback is lazy-initialized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from salary_model.config import get_logger
from salary_model.data.types import JobFamily, Level

log = get_logger("salary_model.data.taxonomy")


# ── Stage A: alias dictionary (curated; extend as needed) ────────────────────

_FAMILY_ALIASES: dict[JobFamily, tuple[str, ...]] = {
    JobFamily.SWE: (
        "software engineer", "software developer", "programmer", "swe",
        "backend developer", "backend engineer", "frontend developer",
        "frontend engineer", "fullstack developer", "fullstack engineer",
        "mobile developer", "android developer", "ios developer",
        "platform engineer", "devops engineer", "site reliability engineer", "sre",
        "embedded engineer", "java developer", "python developer", "go engineer",
        "engineer", "developer", "مهندس برمجيات", "مطور",
    ),
    JobFamily.DATA: (
        "data scientist", "data engineer", "ml engineer", "machine learning engineer",
        "analytics engineer", "data analyst", "research scientist",
        "applied scientist", "ai engineer", "computer vision engineer",
        "nlp engineer", "محلل بيانات", "عالم بيانات",
    ),
    JobFamily.PM: (
        "product manager", "pm", "associate product manager", "apm",
        "senior product manager", "spm", "lead product manager",
        "principal product manager", "group product manager", "مدير منتج",
    ),
    JobFamily.DESIGN: (
        "designer", "product designer", "ux designer", "ui designer",
        "graphic designer", "interaction designer", "design lead", "مصمم",
    ),
    JobFamily.SALES: (
        "sales representative", "account executive", "account manager",
        "business development", "bd", "sales engineer", "sales manager",
        "regional sales manager", "مندوب مبيعات",
    ),
    JobFamily.MARKETING: (
        "marketing specialist", "marketing manager", "performance marketing",
        "content marketing", "marketing analyst", "brand manager",
        "growth marketing", "أخصائي تسويق", "مدير تسويق",
    ),
    JobFamily.FIN: (
        "financial analyst", "finance analyst", "financial controller",
        "financial planning and analysis", "fpa", "treasury analyst",
        "accountant", "auditor", "محاسب", "محلل مالي",
    ),
    JobFamily.HR: (
        "hr specialist", "hrbp", "human resources business partner",
        "talent acquisition", "recruiter", "people operations",
        "compensation and benefits", "أخصائي موارد بشرية",
    ),
    JobFamily.OPS: (
        "operations specialist", "operations manager", "business operations",
        "biz ops", "program manager", "project manager", "مدير عمليات",
    ),
    JobFamily.LEGAL: (
        "legal counsel", "general counsel", "compliance officer",
        "regulatory affairs", "paralegal", "مستشار قانوني",
    ),
    JobFamily.CUSTOMER: (
        "customer success manager", "csm", "customer support specialist",
        "call center agent", "client services", "خدمة عملاء",
    ),
    JobFamily.SUPPLY: (
        "supply chain analyst", "logistics specialist", "procurement specialist",
        "warehouse manager", "inventory analyst",
    ),
    JobFamily.ENG_MECH: (
        "mechanical engineer", "maintenance engineer", "mechanical design engineer",
        "مهندس ميكانيكي",
    ),
    JobFamily.ENG_CIVIL: (
        "civil engineer", "structural engineer", "construction engineer",
        "site engineer", "مهندس مدني",
    ),
    JobFamily.ENG_ELEC: (
        "electrical engineer", "power engineer", "electronics engineer",
        "instrumentation engineer", "مهندس كهرباء",
    ),
    JobFamily.HEALTH: (
        "physician", "doctor", "nurse", "pharmacist", "radiologist",
        "general practitioner", "specialist physician", "طبيب", "ممرض",
    ),
    JobFamily.EDU: (
        "teacher", "lecturer", "professor", "instructor",
        "school principal", "معلم", "أستاذ",
    ),
}

_LEVEL_TOKEN_MAP: tuple[tuple[re.Pattern[str], Level], ...] = (
    (re.compile(r"\b(chief|cxo|cto|cfo|ceo|coo|cmo|cio|chro)\b"), Level.CXO),
    (re.compile(r"\b(svp|senior vice president)\b"), Level.SVP),
    (re.compile(r"\b(vp|vice president)\b"), Level.VP),
    (re.compile(r"\b(senior director|sr\.? director)\b"), Level.D2),
    (re.compile(r"\b(director)\b"), Level.D1),
    (re.compile(r"\b(senior manager|sr\.? manager|head of|head)\b"), Level.M3),
    (re.compile(r"\b(manager|lead engineer)\b"), Level.M1),
    (re.compile(r"\b(principal|distinguished|fellow)\b"), Level.IC6),
    (re.compile(r"\b(staff)\b"), Level.IC5),
    (re.compile(r"\b(senior|sr\.?|lead)\b"), Level.IC4),
    (re.compile(r"\b(mid|intermediate)\b"), Level.IC3),
    (re.compile(r"\b(junior|jr\.?|associate|entry)\b"), Level.IC2),
    (re.compile(r"\b(intern|internship|graduate trainee|trainee)\b"), Level.IC1),
)


_ARABIC_NORMALIZE: tuple[tuple[str, str], ...] = (
    ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"),
)


def _clean(text: str) -> str:
    s = text.strip().lower()
    for src, dst in _ARABIC_NORMALIZE:
        s = s.replace(src, dst)
    s = re.sub(r"[/_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


@dataclass(frozen=True)
class NormalizedTitle:
    """Output of title normalization. ``confidence`` is the rule-based or embedding score."""

    family: JobFamily
    level: Level
    specialization: str | None
    confidence: float  # 0..1; 1.0 == exact rule hit
    method: str        # 'rules' | 'embedding' | 'fallback'


def _yoe_to_level(yoe: float | None) -> Level:
    if yoe is None:
        return Level.IC3
    if yoe < 1.5:
        return Level.IC1
    if yoe < 3:
        return Level.IC2
    if yoe < 6:
        return Level.IC3
    if yoe < 10:
        return Level.IC4
    if yoe < 14:
        return Level.IC5
    if yoe < 20:
        return Level.IC6
    return Level.IC7


def _detect_family(cleaned: str) -> tuple[JobFamily | None, float]:
    best: tuple[JobFamily | None, int] = (None, 0)
    for family, aliases in _FAMILY_ALIASES.items():
        for alias in aliases:
            if alias in cleaned:
                score = len(alias)
                if score > best[1]:
                    best = (family, score)
    if best[0] is None:
        return None, 0.0
    return best[0], min(1.0, best[1] / max(len(cleaned), 1))


def _detect_level(cleaned: str, yoe: float | None) -> Level:
    for pattern, level in _LEVEL_TOKEN_MAP:
        if pattern.search(cleaned):
            return level
    return _yoe_to_level(yoe)


@lru_cache(maxsize=1)
def _load_embedder() -> object | None:
    """Lazy-load the multilingual encoder. Returns None if not installed."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        log.warning("embedder_unavailable")
        return None
    try:
        return SentenceTransformer("intfloat/multilingual-e5-small")
    except (OSError, RuntimeError) as exc:
        log.warning("embedder_load_failed", error=str(exc))
        return None


def normalize_title(
    raw_title: str,
    *,
    yoe: float | None = None,
) -> NormalizedTitle:
    """Best-effort normalization of a free-form job title into family + level."""
    cleaned = _clean(raw_title)
    family, score = _detect_family(cleaned)
    if family is not None:
        level = _detect_level(cleaned, yoe)
        return NormalizedTitle(
            family=family,
            level=level,
            specialization=None,
            confidence=float(score),
            method="rules",
        )

    embedder = _load_embedder()
    if embedder is None:
        return NormalizedTitle(
            family=JobFamily.OPS,
            level=_detect_level(cleaned, yoe),
            specialization=None,
            confidence=0.20,
            method="fallback",
        )

    # crude nearest-family by embedding of a canonical prompt per family
    prompts = {f: f"query: {f.value.lower()}" for f in JobFamily}
    query_vec = embedder.encode([f"query: {cleaned}"], normalize_embeddings=True)  # type: ignore[attr-defined]
    fam_vecs = embedder.encode(  # type: ignore[attr-defined]
        list(prompts.values()), normalize_embeddings=True
    )
    sims = (query_vec @ fam_vecs.T).flatten()
    best_idx = int(sims.argmax())
    family_pick = list(prompts.keys())[best_idx]
    return NormalizedTitle(
        family=family_pick,
        level=_detect_level(cleaned, yoe),
        specialization=None,
        confidence=float(sims[best_idx]),
        method="embedding",
    )

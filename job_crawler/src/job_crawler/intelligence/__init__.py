"""Intelligence layer — post-processing that turns raw ingested postings
into structured, deduped, search-ready clusters."""

from . import dedup, extractors, pipeline, skill_extractor, title_norm

__all__ = [
    "dedup",
    "extractors",
    "pipeline",
    "skill_extractor",
    "title_norm",
]

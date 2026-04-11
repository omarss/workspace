"""
Quran text matching engine.

Stage 0: Preprocess - normalize all 6,236 ayat, build n-gram index
Stage 1: Candidate Generation - find top candidates via n-gram overlap
Stage 2: Precise Alignment - compute edit distance for ranking
"""

import json
import os
from dataclasses import dataclass

from .arabic_norm import normalize

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "quran.json")


@dataclass
class AyahEntry:
    surah: int
    ayah: int
    text: str  # Original text with tashkeel
    text_normalized: str  # Normalized (no tashkeel)
    words: list[str]  # Normalized words
    surah_name_ar: str
    surah_name_en: str


@dataclass
class MatchResult:
    surah: int
    ayah: int
    surah_name_ar: str
    surah_name_en: str
    text: str  # Original text with tashkeel
    score: float


class QuranMatcher:
    def __init__(self):
        self.ayat: list[AyahEntry] = []
        self.ngram_index: dict[tuple[str, ...], list[int]] = {}
        self._ayah_lookup: dict[tuple[int, int], AyahEntry] = {}
        self._loaded = False

    def load(self, data_path: str | None = None):
        """Load Quran data and build index."""
        path = data_path or DATA_PATH

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.ayat = []
        self._ayah_lookup = {}
        for entry in data:
            text = entry["text"]
            normalized = normalize(text)
            words = normalized.split()
            ayah_entry = AyahEntry(
                surah=entry["surah"],
                ayah=entry["ayah"],
                text=text,
                text_normalized=normalized,
                words=words,
                surah_name_ar=entry.get("surah_name_ar", ""),
                surah_name_en=entry.get("surah_name_en", ""),
            )
            self.ayat.append(ayah_entry)
            self._ayah_lookup[(entry["surah"], entry["ayah"])] = ayah_entry

        # Build word trigram index
        self.ngram_index = {}
        for idx, ayah in enumerate(self.ayat):
            for ngram in self._get_word_ngrams(ayah.words, n=3):
                if ngram not in self.ngram_index:
                    self.ngram_index[ngram] = []
                self.ngram_index[ngram].append(idx)

        self._loaded = True

    def get_ayah_info(self, surah: int, ayah: int) -> AyahEntry | None:
        """Look up a specific ayah by surah and ayah number. O(1)."""
        return self._ayah_lookup.get((surah, ayah))

    def match(self, text: str, top_k: int = 5) -> list[MatchResult]:
        """
        Match transcribed text against Quran corpus.

        Args:
            text: ASR output (Arabic text)
            top_k: Number of top results to return

        Returns:
            List of MatchResult sorted by score (descending)
        """
        if not self._loaded:
            self.load()

        normalized = normalize(text)
        query_words = normalized.split()

        if not query_words:
            return []

        # Stage 1: Candidate generation via n-gram overlap
        candidate_scores: dict[int, int] = {}
        query_ngrams = self._get_word_ngrams(query_words, n=3)

        for ngram in query_ngrams:
            for idx in self.ngram_index.get(ngram, []):
                candidate_scores[idx] = candidate_scores.get(idx, 0) + 1

        # Also check bigrams for short queries
        if len(query_words) <= 4:
            for ngram in self._get_word_ngrams(query_words, n=2):
                for idx in self.ngram_index.get(ngram, []):
                    candidate_scores[idx] = candidate_scores.get(idx, 0) + 1

        # Also check cross-boundary: ayah(i) + ayah(i+1)
        for idx in range(len(self.ayat) - 1):
            if idx in candidate_scores or (idx + 1) in candidate_scores:
                combined_words = self.ayat[idx].words + self.ayat[idx + 1].words
                combined_ngrams = set(self._get_word_ngrams(combined_words, n=3))
                overlap = len(set(query_ngrams) & combined_ngrams)
                if overlap > 0:
                    candidate_scores[idx] = max(candidate_scores.get(idx, 0), overlap)

        # Get top 20 candidates
        sorted_candidates = sorted(candidate_scores.items(), key=lambda x: -x[1])[:20]

        if not sorted_candidates:
            # Fallback: try simple word overlap
            return self._fallback_word_match(query_words, top_k)

        # Stage 2: Precise alignment with edit distance
        results: list[MatchResult] = []
        for idx, _ in sorted_candidates:
            ayah = self.ayat[idx]
            score = self._compute_alignment_score(query_words, ayah.words)
            results.append(
                MatchResult(
                    surah=ayah.surah,
                    ayah=ayah.ayah,
                    surah_name_ar=ayah.surah_name_ar,
                    surah_name_en=ayah.surah_name_en,
                    text=ayah.text,
                    score=score,
                )
            )

        results.sort(key=lambda x: -x.score)
        return results[:top_k]

    def _get_word_ngrams(self, words: list[str], n: int) -> list[tuple[str, ...]]:
        """Get word-level n-grams."""
        if len(words) < n:
            return [tuple(words)] if words else []
        return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]

    def _compute_alignment_score(self, query: list[str], target: list[str]) -> float:
        """
        Compute alignment score using sliding window + edit distance.
        Handles partial matches (user recited only part of an ayah).
        """
        if not query or not target:
            return 0.0

        query_len = len(query)
        target_len = len(target)

        # If query is shorter, slide it over the target
        if query_len <= target_len:
            best_score = 0.0
            for start in range(target_len - query_len + 1):
                window = target[start : start + query_len]
                dist = self._edit_distance(query, window)
                score = 1.0 - (dist / max(len(query), len(window)))
                best_score = max(best_score, score)
            return best_score
        else:
            # Query is longer than target (spanning multiple ayat)
            dist = self._edit_distance(query[:target_len], target)
            return 1.0 - (dist / max(len(query), target_len))

    def _edit_distance(self, a: list[str], b: list[str]) -> int:
        """Compute word-level Levenshtein distance."""
        m, n = len(a), len(b)
        dp = list(range(n + 1))

        for i in range(1, m + 1):
            prev = dp[0]
            dp[0] = i
            for j in range(1, n + 1):
                temp = dp[j]
                if a[i - 1] == b[j - 1]:
                    dp[j] = prev
                else:
                    dp[j] = 1 + min(prev, dp[j], dp[j - 1])
                prev = temp

        return dp[n]

    def _fallback_word_match(self, query_words: list[str], top_k: int) -> list[MatchResult]:
        """Fallback matching using simple word overlap ratio."""
        query_set = set(query_words)
        results: list[MatchResult] = []

        for ayah in self.ayat:
            ayah_set = set(ayah.words)
            if not ayah_set:
                continue
            overlap = len(query_set & ayah_set)
            score = (2 * overlap) / (len(query_set) + len(ayah_set))
            if score > 0.1:
                results.append(
                    MatchResult(
                        surah=ayah.surah,
                        ayah=ayah.ayah,
                        surah_name_ar=ayah.surah_name_ar,
                        surah_name_en=ayah.surah_name_en,
                        text=ayah.text,
                        score=score,
                    )
                )

        results.sort(key=lambda x: -x.score)
        return results[:top_k]


# Singleton instance
quran_matcher = QuranMatcher()

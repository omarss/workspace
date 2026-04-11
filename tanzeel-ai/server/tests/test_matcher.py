"""Tests for Quran text matcher."""

import os

import pytest

from app.services.matcher import QuranMatcher


@pytest.fixture(scope="module")
def matcher():
    m = QuranMatcher()
    data_path = os.path.join(os.path.dirname(__file__), "..", "app", "data", "quran.json")
    m.load(data_path)
    return m


def test_load_all_ayat(matcher: QuranMatcher):
    assert len(matcher.ayat) == 6236


def test_ngram_index_built(matcher: QuranMatcher):
    assert len(matcher.ngram_index) > 0


def test_match_bismillah(matcher: QuranMatcher):
    results = matcher.match("بسم الله الرحمن الرحيم", top_k=3)
    assert len(results) > 0
    top = results[0]
    assert top.surah == 1
    assert top.ayah == 1
    assert top.score > 0.8


def test_match_ikhlas(matcher: QuranMatcher):
    results = matcher.match("قل هو الله احد", top_k=3)
    assert len(results) > 0
    top = results[0]
    assert top.surah == 112
    assert top.ayah == 1


def test_match_fatiha_second_ayah(matcher: QuranMatcher):
    results = matcher.match("الحمد لله رب العالمين", top_k=3)
    assert len(results) > 0
    top = results[0]
    assert top.surah == 1
    assert top.ayah == 2


def test_match_returns_surah_names(matcher: QuranMatcher):
    results = matcher.match("بسم الله الرحمن الرحيم", top_k=1)
    assert results[0].surah_name_ar != ""
    assert results[0].surah_name_en != ""


def test_empty_input(matcher: QuranMatcher):
    results = matcher.match("", top_k=3)
    assert len(results) == 0


def test_nonsense_input(matcher: QuranMatcher):
    results = matcher.match("xyz abc 123", top_k=3)
    # Should either return empty or low-confidence results
    assert all(r.score < 0.5 for r in results)


def test_get_ayah_info(matcher: QuranMatcher):
    info = matcher.get_ayah_info(1, 1)
    assert info is not None
    assert info.surah == 1
    assert info.ayah == 1
    assert "بسم" in info.text_normalized


def test_get_ayah_info_not_found(matcher: QuranMatcher):
    info = matcher.get_ayah_info(999, 999)
    assert info is None

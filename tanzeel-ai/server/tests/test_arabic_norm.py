"""Tests for Arabic text normalization."""

from app.services.arabic_norm import normalize


def test_remove_tashkeel():
    # Bismillah with full tashkeel
    text = "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"
    result = normalize(text)
    assert "ِ" not in result
    assert "ْ" not in result
    assert "َ" not in result


def test_normalize_alef_variants():
    assert normalize("إبراهيم") == normalize("ابراهيم")
    assert normalize("أحمد") == normalize("احمد")
    assert normalize("آمن") == "امن"  # alef-madda → single alef


def test_taa_marbuta_to_haa():
    assert normalize("رحمة") == "رحمه"


def test_alef_maqsura_to_yaa():
    assert normalize("على") == "علي"


def test_hamza_carriers():
    assert normalize("مؤمن") == "مومن"
    assert normalize("رئيس") == "رييس"


def test_collapse_whitespace():
    assert normalize("كلمة   كلمة") == "كلمه كلمه"


def test_remove_tatweel():
    assert normalize("كتـــاب") == "كتاب"


def test_empty_string():
    assert normalize("") == ""


def test_no_arabic():
    assert normalize("hello world") == "hello world"

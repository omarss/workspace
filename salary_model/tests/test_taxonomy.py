from __future__ import annotations

from salary_model.data.taxonomy import normalize_title
from salary_model.data.types import JobFamily, Level


def test_software_engineer() -> None:
    n = normalize_title("Software Engineer", yoe=4.0)
    assert n.family == JobFamily.SWE
    assert n.level == Level.IC3
    assert n.method == "rules"


def test_senior_java_engineer() -> None:
    n = normalize_title("Senior Java Engineer", yoe=7.0)
    assert n.family == JobFamily.SWE
    assert n.level == Level.IC4


def test_engineering_manager() -> None:
    n = normalize_title("Engineering Manager", yoe=10.0)
    # "manager" token in raw, matched by SWE alias is more specific so family is SWE;
    # the level token map picks up "manager" -> M1.
    assert n.level == Level.M1


def test_product_manager() -> None:
    n = normalize_title("Product Manager", yoe=8.0)
    assert n.family == JobFamily.PM


def test_arabic_software_dev() -> None:
    n = normalize_title("مطور برمجيات", yoe=3.0)
    assert n.family == JobFamily.SWE

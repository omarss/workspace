"""Unit tests for `job_crawler.core.restrictions` heuristic detectors.

Pure functions — no DB, no network. Covers the existing detectors
(Saudi-only + gender) plus the three new ones (experience level,
Arabic-required, visa sponsorship).
"""

from __future__ import annotations

import pytest

from job_crawler.core.restrictions import (
    detect_category_code,
    detect_experience_level,
    detect_gender_preference,
    detect_hybrid_days_per_week,
    detect_relocation_assistance,
    detect_remote_country_restriction,
    detect_requires_arabic,
    detect_saudi_only,
    detect_visa_sponsorship,
)
from job_crawler_db import ExperienceLevel, GenderPreference

# ---------------------------------------------------------------------------
# detect_saudi_only — existing behaviour, regression coverage
# ---------------------------------------------------------------------------


def test_saudi_only_explicit_en() -> None:
    assert detect_saudi_only("This role is open to Saudi nationals only.") is True


def test_saudi_only_explicit_ar() -> None:
    assert detect_saudi_only("الوظيفة للسعوديين فقط") is True


def test_saudi_only_negative() -> None:
    assert detect_saudi_only("Open to all GCC nationals.") is False
    assert detect_saudi_only(None) is False
    assert detect_saudi_only("") is False


# ---------------------------------------------------------------------------
# detect_gender_preference — existing behaviour
# ---------------------------------------------------------------------------


def test_gender_female_explicit() -> None:
    assert detect_gender_preference("Female candidates only.") is GenderPreference.female_only


def test_gender_male_explicit() -> None:
    assert detect_gender_preference("This position is for males.") is GenderPreference.male_only


def test_gender_both_means_any() -> None:
    """Contradictory signals → no restriction (safer than picking one)."""
    assert detect_gender_preference(
        "Females only / Males only — placeholder text"
    ) is GenderPreference.any


def test_gender_default() -> None:
    assert detect_gender_preference("Hiring for our growing team.") is GenderPreference.any


# ---------------------------------------------------------------------------
# detect_experience_level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Python Engineer", ExperienceLevel.senior),
        ("Sr. Backend Developer", ExperienceLevel.senior),
        ("Junior Software Engineer", ExperienceLevel.junior),
        ("Jr. Web Developer", ExperienceLevel.junior),
        ("Associate Product Manager", ExperienceLevel.junior),
        ("Lead Data Scientist", ExperienceLevel.lead),
        ("Principal Engineer", ExperienceLevel.lead),
        ("Staff Backend Engineer", ExperienceLevel.lead),
        ("Engineering Manager", ExperienceLevel.manager),
        ("Senior Engineering Manager", ExperienceLevel.manager),  # manager wins over senior
        ("Site Reliability Supervisor", ExperienceLevel.manager),
        ("Director of Engineering", ExperienceLevel.director),
        ("Head of Product", ExperienceLevel.director),
        ("Chief Technology Officer", ExperienceLevel.executive),
        ("VP Engineering", ExperienceLevel.executive),
        ("CFO", ExperienceLevel.executive),
        ("Software Engineering Intern", ExperienceLevel.entry),
        ("Graduate Software Engineer", ExperienceLevel.entry),
        ("Trainee Engineer", ExperienceLevel.entry),
        ("Entry-Level Data Analyst", ExperienceLevel.entry),
    ],
)
def test_experience_level_title(title: str, expected: ExperienceLevel) -> None:
    assert detect_experience_level(title) is expected


def test_experience_level_ambiguous_title_uses_body() -> None:
    """A neutral title like 'Python Engineer' falls back to the body's
    first paragraph."""
    body = "We're hiring a senior contributor to drive system design."
    assert detect_experience_level("Python Engineer", body) is ExperienceLevel.senior


def test_experience_level_silent_returns_none() -> None:
    assert detect_experience_level("Python Engineer", "We build software.") is None


def test_experience_level_body_only_late_mention_ignored() -> None:
    """Body fallback only honours the first 500 chars — a 'what we offer'
    section that mentions 'senior leadership opportunities' shouldn't
    misclassify a junior role."""
    body = "We're hiring. " + ("Engineer. " * 60) + "Senior leadership opportunities await."
    assert detect_experience_level("Engineer", body) is None


# ---------------------------------------------------------------------------
# detect_requires_arabic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Native Arabic speaker required.",
        "Must be fluent in Arabic.",
        "Arabic is mandatory for this role.",
        "Arabic language required.",
        "Must speak Arabic.",
        "Bilingual (Arabic/English).",
        "Proficiency in Arabic is essential.",
        "إتقان اللغة العربية مطلوب",
        "اللغة العربية مطلوبة",
    ],
)
def test_requires_arabic_positive(text: str) -> None:
    assert detect_requires_arabic(text) is True


def test_requires_arabic_silent() -> None:
    assert detect_requires_arabic("We build software.") is None
    assert detect_requires_arabic(None) is None
    assert detect_requires_arabic("") is None


def test_requires_arabic_mention_without_qualifier_is_none() -> None:
    """A casual mention of Arabic (without 'required / fluent / native')
    is NOT enough — we don't want to mis-flag postings that merely say
    'Arabic speakers welcome'."""
    assert detect_requires_arabic("Arabic speakers welcome to apply.") is None


# ---------------------------------------------------------------------------
# detect_visa_sponsorship
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Visa sponsorship available.",
        "We will sponsor your work visa.",
        "Employer provides iqama.",
        "Iqama will be provided.",
        "We sponsor employment visas for qualified candidates.",
    ],
)
def test_visa_sponsorship_positive(text: str) -> None:
    assert detect_visa_sponsorship(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Must have transferable iqama.",
        "No visa sponsorship provided.",
        "Does not offer visa sponsorship.",
        "Candidates must have own valid iqama.",
        "Iqama transferable required.",
    ],
)
def test_visa_sponsorship_negative(text: str) -> None:
    assert detect_visa_sponsorship(text) is False


def test_visa_sponsorship_silent() -> None:
    assert detect_visa_sponsorship("We're hiring a backend engineer.") is None
    assert detect_visa_sponsorship(None) is None
    assert detect_visa_sponsorship("") is None


def test_visa_sponsorship_contradictory_returns_none() -> None:
    """When the text mentions both sponsorship-yes and sponsorship-no
    phrases (e.g. mixed eligibility paragraphs), stay silent."""
    text = "Visa sponsorship for engineers. No visa sponsorship for contractors."
    assert detect_visa_sponsorship(text) is None


# ---------------------------------------------------------------------------
# detect_hybrid_days_per_week
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("This is a hybrid role with 3 days in office.", 3),
        ("4 days a week onsite, 1 day remote.", 4),
        ("Hybrid (2 days office).", 2),
        ("Onsite 5 days per week required.", 5),
        ("You will be in-person three days a week.", 3),
        ("Hybrid model: two days in-office.", 2),
    ],
)
def test_hybrid_days_positive(text: str, expected: int) -> None:
    assert detect_hybrid_days_per_week(text) == expected


def test_hybrid_days_silent_returns_none() -> None:
    assert detect_hybrid_days_per_week("Fully remote position.") is None
    assert detect_hybrid_days_per_week("We're hiring an engineer.") is None
    assert detect_hybrid_days_per_week(None) is None
    assert detect_hybrid_days_per_week("") is None


def test_hybrid_days_ignores_remote_day_count() -> None:
    """A '2 days remote' phrase doesn't make us return 2 — that's
    the wrong direction. Only in-office cues count."""
    assert detect_hybrid_days_per_week("Work 2 days remote from home.") is None


# ---------------------------------------------------------------------------
# detect_remote_country_restriction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Must be resident in Saudi Arabia.", "sa"),
        ("Must be based in the UAE.", "ae"),
        ("Candidates residing in Egypt.", "eg"),
        ("Open to candidates in India.", "in"),
        ("Remote from Saudi Arabia only.", "sa"),
        ("Must reside in Bahrain.", "bh"),
        ("Open to residents of Qatar.", "qa"),
    ],
)
def test_remote_country_positive(text: str, expected: str) -> None:
    assert detect_remote_country_restriction(text) == expected


def test_remote_country_silent_returns_none() -> None:
    assert detect_remote_country_restriction("Fully remote position.") is None
    assert detect_remote_country_restriction("We're hiring.") is None
    assert detect_remote_country_restriction(None) is None


def test_remote_country_ambiguous_returns_none() -> None:
    """Two distinct countries mentioned as restrictions → ambiguous."""
    text = "Candidates residing in Saudi Arabia or based in UAE."
    assert detect_remote_country_restriction(text) is None


# ---------------------------------------------------------------------------
# detect_relocation_assistance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Relocation assistance available.",
        "We offer relocation support to qualified candidates.",
        "Relocation package included.",
        "We will help you relocate.",
        "Relocation is provided.",
    ],
)
def test_relocation_positive(text: str) -> None:
    assert detect_relocation_assistance(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "No relocation provided.",
        "Relocation is not offered.",
        "Does not offer relocation.",
        "Candidates must be currently local.",
        "Must be locally based.",
    ],
)
def test_relocation_negative(text: str) -> None:
    assert detect_relocation_assistance(text) is False


def test_relocation_silent_returns_none() -> None:
    assert detect_relocation_assistance("We're hiring a backend engineer.") is None
    assert detect_relocation_assistance(None) is None
    assert detect_relocation_assistance("") is None


def test_relocation_contradictory_returns_none() -> None:
    text = "Relocation assistance for engineers. No relocation for contractors."
    assert detect_relocation_assistance(text) is None


# ---------------------------------------------------------------------------
# detect_category_code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Software / tech
        ("Senior Python Engineer", "software_engineering"),
        ("Backend Developer", "software_engineering"),
        ("Mobile Developer (iOS)", "software_engineering"),
        ("QA Engineer", "software_engineering"),
        # Data / analytics
        ("Data Engineer", "data_analytics"),
        ("Business Analyst", "data_analytics"),
        ("Machine Learning Engineer", "data_analytics"),
        # Security / infrastructure / product / design
        ("Security Engineer", "cybersecurity"),
        ("SOC Analyst", "cybersecurity"),
        ("DevOps Engineer", "it_infrastructure"),
        ("IT Support Technician", "it_infrastructure"),
        ("Cloud Architect", "it_infrastructure"),
        ("Product Manager", "product_management"),
        ("UI/UX Designer", "design_creative"),
        # Engineering subspecialties
        ("Civil Engineer", "engineering_civil"),
        ("Site Engineer", "engineering_civil"),
        ("Mechanical Engineer", "engineering_mechanical"),
        ("Electrical Engineer", "engineering_electrical"),
        ("Chemical Engineer", "engineering_chemical"),
        ("Petroleum Engineer", "engineering_chemical"),
        ("HVAC Engineer", "engineering_mep"),
        ("Hiring Now | Tendering Engineer - MEP", "engineering_mep"),
        ("Architect", "architecture"),
        # Commercial / support
        ("Senior Treasury Accountant", "finance_accounting"),
        ("Tax Manager", "finance_accounting"),
        ("Sales Executive", "sales_business_dev"),
        ("Business Development Manager", "sales_business_dev"),
        ("Marketing Manager", "marketing"),
        ("Digital Marketing Specialist", "marketing"),
        ("HR Manager", "hr_recruitment"),
        ("Talent Acquisition Partner", "hr_recruitment"),
        ("Legal Counsel", "legal_compliance"),
        ("Corporate Governance Manager", "legal_compliance"),
        ("Operations Manager", "operations_supply_chain"),
        ("Supply Chain Analyst", "operations_supply_chain"),
        ("Procurement Officer", "operations_supply_chain"),
        ("Customer Service Representative", "customer_service"),
        # Healthcare / academic
        ("Senior Pharmacist", "healthcare"),
        ("Faculty Member in Respiratory Therapy", "healthcare"),
        ("Lecturer in Computer Science", "education_academic"),
        # Hospitality / retail / construction / transport / production
        ("Chef de Partie", "hospitality"),
        ("Barista And Cashier", "hospitality"),  # 'barista' wins over 'cashier'
        ("Store Manager", "retail"),
        ("Construction Manager", "construction"),
        ("Private And Ride-Hailing Driver", "transport_logistics"),
        ("Production Supervisor", "manufacturing_production"),
        ("HSE Trainer", "hse_safety"),
        ("Safety Officer", "hse_safety"),
        ("EHSS Manager", "hse_safety"),
        ("Executive Assistant", "administrative"),
        ("Receptionist", "administrative"),
        ("Strategy Consultants", "consulting"),
        # v2 — patterns added to lift coverage from 65% to 80%+
        ("Project Manager", "operations_supply_chain"),
        ("Project Engineer", "operations_supply_chain"),
        ("Manager Of Supply Chain", "operations_supply_chain"),
        ("Store Keeper", "operations_supply_chain"),
        ("Forklift Operator", "operations_supply_chain"),
        ("Procurement Intern (Tamheer)", "operations_supply_chain"),
        ("Cost Estimator", "operations_supply_chain"),
        ("Senior BIM Engineer", "engineering_civil"),
        ("Lead Infrastructure / Utilities Engineer", "engineering_civil"),
        ("Mechanical Design Engineer", "engineering_mechanical"),
        ("Elevator Electrical Technician", "engineering_electrical"),
        ("MEP Manager", "engineering_mep"),
        ("Assistant AC Technician", "engineering_mep"),
        ("Senior Architectural Technical Office Engineer (BIM)", "architecture"),
        ("Credit Risk Data Specialist", "data_analytics"),
        ("Corporate Data Officer", "data_analytics"),
        ("NOC Engineer", "it_infrastructure"),
        ("SysOps Intern - Tamheer", "it_infrastructure"),
        ("IT Administrator", "it_infrastructure"),
        ("Wired/Wireless Technician", "it_infrastructure"),
        ("Embroidery Designer", "design_creative"),
        ("Content / Reel Creator", "design_creative"),
        ("Head Of Media", "design_creative"),
        ("Corporate Financial Specialist", "finance_accounting"),
        ("Commercial Director - Lead Recycling", "sales_business_dev"),
        ("Regional Aftersales Manager", "sales_business_dev"),
        ("Account Supervisor", "sales_business_dev"),
        ("Laminated Glass Sales", "sales_business_dev"),
        ("Training & OD Specialist", "hr_recruitment"),
        ("SAP Human Capital Management Manager", "hr_recruitment"),
        ("Government Relations & Administration Officer", "administrative"),
        ("Language Translator", "administrative"),
        ("Camp Boss", "hospitality"),
        ("Guest Relations Officer", "hospitality"),
        ("Mathematics Trainer", "education_academic"),
        ("Arduino Trainer", "education_academic"),
        ("Maintenance Technician", "manufacturing_production"),
        ("Food Inspector", "manufacturing_production"),
        ("Rigger I Aramco Certified", "construction"),
    ],
)
def test_category_code_title(title: str, expected: str) -> None:
    assert detect_category_code(title) == expected


def test_category_code_silent_returns_none() -> None:
    """A generic role with no taxonomy keyword stays None — better to
    leave the cluster uncategorised than to misclassify it."""
    assert detect_category_code("General Application") is None
    assert detect_category_code("Open Position") is None
    assert detect_category_code(None) is None
    assert detect_category_code("") is None


def test_category_code_body_fallback() -> None:
    """A neutral title falls back to the first 500 chars of the body."""
    body = "We are hiring a mechanical engineer for our Riyadh plant."
    assert detect_category_code("Engineering Role", body) == "engineering_mechanical"


def test_category_code_specificity_wins() -> None:
    """Specific subcategories beat generic catch-alls."""
    # 'Mechanical Engineer' is more specific than any generic engineering pattern.
    assert detect_category_code("Senior Mechanical Engineer") == "engineering_mechanical"
    # 'Sales Engineer' is a sales role, not engineering (per taxonomy intent).
    assert detect_category_code("Sales Engineer - SaaS") == "sales_business_dev"


# ---------------------------------------------------------------------------
# detect_industry_code (companies)
# ---------------------------------------------------------------------------


from job_crawler.core.restrictions import detect_industry_code  # noqa: E402


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Tech / digital
        ("Cognizant Technology Solutions", "tech_software"),
        ("Intertec Systems LLC", "tech_software"),
        ("Saudi Cyber Security Co", "cybersecurity"),
        ("STC Pay", "fintech"),
        ("Tamara Fintech", "fintech"),
        ("Souq Online Marketplace", "ecommerce"),
        ("Saudi Telecom Company", "telecom"),
        # Energy / heavy industry
        ("Saudi Aramco", "oil_gas"),
        ("SABIC", "petrochemicals"),
        ("Maaden Mining", "mining"),
        ("ACWA Power Renewables", "energy"),
        ("Riyadh Water Utilities", "utilities"),
        ("Al Yamamah Chemicals Co", "chemicals"),
        # Financial
        ("Al Rajhi Bank", "banking"),
        ("Tawuniya Insurance", "insurance"),
        ("Kingdom Investments Co", "investment"),
        ("WATHEEQ INVESTMENTS CO", "investment"),
        # Real estate / construction / cement
        ("نارين العقارية", "real_estate"),
        ("ROSHN Real Estate Developer", "real_estate"),
        ("Tenvidh contracting company", "construction"),
        ("Al Saif Building Co", "construction"),
        ("Yamama Cement", "cement"),
        # Healthcare / pharma
        ("King Faisal Specialist Hospital", "healthcare"),
        ("Batterjee Medical College", "healthcare"),
        ("Al Nahdi Pharmacy", "pharma"),
        ("Saudi Pharmaceuticals", "pharma"),
        # Food / agri / retail / hospitality
        ("Saudi Lebanese Factories For Chocolate", "food_beverage"),
        ("Al Marai Dairy Co", "food_beverage"),
        ("Saudi Agricultural Co", "agriculture"),
        ("Panda Retail Stores", "retail"),
        ("Oriental Horizon Trading Co.", "retail"),
        ("Hilton Hotels Riyadh", "hospitality"),
        ("Starbucks Coffee Cafe", "hospitality"),
        # Education / NGO / gov
        ("King Saud University", "education"),
        ("Riyadh Schools Group", "education"),
        ("Saudi Red Crescent NGO", "ngo"),
        ("Ministry of Health", "government"),
        # Transport / logistics / airline
        ("Saudia Airlines", "airline"),
        ("Aramex Logistics Services", "logistics"),
        ("Emdad United Transportation", "transport"),
        # Manufacturing / automotive
        ("Saudi Lebanese Factories For Chocolate & Confectionery", "food_beverage"),  # food wins over manufacturing
        ("شركة مصنع دار فصوص للصناعة", "manufacturing"),
        ("Al-Futtaim Automotive", "automotive"),
        # Media / entertainment / sports
        ("Saudi Broadcasting Media", "media"),
        ("Intro Events", "entertainment"),
        ("Riyadh Sports Club", "sports"),
        # Services
        ("Falcon Security Services", "security_services"),
        ("Talent Acquisition Recruitment Services", "hr_services"),
        # Conglomerate
        ("Al-Futtaim Holding Co", "conglomerate"),
    ],
)
def test_industry_code_classification(name: str, expected: str) -> None:
    assert detect_industry_code(name) == expected


def test_industry_code_silent_returns_none() -> None:
    """Generic names with no industry signal stay None."""
    assert detect_industry_code("AK gorop") is None
    assert detect_industry_code("Al Safsaf") is None
    assert detect_industry_code("سنام") is None
    assert detect_industry_code(None) is None
    assert detect_industry_code("") is None


def test_industry_code_arabic_name() -> None:
    """Arabic name path."""
    assert detect_industry_code(None, "شركة مجموعة مودة العالمية للفنادق") == "hospitality"
    assert detect_industry_code(None, "ثوب سار للخياطة الرجالية", description=None) is None  # tailoring not in taxonomy


def test_industry_code_description_fallback() -> None:
    """When the name is generic, the description (about-blurb) is scanned."""
    assert detect_industry_code(
        "Mada Co",
        description="We are a leading software company building SaaS for banks.",
    ) == "tech_software"

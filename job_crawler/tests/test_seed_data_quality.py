"""Data-quality tests for the curated seed CSV.

Finding 5 from FINDINGS.md called out 5 duplicate official identifiers
(website + LinkedIn URL) in the seed CSV. The loader merges on LinkedIn
match so a duplicated LinkedIn URL silently makes the second row patch
the first row's company — fine for an explicit alias / subsidiary, a
data bug otherwise.

This test fails when a NEW duplicate appears that isn't on the
`_KNOWN_INTENTIONAL_DUPS` whitelist. To add a deliberate alias, either
distinguish the second row (give it its own URL / linkedin_url) or add
the duplicated value to the whitelist with a one-line justification.
"""

from __future__ import annotations

from job_crawler.discover.manual_seed import _seed_csv_path, audit_seed_duplicates

# Duplicates that already existed when Finding 5 was filed. Each entry
# should be paired with a justification — either resolve the duplication
# in the CSV, or move the value here with a note explaining why both
# rows are intentional (e.g. parent + subsidiary share the same LinkedIn
# while the user works on a parent/alias schema). Kept lowercase + no
# trailing slash to match the audit helper's normalisation.
_KNOWN_INTENTIONAL_DUPS: dict[str, set[str]] = {
    "linkedin_url": {
        # Abdul Latif Jameel Holding + ALJ Motors share the conglomerate's
        # LinkedIn page. Will get a dedicated `alias_of`/`parent_name`
        # column in a follow-up; until then this is the operator's
        # acknowledged exception.
        "https://www.linkedin.com/company/abdul-latif-jameel",
    },
    "website": {
        # Two Petromin rows: holding + lubricants division. Both point
        # at the same domain because the division's separate site is gone.
        "https://www.petromin.com",
        # NEOM appears in two industries (city + tech vertical) until the
        # CSV gets a `relationship` column to model the subsidiary.
        "https://www.neom.com",
        # ALJ Motors + Abdul Latif Jameel Holding (same conglomerate).
        "https://www.alj.com",
        # Wakeb appears under both data + analytics rows.
        "https://wakeb.com",
    },
}


def test_seed_csv_has_no_new_duplicates() -> None:
    """A duplicate website / linkedin_url not on the whitelist is almost
    always an accident — block it from landing silently."""
    dups = audit_seed_duplicates(_seed_csv_path())
    for col, values in dups.items():
        unexpected = set(values) - _KNOWN_INTENTIONAL_DUPS.get(col, set())
        assert not unexpected, (
            f"sa_companies_seed.csv has unexpected duplicate {col} value(s): "
            f"{sorted(unexpected)}. Either disambiguate the second row or add "
            f"the value to _KNOWN_INTENTIONAL_DUPS in this test with a comment "
            f"justifying why both rows should share the identifier."
        )


def test_known_intentional_dups_actually_exist() -> None:
    """If a whitelisted duplicate disappears from the CSV (someone fixed it),
    drop the entry from the whitelist so it can't mask a future regression."""
    dups = audit_seed_duplicates(_seed_csv_path())
    for col, expected in _KNOWN_INTENTIONAL_DUPS.items():
        actually_present = set(dups.get(col, []))
        stale = expected - actually_present
        assert not stale, (
            f"_KNOWN_INTENTIONAL_DUPS[{col!r}] still lists {sorted(stale)} "
            "but that value is no longer duplicated in the CSV. Remove the "
            "whitelist entry so a future re-duplication is caught."
        )

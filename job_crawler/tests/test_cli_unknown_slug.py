"""CLI tolerance for unknown source slugs.

A slug that no longer exists in the registry (typical scenario: a
source got retired but the operator-side systemd unit still lists it)
must NOT crash the whole run. The CLI partitions the list into known
+ unknown and only invokes the runner with the known ones.
"""

from __future__ import annotations

from job_crawler.cli.run import partition_known_slugs
from job_crawler.registry import REGISTRY


def test_partition_all_known() -> None:
    """A list of only-known slugs returns them intact, no unknowns."""
    sample = tuple(list(REGISTRY)[:2])
    known, unknown = partition_known_slugs(sample)
    assert known == sample
    assert unknown == ()


def test_partition_mixes_known_and_unknown() -> None:
    """A list with one valid and one retired slug returns each in its
    bucket. The valid one is preserved in input order."""
    a_known = next(iter(REGISTRY))
    known, unknown = partition_known_slugs((a_known, "mihnati", "ghost-source"))
    assert known == (a_known,)
    assert set(unknown) == {"mihnati", "ghost-source"}


def test_partition_all_unknown() -> None:
    """A list of only-unknown slugs returns ((), tuple-of-all). The
    caller is responsible for erroring out in that case."""
    known, unknown = partition_known_slugs(("mihnati", "ghost"))
    assert known == ()
    assert set(unknown) == {"mihnati", "ghost"}

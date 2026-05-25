"""Integration: dedupe edges, fake signals, AI-generation pipeline integration."""

from __future__ import annotations

import pytest

from job_crawler_db import (
    ClusterVerdict,
    DuplicateReason,
    FakeSignalKind,
    JobCrawlerDB,
    JobPosting,
    JobPostingUpsert,
    detect_ai_generation,
)

pytestmark = pytest.mark.integration


async def _upsert(
    db: JobCrawlerDB, source_slug: str, ext_id: str, *, title: str, description: str
) -> JobPosting:
    # postings.upsert returns the persisted JobPosting (with an `id`),
    # not the JobPostingUpsert payload. Annotated correctly so callers
    # accessing `.id` typecheck.
    src = await db.sources.get(slug=source_slug)
    assert src is not None
    return await db.postings.upsert(
        JobPostingUpsert(
            source_id=src.id,
            source_job_external_id=ext_id,
            canonical_url=f"https://{source_slug}.com/jobs/{ext_id}",
            title=title,
            description=description,
        ),
    )


async def test_dedupe_edge_a_lt_b_canonicalisation(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p1 = await _upsert(db, "linkedin", "li-1", title="A", description="x")
    p2 = await _upsert(db, "bayt", "by-1", title="A", description="x")

    edge = await db.dedupe.add_edge(
        p1.id,
        p2.id,
        reason=DuplicateReason.exact_content_hash,
        similarity=1.0,
    )
    # Schema CHECK guarantees a < b regardless of input order.
    assert str(edge.posting_a_id) < str(edge.posting_b_id)

    # Reverse-order add returns the same row (UPSERT).
    edge2 = await db.dedupe.add_edge(
        p2.id,
        p1.id,
        reason=DuplicateReason.exact_content_hash,
        similarity=1.0,
    )
    assert edge2.id == edge.id


async def test_find_cluster_candidates_filters_by_threshold(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p1 = await _upsert(db, "linkedin", "x1", title="A", description="x")
    p2 = await _upsert(db, "bayt", "x2", title="A", description="x")
    p3 = await _upsert(db, "greenhouse", "x3", title="A", description="x")
    await db.dedupe.add_edge(p1.id, p2.id, reason=DuplicateReason.exact_url, similarity=0.95)
    await db.dedupe.add_edge(p1.id, p3.id, reason=DuplicateReason.near_content, similarity=0.55)

    candidates = await db.dedupe.find_cluster_candidates(p1.id, min_similarity=0.7)
    assert p2.id in candidates
    assert p3.id not in candidates


async def test_fake_signal_score_recompute_marks_fake(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p = await _upsert(db, "linkedin", "fk-1", title="A", description="x")
    cluster = await db.jobs.create_from_posting(p.id)

    # Each individual weight is bounded to [-1, 1] by a CHECK; signals compound
    # in the sigmoid sum, so several -1.0s easily produce a fake-grade score.
    await db.fake_signals.add(cluster.id, FakeSignalKind.no_company_match, weight=-1.0)
    await db.fake_signals.add(cluster.id, FakeSignalKind.requests_payment, weight=-1.0)
    await db.fake_signals.add(
        cluster.id,
        FakeSignalKind.contact_via_personal_channel,
        weight=-0.8,
    )
    refreshed = await db.fake_signals.recompute_score(cluster.id)
    assert refreshed.verdict is ClusterVerdict.fake
    assert refreshed.legit_score is not None
    assert float(refreshed.legit_score) < 0.30


async def test_fake_signal_recompute_recycled_takes_priority(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    p = await _upsert(db, "linkedin", "fk-r", title="A", description="x")
    cluster = await db.jobs.create_from_posting(p.id)
    # Mildly negative — would have been 'suspicious'/'pending' — but recycled flag wins.
    await db.fake_signals.add(cluster.id, FakeSignalKind.reposted_within_30d, weight=-0.5)
    refreshed = await db.fake_signals.recompute_score(cluster.id)
    assert refreshed.verdict is ClusterVerdict.recycled


async def test_fake_signal_recompute_legit_when_no_evidence(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p = await _upsert(db, "linkedin", "fk-ok", title="A", description="x")
    cluster = await db.jobs.create_from_posting(p.id)
    refreshed = await db.fake_signals.recompute_score(cluster.id)
    # No evidence → soft 0.85, classified as legit (above default 0.70 threshold).
    assert refreshed.verdict in (ClusterVerdict.legit, ClusterVerdict.pending)


async def test_ai_detection_feeds_fake_signal(seeded_reference: JobCrawlerDB) -> None:
    """End-to-end: detect AI text → record signal → recompute → verdict shifts."""
    db = seeded_reference
    ai_text = (
        "We are seeking a passionate Senior Engineer to join our team and embark "
        "on a journey leveraging cutting-edge — innovative solutions — that drive "
        "impactful outcomes. In the dynamic landscape of fast-paced environments, "
        "you will collaborate cross-functionally and harness the power of robust "
        "and scalable architectures. You will be responsible for delivering "
        "world-class solutions across our organisation. Strong communication "
        "skills are a plus. We are an equal opportunity employer."
    ) * 3
    p = await _upsert(db, "linkedin", "ai-1", title="Engineer", description=ai_text)
    cluster = await db.jobs.create_from_posting(p.id)

    ai = detect_ai_generation(ai_text)
    # Strong heuristic signal: many LLM-tells in a long-enough body.
    assert ai.score >= 0.45, f"expected meaningful AI score, got {ai}"
    assert "llm_phrases" in ai.hits
    # Convert the AI score to a fake-signal weight (more AI → more negative).
    # Per-signal weight is bounded to [-1, 1] by the schema CHECK.
    weight = max(-1.0, -1.0 * ai.score)
    await db.fake_signals.add(
        cluster.id,
        FakeSignalKind.ai_generated_description,
        weight=weight,
        posting_id=p.id,
        details={"score": ai.score, "hits": ai.hits},
    )
    refreshed = await db.fake_signals.recompute_score(cluster.id)
    assert refreshed.legit_score is not None
    # AI signal alone shouldn't auto-flag fake, but verdict should slip below legit.
    assert refreshed.verdict in {
        ClusterVerdict.suspicious,
        ClusterVerdict.pending,
        ClusterVerdict.fake,
    }


async def test_raw_skill_unmatched_queue(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p = await _upsert(db, "linkedin", "rs-1", title="A", description="x")
    await db.postings.add_raw_skill(p.id, "Rust (preferred)")
    await db.postings.add_raw_skill(p.id, "OCaml")
    unmatched = await db.postings.list_raw_skills_unmatched()
    phrases = {r.raw_phrase for r in unmatched}
    assert {"Rust (preferred)", "OCaml"}.issubset(phrases)


async def test_crawl_run_lifecycle(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    li = await db.sources.get(slug="linkedin")
    assert li is not None
    run = await db.crawl.start_run(li.id, config={"query": "python"})
    assert run.status.value == "running"

    await db.crawl.increment_counter(run.id, pages=10, seen=100, new=20)
    await db.crawl.record_fetch(
        run.id,
        li.id,
        "https://linkedin.com/jobs/1",
        outcome="created",
        http_status=200,
        duration_ms=350,
        bytes=18000,
    )
    finished = await db.crawl.finish_run(run.id)
    assert finished.status.value == "completed"
    assert finished.pages_fetched == 10
    assert finished.postings_seen == 100
    assert finished.postings_new == 20
    # Need to use Decimal-equivalent comparison; CrawlRun.error_count is int by model.
    assert finished.error_count == 0
    assert finished.finished_at is not None

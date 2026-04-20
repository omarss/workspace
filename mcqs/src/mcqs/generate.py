"""MCQ generation — resumable worker shelling out to the `claude` CLI.

Why the CLI instead of the Anthropic SDK:
* Uses the user's Claude Code login — no separate API key to manage.
* `--output-format json` + `--json-schema` gives us schema-validated
  structured output for free; malformed replies are rejected by the CLI
  before they ever reach us.

Concurrency: `SELECT ... FOR UPDATE SKIP LOCKED` when claiming the next
job means multiple `mcqs generate` processes can run side by side and
never pick the same row. Crashes are safe — a crashed worker leaves the
job in `in_progress`; restart with `mcqs generate --requeue` (handled by
an `UPDATE ... WHERE started_at < now() - interval '15 minutes'` reset
we run before the main loop).
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from rich.console import Console
from rich.table import Table

from . import prompts, subjects
from .config import settings
from .db import connection

log = logging.getLogger(__name__)
console = Console()

QUESTION_TYPES = ("knowledge", "analytical", "problem_solving")
CHUNK_BUDGET_TOKENS = 6000
STALE_JOB_MINUTES = 15
CLAUDE_TIMEOUT_SEC = 600


# ---------------------------------------------------------------------------
# plan-round
# ---------------------------------------------------------------------------


def plan_round(target: int | None = None, notes: str = "") -> None:
    """Open a new round and queue one pending job per (subject, type).

    Rounds are numbered monotonically. The same target cascades to every
    job so the worker has a uniform yardstick. A later round with a
    larger target still adds up on top of earlier rounds — questions
    across rounds are additive."""
    target = target or settings.mcqs_per_type_target

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM rounds")
            num = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO rounds (number, notes) VALUES (%s, %s) RETURNING id",
                (num, notes or None),
            )
            round_id = cur.fetchone()[0]

            cur.execute("SELECT slug FROM subjects ORDER BY slug")
            subject_slugs = [r[0] for r in cur.fetchall()]

            inserted = 0
            for slug in subject_slugs:
                for qtype in QUESTION_TYPES:
                    cur.execute(
                        """
                        INSERT INTO generation_jobs
                          (subject_slug, round_id, question_type, target_count, status)
                        VALUES (%s, %s, %s::question_type, %s, 'pending')
                        ON CONFLICT (subject_slug, round_id, question_type) DO NOTHING
                        """,
                        (slug, round_id, qtype, target),
                    )
                    inserted += cur.rowcount or 0
        conn.commit()

    console.print(
        f"[bold green]round {num}[/bold green] opened: "
        f"{inserted} jobs across {len(subject_slugs)} subjects × {len(QUESTION_TYPES)} types, "
        f"target={target}"
    )


# ---------------------------------------------------------------------------
# stale-job reset
# ---------------------------------------------------------------------------


def _requeue_stale(conn: Connection) -> int:
    """Reset in_progress jobs whose `started_at` is older than the timeout.

    A crashed worker can leave a job stuck at `in_progress`. We don't wait
    for a human to notice — next worker through the door frees them up.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE generation_jobs
               SET status = 'pending', started_at = NULL
             WHERE status = 'in_progress'
               AND started_at < now() - interval '{STALE_JOB_MINUTES} minutes'
            """
        )
        reset = cur.rowcount
    conn.commit()
    return reset


# ---------------------------------------------------------------------------
# job claim
# ---------------------------------------------------------------------------


@dataclass
class Job:
    id: int
    subject_slug: str
    round_id: int
    question_type: str
    target_count: int
    produced_count: int


def _claim_job(
    conn: Connection,
    *,
    subject: str | None,
    qtype: str | None,
) -> Job | None:
    filters = ["status = 'pending'"]
    params: list[Any] = []
    if subject:
        filters.append("subject_slug = %s")
        params.append(subject)
    if qtype:
        filters.append("question_type = %s::question_type")
        params.append(qtype)

    sql = (
        "SELECT id, subject_slug, round_id, question_type::text, target_count, produced_count "
        "FROM generation_jobs WHERE "
        + " AND ".join(filters)
        + " ORDER BY round_id ASC, id ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
    )

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            conn.commit()
            return None
        cur.execute(
            "UPDATE generation_jobs SET status = 'in_progress', started_at = now() WHERE id = %s",
            (row[0],),
        )
    conn.commit()
    return Job(
        id=row[0],
        subject_slug=row[1],
        round_id=row[2],
        question_type=row[3],
        target_count=row[4],
        produced_count=row[5],
    )


def _mark_done(conn: Connection, job_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE generation_jobs SET status='done', finished_at=now() WHERE id=%s",
            (job_id,),
        )
    conn.commit()


def _mark_failed(conn: Connection, job_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE generation_jobs SET status='failed', last_error=%s, finished_at=now() WHERE id=%s",
            (error[:4000], job_id),
        )
    conn.commit()


def _bump_produced(conn: Connection, job_id: int, delta: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE generation_jobs SET produced_count = produced_count + %s "
            "WHERE id=%s RETURNING produced_count",
            (delta, job_id),
        )
        new = cur.fetchone()[0]
    conn.commit()
    return new


# ---------------------------------------------------------------------------
# context selection
# ---------------------------------------------------------------------------


def _pick_chunks(conn: Connection, subject_slug: str) -> list[prompts.ChunkCtx]:
    """Pick chunks biased toward ones that haven't been used yet.

    The `uses` correlated subquery counts how many questions already
    reference each chunk via `source_chunk_ids`. Sorting `uses ASC,
    random()` means un-touched chunks come first, then everything else
    in random order. Ties are broken randomly so a rerun of the same job
    doesn't produce the same prompt.
    """
    sql = """
    SELECT c.id, c.heading_path, c.text, c.token_count,
           (SELECT COUNT(*) FROM questions q
              WHERE q.subject_slug = %s AND c.id = ANY(q.source_chunk_ids)) AS uses
    FROM doc_chunks c
    JOIN source_docs d ON d.id = c.source_doc_id
    WHERE d.subject_slug = %s
    ORDER BY uses ASC, random()
    LIMIT 50
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (subject_slug, subject_slug))
        rows = list(cur.fetchall())

    budget = CHUNK_BUDGET_TOKENS
    picked: list[prompts.ChunkCtx] = []
    for r in rows:
        toks = int(r["token_count"])
        if toks > budget and picked:
            # Already have something; stop at budget to keep prompt size sane.
            break
        if toks > budget and not picked:
            # Single chunk exceeds budget — truncate. Rare; only for
            # very long sections that survived token windowing.
            picked.append(
                prompts.ChunkCtx(id=r["id"], heading_path=r["heading_path"], text=r["text"])
            )
            break
        picked.append(
            prompts.ChunkCtx(id=r["id"], heading_path=r["heading_path"], text=r["text"])
        )
        budget -= toks
    return picked


def _recent_stems(conn: Connection, subject_slug: str, qtype: str, limit: int = 30) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT stem FROM questions
            WHERE subject_slug = %s AND question_type = %s::question_type
            ORDER BY id DESC LIMIT %s
            """,
            (subject_slug, qtype, limit),
        )
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# claude CLI wrapper
# ---------------------------------------------------------------------------


def _call_claude(*, system: str, user: str, schema: dict) -> list[dict]:
    """Invoke `claude -p` and return the parsed JSON array.

    `--json-schema` makes the CLI validate the reply against the schema
    before returning it, so a malformed payload causes a non-zero exit
    that we translate into a retryable exception.
    """
    # Pass the user prompt via stdin. The positional `prompt` argument
    # form would clash with `--disallowed-tools <tools...>` (variadic)
    # and with shells that re-interpret large prompts on the command
    # line; stdin avoids both.
    cmd = [
        settings.claude_cli,
        "--print",
        "--output-format",
        "json",
        "--model",
        settings.claude_model,
        "--json-schema",
        json.dumps(schema),
        "--append-system-prompt",
        system,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 — trusted binary path from settings
            cmd,
            input=user,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude CLI timed out after {CLAUDE_TIMEOUT_SEC}s") from e

    if proc.returncode != 0:
        raise RuntimeError(f"claude exit {proc.returncode}: {proc.stderr[:600]}")

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"claude returned non-JSON envelope: {e}: {proc.stdout[:400]}"
        ) from e

    if envelope.get("is_error"):
        raise RuntimeError(f"claude error: {(envelope.get('result') or '')[:400]}")

    # With `--json-schema` set, the structured payload lands in
    # `structured_output` (the `result` field holds any natural-language
    # summary the model emitted alongside, usually empty). The schema
    # wraps the array in `{"questions": [...]}` so the top level can
    # satisfy Anthropic's object-schema requirement — unwrap here.
    payload = envelope.get("structured_output")
    if not isinstance(payload, dict) or "questions" not in payload:
        raise RuntimeError(
            f"claude envelope missing structured_output.questions: keys={list(envelope.keys())}"
        )
    items = payload["questions"]
    if not isinstance(items, list):
        raise RuntimeError(f"'questions' is not a JSON array: {type(items).__name__}")
    return items


# ---------------------------------------------------------------------------
# validation + persistence
# ---------------------------------------------------------------------------


_LETTERS = ("A", "B", "C", "D", "E", "F", "G", "H")


def _normalize_stem(s: str) -> str:
    # Collapse whitespace + strip trailing punctuation for hashing so
    # "What is X?" and "what is x  ?" dedup together.
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(" ?.!")


def _stem_hash(s: str) -> str:
    return hashlib.sha256(_normalize_stem(s).encode("utf-8")).hexdigest()


class _SkipItemError(Exception):  # noqa: N818 — internal, raised + caught in-module only
    """Raised when a single MCQ should be dropped but the batch can continue."""


def _validate_mcq(item: dict, chunk_ids: set[int]) -> None:
    opts = item.get("options") or []
    if len(opts) != 8 or not all(isinstance(o, str) and o.strip() for o in opts):
        raise _SkipItemError("options must be 8 non-empty strings")
    ci = item.get("correct_index")
    if not isinstance(ci, int) or ci < 0 or ci > 7:
        raise _SkipItemError("correct_index out of range")
    if not (item.get("stem") or "").strip():
        raise _SkipItemError("empty stem")
    if not (item.get("explanation") or "").strip():
        raise _SkipItemError("empty explanation")
    if not isinstance(item.get("difficulty"), int) or not 1 <= item["difficulty"] <= 5:
        raise _SkipItemError("difficulty out of range")
    topics = item.get("topics") or []
    if not topics or not all(isinstance(t, str) and t.strip() for t in topics):
        raise _SkipItemError("topics missing")
    scids = item.get("source_chunk_ids") or []
    if not scids:
        raise _SkipItemError("source_chunk_ids missing")
    # Silently drop chunk ids the LLM hallucinated — the `ANY(...)`
    # lookups in the API still work for the surviving ids.
    item["source_chunk_ids"] = [int(cid) for cid in scids if int(cid) in chunk_ids]
    if not item["source_chunk_ids"]:
        raise _SkipItemError("all source_chunk_ids hallucinated")


def _slugify_topic(t: str) -> str:
    t = t.strip().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")[:60] or "misc"


def _upsert_topic(conn: Connection, subject_slug: str, raw: str) -> int | None:
    slug = _slugify_topic(raw)
    if not slug:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO topics (subject_slug, slug, title) VALUES (%s, %s, %s)
            ON CONFLICT (subject_slug, slug) DO UPDATE SET title = topics.title
            RETURNING id
            """,
            (subject_slug, slug, raw.strip()[:80]),
        )
        return cur.fetchone()[0]


def _persist_item(conn: Connection, job: Job, item: dict) -> bool:
    """Insert one MCQ. Returns True on write, False on dedup/validation skip."""
    stem_hash = _stem_hash(item["stem"])

    with conn.cursor() as cur:
        # Dedup check up front — cheaper than racing the UNIQUE index.
        cur.execute("SELECT 1 FROM questions WHERE stem_hash = %s", (stem_hash,))
        if cur.fetchone():
            return False

        cur.execute(
            """
            INSERT INTO questions
              (subject_slug, round_id, question_type, stem, stem_hash, difficulty,
               explanation, generation_model, source_chunk_ids)
            VALUES (%s, %s, %s::question_type, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                job.subject_slug,
                job.round_id,
                job.question_type,
                item["stem"].strip(),
                stem_hash,
                int(item["difficulty"]),
                item["explanation"].strip(),
                settings.claude_model,
                item["source_chunk_ids"],
            ),
        )
        qid = cur.fetchone()[0]

        # Stable letter assignment at write time — A is whichever option
        # the LLM put at index 0, B at index 1, etc. The API re-shuffles
        # on retrieval so this order is never exposed to consumers.
        for idx, opt_text in enumerate(item["options"]):
            cur.execute(
                """
                INSERT INTO question_options (question_id, letter, text, is_correct)
                VALUES (%s, %s, %s, %s)
                """,
                (qid, _LETTERS[idx], opt_text.strip(), idx == int(item["correct_index"])),
            )

        # Topics: upsert each, link to this question.
        seen_topic_ids: set[int] = set()
        for raw in item["topics"]:
            tid = _upsert_topic(conn, job.subject_slug, raw)
            if tid is None or tid in seen_topic_ids:
                continue
            seen_topic_ids.add(tid)
            cur.execute(
                "INSERT INTO question_topics (question_id, topic_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (qid, tid),
            )
    return True


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------


def run_worker(
    subject: str | None = None,
    qtype: str | None = None,
    limit_jobs: int | None = None,
) -> None:
    """Process pending generation jobs until none remain (or `limit_jobs` hit)."""
    if qtype is not None and qtype not in QUESTION_TYPES:
        raise SystemExit(f"--type must be one of: {QUESTION_TYPES}")

    with connection() as conn:
        reset = _requeue_stale(conn)
        if reset:
            console.print(f"[yellow]requeued {reset} stale in_progress jobs[/yellow]")

    done_jobs = 0
    while True:
        if limit_jobs is not None and done_jobs >= limit_jobs:
            console.print(f"[bold]reached --limit-jobs={limit_jobs}, stopping[/bold]")
            return

        with connection() as conn:  # noqa: SIM117
            job = _claim_job(conn, subject=subject, qtype=qtype)
        if job is None:
            console.print("[bold green]no more pending jobs[/bold green]")
            return

        console.print(
            f"\n[bold cyan]→ job {job.id}[/bold cyan] "
            f"subject={job.subject_slug} type={job.question_type} "
            f"round={job.round_id} "
            f"target={job.target_count} produced={job.produced_count}"
        )

        try:
            _process_job(job)
            done_jobs += 1
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job.id)
            with connection() as conn:
                _mark_failed(conn, job.id, str(e))
            console.print(f"[red]✗ job {job.id} failed: {e}[/red]")
            # Keep going; other jobs are independent.


def _process_job(job: Job) -> None:
    batch_size = settings.mcqs_batch_size
    stall_streak = 0
    stall_limit = 3  # 3 consecutive batches with 0 new writes = give up

    while True:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT produced_count, target_count FROM generation_jobs WHERE id=%s",
                (job.id,),
            )
            produced, target = cur.fetchone()

        if produced >= target:
            with connection() as conn:
                _mark_done(conn, job.id)
            console.print(f"[green]✓ job {job.id} done ({produced}/{target})[/green]")
            return

        need = min(batch_size, target - produced)
        with connection() as conn:
            chunks = _pick_chunks(conn, job.subject_slug)
            stems = _recent_stems(conn, job.subject_slug, job.question_type)

        if not chunks:
            raise RuntimeError(f"no chunks available for subject={job.subject_slug}")

        subj = subjects.Subject(
            slug=job.subject_slug,
            title=job.subject_slug,  # title shown to LLM is cosmetic
            docs_root=None,  # type: ignore[arg-type]  (unused here)
        )
        user = prompts.render_user_prompt(
            subject=subj,
            qtype=job.question_type,
            count=need,
            chunks=chunks,
            existing_stems=stems,
        )
        schema = prompts.json_schema(need)

        t0 = time.time()
        mcqs = _call_claude(system=prompts.SYSTEM, user=user, schema=schema)
        dt = time.time() - t0

        chunk_ids = {c.id for c in chunks}
        written = 0
        skipped = 0
        with connection() as conn:
            for item in mcqs:
                try:
                    _validate_mcq(item, chunk_ids)
                except _SkipItemError as e:
                    skipped += 1
                    log.info("skip item: %s", e)
                    continue
                try:
                    if _persist_item(conn, job, item):
                        written += 1
                    else:
                        skipped += 1  # stem_hash dedup
                except Exception:
                    conn.rollback()
                    skipped += 1
                    continue
            conn.commit()

        if written:
            with connection() as conn:
                _bump_produced(conn, job.id, written)

        console.print(
            f"  batch: asked={need} returned={len(mcqs)} "
            f"written={written} skipped={skipped} in {dt:.1f}s"
        )

        if written == 0:
            stall_streak += 1
            if stall_streak >= stall_limit:
                raise RuntimeError(
                    f"{stall_limit} consecutive batches produced zero new questions"
                )
            # Tiny backoff; most zero-write streaks are just dedup noise.
            time.sleep(1 + random.random())
        else:
            stall_streak = 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def print_status() -> None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT r.number AS round, s.slug AS subject,
                   j.question_type::text AS qtype,
                   j.target_count, j.produced_count, j.status::text, j.last_error
            FROM generation_jobs j
            JOIN rounds r ON r.id = j.round_id
            JOIN subjects s ON s.slug = j.subject_slug
            ORDER BY r.number DESC, s.slug, j.question_type
            """
        )
        rows = list(cur.fetchall())
        cur.execute("SELECT COUNT(*) AS n FROM questions")
        total_q = cur.fetchone()["n"]

    t = Table(title=f"generation_jobs  ·  total questions = {total_q:,}")
    for h in ("round", "subject", "type", "progress", "status", "error"):
        t.add_column(h)
    for r in rows:
        err = (r["last_error"] or "")[:60]
        status_color = {
            "pending": "yellow",
            "in_progress": "cyan",
            "done": "green",
            "failed": "red",
        }.get(r["status"], "white")
        t.add_row(
            str(r["round"]),
            r["subject"],
            r["qtype"],
            f"{r['produced_count']}/{r['target_count']}",
            f"[{status_color}]{r['status']}[/{status_color}]",
            err,
        )
    console.print(t)

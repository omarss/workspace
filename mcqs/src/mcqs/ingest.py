"""Ingestion — walk docs-bundle, persist subjects/source_docs/doc_chunks.

Idempotent: running again after upstream docs change only re-chunks files
whose `content_hash` changed. Files that disappear stay in the DB (we
don't prune). The generator works off whatever chunks exist.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn

from . import chunker, subjects
from .config import settings
from .db import connection

log = logging.getLogger(__name__)
console = Console()

# Anything bigger than this is probably a generated dump (minified JS,
# huge JSON sitemap, compressed blob that slipped through) — skip.
MAX_FILE_BYTES = 8 * 1024 * 1024

# 200 bytes of text is not enough to produce a useful MCQ; skip the
# chunking overhead entirely.
MIN_FILE_BYTES = 200


@dataclass
class FileStats:
    ingested: int = 0
    unchanged: int = 0
    skipped: int = 0
    chunks_written: int = 0


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in chunker.TEXT_EXTS


def _guess_mime(path: Path) -> str:
    mt, _ = mimetypes.guess_type(path.name)
    return mt or "text/plain"


def _decode(raw: bytes) -> str:
    # Docs corpus is predominantly UTF-8. Latin-1 fallback is loss-free
    # for single-byte encodings and keeps weird bytes inside the ingest
    # without raising; the LLM will still see usable text.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _upsert_subject(conn: Connection, s: subjects.Subject) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO subjects (slug, title, docs_root, indexed_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (slug) DO UPDATE SET
              title = EXCLUDED.title,
              docs_root = EXCLUDED.docs_root,
              indexed_at = now()
            """,
            (s.slug, s.title, str(s.docs_root)),
        )


def _ingest_file(
    conn: Connection,
    subject: subjects.Subject,
    abs_path: Path,
    rel_path: str,
    stats: FileStats,
) -> None:
    try:
        size = abs_path.stat().st_size
    except OSError:
        stats.skipped += 1
        return
    if size < MIN_FILE_BYTES or size > MAX_FILE_BYTES:
        stats.skipped += 1
        return
    if not _is_text_file(abs_path):
        stats.skipped += 1
        return

    raw = abs_path.read_bytes()
    content_hash = hashlib.sha256(raw).hexdigest()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content_hash, content_text IS NOT NULL "
            "FROM source_docs WHERE subject_slug=%s AND rel_path=%s",
            (subject.slug, rel_path),
        )
        row = cur.fetchone()

        # Fast path: hash is unchanged AND the content_text column is
        # already populated → nothing to re-chunk, nothing to backfill.
        # Rows left over from before migration 0003 have content_text
        # NULL, so we fall through to the text-read path below just
        # long enough to populate it.
        if row and row[1] == content_hash and row[2]:
            stats.unchanged += 1
            return

        text = _decode(raw)
        mime = _guess_mime(abs_path)

        # Backfill case: hash unchanged but content_text is NULL. Just
        # populate the text column and skip re-chunking — the existing
        # chunk rows still reflect this content_hash.
        if row and row[1] == content_hash:
            cur.execute(
                "UPDATE source_docs SET content_text=%s WHERE id=%s",
                (text, row[0]),
            )
            stats.unchanged += 1
            return

        cur.execute(
            """
            INSERT INTO source_docs (subject_slug, rel_path, content_hash, byte_size, mime, content_text, indexed_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (subject_slug, rel_path) DO UPDATE SET
              content_hash = EXCLUDED.content_hash,
              byte_size    = EXCLUDED.byte_size,
              mime         = EXCLUDED.mime,
              content_text = EXCLUDED.content_text,
              indexed_at   = now()
            RETURNING id
            """,
            (subject.slug, rel_path, content_hash, size, mime, text),
        )
        source_id = cur.fetchone()[0]

        # Hash changed → throw out old chunks and rechunk. This is why we
        # can safely re-run `ingest` after upstream docs move — history is
        # never preserved for chunks; questions keep their `source_chunk_ids`
        # reference but we tolerate a dangling id (the array is advisory).
        cur.execute("DELETE FROM doc_chunks WHERE source_doc_id=%s", (source_id,))

        chunks = chunker.chunk_file(
            text,
            abs_path.suffix,
            max_tokens=settings.mcqs_chunk_tokens,
            overlap=settings.mcqs_chunk_overlap,
        )

        for c in chunks:
            # Empty or whitespace-only chunks add no value.
            if not c.text.strip():
                continue
            cur.execute(
                """
                INSERT INTO doc_chunks (source_doc_id, idx, heading_path, text, token_count)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (source_id, c.idx, c.heading_path, c.text, c.token_count),
            )
            stats.chunks_written += 1

    stats.ingested += 1


def _walk_subject(subject: subjects.Subject) -> list[tuple[Path, str]]:
    """All eligible files under a subject, returned as (absolute, relative) pairs."""
    out: list[tuple[Path, str]] = []
    for p in subject.docs_root.rglob("*"):
        if not p.is_file():
            continue
        # Skip obvious cruft.
        parts = set(p.parts)
        if any(seg.startswith(".") and seg not in {".", ".."} for seg in p.relative_to(subject.docs_root).parts):
            continue
        if parts & {"node_modules", "__pycache__", "dist", "build"}:
            continue
        rel = str(p.relative_to(subject.docs_root))
        out.append((p, rel))
    return out


def run(subject: str | None = None) -> None:
    root = Path(settings.docs_bundle_root)
    all_subjects = subjects.discover(root)
    if subject:
        all_subjects = [s for s in all_subjects if s.slug == subject]
        if not all_subjects:
            raise SystemExit(f"unknown subject: {subject}")

    console.print(f"[bold]Ingesting {len(all_subjects)} subjects from {root}[/bold]")

    with (
        connection() as conn,
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress,
    ):
        total_task = progress.add_task("[cyan]subjects", total=len(all_subjects))
        totals = FileStats()

        for s in all_subjects:
            _upsert_subject(conn, s)
            files = _walk_subject(s)
            stats = FileStats()

            subj_task = progress.add_task(
                f"  [magenta]{s.slug}[/magenta]",
                total=max(1, len(files)),
            )
            for abs_path, rel in files:
                try:
                    _ingest_file(conn, s, abs_path, rel, stats)
                except Exception as e:  # noqa: BLE001
                    log.warning("failed %s/%s: %s", s.slug, rel, e)
                    stats.skipped += 1
                progress.advance(subj_task)
            conn.commit()
            progress.remove_task(subj_task)

            console.print(
                f"  {s.slug}: "
                f"ingested={stats.ingested} "
                f"unchanged={stats.unchanged} "
                f"skipped={stats.skipped} "
                f"chunks={stats.chunks_written}"
            )
            totals.ingested += stats.ingested
            totals.unchanged += stats.unchanged
            totals.skipped += stats.skipped
            totals.chunks_written += stats.chunks_written
            progress.advance(total_task)

    console.print(
        f"[bold green]done[/bold green] "
        f"ingested={totals.ingested} "
        f"unchanged={totals.unchanged} "
        f"skipped={totals.skipped} "
        f"chunks={totals.chunks_written}"
    )

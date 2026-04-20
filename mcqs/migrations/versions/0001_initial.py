"""initial schema — subjects, docs, chunks, topics, rounds, questions, jobs, usage

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-20
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Corpus: one row per top-level docs-bundle directory.
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE subjects (
        slug         TEXT PRIMARY KEY,
        title        TEXT NOT NULL,
        description  TEXT,
        docs_root    TEXT NOT NULL,
        indexed_at   TIMESTAMPTZ
    );
    """)

    # Source documents discovered under docs_root. `content_hash` is the
    # SHA-256 of the bytes — lets `ingest` short-circuit on re-runs when
    # upstream docs haven't changed.
    op.execute("""
    CREATE TABLE source_docs (
        id            BIGSERIAL PRIMARY KEY,
        subject_slug  TEXT NOT NULL REFERENCES subjects(slug) ON DELETE CASCADE,
        rel_path      TEXT NOT NULL,
        content_hash  TEXT NOT NULL,
        byte_size     BIGINT NOT NULL,
        mime          TEXT,
        indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (subject_slug, rel_path)
    );
    """)
    op.execute("CREATE INDEX source_docs_subject_idx ON source_docs (subject_slug);")
    op.execute("CREATE INDEX source_docs_hash_idx ON source_docs (content_hash);")

    # Chunks are the unit of context we hand to Claude for a generation
    # batch. `heading_path` preserves the section trail (H1 > H2 > H3)
    # for markdown/asciidoc sources so the LLM knows where the chunk sits.
    op.execute("""
    CREATE TABLE doc_chunks (
        id             BIGSERIAL PRIMARY KEY,
        source_doc_id  BIGINT NOT NULL REFERENCES source_docs(id) ON DELETE CASCADE,
        idx            INTEGER NOT NULL,
        heading_path   TEXT,
        text           TEXT NOT NULL,
        token_count    INTEGER NOT NULL,
        UNIQUE (source_doc_id, idx)
    );
    """)
    op.execute("CREATE INDEX doc_chunks_source_idx ON doc_chunks (source_doc_id);")

    # ------------------------------------------------------------------
    # Topics: derived from the first heading / top path element of a
    # chunk. Questions can span several topics within a subject.
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE topics (
        id            BIGSERIAL PRIMARY KEY,
        subject_slug  TEXT NOT NULL REFERENCES subjects(slug) ON DELETE CASCADE,
        slug          TEXT NOT NULL,
        title         TEXT NOT NULL,
        UNIQUE (subject_slug, slug)
    );
    """)
    op.execute("CREATE INDEX topics_subject_idx ON topics (subject_slug);")

    # ------------------------------------------------------------------
    # Generation rounds. Each round adds ≥100 questions per (subject,
    # type). A later round can re-target chunks already seen — the user
    # asked for this explicitly ("so later we can do another round").
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE rounds (
        id           BIGSERIAL PRIMARY KEY,
        number       INTEGER NOT NULL UNIQUE,
        started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at  TIMESTAMPTZ,
        notes        TEXT
    );
    """)

    # ------------------------------------------------------------------
    # Questions. `question_type` is one of:
    #   knowledge       — literal recall from the docs
    #   analytical      — why / trade-offs / interactions
    #   problem_solving — scenario → best documented action
    # `stem_hash` is SHA-256(normalized_stem) and is UNIQUE across the
    # whole table so rerunning generation can't duplicate questions.
    # ------------------------------------------------------------------
    op.execute("CREATE TYPE question_type AS ENUM ('knowledge', 'analytical', 'problem_solving');")

    op.execute("""
    CREATE TABLE questions (
        id                BIGSERIAL PRIMARY KEY,
        subject_slug      TEXT NOT NULL REFERENCES subjects(slug) ON DELETE CASCADE,
        round_id          BIGINT NOT NULL REFERENCES rounds(id) ON DELETE RESTRICT,
        question_type     question_type NOT NULL,
        stem              TEXT NOT NULL,
        stem_hash         TEXT NOT NULL UNIQUE,
        difficulty        SMALLINT NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
        explanation       TEXT NOT NULL,
        generation_model  TEXT NOT NULL,
        source_chunk_ids  BIGINT[] NOT NULL DEFAULT '{}',
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX questions_subject_type_idx ON questions (subject_slug, question_type);")
    op.execute("CREATE INDEX questions_round_idx ON questions (round_id);")

    # Exactly 4 options per question (A/B/C/D). The CHECK on letter
    # plus the UNIQUE (question_id, letter) lets us enforce at insert
    # time; the "exactly-one-correct" rule is enforced in the writer.
    op.execute("""
    CREATE TABLE question_options (
        id           BIGSERIAL PRIMARY KEY,
        question_id  BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        letter       CHAR(1) NOT NULL CHECK (letter IN ('A','B','C','D')),
        text         TEXT NOT NULL,
        is_correct   BOOLEAN NOT NULL DEFAULT FALSE,
        UNIQUE (question_id, letter)
    );
    """)
    op.execute("CREATE INDEX question_options_question_idx ON question_options (question_id);")

    # Join table: a question may tag multiple topics within its subject.
    op.execute("""
    CREATE TABLE question_topics (
        question_id  BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        topic_id     BIGINT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
        PRIMARY KEY (question_id, topic_id)
    );
    """)
    op.execute("CREATE INDEX question_topics_topic_idx ON question_topics (topic_id);")

    # ------------------------------------------------------------------
    # Resumable generation queue. One row per (subject, round, type).
    # Worker uses SELECT ... FOR UPDATE SKIP LOCKED so multiple workers
    # never pick the same row.
    # ------------------------------------------------------------------
    op.execute("CREATE TYPE job_status AS ENUM ('pending', 'in_progress', 'done', 'failed');")

    op.execute("""
    CREATE TABLE generation_jobs (
        id              BIGSERIAL PRIMARY KEY,
        subject_slug    TEXT NOT NULL REFERENCES subjects(slug) ON DELETE CASCADE,
        round_id        BIGINT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        question_type   question_type NOT NULL,
        target_count    INTEGER NOT NULL,
        produced_count  INTEGER NOT NULL DEFAULT 0,
        status          job_status NOT NULL DEFAULT 'pending',
        last_error      TEXT,
        started_at      TIMESTAMPTZ,
        finished_at     TIMESTAMPTZ,
        UNIQUE (subject_slug, round_id, question_type)
    );
    """)
    op.execute("CREATE INDEX generation_jobs_status_idx ON generation_jobs (status);")
    op.execute("CREATE INDEX generation_jobs_round_idx ON generation_jobs (round_id);")

    # ------------------------------------------------------------------
    # Per-key per-endpoint daily counters — identical shape to
    # gplaces_parser's api_usage table so the admin view pattern carries
    # over cleanly.
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE api_usage (
        key_prefix    TEXT    NOT NULL,
        endpoint      TEXT    NOT NULL,
        status_bucket INTEGER NOT NULL,
        day           DATE    NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')::date,
        count         BIGINT  NOT NULL DEFAULT 0,
        last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (key_prefix, endpoint, status_bucket, day)
    );
    """)
    op.execute("CREATE INDEX api_usage_day ON api_usage (day DESC);")
    op.execute("CREATE INDEX api_usage_last_seen ON api_usage (last_seen DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_usage;")
    op.execute("DROP TABLE IF EXISTS generation_jobs;")
    op.execute("DROP TABLE IF EXISTS question_topics;")
    op.execute("DROP TABLE IF EXISTS question_options;")
    op.execute("DROP TABLE IF EXISTS questions;")
    op.execute("DROP TABLE IF EXISTS rounds;")
    op.execute("DROP TABLE IF EXISTS topics;")
    op.execute("DROP TABLE IF EXISTS doc_chunks;")
    op.execute("DROP TABLE IF EXISTS source_docs;")
    op.execute("DROP TABLE IF EXISTS subjects;")
    op.execute("DROP TYPE IF EXISTS job_status;")
    op.execute("DROP TYPE IF EXISTS question_type;")

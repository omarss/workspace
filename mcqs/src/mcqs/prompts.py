"""Prompt templates for MCQ generation.

Three distinct user instructions are layered on top of a single shared
system prompt — that way the JSON schema and quality bar are specified
once and the per-type differences read as a short rubric.

Inputs:
  subject      — the Subject row (slug + title)
  qtype        — "knowledge" | "analytical" | "problem_solving"
  count        — how many MCQs to produce in this call
  chunks       — list of (id, heading_path, text) tuples to use as context
  existing_stems — a short list of already-produced stems for this
                   (subject, type) so the LLM can avoid duplicates
                   without us needing a semantic similarity check
"""

from __future__ import annotations

from dataclasses import dataclass

from . import subjects

# ---------------------------------------------------------------------------
# Shared system prompt — defines the JSON schema and quality bar.
# ---------------------------------------------------------------------------

SYSTEM = """You are a subject-matter expert writing a multiple-choice question bank from technical documentation. Your output is parsed programmatically — reply with a single JSON array and nothing else. No markdown fences, no preamble, no trailing commentary.

Every question must:
- Have exactly 8 options, with exactly one correct and seven distractors.
- Be answerable solely from the excerpts below. Never invent facts.
- Have distractors that are plausible but clearly wrong given the source
  (wrong default value, outdated behaviour, opposite trade-off, common
  misconception, adjacent-but-wrong concept, mis-remembered command).
  Do NOT use joke options, empty options, or "all of the above" /
  "none of the above" / "any of A, B".
- Reference concepts directly in the `explanation` — never say "option A"
  or "the third choice". The API re-shuffles and re-letters options on
  every retrieval, so positional references become meaningless.
- Cite at least one `source_chunk_ids` entry — use the numeric ids shown
  in the `<chunk id="N" ...>` markers.
- Tag 1–3 `topics`: short lowercase slugs naming the concepts the
  question touches (e.g. "installation", "caching", "rbac"). A single
  question may touch multiple topics across the subject.
- Have a `difficulty` integer 1–5 (1 = trivial recall, 5 = expert-level
  synthesis). Aim for a mix across the batch, not all the same value.
- Have an `explanation` (1–3 sentences) grounded in the source.

Strict per-item JSON schema:
{
  "stem": "string, a full question ending with '?'",
  "options": ["text1", "text2", "text3", "text4", "text5", "text6", "text7", "text8"],
  "correct_index": 0..7,
  "explanation": "string (no positional references like 'option A')",
  "topics": ["slug", ...],
  "difficulty": 1..5,
  "source_chunk_ids": [int, ...]
}

Return: a single JSON object with one key `questions`, whose value is an array of exactly the requested number of question objects. Do not include any other keys at the top level."""

# ---------------------------------------------------------------------------
# Per-type rubric — dropped into the user message.
# ---------------------------------------------------------------------------

RUBRIC_KNOWLEDGE = (
    "Type: KNOWLEDGE RECALL.\n"
    "Test literal recall of facts, definitions, command names, flags, configuration keys, "
    "default values, ports, version numbers, or API signatures that appear in the excerpts. "
    "The correct answer should be directly quotable from the source. Distractors should be "
    "wrong values of the same kind (wrong default port, wrong flag name, wrong RFC number)."
)

RUBRIC_ANALYTICAL = (
    "Type: ANALYTICAL.\n"
    "Test understanding of why things work the way they do: trade-offs, consequences, "
    "interactions between components, ordering, side effects, edge cases. Correct answers "
    "should require synthesis across multiple sentences of the source (not a verbatim "
    "snippet). Distractors should be the plausible misconceptions a newcomer would pick."
)

RUBRIC_PROBLEM_SOLVING = (
    "Type: PROBLEM-SOLVING.\n"
    "Begin the stem with a realistic scenario in 1–2 sentences ('A team is seeing X when Y; "
    "they want Z') then ask which action best resolves it. The correct action must match "
    "the documented recommendation. Distractors should be moves that sound reasonable but "
    "are explicitly discouraged, outdated, or unsupported by the docs."
)

_RUBRIC: dict[str, str] = {
    "knowledge": RUBRIC_KNOWLEDGE,
    "analytical": RUBRIC_ANALYTICAL,
    "problem_solving": RUBRIC_PROBLEM_SOLVING,
}


# JSON Schema handed to `claude -p --json-schema`. Anthropic's structured-
# output path requires the top-level schema to be an `object` (it becomes
# a tool's `input_schema` internally), so we wrap the actual array in a
# single `questions` key and unwrap after the call.
def json_schema(count: int) -> dict:
    return {
        "type": "object",
        "required": ["questions"],
        "additionalProperties": False,
        "properties": {
            "questions": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "required": [
                        "stem",
                        "options",
                        "correct_index",
                        "explanation",
                        "topics",
                        "difficulty",
                        "source_chunk_ids",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "stem": {"type": "string", "minLength": 10},
                        "options": {
                            "type": "array",
                            "minItems": 8,
                            "maxItems": 8,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "correct_index": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 7,
                        },
                        "explanation": {"type": "string", "minLength": 10},
                        "topics": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 5,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 60,
                            },
                        },
                        "difficulty": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                        },
                        "source_chunk_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "integer"},
                        },
                    },
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@dataclass
class ChunkCtx:
    id: int
    heading_path: str | None
    text: str


def _render_chunks(chunks: list[ChunkCtx]) -> str:
    out: list[str] = []
    for c in chunks:
        heading = c.heading_path or "(no heading)"
        out.append(f'<chunk id="{c.id}" heading="{heading}">\n{c.text.strip()}\n</chunk>')
    return "\n\n".join(out)


def render_user_prompt(
    *,
    subject: subjects.Subject,
    qtype: str,
    count: int,
    chunks: list[ChunkCtx],
    existing_stems: list[str] | None = None,
) -> str:
    if qtype not in _RUBRIC:
        raise ValueError(f"unknown qtype: {qtype}")
    rubric = _RUBRIC[qtype]

    parts = [
        f"Subject: {subject.title} ({subject.slug})",
        rubric,
        f"Write exactly {count} multiple-choice questions from the documentation excerpts below.",
    ]

    if existing_stems:
        # Cap the list so it never dominates the token budget. The LLM
        # doesn't need to see thousands of prior stems — a random recent
        # sample is enough to stop it repeating the same phrasing.
        sample = existing_stems[-30:]
        stems_block = "\n".join(f"- {s}" for s in sample)
        parts.append(
            "Avoid questions whose stem or answer substantively overlaps any of these "
            "already-written questions for this subject:\n" + stems_block
        )

    parts.append("Documentation excerpts:\n" + _render_chunks(chunks))

    parts.append(
        f"Now return a JSON array of exactly {count} question objects, conforming to the "
        "schema in the system prompt. Output only the JSON array."
    )

    return "\n\n".join(parts)

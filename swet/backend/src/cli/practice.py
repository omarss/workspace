"""Core practice flow: generate question -> collect answer -> grade -> explain.

Reuses the existing question generator and AI grader from the backend,
but runs standalone without PostgreSQL.
"""

import random

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

from src.cli.config import CLIConfig
from src.cli.data import COMPETENCIES, ROLE_WEIGHTS
from src.cli.display import (
    collect_answer,
    display_grade_result,
    display_mcq_result,
    display_question,
)
from src.cli.history import append_history, create_entry

console = Console()

# Question formats supported in CLI mode
FORMATS = ["mcq", "code_review", "debugging", "short_answer", "design_prompt"]


def _pick_competency(role: str, override: str | None = None) -> dict[str, str | int]:
    """Select a competency, optionally weighted by role.

    Args:
        role: The user's primary role (for weighted selection).
        override: If set, use this competency slug directly.

    Returns:
        Competency dict from COMPETENCIES.
    """
    if override:
        for comp in COMPETENCIES:
            if comp["slug"] == override:
                return comp
        slugs = [str(c["slug"]) for c in COMPETENCIES]
        raise ValueError(f"Unknown competency '{override}'. Valid: {', '.join(slugs)}")

    # Weighted random selection based on role
    weights = ROLE_WEIGHTS.get(role, ROLE_WEIGHTS["backend"])
    # weights is list of (competency_id, weight, question_count)
    comp_ids = [w[0] for w in weights]
    comp_weights = [w[1] for w in weights]

    chosen_id = random.choices(comp_ids, weights=comp_weights, k=1)[0]
    for comp in COMPETENCIES:
        if comp["id"] == chosen_id:
            return comp

    # Fallback (should never happen)
    return COMPETENCIES[0]


def _pick_difficulty(experience_years: int, override: int | None = None) -> int:
    """Map experience to difficulty level, or use override."""
    if override:
        return max(1, min(5, override))

    if experience_years <= 1:
        return 1
    elif experience_years <= 3:
        return 2
    elif experience_years <= 6:
        return 3
    elif experience_years <= 10:
        return 4
    else:
        return 5


def _pick_format(override: str | None = None) -> str:
    """Pick a random question format, or use override."""
    if override:
        if override not in FORMATS:
            raise ValueError(f"Unknown format '{override}'. Valid: {', '.join(FORMATS)}")
        return override
    return random.choice(FORMATS)


async def run_practice(
    config: CLIConfig,
    format_override: str | None = None,
    difficulty_override: int | None = None,
    competency_override: str | None = None,
) -> None:
    """Run a single practice question session.

    1. Pick question parameters (competency, difficulty, format)
    2. Generate a question via Claude
    3. Present question and collect answer
    4. Grade the answer (auto for MCQ, AI for others)
    5. Display result with explanation
    6. Save to history
    """
    # Lazy imports to ensure settings are patched first
    from src.questions.generator import generate_questions
    from src.scoring.grader import grade_answer

    profile = config.profile

    # Pick question parameters
    competency = _pick_competency(profile.primary_role, competency_override)
    difficulty = _pick_difficulty(profile.experience_years, difficulty_override)
    question_format = _pick_format(format_override)

    console.print(
        f"[dim]Generating a {question_format.replace('_', ' ')} question "
        f"on {competency['name']} (L{difficulty})...[/dim]"
    )

    # Generate question
    with Live(Spinner("dots", text="Thinking..."), console=console, transient=True):
        questions = await generate_questions(
            competency_name=str(competency["name"]),
            competency_description=str(competency["description"]),
            difficulty=difficulty,
            question_format=question_format,
            role=profile.primary_role,
            languages=profile.languages,
            frameworks=profile.frameworks,
            count=1,
        )

    if not questions:
        console.print("[red]Failed to generate a question. Please try again.[/red]")
        return

    question = questions[0]

    # Display question and collect answer
    display_question(question)
    answer = collect_answer(question)

    if not answer:
        console.print("[yellow]No answer provided. Skipping.[/yellow]")
        return

    # Grade the answer
    if question.format == "mcq":
        correct = question.correct_answer or ""
        is_correct = answer.upper() == correct.upper()
        score = 1.0 if is_correct else 0.0
        max_score = 1.0
        display_mcq_result(answer, correct, question.explanation)
    else:
        # AI grading for open-ended formats
        console.print()
        with Live(Spinner("dots", text="Grading your answer..."), console=console, transient=True):
            rubric = question.grading_rubric.model_dump() if question.grading_rubric else {}
            result = await grade_answer(
                question_title=question.title,
                question_body=question.body,
                question_format=question.format,
                rubric=rubric,
                answer_text=answer,
                code_snippet=question.code_snippet,
            )

        score = result.normalized_score
        max_score = 1.0
        display_grade_result(result, question.explanation)

    # Save to history
    entry = create_entry(
        competency=str(competency["slug"]),
        question_format=question_format,
        difficulty=difficulty,
        title=question.title,
        score=score,
        max_score=max_score,
    )
    append_history(entry)

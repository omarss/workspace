"""Prompt templates for Claude-based question generation (SPEC-012).

Contains the system prompt, difficulty calibration guide, format-specific
instructions, and the main prompt builder that assembles everything.
"""

SYSTEM_PROMPT = """\
You are an expert software engineering assessment author. Your task is to \
generate high-quality assessment questions that accurately measure software \
engineering competency.

IMPORTANT RULES:
1. Return ONLY a JSON array of question objects. No markdown fences, no extra text.
2. Each question must be unique within the batch (no duplicate or near-identical titles).
3. Questions must be realistic, practical, and relevant to real-world engineering work.
4. Code snippets must be self-contained (no external dependencies) and 20-80 lines.
5. MCQ distractors must be plausible - no obviously wrong answers.
6. Grading rubrics must have criteria point totals that exactly equal max_score.
"""

DIFFICULTY_GUIDE = """\
Difficulty calibration:
- L1 (Beginner, 0-1 years): Fundamental concepts, syntax-level knowledge, basic patterns.
- L2 (Intermediate, 1-3 years): Applied knowledge, common patterns, standard best practices.
- L3 (Advanced, 3-6 years): Nuanced trade-offs, edge cases, architectural reasoning.
- L4 (Expert, 6-10 years): Complex system interactions, production-grade considerations.
- L5 (Principal, 10+ years): Strategic technical decisions, cross-cutting concerns, mentoring-level depth.\
"""

# Format-specific generation instructions
FORMAT_INSTRUCTIONS: dict[str, str] = {
    "mcq": """\
Generate multiple-choice questions with exactly 4 options labeled A, B, C, D.
- Exactly one option must be the correct answer.
- Distractors must be plausible and test genuine understanding, not elimination ability.
- Set "correct_answer" to the letter of the correct option.
- Set "grading_rubric" to null.
- Set "code_snippet" and "language" to null unless the question includes a code example in the body.
- Include a clear explanation of why the correct answer is right and others are wrong.
- Set options as an object with keys "A", "B", "C", "D".\
""",
    "code_review": """\
Generate code review questions with a code snippet (20-80 lines) containing intentional issues.
- The body should ask the candidate to identify problems and suggest improvements.
- Provide "code_snippet" with realistic but self-contained code.
- Specify the "language" of the code snippet.
- Set "options" and "correct_answer" to null.
- Include a "grading_rubric" with 2-4 criteria covering issue identification, improvement quality, and depth of analysis.
- Rubric criteria max_points must sum to max_score. Set max_score to 10.
- Include key_indicators listing specific things a good answer would mention.\
""",
    "debugging": """\
Generate debugging scenario questions with code and error output.
- Present a realistic scenario with code, error logs, or stack traces.
- The body should ask to identify root cause, provide a fix, and suggest prevention measures.
- Provide "code_snippet" including both the problematic code and error output/logs.
- Specify the "language" of the code snippet.
- Set "options" and "correct_answer" to null.
- Include a "grading_rubric" with 3 criteria: root cause identification, fix quality, and prevention strategy.
- Rubric criteria max_points must sum to max_score. Set max_score to 10.
- Include key_indicators listing specific insights expected.\
""",
    "short_answer": """\
Generate conceptual or scenario-based questions requiring written explanation.
- Questions should require 100-300 words to answer well.
- Set "code_snippet", "language", "options", and "correct_answer" to null.
- Include a "grading_rubric" with 2-3 criteria covering conceptual accuracy, examples, and analysis depth.
- Rubric criteria max_points must sum to max_score. Set max_score to 10.
- Include key_indicators for each criterion.\
""",
    "design_prompt": """\
Generate system design questions asking candidates to design a system or feature.
- Questions should cover architecture, data model, trade-offs, and scalability.
- Set "code_snippet", "language", "options", and "correct_answer" to null.
- Include a "grading_rubric" with 3-4 criteria covering architecture, data model, trade-offs, and scalability.
- Rubric criteria max_points must sum to max_score. Set max_score to 10.
- Include key_indicators for each criterion.\
""",
}

# JSON schema referenced in the prompt so Claude knows the expected output shape
OUTPUT_SCHEMA = """\
Each question object must have this exact structure:
{
  "title": "string (concise question title, max 200 chars)",
  "body": "string (full question in markdown)",
  "code_snippet": "string or null",
  "language": "string or null (e.g. python, typescript, go, java, rust)",
  "options": {"A": "string", "B": "string", "C": "string", "D": "string"} or null,
  "correct_answer": "A" | "B" | "C" | "D" | null,
  "grading_rubric": {
    "criteria": [
      {
        "name": "string",
        "description": "string",
        "max_points": number,
        "key_indicators": ["string", ...]
      }
    ],
    "max_score": number,
    "passing_threshold": number
  } or null,
  "explanation": "string (detailed explanation of the expected answer)",
  "metadata": {
    "topics": ["string", ...],
    "estimated_time_minutes": number
  }
}\
"""


def build_generation_prompt(
    competency_name: str,
    competency_description: str,
    difficulty: int,
    question_format: str,
    role: str,
    languages: list[str],
    frameworks: list[str],
    count: int = 20,
) -> tuple[str, str]:
    """Build the system and user messages for question generation.

    Returns:
        Tuple of (system_message, user_message).
    """
    difficulty_labels = {
        1: "L1 Beginner",
        2: "L2 Intermediate",
        3: "L3 Advanced",
        4: "L4 Expert",
        5: "L5 Principal",
    }
    difficulty_label = difficulty_labels.get(difficulty, f"L{difficulty}")

    format_instruction = FORMAT_INSTRUCTIONS.get(question_format, "")

    user_message = f"""\
Generate {count} {question_format} questions for the following assessment:

COMPETENCY: {competency_name}
DESCRIPTION: {competency_description}

DIFFICULTY: {difficulty_label}
{DIFFICULTY_GUIDE}

ROLE CONTEXT:
- Primary role: {role}
- Languages: {", ".join(languages) if languages else "general"}
- Frameworks: {", ".join(frameworks) if frameworks else "general"}

FORMAT: {question_format}
{format_instruction}

OUTPUT FORMAT:
Return a JSON array of exactly {count} question objects. No extra text or markdown fences.
{OUTPUT_SCHEMA}

Remember: Return ONLY the JSON array, nothing else."""

    return SYSTEM_PROMPT, user_message

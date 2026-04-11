"""Tests for question generation via LLM API (SPEC-012)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.questions.generator import _parse_and_validate, generate_questions
from src.questions.prompts import FORMAT_INSTRUCTIONS, build_generation_prompt

# ---------------------------------------------------------------------------
# Prompt building tests
# ---------------------------------------------------------------------------


class TestBuildGenerationPrompt:
    def test_returns_system_and_user_messages(self) -> None:
        system, user = build_generation_prompt(
            competency_name="Problem Solving",
            competency_description="Breaking down complex problems",
            difficulty=3,
            question_format="mcq",
            role="backend",
            languages=["python", "go"],
            frameworks=["fastapi"],
            count=5,
        )
        assert "expert software engineering assessment author" in system
        assert "Problem Solving" in user
        assert "L3 Advanced" in user
        assert "mcq" in user
        assert "backend" in user
        assert "python" in user
        assert "fastapi" in user
        assert "5" in user  # count

    def test_all_formats_have_instructions(self) -> None:
        expected = {"mcq", "code_review", "debugging", "short_answer", "design_prompt"}
        assert set(FORMAT_INSTRUCTIONS.keys()) == expected

    def test_difficulty_labels_l1_to_l5(self) -> None:
        for level in range(1, 6):
            _, user = build_generation_prompt(
                competency_name="Test",
                competency_description="Test desc",
                difficulty=level,
                question_format="mcq",
                role="backend",
                languages=[],
                frameworks=[],
            )
            assert f"L{level}" in user

    def test_empty_languages_shows_general(self) -> None:
        _, user = build_generation_prompt(
            competency_name="Test",
            competency_description="Desc",
            difficulty=1,
            question_format="mcq",
            role="backend",
            languages=[],
            frameworks=[],
        )
        assert "general" in user


# ---------------------------------------------------------------------------
# Parse and validate tests
# ---------------------------------------------------------------------------


class TestParseAndValidate:
    def _make_mcq_json(self, count: int = 1) -> str:
        questions = []
        for i in range(count):
            questions.append(
                {
                    "title": f"What is question {i}?",
                    "body": f"Choose the best answer for question {i}...",
                    "code_snippet": None,
                    "language": None,
                    "options": {"A": "opt1", "B": "opt2", "C": "opt3", "D": "opt4"},
                    "correct_answer": "A",
                    "grading_rubric": None,
                    "explanation": "A is correct because it represents the right answer.",
                    "metadata": {"topics": ["testing"], "estimated_time_minutes": 1},
                }
            )
        return json.dumps(questions)

    def _make_code_review_json(self) -> str:
        return json.dumps(
            [
                {
                    "title": "Review this authentication handler",
                    "body": "Review the following code for security and quality issues...",
                    "code_snippet": "class AuthHandler:\n    def authenticate(self, token):\n        return jwt.decode(token, 'secret')",
                    "language": "python",
                    "options": None,
                    "correct_answer": None,
                    "grading_rubric": {
                        "criteria": [
                            {
                                "name": "Issue Identification",
                                "description": "Identifies security issues",
                                "max_points": 5,
                                "key_indicators": ["hardcoded secret", "no algorithm specified"],
                            },
                            {
                                "name": "Fix Quality",
                                "description": "Provides correct fixes",
                                "max_points": 5,
                                "key_indicators": ["uses env variable", "specifies algorithm"],
                            },
                        ],
                        "max_score": 10,
                        "passing_threshold": 5,
                    },
                    "explanation": "The code has several security issues including...",
                    "metadata": {"topics": ["security", "jwt"], "estimated_time_minutes": 5},
                }
            ]
        )

    def test_parses_valid_mcq_json(self) -> None:
        result = _parse_and_validate(self._make_mcq_json(3), "mcq")
        assert len(result) == 3
        assert all(q.format == "mcq" for q in result)

    def test_parses_valid_code_review_json(self) -> None:
        result = _parse_and_validate(self._make_code_review_json(), "code_review")
        assert len(result) == 1
        assert result[0].format == "code_review"
        assert result[0].code_snippet is not None

    def test_strips_markdown_fences(self) -> None:
        raw = "```json\n" + self._make_mcq_json(1) + "\n```"
        result = _parse_and_validate(raw, "mcq")
        assert len(result) == 1

    def test_injects_format_if_missing(self) -> None:
        """If LLM omits the format field, it should be injected."""
        data = [
            {
                "title": "What is question?",
                "body": "Choose the best answer...",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "correct_answer": "A",
                "explanation": "A is correct because it is the right answer.",
            }
        ]
        result = _parse_and_validate(json.dumps(data), "mcq")
        assert len(result) == 1
        assert result[0].format == "mcq"

    def test_skips_invalid_questions(self) -> None:
        """Invalid questions are skipped, valid ones are kept."""
        data = [
            {
                "title": "Valid MCQ question here",
                "body": "Choose the best answer for this question...",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "correct_answer": "A",
                "explanation": "A is correct because it represents the right choice.",
            },
            {
                "title": "Bad",  # Too short body, missing fields
                "body": "x",
            },
        ]
        result = _parse_and_validate(json.dumps(data), "mcq")
        assert len(result) == 1

    def test_raises_on_non_array(self) -> None:
        with pytest.raises(ValueError, match="Expected a JSON array"):
            _parse_and_validate('{"not": "an array"}', "mcq")

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_and_validate("not json at all", "mcq")


# ---------------------------------------------------------------------------
# Full generation pipeline tests (mocked LLM client)
# ---------------------------------------------------------------------------


class TestGenerateQuestions:
    def _mock_chat_completion(self, response_text: str) -> AsyncMock:
        """Create a mock for chat_completion that returns the given text."""
        return AsyncMock(return_value=(response_text, 1000, 2000))

    def _make_questions_json(self, fmt: str, count: int = 3) -> str:
        """Generate a JSON string of sample questions for a given format."""
        questions = []
        for i in range(count):
            q: dict[str, object] = {
                "title": f"Question {i} about {fmt} topic here",
                "body": f"This is the full question body for {fmt} question {i}...",
                "code_snippet": None,
                "language": None,
                "options": None,
                "correct_answer": None,
                "grading_rubric": None,
                "explanation": f"This is the detailed explanation for question {i}.",
                "metadata": {"topics": ["testing"], "estimated_time_minutes": 3},
            }

            if fmt == "mcq":
                q["options"] = {"A": "a", "B": "b", "C": "c", "D": "d"}
                q["correct_answer"] = "B"
            elif fmt in ("code_review", "debugging"):
                q["code_snippet"] = (
                    "def example():\n    # intentional issue here\n    return None\n"
                    "# more code to meet min length\n"
                )
                q["language"] = "python"
                q["grading_rubric"] = {
                    "criteria": [
                        {
                            "name": "Analysis",
                            "description": "Quality of analysis",
                            "max_points": 10,
                            "key_indicators": ["identifies the issue"],
                        }
                    ],
                    "max_score": 10,
                    "passing_threshold": 5,
                }
            else:  # short_answer, design_prompt
                q["grading_rubric"] = {
                    "criteria": [
                        {
                            "name": "Depth",
                            "description": "Depth of answer",
                            "max_points": 10,
                            "key_indicators": ["provides examples"],
                        }
                    ],
                    "max_score": 10,
                    "passing_threshold": 5,
                }

            questions.append(q)
        return json.dumps(questions)

    async def test_generates_mcq_questions(self) -> None:
        response_json = self._make_questions_json("mcq", count=5)
        mock_fn = self._mock_chat_completion(response_json)

        with patch("src.questions.generator.chat_completion", mock_fn):
            result = await generate_questions(
                competency_name="Problem Solving",
                competency_description="Breaking down complex problems",
                difficulty=2,
                question_format="mcq",
                role="backend",
                languages=["python"],
                frameworks=["fastapi"],
                count=5,
            )

        assert len(result) == 5
        assert all(q.format == "mcq" for q in result)
        assert all(q.correct_answer is not None for q in result)
        mock_fn.assert_called_once()

    async def test_generates_code_review_questions(self) -> None:
        response_json = self._make_questions_json("code_review", count=3)
        mock_fn = self._mock_chat_completion(response_json)

        with patch("src.questions.generator.chat_completion", mock_fn):
            result = await generate_questions(
                competency_name="Code Quality",
                competency_description="Writing clean code",
                difficulty=3,
                question_format="code_review",
                role="backend",
                languages=["python"],
                frameworks=[],
                count=3,
            )

        assert len(result) == 3
        assert all(q.code_snippet is not None for q in result)
        assert all(q.grading_rubric is not None for q in result)

    async def test_generates_debugging_questions(self) -> None:
        response_json = self._make_questions_json("debugging", count=2)
        mock_fn = self._mock_chat_completion(response_json)

        with patch("src.questions.generator.chat_completion", mock_fn):
            result = await generate_questions(
                competency_name="Debugging",
                competency_description="Systematic debugging",
                difficulty=4,
                question_format="debugging",
                role="backend",
                languages=["python"],
                frameworks=[],
                count=2,
            )

        assert len(result) == 2
        assert all(q.format == "debugging" for q in result)

    async def test_generates_short_answer_questions(self) -> None:
        response_json = self._make_questions_json("short_answer", count=2)
        mock_fn = self._mock_chat_completion(response_json)

        with patch("src.questions.generator.chat_completion", mock_fn):
            result = await generate_questions(
                competency_name="System Design",
                competency_description="Designing scalable systems",
                difficulty=3,
                question_format="short_answer",
                role="backend",
                languages=["python"],
                frameworks=[],
                count=2,
            )

        assert len(result) == 2
        assert all(q.grading_rubric is not None for q in result)

    async def test_generates_design_prompt_questions(self) -> None:
        response_json = self._make_questions_json("design_prompt", count=2)
        mock_fn = self._mock_chat_completion(response_json)

        with patch("src.questions.generator.chat_completion", mock_fn):
            result = await generate_questions(
                competency_name="System Design",
                competency_description="Designing scalable systems",
                difficulty=5,
                question_format="design_prompt",
                role="backend",
                languages=["python"],
                frameworks=[],
                count=2,
            )

        assert len(result) == 2
        assert all(q.format == "design_prompt" for q in result)

    async def test_raises_on_no_valid_questions(self) -> None:
        """If LLM returns all invalid questions, raise ValueError."""
        bad_json = json.dumps([{"title": "x", "body": "y"}])
        mock_fn = self._mock_chat_completion(bad_json)

        with (
            patch("src.questions.generator.chat_completion", mock_fn),
            pytest.raises(ValueError, match="no valid questions"),
        ):
            await generate_questions(
                competency_name="Test",
                competency_description="Test desc",
                difficulty=1,
                question_format="mcq",
                role="backend",
                languages=[],
                frameworks=[],
                count=5,
            )

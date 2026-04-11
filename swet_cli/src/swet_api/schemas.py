"""Shared Pydantic schemas for API request/response models."""

from pydantic import BaseModel, Field


class PreferencesRequest(BaseModel):
    """Request to set or update preferences."""

    roles: list[str]
    languages: list[str]
    frameworks: list[str]
    preferred_formats: list[str] | None = None
    question_length: str = "standard"


class PreferencesResponse(BaseModel):
    """User preferences."""

    roles: list[str]
    languages: list[str]
    frameworks: list[str]
    difficulty: int
    preferred_formats: list[str] | None = None
    question_length: str = "standard"


class GenerateRequest(BaseModel):
    """Request to generate questions."""

    competency_slug: str | None = None
    question_format: str | None = None
    difficulty: int | None = Field(None, ge=1, le=5)
    count: int = Field(10, ge=1, le=20)


class AnswerRequest(BaseModel):
    """Submit an answer to a question."""

    question_id: str
    answer_text: str
    time_seconds: float | None = None
    confidence: int | None = Field(None, ge=1, le=5)


class QuestionResponse(BaseModel):
    """A question returned by the API."""

    id: str
    competency_slug: str
    format: str
    difficulty: int
    title: str
    body: str
    code_snippet: str | None = None
    language: str | None = None
    options: dict[str, str] | None = None
    # correct_answer intentionally excluded — revealed after grading
    explanation_detail: dict | None = None
    metadata: dict | None = None


class CriterionScoreResponse(BaseModel):
    """A single grading criterion with score."""

    criterion: str
    score: int
    max_score: int
    feedback: str


class GradeResponse(BaseModel):
    """Grading result for a submitted answer."""

    attempt_id: str
    score: float
    max_score: int
    total_score: float
    normalized_score: float
    criteria_scores: list[CriterionScoreResponse] | None = None
    overall_feedback: str
    explanation: str | None = None
    correct_answer: str | None = None


class StatsResponse(BaseModel):
    """Aggregate stats for a competency."""

    competency_slug: str
    total_attempts: int
    avg_score: float
    min_score: float
    max_score: float


class StreakResponse(BaseModel):
    """Current streak data."""

    current_streak: int
    longest_streak: int


class BookmarkResponse(BaseModel):
    """A bookmarked question."""

    id: str
    title: str
    competency_slug: str
    format: str
    difficulty: int
    bookmarked_at: str | None = None


class CompetencyLevelResponse(BaseModel):
    """Competency with its estimated level."""

    slug: str
    name: str
    estimated_level: int | None = None
    total_attempts: int = 0


# --- Assessments ---


class AssessmentStartRequest(BaseModel):
    """Request to start an assessment with optional self-evaluation ratings."""

    self_ratings: dict[str, int] | None = None  # competency_slug → 0 (skip) to 5 (expert)


class AssessmentStartResponse(BaseModel):
    """Response when starting a new assessment."""

    assessment_id: str
    competencies: list[str]
    total_questions: int
    first_question: QuestionResponse
    primary_language: str | None = None
    assessment_phase: str = "concepts"


class AssessmentAnswerRequest(BaseModel):
    """Submit an answer during an assessment."""

    answer: str


class CompetencyResult(BaseModel):
    """Result for a single competency in an assessment."""

    slug: str
    name: str
    estimated_level: int
    confidence: float
    posterior: dict[int, float]


class AssessmentResultsResponse(BaseModel):
    """Assessment results with per-competency levels."""

    assessment_id: str
    status: str
    competencies: list[CompetencyResult]
    completed_at: str | None = None


class AssessmentAnswerResponse(BaseModel):
    """Response after answering an assessment question."""

    correct: bool
    correct_answer: str
    explanation: str | None = None
    questions_completed: int
    total_questions: int
    is_complete: bool
    next_question: QuestionResponse | None = None
    results: AssessmentResultsResponse | None = None
    assessment_phase: str = "concepts"


class AssessmentStateResponse(BaseModel):
    """Current state of an in-progress assessment."""

    assessment_id: str
    status: str
    competencies: list[str]
    questions_completed: int
    total_questions: int
    current_question: QuestionResponse | None = None
    assessment_phase: str = "concepts"
    primary_language: str | None = None


# --- Sessions ---


class SessionStartRequest(BaseModel):
    """Request to start a training session."""

    count: int = Field(5, ge=1, le=20)
    competency_slug: str | None = None
    question_format: str | None = None
    difficulty: int | None = Field(None, ge=1, le=5)
    question_id: str | None = None


class SessionStartResponse(BaseModel):
    """Response when starting a new session."""

    session_id: str
    target_count: int
    first_question: QuestionResponse


class SessionAnswerRequest(BaseModel):
    """Submit an answer during a session."""

    question_id: str
    answer_text: str
    time_seconds: float | None = None
    confidence: int | None = Field(None, ge=1, le=5)


class SessionQuestionResult(BaseModel):
    """Result for a single question in a session."""

    question_id: str
    title: str
    competency_slug: str
    format: str
    score: float | None = None
    time_seconds: float | None = None
    sequence_num: int


class SessionSummaryResponse(BaseModel):
    """Summary of a completed or ended session."""

    session_id: str
    status: str
    target_count: int
    completed_count: int
    avg_score: float | None = None
    results: list[SessionQuestionResult]
    started_at: str
    completed_at: str | None = None


class SessionAnswerResponse(BaseModel):
    """Response after answering a session question."""

    grade: GradeResponse
    completed_count: int
    target_count: int
    is_complete: bool
    next_question: QuestionResponse | None = None
    summary: SessionSummaryResponse | None = None


class SessionStateResponse(BaseModel):
    """Current state of an in-progress session, including the active question."""

    session_id: str
    status: str
    target_count: int
    completed_count: int
    current_question: QuestionResponse | None = None
    started_at: str
    competency_slug: str | None = None
    question_format: str | None = None
    difficulty: int | None = None


class SessionListItem(BaseModel):
    """Session summary for list views."""

    session_id: str
    status: str
    target_count: int
    completed_count: int
    avg_score: float | None = None
    started_at: str
    completed_at: str | None = None


# --- Reviews ---


class ReviewItemResponse(BaseModel):
    """A review queue item."""

    id: str
    question_id: str
    title: str
    competency_slug: str
    format: str
    difficulty: int
    source: str
    due_date: str
    interval_days: int
    review_count: int


class ReviewCountResponse(BaseModel):
    """Review queue counts."""

    due_today: int
    due_this_week: int
    total_pending: int


class ReviewCompleteRequest(BaseModel):
    """Mark a review item as completed."""

    quality: int = Field(ge=0, le=5)


class ReviewSnoozeRequest(BaseModel):
    """Snooze a review item."""

    days: int = Field(1, ge=1, le=30)


# --- Dashboard ---


class DashboardResponse(BaseModel):
    """Aggregated data for the Today page."""

    streak: StreakResponse
    review_due_count: int
    has_completed_assessment: bool
    focus_competency: str | None = None
    total_attempts: int
    competencies_assessed: int


# --- Enhanced Stats ---


class StreakCalendarResponse(BaseModel):
    """Contribution-style calendar data."""

    year: int
    month: int
    active_days: list[int]


class FormatPerformanceResponse(BaseModel):
    """Performance breakdown by format."""

    format: str
    total_attempts: int
    avg_score: float


class WeakAreaResponse(BaseModel):
    """A weak competency area."""

    competency_slug: str
    avg_score: float
    total_attempts: int


# --- Follow-up ---


class FollowupRequest(BaseModel):
    """Request a follow-up question based on a previous attempt."""

    attempt_id: str
    mode: str = "same_concept"

"""Sessions API router: workout/training session management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from swet_api.auth.dependencies import get_current_user
from swet_api.db import (
    add_session_result,
    complete_session,
    create_session,
    get_active_session,
    get_session,
    get_session_history,
    get_session_results,
    get_user_preferences,
    get_user_question,
    update_session_progress,
)
from swet_api.schemas import (
    AnswerRequest,
    QuestionResponse,
    SessionAnswerRequest,
    SessionAnswerResponse,
    SessionListItem,
    SessionQuestionResult,
    SessionStartRequest,
    SessionStartResponse,
    SessionStateResponse,
    SessionSummaryResponse,
)
from swet_api.services.attempt_service import grade_and_save
from swet_api.services.question_service import generate_single

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _build_summary(session: dict, results: list[dict]) -> SessionSummaryResponse:
    """Build a session summary from DB data."""
    scores = [r["score"] for r in results if r["score"] is not None]
    avg_score = sum(scores) / len(scores) if scores else None
    return SessionSummaryResponse(
        session_id=session["id"],
        status=session["status"],
        target_count=session["target_count"],
        completed_count=session["completed_count"],
        avg_score=avg_score,
        results=[
            SessionQuestionResult(
                question_id=r["question_id"],
                title=r["title"],
                competency_slug=r["competency_slug"],
                format=r["format"],
                score=r["score"],
                time_seconds=r["time_seconds"],
                sequence_num=r["sequence_num"],
            )
            for r in results
        ],
        started_at=session["started_at"],
        completed_at=session["completed_at"],
    )


@router.post("", response_model=SessionStartResponse, status_code=status.HTTP_201_CREATED)
def start_session(
    req: SessionStartRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> SessionStartResponse:
    """Start a new training session."""
    existing = get_active_session(user["id"])
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session {existing['id']} already in progress. End it first.",
        )

    prefs = get_user_preferences(user["id"])
    if prefs is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Set preferences first")

    session_id = create_session(
        user["id"],
        req.count,
        competency_slug=req.competency_slug,
        question_format=req.question_format,
        difficulty=req.difficulty,
    )

    # If a specific question_id was requested (e.g. from review), use it directly
    if req.question_id:
        q = get_user_question(user["id"], req.question_id)
        if q is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
        first_question = QuestionResponse(
            **{k: v for k, v in q.items() if k != "correct_answer"}
        )
    else:
        first_question = generate_single(
            user["id"],
            prefs,
            competency_slug=req.competency_slug,
            question_format=req.question_format,
            difficulty=req.difficulty,
        )
    update_session_progress(session_id, 0, first_question.id)

    return SessionStartResponse(
        session_id=session_id,
        target_count=req.count,
        first_question=first_question,
    )


@router.get("/current", response_model=SessionStateResponse | None)
def get_current_session(
    user: Annotated[dict, Depends(get_current_user)],
) -> SessionStateResponse | None:
    """Get the current in-progress session with the active question for resume."""
    session = get_active_session(user["id"])
    if session is None:
        return None

    # Fetch current question for resume
    current_question = None
    if session.get("current_question_id"):
        q = get_user_question(user["id"], session["current_question_id"])
        if q:
            current_question = QuestionResponse(
                **{k: v for k, v in q.items() if k != "correct_answer"}
            )

    return SessionStateResponse(
        session_id=session["id"],
        status=session["status"],
        target_count=session["target_count"],
        completed_count=session["completed_count"],
        current_question=current_question,
        started_at=session["started_at"],
        competency_slug=session.get("competency_slug"),
        question_format=session.get("question_format"),
        difficulty=session.get("difficulty"),
    )


@router.post("/{session_id}/answer", response_model=SessionAnswerResponse)
def answer_session_question(
    session_id: str,
    req: SessionAnswerRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> SessionAnswerResponse:
    """Answer the current session question and get the next one."""
    session = get_session(user["id"], session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session["status"] != "in_progress":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not in progress")

    # Grade via the shared attempt service
    answer_req = AnswerRequest(
        question_id=req.question_id,
        answer_text=req.answer_text,
        time_seconds=req.time_seconds,
        confidence=req.confidence,
    )
    try:
        grade_response, _ = grade_and_save(user["id"], answer_req)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # Track session result
    completed_count = session["completed_count"] + 1
    add_session_result(
        session_id, req.question_id, grade_response.attempt_id,
        grade_response.normalized_score, req.time_seconds, completed_count,
    )

    is_complete = completed_count >= session["target_count"]
    next_question: QuestionResponse | None = None
    summary: SessionSummaryResponse | None = None

    if is_complete:
        complete_session(session_id)
        updated_session = get_session(user["id"], session_id)
        results = get_session_results(session_id)
        summary = _build_summary(updated_session, results)
    else:
        prefs = get_user_preferences(user["id"])
        next_question = generate_single(
            user["id"],
            prefs,
            competency_slug=session.get("competency_slug"),
            question_format=session.get("question_format"),
            difficulty=session.get("difficulty"),
        )
        update_session_progress(session_id, completed_count, next_question.id)

    return SessionAnswerResponse(
        grade=grade_response,
        completed_count=completed_count,
        target_count=session["target_count"],
        is_complete=is_complete,
        next_question=next_question,
        summary=summary,
    )


@router.post("/{session_id}/end", response_model=SessionSummaryResponse)
def end_session(
    session_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> SessionSummaryResponse:
    """End a session early."""
    session = get_session(user["id"], session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session["status"] == "in_progress":
        complete_session(session_id)
    updated_session = get_session(user["id"], session_id)
    results = get_session_results(session_id)
    return _build_summary(updated_session, results)


@router.get("/history", response_model=list[SessionListItem])
def list_sessions(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 20,
) -> list[SessionListItem]:
    """List past sessions."""
    return [SessionListItem(**s) for s in get_session_history(user["id"], limit=limit)]


@router.get("/{session_id}", response_model=SessionSummaryResponse)
def get_session_detail(
    session_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> SessionSummaryResponse:
    """Get a past session's details."""
    session = get_session(user["id"], session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    results = get_session_results(session_id)
    return _build_summary(session, results)

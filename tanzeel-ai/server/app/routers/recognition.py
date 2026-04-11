"""Recognition endpoint - accepts audio, runs ASR + Quran matching."""

import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..dependencies import get_optional_user
from ..models.user import User
from ..models.recitation import Recitation, DailyProgress
from ..services.asr import transcribe_audio
from ..services.matcher import quran_matcher, MatchResult

router = APIRouter(prefix="/api", tags=["recognition"])

# In-memory IP-based daily rate limiter for guests
_guest_usage: dict[str, list[float]] = defaultdict(list)
_GUEST_WINDOW = 86_400  # 24 hours


def _check_guest_rate_limit(client_ip: str) -> None:
    """Raise 429 if guest IP exceeds daily recognition limit."""
    now = time.monotonic()
    entries = _guest_usage[client_ip]
    _guest_usage[client_ip] = [t for t in entries if now - t < _GUEST_WINDOW]
    if len(_guest_usage[client_ip]) >= settings.guest_daily_limit:
        raise HTTPException(
            status_code=429,
            detail="Daily guest limit reached. Create an account for unlimited access.",
        )


class MatchResponse(BaseModel):
    surah: int
    ayah: int
    surah_name_ar: str
    surah_name_en: str
    text: str
    score: float


class RecognitionResponse(BaseModel):
    id: str
    recognized_text: str
    top_match: MatchResponse | None
    alternatives: list[MatchResponse]
    created_at: str


def match_to_response(m: MatchResult) -> MatchResponse:
    return MatchResponse(
        surah=m.surah,
        ayah=m.ayah,
        surah_name_ar=m.surah_name_ar,
        surah_name_en=m.surah_name_en,
        text=m.text,
        score=round(m.score, 4),
    )


@router.post("/recognize", response_model=RecognitionResponse)
async def recognize_audio(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    # Validate file
    if not file.content_type or not file.content_type.startswith(("audio/", "application/octet-stream")):
        raise HTTPException(status_code=400, detail="File must be an audio file")

    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_audio_size_bytes:
        raise HTTPException(status_code=400, detail="Audio file too large (max 10MB)")

    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # Server-side guest rate limiting
    if current_user is None:
        client_ip = request.client.host if request.client else "unknown"
        _check_guest_rate_limit(client_ip)

    # Step 1: ASR transcription via RunPod
    try:
        asr_result = await transcribe_audio(audio_bytes)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ASR service error: {str(e)}")

    recognized_text = asr_result.get("text", "")
    if not recognized_text.strip():
        raise HTTPException(status_code=422, detail="No speech detected in the audio")

    # Step 2: Match against Quran corpus
    matches = quran_matcher.match(recognized_text, top_k=4)

    top_match = matches[0] if matches and matches[0].score >= 0.3 else None
    alternatives = matches[1:] if top_match else matches[:3]

    # Step 3: Save to history (if authenticated)
    recitation_id = uuid.uuid4()
    if current_user:
        today = date.today()

        # Check uniqueness BEFORE inserting the new recitation (avoids autoflush race)
        is_new_ayah = False
        if top_match:
            existing = await db.execute(
                select(func.count()).where(
                    Recitation.user_id == current_user.id,
                    Recitation.matched_surah == top_match.surah,
                    Recitation.matched_ayah == top_match.ayah,
                    func.date(Recitation.created_at) == today,
                )
            )
            is_new_ayah = existing.scalar() == 0

        recitation = Recitation(
            id=recitation_id,
            user_id=current_user.id,
            recognized_text=recognized_text,
            matched_surah=top_match.surah if top_match else None,
            matched_ayah=top_match.ayah if top_match else None,
            confidence=top_match.score if top_match else None,
        )
        db.add(recitation)

        # Update daily progress
        result = await db.execute(
            select(DailyProgress).where(
                DailyProgress.user_id == current_user.id,
                DailyProgress.date == today,
            )
        )
        daily = result.scalar_one_or_none()

        if daily:
            daily.recitation_count += 1
            if is_new_ayah:
                daily.unique_ayat_count += 1
        else:
            daily = DailyProgress(
                user_id=current_user.id,
                date=today,
                recitation_count=1,
                unique_ayat_count=1 if is_new_ayah else 0,
            )
            db.add(daily)

        await db.commit()
    else:
        # Record guest usage for rate limiting
        client_ip = request.client.host if request.client else "unknown"
        _guest_usage[client_ip].append(time.monotonic())

    return RecognitionResponse(
        id=str(recitation_id),
        recognized_text=recognized_text,
        top_match=match_to_response(top_match) if top_match else None,
        alternatives=[match_to_response(a) for a in alternatives],
        created_at=datetime.now(timezone.utc).isoformat(),
    )

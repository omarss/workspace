"""Progress tracking endpoints."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import get_current_user
from ..models.user import User
from ..models.recitation import Recitation, DailyProgress
from ..services.matcher import quran_matcher

router = APIRouter(prefix="/api/progress", tags=["progress"])


class ProgressSummary(BaseModel):
    total_recitations: int
    unique_ayat: int
    current_streak: int
    today_count: int


class DailyActivity(BaseModel):
    date: str
    count: int


class MatchInfo(BaseModel):
    surah: int
    ayah: int
    surah_name_ar: str
    surah_name_en: str
    text: str
    score: float


class HistoryItem(BaseModel):
    id: str
    recognized_text: str
    top_match: MatchInfo | None
    alternatives: list[MatchInfo]
    created_at: str


@router.get("/summary", response_model=ProgressSummary)
async def get_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Total recitations
    total_result = await db.execute(
        select(func.count()).where(Recitation.user_id == current_user.id)
    )
    total_recitations = total_result.scalar() or 0

    # Unique ayat (distinct surah:ayah pairs)
    unique_result = await db.execute(
        select(func.count(func.distinct(
            func.concat(Recitation.matched_surah, ":", Recitation.matched_ayah)
        ))).where(
            Recitation.user_id == current_user.id,
            Recitation.matched_surah.is_not(None),
        )
    )
    unique_ayat = unique_result.scalar() or 0

    # Today's count
    today = date.today()
    today_result = await db.execute(
        select(DailyProgress.recitation_count).where(
            DailyProgress.user_id == current_user.id,
            DailyProgress.date == today,
        )
    )
    today_count = today_result.scalar() or 0

    # Current streak — fetch all active dates in one query, iterate in memory
    streak = 0
    streak_result = await db.execute(
        select(DailyProgress.date)
        .where(
            DailyProgress.user_id == current_user.id,
            DailyProgress.recitation_count > 0,
        )
        .order_by(DailyProgress.date.desc())
    )
    active_dates = {row[0] for row in streak_result.all()}
    check_date = today
    while check_date in active_dates:
        streak += 1
        check_date -= timedelta(days=1)

    return ProgressSummary(
        total_recitations=total_recitations,
        unique_ayat=unique_ayat,
        current_streak=streak,
        today_count=today_count,
    )


@router.get("/history", response_model=list[HistoryItem])
async def get_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    result = await db.execute(
        select(Recitation)
        .where(Recitation.user_id == current_user.id)
        .order_by(desc(Recitation.created_at))
        .offset(offset)
        .limit(limit)
    )
    recitations = result.scalars().all()

    items: list[HistoryItem] = []
    for r in recitations:
        top_match = None
        if r.matched_surah is not None and r.matched_ayah is not None:
            ayah_info = quran_matcher.get_ayah_info(r.matched_surah, r.matched_ayah)
            if ayah_info:
                top_match = MatchInfo(
                    surah=r.matched_surah,
                    ayah=r.matched_ayah,
                    surah_name_ar=ayah_info.surah_name_ar,
                    surah_name_en=ayah_info.surah_name_en,
                    text=ayah_info.text,
                    score=r.confidence or 0.0,
                )
        items.append(HistoryItem(
            id=str(r.id),
            recognized_text=r.recognized_text,
            top_match=top_match,
            alternatives=[],
            created_at=r.created_at.isoformat(),
        ))
    return items


@router.get("/heatmap", response_model=list[DailyActivity])
async def get_heatmap(
    days: int = Query(90, ge=7, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start_date = date.today() - timedelta(days=days)
    result = await db.execute(
        select(DailyProgress)
        .where(
            DailyProgress.user_id == current_user.id,
            DailyProgress.date >= start_date,
        )
        .order_by(DailyProgress.date)
    )
    entries = result.scalars().all()

    return [
        DailyActivity(
            date=entry.date.isoformat(),
            count=entry.recitation_count,
        )
        for entry in entries
    ]

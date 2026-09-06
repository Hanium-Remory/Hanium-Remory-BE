"""감정 추이·현재 감정 조회. (감정 기록 저장은 기기 담당)"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import EmotionRecord, Protector
from ..services.access import emotion_json, get_owned_user
from ..services.kst import day_bounds

router = APIRouter(tags=["emotions"])


@router.get("/users/{user_id}/emotions")
def list_emotions(
    user_id: int,
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD (한국 시간 기준)"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """감정 추이 조회 (최신순). 감정 상태 모니터링 그래프용.

    ?date= 를 주면 그 하루치만 준다. 리포트 화면이 '그날의 감정 흐름' 을
    그릴 때 쓰며, 없으면 예전처럼 전부 준다.
    """
    user = get_owned_user(db, protector, user_id)

    query = select(EmotionRecord).where(EmotionRecord.user_id == user.id)
    if date is not None:
        try:
            day = dt.date.fromisoformat(date)
        except ValueError:
            raise APIError(400, "date 는 YYYY-MM-DD 형식이어야 합니다.")
        start, end = day_bounds(day)
        query = query.where(
            EmotionRecord.created_at >= start, EmotionRecord.created_at < end
        )

    records = db.scalars(query.order_by(EmotionRecord.created_at.desc())).all()
    return envelope([emotion_json(r) for r in records], "OK", 200)


@router.get("/users/{user_id}/emotions/current")
def get_current_emotion(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """현재(가장 최근) 감정 조회."""
    user = get_owned_user(db, protector, user_id)
    record = db.scalars(
        select(EmotionRecord)
        .where(EmotionRecord.user_id == user.id)
        .order_by(EmotionRecord.created_at.desc())
    ).first()
    # 기록이 아직 없는 건 정상 상황이므로 404 대신 null.
    if record is None:
        return envelope(None, "감정 기록이 아직 없습니다.", 200)
    return envelope(emotion_json(record), "OK", 200)

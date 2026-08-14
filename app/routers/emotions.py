"""감정 추이·현재 감정 조회. (감정 기록 저장은 기기 담당)"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import envelope
from ..models import EmotionRecord, Protector
from ..services.access import emotion_json, get_owned_user

router = APIRouter(tags=["emotions"])


@router.get("/users/{user_id}/emotions")
def list_emotions(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """감정 추이 조회 (최신순). 감정 상태 모니터링 그래프용."""
    user = get_owned_user(db, protector, user_id)
    records = db.scalars(
        select(EmotionRecord)
        .where(EmotionRecord.user_id == user.id)
        .order_by(EmotionRecord.created_at.desc())
    ).all()
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

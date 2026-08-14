"""활동 타임라인 조회. (활동 로그 저장은 기기 담당)"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import envelope
from ..models import ActivityLog, Protector
from ..services.access import activity_json, get_owned_user

router = APIRouter(tags=["activities"])


@router.get("/users/{user_id}/activities")
def list_activities(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """활동 타임라인 조회 (최신순)."""
    user = get_owned_user(db, protector, user_id)
    logs = db.scalars(
        select(ActivityLog)
        .where(ActivityLog.user_id == user.id)
        .order_by(ActivityLog.created_at.desc())
    ).all()
    return envelope([activity_json(a) for a in logs], "OK", 200)

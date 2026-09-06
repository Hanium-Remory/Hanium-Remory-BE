"""활동 타임라인 조회. (활동 로그 저장은 기기 담당)"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import ActivityLog, Protector
from ..services.access import activity_json, get_owned_user
from ..services.kst import day_bounds

router = APIRouter(tags=["activities"])


@router.get("/users/{user_id}/activities")
def list_activities(
    user_id: int,
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD (한국 시간 기준)"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """활동 타임라인 조회 (최신순).

    ?date= 를 주면 그 하루치만 준다. 리포트 화면이 '그날의 일과'를 보여줄 때
    쓰며, 없으면 예전처럼 전부 준다(홈 타임라인).
    """
    user = get_owned_user(db, protector, user_id)

    query = select(ActivityLog).where(ActivityLog.user_id == user.id)
    if date is not None:
        try:
            day = dt.date.fromisoformat(date)
        except ValueError:
            raise APIError(400, "date 는 YYYY-MM-DD 형식이어야 합니다.")
        start, end = day_bounds(day)
        query = query.where(
            ActivityLog.created_at >= start, ActivityLog.created_at < end
        )

    logs = db.scalars(query.order_by(ActivityLog.created_at.desc())).all()
    return envelope([activity_json(a) for a in logs], "OK", 200)

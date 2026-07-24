"""데일리·주간 리포트 조회. (리포트 생성은 배치/다른 담당)

참고: 명세의 ?date=, ?weekStart= 필터는 아직 미구현이라
      우선 '가장 최근 리포트'를 돌려준다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import envelope
from ..models import DailyReport, Protector, WeeklyReport
from ..services.access import daily_report_json, get_owned_user, weekly_report_json

router = APIRouter(tags=["reports"])


@router.get("/users/{user_id}/reports/daily")
def get_daily_report(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """데일리 리포트 조회 (가장 최근)."""
    user = get_owned_user(db, protector, user_id)
    report = db.scalars(
        select(DailyReport)
        .where(DailyReport.user_id == user.id)
        .order_by(DailyReport.created_at.desc())
    ).first()
    if report is None:
        return envelope(None, "리포트가 아직 없습니다.", 200)
    return envelope(daily_report_json(report), "OK", 200)


@router.get("/users/{user_id}/reports/weekly")
def get_weekly_report(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """주간 리포트 조회 (가장 최근)."""
    user = get_owned_user(db, protector, user_id)
    report = db.scalars(
        select(WeeklyReport)
        .where(WeeklyReport.user_id == user.id)
        .order_by(WeeklyReport.created_at.desc())
    ).first()
    if report is None:
        return envelope(None, "리포트가 아직 없습니다.", 200)
    return envelope(weekly_report_json(report), "OK", 200)

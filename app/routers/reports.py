"""데일리·주간 리포트 조회. (리포트 생성은 배치/다른 담당)

앱의 < > 이동을 위해 ?offset= 을 받는다. 0 이 가장 최근이고, 1 씩 늘릴수록
한 칸씩 이전 리포트를 준다. 더 없으면 data 가 null 이라 앱이 끝을 알 수 있다.

참고: 명세의 ?date=, ?weekStart= 는 아직 미구현이다.
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
    offset: int = 0,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """데일리 리포트 조회. offset=0 이 가장 최근, 1 이 그 전날치."""
    user = get_owned_user(db, protector, user_id)
    report = db.scalars(
        select(DailyReport)
        .where(DailyReport.user_id == user.id)
        # '어느 날의 요약인지' 로 줄 세운다. 만들어진 시각으로 세우면 과거
        # 날짜를 다시 만들었을 때 그것이 맨 앞에 와서, 앱이 '오늘' 자리에
        # 며칠 전 리포트를 보여준다.
        # 날짜를 모르는 예전 행은 뒤로 보낸다(NULL 은 기본이 앞이다).
        .order_by(
            DailyReport.report_date.desc().nullslast(),
            DailyReport.created_at.desc(),
        )
        .offset(max(offset, 0))
        .limit(1)
    ).first()
    if report is None:
        return envelope(None, "리포트가 아직 없습니다.", 200)
    return envelope(daily_report_json(report), "OK", 200)


@router.get("/users/{user_id}/reports/weekly")
def get_weekly_report(
    user_id: int,
    offset: int = 0,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """주간 리포트 조회. offset=0 이 가장 최근, 1 이 그 전주치."""
    user = get_owned_user(db, protector, user_id)
    report = db.scalars(
        select(WeeklyReport)
        .where(WeeklyReport.user_id == user.id)
        # 데일리와 같은 이유로 '어느 주인지' 로 줄 세운다.
        .order_by(
            WeeklyReport.week_start.desc().nullslast(),
            WeeklyReport.created_at.desc(),
        )
        .offset(max(offset, 0))
        .limit(1)
    ).first()
    if report is None:
        return envelope(None, "리포트가 아직 없습니다.", 200)
    return envelope(weekly_report_json(report), "OK", 200)

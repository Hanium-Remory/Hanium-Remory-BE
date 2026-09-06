"""데일리·주간 리포트 조회. (리포트 생성은 배치/다른 담당)

앱의 < > 이동을 위해 ?offset= 을 받는다. 0 이 가장 최근이고, 1 씩 늘릴수록
한 칸씩 이전 리포트를 준다. 더 없으면 data 가 null 이라 앱이 끝을 알 수 있다.

달력에서 날짜를 골라 올 때는 ?date= 를 쓴다. 그리고 달력이 어느 날에 점을
찍을지 알아야 해서, 리포트가 있는 날 목록을 따로 준다(/reports/daily/dates).
"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import DailyReport, Protector, WeeklyReport
from ..services.access import daily_report_json, get_owned_user, weekly_report_json

router = APIRouter(tags=["reports"])


@router.get("/users/{user_id}/reports/daily/dates")
def list_daily_report_dates(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """리포트가 있는 날들(오래된 순).

    달력이 어느 날에 점을 찍을지 정하는 데 쓴다. 날짜만 주므로 가벼워서
    달을 넘길 때마다 다시 묻지 않아도 된다.
    """
    user = get_owned_user(db, protector, user_id)
    days = db.scalars(
        select(DailyReport.report_date)
        .where(DailyReport.user_id == user.id, DailyReport.report_date.isnot(None))
        .order_by(DailyReport.report_date)
    ).all()
    return envelope([d.isoformat() for d in days], "OK", 200)


@router.get("/users/{user_id}/reports/daily")
def get_daily_report(
    user_id: int,
    offset: int = 0,
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD. 주면 그날 것을 준다"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """데일리 리포트 조회.

    ?date= 를 주면 그날 것을, 없으면 offset 으로 센다(0 이 가장 최근).
    달력에서 고른 날은 '몇 번째로 최근인지' 를 앱이 알 수 없어 날짜로 묻는다.
    """
    user = get_owned_user(db, protector, user_id)

    if date is not None:
        try:
            day = dt.date.fromisoformat(date)
        except ValueError:
            raise APIError(400, "date 는 YYYY-MM-DD 형식이어야 합니다.")
        report = db.scalars(
            select(DailyReport).where(
                DailyReport.user_id == user.id, DailyReport.report_date == day
            )
        ).first()
        if report is None:
            return envelope(None, "그날 리포트가 없습니다.", 200)
        return envelope(daily_report_json(report), "OK", 200)

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

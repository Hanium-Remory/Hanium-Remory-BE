"""리포트를 '어느 날/어느 주인지' 로 줄 세우는지.

만들어진 시각으로 세우면 과거 것을 다시 만들었을 때 그것이 맨 앞에 온다.
실제로 프로덕션에서 앱이 '이번 주' 자리에 지지난 주 리포트를 보여줬다.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import DailyReport, FamilyMember, Protector, User, WeeklyReport
from app.security import create_access_token

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


client = TestClient(app)


@pytest.fixture
def world():
    db = TestSession()
    try:
        me = Protector(phone_number="01011112222", display_name="김지영", user_handle=b"h1")
        db.add(me)
        db.flush()
        user = User(name="김순자", gender="female", birth_date=dt.date(1948, 2, 1))
        db.add(user)
        db.flush()
        db.add(FamilyMember(user_id=user.id, protector_id=me.id, is_primary=True))
        db.commit()
        return {"me": me.id, "user": user.id}
    finally:
        db.close()


def auth(pid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(pid)}"}


def get(world, kind: str, offset: int):
    r = client.get(
        f"/users/{world['user']}/reports/{kind}?offset={offset}",
        headers=auth(world["me"]),
    )
    assert r.status_code < 400, r.text
    return r.json()["data"]


NOW = dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc)


def test_daily_newest_day_comes_first_even_if_made_later(world):
    """9월 6일치를 먼저 만들고 9월 1일치를 나중에 만들어도, 최신은 9월 6일이다."""
    db = TestSession()
    try:
        db.add(DailyReport(
            user_id=world["user"], report_date=dt.date(2026, 9, 6),
            summary="6일", created_at=NOW - dt.timedelta(hours=2),
        ))
        db.add(DailyReport(                       # 나중에 만들어진 과거 날짜
            user_id=world["user"], report_date=dt.date(2026, 9, 1),
            summary="1일", created_at=NOW,
        ))
        db.commit()
    finally:
        db.close()

    assert get(world, "daily", 0)["summary"] == "6일"
    assert get(world, "daily", 1)["summary"] == "1일"


def test_weekly_newest_week_comes_first_even_if_made_later(world):
    db = TestSession()
    try:
        db.add(WeeklyReport(
            user_id=world["user"], week_start=dt.date(2026, 8, 31),
            weekly_summary="8/31 주", created_at=NOW - dt.timedelta(hours=2),
        ))
        db.add(WeeklyReport(                      # 나중에 만들어진 이전 주
            user_id=world["user"], week_start=dt.date(2026, 8, 24),
            weekly_summary="8/24 주", created_at=NOW,
        ))
        db.commit()
    finally:
        db.close()

    assert get(world, "weekly", 0)["weeklySummary"] == "8/31 주"
    assert get(world, "weekly", 1)["weeklySummary"] == "8/24 주"


def test_reports_without_a_date_go_last(world):
    """날짜를 모르는 예전 행이 맨 앞에 오면 안 된다(NULL 은 기본이 앞이다)."""
    db = TestSession()
    try:
        db.add(DailyReport(
            user_id=world["user"], report_date=None,
            summary="날짜 모름", created_at=NOW,
        ))
        db.add(DailyReport(
            user_id=world["user"], report_date=dt.date(2026, 9, 1),
            summary="1일", created_at=NOW - dt.timedelta(days=5),
        ))
        db.commit()
    finally:
        db.close()

    assert get(world, "daily", 0)["summary"] == "1일"
    assert get(world, "daily", 1)["summary"] == "날짜 모름"


# ── 달력에서 날짜로 골라 오기 ─────────────────────────
def _seed_days(world, days: list[dt.date]) -> None:
    db = TestSession()
    try:
        for d in days:
            db.add(DailyReport(
                user_id=world["user"], report_date=d, summary=f"{d.day}일",
                created_at=NOW,
            ))
        db.commit()
    finally:
        db.close()


def test_a_day_can_be_asked_for_by_date(world):
    """달력에서 고른 날은 '몇 번째로 최근인지' 를 앱이 알 수 없다."""
    _seed_days(world, [dt.date(2026, 9, 1), dt.date(2026, 9, 5)])
    r = client.get(
        f"/users/{world['user']}/reports/daily?date=2026-09-01",
        headers=auth(world["me"]),
    )
    assert r.json()["data"]["summary"] == "1일"


def test_a_day_without_a_report_is_not_an_error(world):
    """달력에서 점 없는 날을 눌러도 화면이 깨지면 안 된다."""
    _seed_days(world, [dt.date(2026, 9, 1)])
    r = client.get(
        f"/users/{world['user']}/reports/daily?date=2026-09-02",
        headers=auth(world["me"]),
    )
    assert r.status_code == 200
    assert r.json()["data"] is None


def test_bad_date_is_rejected(world):
    r = client.get(
        f"/users/{world['user']}/reports/daily?date=2026-13-99",
        headers=auth(world["me"]),
    )
    assert r.status_code == 400


def test_dates_tell_the_calendar_where_to_put_dots(world):
    _seed_days(world, [dt.date(2026, 9, 5), dt.date(2026, 9, 1), dt.date(2026, 8, 30)])
    r = client.get(
        f"/users/{world['user']}/reports/daily/dates", headers=auth(world["me"])
    )
    assert r.json()["data"] == ["2026-08-30", "2026-09-01", "2026-09-05"]


def test_dates_leave_out_rows_without_a_date(world):
    db = TestSession()
    try:
        db.add(DailyReport(user_id=world["user"], report_date=None, summary="x",
                           created_at=NOW))
        db.commit()
    finally:
        db.close()
    _seed_days(world, [dt.date(2026, 9, 1)])

    r = client.get(
        f"/users/{world['user']}/reports/daily/dates", headers=auth(world["me"])
    )
    assert r.json()["data"] == ["2026-09-01"]

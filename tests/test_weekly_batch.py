"""주간 배치 — 주 경계, 데일리 합산, 긴급 알림 세기, 다시 돌려도 안전한지."""

import datetime as dt
import os
import sys

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import generate_weekly_reports as batch  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    DailyReport,
    EmotionRecord,
    FamilyMember,
    Notification,
    Protector,
    User,
    Utterance,
)
from app.services.kst import KST, today, week_bounds, week_start_of  # noqa: E402
from app.services.notifications import TYPE_REPORT, TYPE_URGENT  # noqa: E402

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# 2026-08-31 은 월요일. 그 주는 8/31 ~ 9/6 이다.
MONDAY = dt.date(2026, 8, 31)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# ── 주 경계 ──────────────────────────────────────────
def test_week_starts_on_monday():
    assert week_start_of(dt.date(2026, 9, 6)) == MONDAY   # 일요일 → 그 주 월요일
    assert week_start_of(MONDAY) == MONDAY                # 월요일은 그대로
    assert week_start_of(dt.date(2026, 9, 7)) == dt.date(2026, 9, 7)  # 다음 월요일


def test_week_bounds_cover_seven_kst_days():
    start, end = week_bounds(MONDAY)
    assert start == dt.datetime(2026, 8, 31, tzinfo=KST).astimezone(dt.timezone.utc)
    assert end == dt.datetime(2026, 9, 7, tzinfo=KST).astimezone(dt.timezone.utc)
    assert (end - start).days == 7


# ── 긴급 알림 세기 ───────────────────────────────────
def test_urgent_alerts_are_counted_once_per_event(db):
    """알림은 보호자마다 한 줄씩 생기지만 사건은 한 번이다."""
    user = User(id=1, name="박순자")
    db.add(user)
    when = dt.datetime(2026, 9, 1, 3, 0, tzinfo=dt.timezone.utc)
    # 한 사건이 보호자 둘에게 간 모양
    db.add_all(
        [
            Notification(
                protector_id=p,
                user_id=1,
                type=TYPE_URGENT,
                title="감정이 평소와 달라요",
                content="x",
                created_at=when,
            )
            for p in (1, 2)
        ]
    )
    # 리포트 알림은 긴급이 아니라 안 세어야 한다
    db.add(
        Notification(
            protector_id=1,
            user_id=1,
            type=TYPE_REPORT,
            title="오늘의 데일리 리포트가 준비됐어요",
            content="x",
            created_at=when,
        )
    )
    db.commit()

    start, end = week_bounds(MONDAY)
    assert batch.count_urgent_alerts(db, 1, start, end) == 1


def test_one_event_counts_once_even_when_timestamps_drift(db):
    """실제로 알림을 만들어 본다.

    줄마다 created_at 기본값이 따로 매겨져 마이크로초가 어긋난다. 손으로
    같은 시각을 넣어 만든 테스트는 이걸 못 잡았고, 그래서 한 사건이 두 번으로
    세어지고 있었다.
    """
    from app.services import notifications as notif

    user = User(id=1, name="박순자")
    db.add(user)
    db.add_all([
        Protector(id=1, phone_number="01011112222", display_name="김지영", user_handle=b"h1"),
        Protector(id=2, phone_number="01033334444", display_name="김민수", user_handle=b"h2"),
    ])
    db.flush()
    db.add_all([
        FamilyMember(user_id=1, protector_id=1, is_primary=True),
        FamilyMember(user_id=1, protector_id=2),
    ])
    db.commit()

    made = notif.notify_self_harm(db, 1, "이제 그만 죽고 싶어")
    assert made == 2                      # 보호자 둘에게 한 줄씩

    stamps = {n.created_at for n in db.scalars(select(Notification)).all()}
    assert len(stamps) == 2, "두 줄의 시각이 같으면 이 테스트가 의미가 없다"

    start, end = week_bounds(week_start_of(today()))
    assert batch.count_urgent_alerts(db, 1, start, end) == 1


def test_urgent_alerts_outside_the_week_are_ignored(db):
    db.add(User(id=1, name="박순자"))
    db.add(
        Notification(
            protector_id=1,
            user_id=1,
            type=TYPE_URGENT,
            title="감정이 평소와 달라요",
            content="x",
            # 그 주 월요일 00:00 KST 직전 = 지난주
            created_at=dt.datetime(2026, 8, 30, 23, 0, tzinfo=KST).astimezone(
                dt.timezone.utc
            ),
        )
    )
    db.commit()

    start, end = week_bounds(MONDAY)
    assert batch.count_urgent_alerts(db, 1, start, end) == 0


# ── 기본 문구 ────────────────────────────────────────
def test_summary_mentions_what_happened():
    text = batch.build_summary("박순자", 12, 3, "평온해요", 1)
    assert "박순자님은 이번 주 인형과 12번 이야기, 가족과 3번 소통하셨어요." in text
    assert "평온해요" in text
    assert "긴급 알림이 1번" in text


def test_summary_of_a_quiet_week_stays_plain():
    text = batch.build_summary("박순자", 0, 0, None, 0)
    assert text == "박순자님의 이번 주 대화 기록은 없었어요."


# ── 감정 점수 ────────────────────────────────────────
def test_emotion_scores_match_the_app_graph():
    """앱 그래프 높이(_emotionHeights)와 같은 기준이어야 두 화면이 같은 말을 한다."""
    assert batch.EMOTION_SCORES == {
        "happy": 85,
        "calm": 65,
        "lonely": 40,
        "anxious": 32,
        "sad": 25,
        "angry": 20,
    }


# ── 발화를 언제 지우는가 ─────────────────────────────
def _utterance(db, when: dt.datetime) -> None:
    db.add(Utterance(user_id=1, speaker="user", content="이야기", created_at=when))


def test_purge_takes_everything_up_to_the_week_end(db):
    """리포트로 옮겨 담았으니 그 주 발화는 지운다.

    지난주에 배치가 걸렀더라도 이번에 따라잡도록, 그보다 이전 것도 함께 치운다.
    """
    db.add(User(id=1, name="박순자"))
    start, end = week_bounds(MONDAY)
    _utterance(db, start - dt.timedelta(days=30))    # 훨씬 이전 (걸렀던 것)
    _utterance(db, start + dt.timedelta(days=1))     # 그 주
    _utterance(db, end + dt.timedelta(hours=1))      # 다음 주 — 남아야 한다
    db.commit()

    assert batch.purge_utterances_before(db, end) == 2
    left = db.scalars(select(Utterance)).all()
    assert len(left) == 1
    assert left[0].created_at.replace(tzinfo=dt.timezone.utc) > end


def test_nothing_to_purge_is_fine(db):
    db.add(User(id=1, name="박순자"))
    db.commit()
    _, end = week_bounds(MONDAY)
    assert batch.purge_utterances_before(db, end) == 0

"""데일리 배치의 발화 처리 — 대화 글 조립과 보관 기간 지난 발화 삭제."""

import datetime as dt
import os
import sys

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import generate_daily_reports as batch  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import User, Utterance  # noqa: E402

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _utterance(speaker: str, content: str, when: dt.datetime = None) -> Utterance:
    return Utterance(
        user_id=1,
        speaker=speaker,
        content=content,
        created_at=when or dt.datetime.now(dt.timezone.utc),
    )


# ── 대화 글 조립 ─────────────────────────────────────
def test_transcript_labels_both_sides():
    rows = [
        _utterance("user", "밥은 먹었다"),
        _utterance("mori", "잘하셨어요."),
    ]
    assert batch.build_transcript(rows) == "어르신: 밥은 먹었다\n모리: 잘하셨어요."


def test_transcript_skips_blank_lines():
    rows = [_utterance("user", "   "), _utterance("mori", "네.")]
    assert batch.build_transcript(rows) == "모리: 네."


def test_transcript_keeps_the_most_recent_lines():
    rows = [_utterance("user", f"{i}번째 말") for i in range(batch.TRANSCRIPT_MAX_LINES + 10)]
    lines = batch.build_transcript(rows).split("\n")
    assert len(lines) == batch.TRANSCRIPT_MAX_LINES
    assert lines[-1] == f"어르신: {batch.TRANSCRIPT_MAX_LINES + 9}번째 말"


def test_transcript_of_nothing_is_empty():
    assert batch.build_transcript([]) == ""


# ── 보관 기간 ────────────────────────────────────────
def test_purge_drops_only_what_aged_out(db):
    db.add(User(id=1, name="박순자"))
    now = dt.datetime.now(dt.timezone.utc)
    db.add_all(
        [
            _utterance("user", "여드레 전", now - dt.timedelta(days=8)),
            _utterance("mori", "이레하고 조금 전", now - dt.timedelta(days=7, hours=1)),
            _utterance("user", "엿새 전", now - dt.timedelta(days=6)),
            _utterance("mori", "방금"),
        ]
    )
    db.commit()
    # 배치는 리포트를 만들며 발화를 이미 읽어 둔 채로 삭제에 들어간다.
    # SQLite 에서 읽은 값은 시간대가 없어서, 그 상태를 똑같이 만들어야
    # 삭제 조건을 파이썬에서 비교할 때 터지는 문제가 드러난다.
    db.expunge_all()
    db.scalars(select(Utterance)).all()

    assert batch.purge_old_utterances(db, 7) == 2

    left = db.scalars(select(Utterance.content).order_by(Utterance.id)).all()
    assert left == ["엿새 전", "방금"]

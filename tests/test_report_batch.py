"""데일리 배치의 발화 처리 — 대화 글 조립과 보관 기간 지난 발화 삭제."""

import datetime as dt
import json
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


# ── 대화 발췌 ────────────────────────────────────────
def _pair(user_text: str, mori_text: str, minute: int) -> list:
    at = dt.datetime(2026, 9, 6, 9, minute, tzinfo=dt.timezone.utc)
    return [
        _utterance("user", user_text, at),
        _utterance("mori", mori_text, at + dt.timedelta(seconds=20)),
    ]


def test_excerpt_leaves_out_mere_acknowledgements():
    """'응', '그래' 는 가족이 읽어도 그날에 대해 알 수 있는 게 없다.

    길이순으로 고르는 것만으로는 안 걸러진다. 대화가 세 번뿐인 날이면
    맞장구도 상위 세 개에 들어와 버린다.
    """
    rows = (
        _pair("응", "네, 어르신.", 0)
        + _pair("오늘 무릎이 시큰거려서 병원에 다녀왔어", "다행이에요.", 10)
        + _pair("그래", "네.", 20)
    )
    picked = json.loads(batch.build_excerpt(rows))
    assert [t["user"] for t in picked] == ["오늘 무릎이 시큰거려서 병원에 다녀왔어"]
    assert picked[0]["mori"] == "다행이에요."
    assert picked[0]["at"]


def test_excerpt_keeps_time_order():
    """고를 때는 길이로 고르지만, 담을 때는 그날 흐름대로 되돌린다."""
    rows = (
        _pair("가" * 30, "네.", 0)
        + _pair("나" * 60, "네.", 10)
        + _pair("다" * 45, "네.", 20)
    )
    picked = json.loads(batch.build_excerpt(rows))
    assert [t["user"][0] for t in picked] == ["가", "나", "다"]


def test_excerpt_holds_at_most_a_few_turns():
    rows = []
    for i in range(10):
        rows += _pair(f"{i}번째로 길게 드린 말씀입니다", "네.", i)
    picked = json.loads(batch.build_excerpt(rows))
    assert len(picked) == batch.EXCERPT_MAX_TURNS


def test_long_lines_are_trimmed():
    rows = _pair("말" * 300, "답" * 300, 0)
    picked = json.loads(batch.build_excerpt(rows))
    assert len(picked[0]["user"]) == batch.EXCERPT_MAX_CHARS
    assert picked[0]["user"].endswith("…")


def test_a_turn_without_a_reply_still_counts():
    """모리가 답하기 전에 대화가 끊겼어도 어르신 말은 남긴다."""
    rows = [_utterance("user", "오늘은 좀 쓸쓸하네",
                       dt.datetime(2026, 9, 6, 9, 0, tzinfo=dt.timezone.utc))]
    picked = json.loads(batch.build_excerpt(rows))
    assert picked[0]["user"] == "오늘은 좀 쓸쓸하네"
    assert picked[0]["mori"] == ""


def test_no_utterances_means_no_excerpt():
    assert batch.build_excerpt([]) is None
    assert batch.build_excerpt([_utterance("user", "   ")]) is None


def test_a_day_of_only_short_replies_has_no_excerpt():
    """보여줄 게 없으면 비운다. 없는 이야기를 지어내지 않는다."""
    rows = _pair("응", "네.", 0) + _pair("그래", "네.", 10)
    assert batch.build_excerpt(rows) is None

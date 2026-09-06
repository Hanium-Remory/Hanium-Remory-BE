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


# ── 오늘 나눈 이야기 ─────────────────────────────────
def _pair(user_text: str, mori_text: str, minute: int) -> list:
    at = dt.datetime(2026, 9, 6, 9, minute, tzinfo=dt.timezone.utc)
    return [
        _utterance("user", user_text, at),
        _utterance("mori", mori_text, at + dt.timedelta(seconds=20)),
    ]


def test_model_picks_and_tidies_the_lines(monkeypatch):
    """받아쓰기 오타는 바로잡되 말투는 그대로 둔다."""
    monkeypatch.setattr(
        batch, "write_conversation_excerpt",
        # 번호는 맞장구를 걸러낸 후보 목록 기준이다. "응" 은 후보가 아니므로 1번.
        lambda name, numbered: [
            {"no": 1, "user": "오늘 무릎이 시큰거려서 병원에 다녀왔어", "mori": "다행이에요."}
        ],
    )
    rows = _pair("응", "네.", 0) + _pair("오늘 무릅이 시큰거려서 병원에 다녀왔어", "다행이에요.", 10)
    picked = json.loads(batch.build_excerpt("김순자", rows))

    assert len(picked) == 1
    assert picked[0]["user"] == "오늘 무릎이 시큰거려서 병원에 다녀왔어"   # 무릅 → 무릎
    assert picked[0]["mori"] == "다행이에요."


def test_time_comes_from_the_record_not_the_model(monkeypatch):
    """모델이 시각을 지어낼 자리를 없앤다. 번호만 고르게 하고 시각은 원본에서 온다."""
    monkeypatch.setattr(
        batch, "write_conversation_excerpt",
        lambda name, numbered: [
            {"no": 1, "user": "손녀가 온다더라", "mori": "네.", "at": "1999-01-01T00:00:00+00:00"}
        ],
    )
    rows = _pair("손녀가 다음 주에 온다더라", "기다려지시겠어요.", 30)
    picked = json.loads(batch.build_excerpt("김순자", rows))
    assert picked[0]["at"].startswith("2026-09-06T09:30")


def test_a_made_up_number_is_ignored(monkeypatch):
    """모델이 없는 번호를 주면 버리고 규칙으로 고른다."""
    monkeypatch.setattr(
        batch, "write_conversation_excerpt",
        lambda name, numbered: [{"no": 99, "user": "없는 말", "mori": ""}],
    )
    rows = _pair("손녀가 다음 주에 온다더라", "기다려지시겠어요.", 0)
    picked = json.loads(batch.build_excerpt("김순자", rows))
    assert picked[0]["user"] == "손녀가 다음 주에 온다더라"


def test_falls_back_to_the_longest_lines_without_a_model(monkeypatch):
    """모델을 못 불러도 빈 자리로 두지 않는다."""
    monkeypatch.setattr(batch, "write_conversation_excerpt", lambda name, numbered: None)
    rows = (
        _pair("응", "네.", 0)
        + _pair("손녀가 다음 주에 온다더라", "기다려지시겠어요.", 10)
    )
    picked = json.loads(batch.build_excerpt("김순자", rows))
    assert [p["user"] for p in picked] == ["손녀가 다음 주에 온다더라"]


def test_fallback_keeps_time_order(monkeypatch):
    monkeypatch.setattr(batch, "write_conversation_excerpt", lambda name, numbered: None)
    rows = _pair("가" * 30, "네.", 0) + _pair("나" * 60, "네.", 10) + _pair("다" * 45, "네.", 20)
    picked = json.loads(batch.build_excerpt("김순자", rows))
    assert [p["user"][0] for p in picked] == ["가", "나", "다"]


def test_only_acknowledgements_means_nothing_to_show(monkeypatch):
    """보여줄 게 없으면 비운다. 모델을 부르지도 않는다."""
    called = []
    monkeypatch.setattr(
        batch, "write_conversation_excerpt",
        lambda name, numbered: called.append(1) or [],
    )
    rows = _pair("응", "네.", 0) + _pair("그래", "네.", 10)
    assert batch.build_excerpt("김순자", rows) is None
    assert called == [], "후보가 없으면 모델을 부를 이유가 없다"


def test_no_utterances_means_nothing_to_show():
    assert batch.build_excerpt("김순자", []) is None


def test_long_lines_are_trimmed(monkeypatch):
    monkeypatch.setattr(batch, "write_conversation_excerpt", lambda name, numbered: None)
    rows = _pair("말" * 300, "답" * 300, 0)
    picked = json.loads(batch.build_excerpt("김순자", rows))
    assert len(picked[0]["user"]) == batch.EXCERPT_MAX_CHARS
    assert picked[0]["user"].endswith("…")

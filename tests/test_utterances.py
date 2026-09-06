"""발화 저장·감정 정규화·일과 날짜 조회 테스트.

인형(기기 토큰)이 쓰는 쪽과 보호자(JWT)가 읽는 쪽을 함께 확인한다.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ActivityLog, Device, EmotionRecord, FamilyMember, Protector, User, Utterance
from app.security import create_access_token
from app.services.kst import KST

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

DEVICE_TOKEN = "test-device-token"


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
    """보호자(김지영) + 어르신(박순자) + 인형(모리)."""
    db = TestSession()
    try:
        me = Protector(
            phone_number="01011112222",
            display_name="김지영",
            relation="딸",
            user_handle=b"handle-me",
        )
        db.add(me)
        db.flush()

        user = User(name="박순자", gender="female", birth_date=dt.date(1952, 3, 15))
        db.add(user)
        db.flush()
        db.add(FamilyMember(user_id=user.id, protector_id=me.id, is_primary=True))

        device = Device(user_id=user.id, name="모리", device_token=DEVICE_TOKEN)
        db.add(device)
        db.commit()
        return {"me": me.id, "user": user.id, "device": device.id}
    finally:
        db.close()


def auth(protector_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(protector_id)}"}


def device_auth() -> dict:
    return {"X-Device-Token": DEVICE_TOKEN}


def data(response):
    assert response.status_code < 400, response.text
    return response.json()["data"]


# ── 발화 저장 ────────────────────────────────────────
def test_device_saves_a_turn(world):
    body = {
        "utterances": [
            {"speaker": "user", "content": "오늘 날씨가 참 좋구나"},
            {"speaker": "mori", "content": "그러게요, 산책 다녀오시면 좋겠어요."},
        ]
    }
    result = data(
        client.post(
            f"/devices/{world['device']}/utterances", json=body, headers=device_auth()
        )
    )
    assert result["saved"] == 2

    db = TestSession()
    try:
        rows = db.scalars(select(Utterance).order_by(Utterance.id)).all()
        assert [r.speaker for r in rows] == ["user", "mori"]
        assert rows[0].user_id == world["user"]
        assert rows[0].content == "오늘 날씨가 참 좋구나"
    finally:
        db.close()


def test_unknown_speaker_is_rejected(world):
    response = client.post(
        f"/devices/{world['device']}/utterances",
        json={"utterances": [{"speaker": "granddaughter", "content": "안녕"}]},
        headers=device_auth(),
    )
    assert response.status_code == 422


def test_utterances_need_a_device_token(world):
    response = client.post(
        f"/devices/{world['device']}/utterances",
        json={"utterances": [{"speaker": "user", "content": "안녕"}]},
    )
    assert response.status_code == 401


def test_utterances_are_not_exposed_to_protectors(world):
    """발화는 리포트 재료일 뿐 보호자에게 그대로 나가지 않는다."""
    response = client.get(f"/users/{world['user']}/utterances", headers=auth(world["me"]))
    assert response.status_code == 404


# ── 감정 정규화 ──────────────────────────────────────
def test_korean_emotion_is_stored_as_code(world):
    data(
        client.post(
            f"/devices/{world['device']}/emotions",
            json={"emotion": "중립"},
            headers=device_auth(),
        )
    )
    db = TestSession()
    try:
        record = db.scalars(select(EmotionRecord)).first()
        assert record.emotion == "calm"
    finally:
        db.close()


def test_unrecognized_emotion_is_rejected(world):
    response = client.post(
        f"/devices/{world['device']}/emotions",
        json={"emotion": "알수없음"},
        headers=device_auth(),
    )
    assert response.status_code == 400

    db = TestSession()
    try:
        assert db.scalars(select(EmotionRecord)).all() == []
    finally:
        db.close()


# ── 일과 날짜 조회 ───────────────────────────────────
def test_activities_can_be_filtered_by_kst_day(world):
    """한국 시간 자정을 사이에 둔 두 기록이 서로 다른 날로 갈린다."""
    db = TestSession()
    try:
        # KST 9/5 23:30 과 9/6 00:30 (둘 다 UTC 로는 9/5 이다)
        late = dt.datetime(2026, 9, 5, 23, 30, tzinfo=KST).astimezone(dt.timezone.utc)
        early = dt.datetime(2026, 9, 6, 0, 30, tzinfo=KST).astimezone(dt.timezone.utc)
        db.add_all(
            [
                ActivityLog(
                    user_id=world["user"],
                    activity_type="DAILY_CONVERSATION",
                    content="어제 늦게",
                    created_at=late,
                ),
                ActivityLog(
                    user_id=world["user"],
                    activity_type="MEDICATION",
                    content="오늘 새벽",
                    created_at=early,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    fifth = data(
        client.get(f"/users/{world['user']}/activities?date=2026-09-05", headers=auth(world["me"]))
    )
    assert [a["content"] for a in fifth] == ["어제 늦게"]

    sixth = data(
        client.get(f"/users/{world['user']}/activities?date=2026-09-06", headers=auth(world["me"]))
    )
    assert [a["content"] for a in sixth] == ["오늘 새벽"]

    every = data(client.get(f"/users/{world['user']}/activities", headers=auth(world["me"])))
    assert len(every) == 2


def test_bad_date_is_rejected(world):
    response = client.get(
        f"/users/{world['user']}/activities?date=2026-13-99", headers=auth(world["me"])
    )
    assert response.status_code == 400


# ── 감정 날짜 조회 ───────────────────────────────────
def test_emotions_can_be_filtered_by_kst_day(world):
    """리포트가 '그날의 감정 흐름' 을 그리려면 그날 것만 와야 한다."""
    db = TestSession()
    try:
        late = dt.datetime(2026, 9, 5, 23, 30, tzinfo=KST).astimezone(dt.timezone.utc)
        early = dt.datetime(2026, 9, 6, 0, 30, tzinfo=KST).astimezone(dt.timezone.utc)
        db.add_all(
            [
                EmotionRecord(user_id=world["user"], emotion="sad", created_at=late),
                EmotionRecord(user_id=world["user"], emotion="happy", created_at=early),
            ]
        )
        db.commit()
    finally:
        db.close()

    fifth = data(
        client.get(f"/users/{world['user']}/emotions?date=2026-09-05", headers=auth(world["me"]))
    )
    assert [e["emotion"] for e in fifth] == ["sad"]

    sixth = data(
        client.get(f"/users/{world['user']}/emotions?date=2026-09-06", headers=auth(world["me"]))
    )
    assert [e["emotion"] for e in sixth] == ["happy"]

    every = data(client.get(f"/users/{world['user']}/emotions", headers=auth(world["me"])))
    assert len(every) == 2

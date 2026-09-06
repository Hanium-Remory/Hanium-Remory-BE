"""푸시 토큰 등록·해제와, 알림이 보호자 설정을 지키는지.

발송 자체(FCM REST)는 서비스 계정이 없으면 꺼지므로 여기서는 타지 않는다.
확인하려는 것은 '누구에게 알림을 만들고 누구의 토큰을 고르는가' 다.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    FamilyMember,
    Notification,
    NotificationSetting,
    Protector,
    PushToken,
    User,
)
from app.security import create_access_token
from app.services import notifications as notif

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
    """보호자 둘(김지영·김민수) + 어르신(박순자)."""
    db = TestSession()
    try:
        me = Protector(
            phone_number="01011112222", display_name="김지영", user_handle=b"h1"
        )
        other = Protector(
            phone_number="01033334444", display_name="김민수", user_handle=b"h2"
        )
        db.add_all([me, other])
        db.flush()
        user = User(name="박순자", gender="female", birth_date=dt.date(1952, 3, 15))
        db.add(user)
        db.flush()
        db.add_all(
            [
                FamilyMember(user_id=user.id, protector_id=me.id, is_primary=True),
                FamilyMember(user_id=user.id, protector_id=other.id),
            ]
        )
        db.commit()
        return {"me": me.id, "other": other.id, "user": user.id}
    finally:
        db.close()


def auth(protector_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(protector_id)}"}


def data(response):
    assert response.status_code < 400, response.text
    return response.json()["data"]


# ── 토큰 등록 ────────────────────────────────────────
def test_register_saves_the_token(world):
    result = data(
        client.post(
            "/protectors/me/push-tokens",
            json={"token": "fcm-abc", "platform": "android"},
            headers=auth(world["me"]),
        )
    )
    assert result["protectorId"] == world["me"]

    db = TestSession()
    try:
        rows = db.scalars(select(PushToken)).all()
        assert len(rows) == 1
        assert rows[0].token == "fcm-abc"
    finally:
        db.close()


def test_registering_twice_does_not_duplicate(world):
    for _ in range(2):
        client.post(
            "/protectors/me/push-tokens",
            json={"token": "fcm-abc"},
            headers=auth(world["me"]),
        )
    db = TestSession()
    try:
        assert len(db.scalars(select(PushToken)).all()) == 1
    finally:
        db.close()


def test_same_phone_relogged_as_someone_else_changes_owner(world):
    """폰을 물려주면 같은 토큰이 새 주인 것이 되어야 한다."""
    client.post(
        "/protectors/me/push-tokens", json={"token": "fcm-abc"}, headers=auth(world["me"])
    )
    client.post(
        "/protectors/me/push-tokens",
        json={"token": "fcm-abc"},
        headers=auth(world["other"]),
    )
    db = TestSession()
    try:
        rows = db.scalars(select(PushToken)).all()
        assert len(rows) == 1
        assert rows[0].protector_id == world["other"]
    finally:
        db.close()


def test_unknown_platform_is_rejected(world):
    response = client.post(
        "/protectors/me/push-tokens",
        json={"token": "fcm-abc", "platform": "windows"},
        headers=auth(world["me"]),
    )
    assert response.status_code == 422


def test_push_tokens_need_login(world):
    response = client.post("/protectors/me/push-tokens", json={"token": "fcm-abc"})
    assert response.status_code == 401


def test_unregister_removes_only_my_token(world):
    client.post(
        "/protectors/me/push-tokens", json={"token": "mine"}, headers=auth(world["me"])
    )
    client.post(
        "/protectors/me/push-tokens", json={"token": "theirs"}, headers=auth(world["other"])
    )

    # 남의 토큰을 지우려 해도 남아 있어야 한다.
    client.request(
        "DELETE",
        "/protectors/me/push-tokens",
        json={"token": "theirs"},
        headers=auth(world["me"]),
    )
    db = TestSession()
    try:
        assert sorted(t.token for t in db.scalars(select(PushToken)).all()) == [
            "mine",
            "theirs",
        ]
    finally:
        db.close()

    client.request(
        "DELETE",
        "/protectors/me/push-tokens",
        json={"token": "mine"},
        headers=auth(world["me"]),
    )
    db = TestSession()
    try:
        assert [t.token for t in db.scalars(select(PushToken)).all()] == ["theirs"]
    finally:
        db.close()


# ── 알림 설정을 지키는지 ─────────────────────────────
def test_notification_goes_to_everyone_by_default(world):
    db = TestSession()
    try:
        made = notif.notify_report_ready(db, world["user"], "요약")
        assert made == 2
        assert len(db.scalars(select(Notification)).all()) == 2
    finally:
        db.close()


def test_a_protector_who_turned_it_off_gets_nothing(world):
    db = TestSession()
    try:
        db.add(NotificationSetting(protector_id=world["other"], daily_report=False))
        db.commit()

        made = notif.notify_report_ready(db, world["user"], "요약")
        assert made == 1
        rows = db.scalars(select(Notification)).all()
        assert [n.protector_id for n in rows] == [world["me"]]
    finally:
        db.close()


def test_turning_off_the_whole_urgent_group_wins(world):
    """'긴급' 을 끄면 세부 항목이 켜져 있어도 오지 않는다."""
    db = TestSession()
    try:
        db.add(
            NotificationSetting(
                protector_id=world["other"], urgent=False, emotion_change=True
            )
        )
        db.commit()

        made = notif._create(
            db,
            user_id=world["user"],
            type_=notif.TYPE_URGENT,
            requires=("urgent", "emotion_change"),
            title=notif.EMOTION_TITLE,
            content="x",
        )
        assert made == 1
        rows = db.scalars(select(Notification)).all()
        assert [n.protector_id for n in rows] == [world["me"]]
    finally:
        db.close()


def test_settings_row_is_created_on_first_use(world):
    """설정을 한 번도 안 건드린 보호자도 기본값 줄이 생겨 다음부터 빨리 판단한다."""
    db = TestSession()
    try:
        notif.notify_report_ready(db, world["user"], "요약")
        assert len(db.scalars(select(NotificationSetting)).all()) == 2
    finally:
        db.close()


def test_push_is_skipped_when_not_configured(world):
    """서비스 계정이 없으면 푸시는 건너뛰고 알림만 만든다."""
    from app.services import fcm

    assert fcm.enabled() is False
    db = TestSession()
    try:
        db.add(PushToken(protector_id=world["me"], token="fcm-abc"))
        db.commit()
        assert notif.notify_report_ready(db, world["user"], "요약") == 2
    finally:
        db.close()


# ── 발송 경로 ────────────────────────────────────────
class _StubResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def fcm_ready(monkeypatch):
    """서비스 계정이 있는 것처럼 만들고, 나간 요청을 받아 둔다."""
    from app.services import fcm

    sent = []

    class _Creds:
        project_id = "remory-test"

    monkeypatch.setattr(fcm, "_load_credentials", lambda: _Creds())
    monkeypatch.setattr(fcm, "_access_token", lambda: "stub-access-token")

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "headers": headers, "body": json})
        token = json["message"]["token"]
        # 'dead-' 로 시작하는 토큰은 FCM 이 404 UNREGISTERED 로 답한다고 본다.
        if token.startswith("dead-"):
            return _StubResponse(404, '{"error":{"status":"NOT_FOUND"}}')
        return _StubResponse(200)

    monkeypatch.setattr(fcm.httpx, "post", fake_post)
    return sent


def test_push_request_has_the_shape_fcm_expects(world, fcm_ready):
    db = TestSession()
    try:
        db.add(PushToken(protector_id=world["me"], token="live-1"))
        db.commit()
        notif.notify_report_ready(db, world["user"], "오늘은 평온하셨어요")
    finally:
        db.close()

    assert len(fcm_ready) == 1
    call = fcm_ready[0]
    assert call["url"] == (
        "https://fcm.googleapis.com/v1/projects/remory-test/messages:send"
    )
    assert call["headers"]["Authorization"] == "Bearer stub-access-token"

    message = call["body"]["message"]
    assert message["token"] == "live-1"
    assert message["notification"]["title"] == notif.REPORT_TITLE
    assert message["notification"]["body"] == "오늘은 평온하셨어요"
    # data 값은 FCM 이 문자열만 받는다.
    assert message["data"] == {"type": str(notif.TYPE_REPORT)}
    assert message["android"]["priority"] == "high"


def test_dead_token_is_dropped(world, fcm_ready):
    db = TestSession()
    try:
        db.add_all(
            [
                PushToken(protector_id=world["me"], token="dead-1"),
                PushToken(protector_id=world["me"], token="live-1"),
            ]
        )
        db.commit()

        notif.notify_report_ready(db, world["user"], "요약")

        left = sorted(t.token for t in db.scalars(select(PushToken)).all())
        assert left == ["live-1"]
    finally:
        db.close()


def test_a_protector_who_turned_it_off_is_not_pushed(world, fcm_ready):
    db = TestSession()
    try:
        db.add(NotificationSetting(protector_id=world["other"], daily_report=False))
        db.add_all(
            [
                PushToken(protector_id=world["me"], token="live-me"),
                PushToken(protector_id=world["other"], token="live-other"),
            ]
        )
        db.commit()

        notif.notify_report_ready(db, world["user"], "요약")
    finally:
        db.close()

    assert [c["body"]["message"]["token"] for c in fcm_ready] == ["live-me"]

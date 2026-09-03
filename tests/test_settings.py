"""설정 API 통합 테스트.

인증 플로우를 거치지 않고, 토큰만 직접 발급해 설정 엔드포인트의 배선·권한을 검증한다.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Device, FamilyMember, Medication, Protector, User, Voice
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


def _make_protector(db, name: str, phone: str, handle: bytes, relation: str) -> Protector:
    protector = Protector(
        phone_number=phone, display_name=name, relation=relation, user_handle=handle
    )
    db.add(protector)
    db.flush()
    return protector


@pytest.fixture
def world():
    """주보호자(김지영) + 가족(김민수) + 어르신(박순자) + 인형(모리) + 약 1개."""
    db = TestSession()
    try:
        me = _make_protector(db, "김지영", "01011112222", b"handle-me", "딸")
        other = _make_protector(db, "김민수", "01033334444", b"handle-other", "아들")

        user = User(name="박순자", gender="female", birth_date=dt.date(1952, 3, 15))
        db.add(user)
        db.flush()
        db.add_all(
            [
                FamilyMember(user_id=user.id, protector_id=me.id, is_primary=True),
                FamilyMember(user_id=user.id, protector_id=other.id),
            ]
        )

        device = Device(user_id=user.id, name="모리", battery_level=78, volume=80)
        db.add(device)
        db.flush()

        voice = Voice(device_id=device.id, protector_id=me.id, name="김지영", status="ready")
        training = Voice(
            device_id=device.id, protector_id=other.id, name="김민수", status="training", progress=52
        )
        db.add_all([voice, training])
        db.flush()
        device.default_voice_id = voice.id

        med = Medication(device_id=device.id, name="아침 혈압약", time="08:00", timing="식후")
        db.add(med)
        db.commit()

        return {
            "me": me.id,
            "other": other.id,
            "user": user.id,
            "device": device.id,
            "voice": voice.id,
            "training_voice": training.id,
            "medication": med.id,
        }
    finally:
        db.close()


def auth(protector_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(protector_id)}"}


def data(response):
    assert response.status_code < 400, response.text
    return response.json()["data"]


# ── 보호자 프로필 ────────────────────────────────────
def test_get_me_returns_profile_users_and_notification_defaults(world):
    d = data(client.get("/protectors/me", headers=auth(world["me"])))
    assert d["name"] == "김지영"
    assert d["relation"] == "딸"
    assert d["users"] == [
        {"userId": world["user"], "name": "박순자", "deviceId": world["device"], "isPrimary": True}
    ]
    assert d["notificationSettings"]["urgent"] is True
    assert d["notificationSettings"]["marketing"] is False


def test_update_me_changes_name_and_relation(world):
    d = data(
        client.put(
            "/protectors/me", headers=auth(world["me"]), json={"name": "김지영2", "relation": "며느리"}
        )
    )
    assert (d["name"], d["relation"]) == ("김지영2", "며느리")


def test_update_me_rejects_phone_change(world):
    r = client.put("/protectors/me", headers=auth(world["me"]), json={"phoneNumber": "01099998888"})
    assert r.status_code == 400
    # 같은 번호(하이픈 포함)는 통과
    assert client.put(
        "/protectors/me", headers=auth(world["me"]), json={"phoneNumber": "010-1111-2222"}
    ).status_code == 200


def test_update_me_rejects_unknown_relation(world):
    r = client.put("/protectors/me", headers=auth(world["me"]), json={"relation": "이웃"})
    assert r.status_code == 422


def test_patch_notification_settings_is_partial(world):
    d = data(
        client.patch(
            "/protectors/me/notification-settings",
            headers=auth(world["me"]),
            json={"marketing": True, "dailyReport": False},
        )
    )
    assert d["marketing"] is True and d["dailyReport"] is False
    assert d["urgent"] is True  # 건드리지 않은 항목은 유지

    d = data(
        client.patch(
            "/protectors/me/notification-settings",
            headers=auth(world["me"]),
            json={"emotionChange": False},
        )
    )
    assert d["emotionChange"] is False and d["marketing"] is True


def test_delete_me_keeps_user_when_family_remains(world):
    assert client.delete("/protectors/me", headers=auth(world["me"])).status_code == 200
    # 남은 가족이 주보호자를 이어받는다.
    d = data(client.get(f"/users/{world['user']}/family-members", headers=auth(world["other"])))
    assert d["stats"]["familyCount"] == 1
    assert d["members"][0]["isPrimary"] is True


def test_delete_last_member_removes_user_and_device(world):
    client.delete("/protectors/me", headers=auth(world["other"]))
    d = data(client.delete("/protectors/me", headers=auth(world["me"])))
    assert d["deletedUserIds"] == [world["user"]]
    db = TestSession()
    try:
        assert db.get(User, world["user"]) is None
        assert db.get(Device, world["device"]) is None
    finally:
        db.close()


# ── 어르신 정보 ──────────────────────────────────────
def test_get_user_includes_age_and_device(world):
    d = data(client.get(f"/users/{world['user']}", headers=auth(world["me"])))
    assert d["name"] == "박순자"
    assert d["gender"] == "female"
    assert d["deviceId"] == world["device"]
    assert d["age"] >= 70


def test_update_user_accepts_korean_gender(world):
    d = data(
        client.put(
            f"/users/{world['user']}",
            headers=auth(world["me"]),
            json={"gender": "남성", "note": "트로트를 좋아하세요"},
        )
    )
    assert d["gender"] == "male"
    assert d["note"] == "트로트를 좋아하세요"
    assert d["name"] == "박순자"  # 안 보낸 필드는 유지


def test_user_of_other_family_is_404(world):
    db = TestSession()
    try:
        stranger = _make_protector(db, "남", "01055556666", b"handle-stranger", "기타")
        db.commit()
        stranger_id = stranger.id
    finally:
        db.close()
    assert client.get(f"/users/{world['user']}", headers=auth(stranger_id)).status_code == 404
    assert client.get(f"/devices/{world['device']}/settings", headers=auth(stranger_id)).status_code == 404


def test_family_members_stats(world):
    d = data(client.get(f"/users/{world['user']}/family-members", headers=auth(world["me"])))
    assert d["stats"] == {"familyCount": 2, "voiceCount": 1, "inviteCodeCount": 0}
    me_row = next(m for m in d["members"] if m["isMe"])
    assert me_row["isPrimary"] is True and me_row["relation"] == "딸"


# ── 가족 멤버 제거 ───────────────────────────────────
def test_primary_can_remove_member(world):
    d = data(client.delete(f"/family-members/{world['other']}", headers=auth(world["me"])))
    assert d["protectorId"] == world["other"]
    remaining = data(
        client.get(f"/users/{world['user']}/family-members", headers=auth(world["me"]))
    )
    assert remaining["stats"]["familyCount"] == 1


def test_non_primary_cannot_remove(world):
    r = client.delete(f"/family-members/{world['me']}", headers=auth(world["other"]))
    assert r.status_code in (400, 403)


def test_cannot_remove_self(world):
    r = client.delete(f"/family-members/{world['me']}", headers=auth(world["me"]))
    assert r.status_code == 400


# ── 인형 설정 ────────────────────────────────────────
def test_get_device_settings(world):
    d = data(client.get(f"/devices/{world['device']}/settings", headers=auth(world["me"])))
    assert d["name"] == "모리"
    assert d["connected"] is False  # heartbeat 없음
    assert d["batteryLevel"] == 78 and d["batteryHoursLeft"] == 14
    assert d["defaultVoiceId"] == world["voice"]
    assert {v["name"] for v in d["voices"]} == {"김지영", "김민수"}


def test_update_device_volume_and_name(world):
    d = data(
        client.put(
            f"/devices/{world['device']}/settings",
            headers=auth(world["me"]),
            json={"volume": 95, "name": "모리야"},
        )
    )
    assert d["volume"] == 95 and d["name"] == "모리야"


def test_volume_out_of_range_is_422(world):
    r = client.put(
        f"/devices/{world['device']}/settings", headers=auth(world["me"]), json={"volume": 120}
    )
    assert r.status_code == 422


def test_default_voice_patch(world):
    r = client.patch(
        f"/devices/{world['device']}/settings/voice",
        headers=auth(world["me"]),
        json={"voiceId": world["training_voice"]},
    )
    assert r.status_code == 400  # 학습 중인 목소리는 지정 불가

    d = data(
        client.patch(
            f"/devices/{world['device']}/settings/voice",
            headers=auth(world["me"]),
            json={"voiceId": world["voice"]},
        )
    )
    assert d["defaultVoiceId"] == world["voice"]


# ── 기기 토큰 ────────────────────────────────────────
def test_issue_device_token_lets_device_call_its_own_api(world):
    # 아직 발급 전(기존에 가입한 기기처럼 device_token 이 NULL 인 상태).
    before = data(client.get(f"/devices/{world['device']}/settings", headers=auth(world["me"])))
    assert before["hasDeviceToken"] is False

    d = data(client.post(f"/devices/{world['device']}/token", headers=auth(world["me"])))
    token = d["deviceToken"]
    assert d["deviceId"] == world["device"] and token

    # 발급받은 토큰으로 인형이 heartbeat 를 보낼 수 있다.
    r = client.patch(
        f"/devices/{world['device']}/heartbeat", headers={"X-Device-Token": token}
    )
    assert r.status_code == 200

    # 조회 응답에는 토큰이 섞이지 않는다(가족 전원이 보는 화면이라서).
    settings_data = data(
        client.get(f"/devices/{world['device']}/settings", headers=auth(world["me"]))
    )
    assert "deviceToken" not in settings_data
    assert settings_data["hasDeviceToken"] is True  # 값 대신 발급 여부만


def test_issuing_again_invalidates_the_previous_token(world):
    old = data(client.post(f"/devices/{world['device']}/token", headers=auth(world["me"])))[
        "deviceToken"
    ]
    new = data(client.post(f"/devices/{world['device']}/token", headers=auth(world["me"])))[
        "deviceToken"
    ]
    assert new != old

    assert client.patch(
        f"/devices/{world['device']}/heartbeat", headers={"X-Device-Token": old}
    ).status_code == 401
    assert client.patch(
        f"/devices/{world['device']}/heartbeat", headers={"X-Device-Token": new}
    ).status_code == 200


def test_issue_device_token_requires_family_membership(world):
    db = TestSession()
    try:
        stranger = _make_protector(db, "남", "01055556666", b"handle-stranger", "기타")
        db.commit()
        stranger_id = stranger.id
    finally:
        db.close()
    assert client.post(
        f"/devices/{world['device']}/token", headers=auth(stranger_id)
    ).status_code == 404
    assert client.post(f"/devices/{world['device']}/token").status_code == 401


# ── 방해 금지 시간 ───────────────────────────────────
def test_dnd_defaults_then_update(world):
    d = data(client.get(f"/devices/{world['device']}/dnd", headers=auth(world["me"])))
    assert (d["enabled"], d["startHour"], d["endHour"]) == (True, 23, 7)

    d = data(
        client.put(
            f"/devices/{world['device']}/dnd",
            headers=auth(world["me"]),
            json={"startHour": 22, "allowWakeWord": False},
        )
    )
    assert d["startHour"] == 22 and d["endHour"] == 7 and d["allowWakeWord"] is False


def test_dnd_same_start_end_rejected(world):
    r = client.put(
        f"/devices/{world['device']}/dnd", headers=auth(world["me"]), json={"startHour": 7}
    )
    assert r.status_code == 400


# ── 약 복용 ──────────────────────────────────────────
def test_medication_crud(world):
    listed = data(client.get(f"/devices/{world['device']}/medications", headers=auth(world["me"])))
    assert listed["medicationCheck"] is True
    assert len(listed["medications"]) == 1

    created = data(
        client.post(
            f"/devices/{world['device']}/medications",
            headers=auth(world["me"]),
            json={"name": "저녁 영양제", "time": "19:00", "timing": "식후"},
        )
    )
    med_id = created["medicationId"]

    updated = data(
        client.put(f"/medications/{med_id}", headers=auth(world["me"]), json={"time": "20:30"})
    )
    assert updated["time"] == "20:30" and updated["name"] == "저녁 영양제"

    assert client.delete(f"/medications/{med_id}", headers=auth(world["me"])).status_code == 200
    after = data(client.get(f"/devices/{world['device']}/medications", headers=auth(world["me"])))
    assert len(after["medications"]) == 1


def test_medication_validation(world):
    bad_time = client.post(
        f"/devices/{world['device']}/medications",
        headers=auth(world["me"]),
        json={"name": "약", "time": "8:00"},
    )
    assert bad_time.status_code == 422

    bad_timing = client.post(
        f"/devices/{world['device']}/medications",
        headers=auth(world["me"]),
        json={"name": "약", "time": "08:00", "timing": "식중"},
    )
    assert bad_timing.status_code == 422


def test_medication_of_other_family_is_404(world):
    db = TestSession()
    try:
        stranger = _make_protector(db, "남", "01077778888", b"handle-stranger2", "기타")
        db.commit()
        stranger_id = stranger.id
    finally:
        db.close()
    r = client.delete(f"/medications/{world['medication']}", headers=auth(stranger_id))
    assert r.status_code == 404


# ── 서비스 정보 / 인증 ───────────────────────────────
def test_service_info_is_public():
    d = data(client.get("/service/info"))
    assert d["version"] and d["termsUrl"]


def test_dev_seed_creates_user_and_device():
    """설정 화면을 붙여볼 수 있게 샘플 데이터를 만들어 주는 개발용 엔드포인트."""
    db = TestSession()
    try:
        protector = _make_protector(db, "김지영", "01012345678", b"handle-seed", "딸")
        db.commit()
        pid = protector.id
    finally:
        db.close()

    d = data(client.post("/dev/seed", headers=auth(pid)))
    assert d["userId"] and d["deviceId"]

    settings_data = data(client.get(f"/devices/{d['deviceId']}/settings", headers=auth(pid)))
    assert settings_data["name"] == "모리"
    assert len(settings_data["voices"]) == 2

    again = data(client.post("/dev/seed", headers=auth(pid)))
    assert again["userId"] == d["userId"]  # 중복 생성하지 않는다


def test_settings_require_token(world):
    assert client.get("/protectors/me").status_code == 401
    assert client.get(f"/devices/{world['device']}/settings").status_code == 401

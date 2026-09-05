"""초대 코드로 들어온 가족의 가입 흐름.

'코드를 받았어요' 로 들어온 사람은 어르신을 등록하지 않는다.
코드 확인 → 패스키 → 전화번호 인증 한 번으로 가족에 붙고 홈으로 간다.
"""

import base64
import datetime as dt
import json
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import FamilyMember, InviteCode, PhoneVerification, Protector, User
from app.security import create_access_token
from app.services import webauthn_service as wa

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
FAMILY_PHONE = "010-9999-8888"


def _b64url(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


@pytest.fixture
def invite_code() -> str:
    """주보호자(김지영)가 어르신(박순자)을 등록하고 만든 초대 코드."""
    db = TestSession()
    try:
        me = Protector(phone_number="01011112222", display_name="김지영", user_handle=b"h-me")
        db.add(me)
        db.flush()
        user = User(name="박순자", gender="female")
        db.add(user)
        db.flush()
        db.add(FamilyMember(user_id=user.id, protector_id=me.id, is_primary=True))
        db.commit()
        owner_id = me.id
    finally:
        db.close()

    r = client.post(
        "/users/1/invite-codes",
        headers={"Authorization": f"Bearer {create_access_token(owner_id)}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["inviteCode"]


def _signup_with_code(monkeypatch, code: Optional[str]):
    """Face-ID-first 가입: 패스키 등록 → 전화번호 인증(초대 코드 동봉)."""
    r = client.post("/auth/passkey/registration/options", json={"displayName": "이철수"})
    assert r.status_code == 200, r.text
    challenge = r.json()["data"]["challenge"]

    class FakeReg:
        credential_public_key = b"\xa5\x01\x02fake-public-key"
        sign_count = 0

    monkeypatch.setattr(wa, "verify_registration", lambda *a, **k: FakeReg())
    r = client.post(
        "/auth/passkey/registration",
        json={
            "credentialId": "AAAAcredential-family",
            "clientDataJSON": _b64url(
                {"type": "webauthn.create", "challenge": challenge, "origin": "https://remory.app"}
            ),
            "attestationObject": "ZmFrZQ",
        },
    )
    assert r.status_code == 201, r.text
    onboarding_token = r.json()["data"]["onboardingToken"]

    r = client.post("/auth/phone/verification-code", json={"phoneNumber": FAMILY_PHONE})
    assert r.status_code == 200, r.text

    db = TestSession()
    try:
        otp = db.scalars(
            select(PhoneVerification)
            .where(PhoneVerification.phone_number == "01099998888")
            .order_by(PhoneVerification.created_at.desc())
        ).first().code
    finally:
        db.close()

    body = {"phoneNumber": FAMILY_PHONE, "code": otp}
    if code is not None:
        body["inviteCode"] = code
    return client.post(
        "/auth/phone/verify",
        json=body,
        headers={"Authorization": f"Bearer {onboarding_token}"},
    )


def test_check_code_without_login(invite_code):
    """가입 전이라 토큰이 없다. 그래도 코드가 쓸 수 있는지 확인된다."""
    r = client.get(f"/invite-codes/{invite_code}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["userName"] == "박순자"
    # 확인만 했으니 코드는 아직 쓰지 않은 상태여야 한다.
    r = client.get(f"/invite-codes/{invite_code.lower()}")
    assert r.status_code == 200, r.text


def test_check_code_rejects_unknown():
    r = client.get("/invite-codes/ZZZZZZ")
    assert r.status_code == 404, r.text


def test_signup_with_code_joins_family(monkeypatch, invite_code):
    """어르신을 등록하지 않고도 문자 인증 한 번으로 가족이 되고 홈으로 간다."""
    r = _signup_with_code(monkeypatch, invite_code)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["accessToken"] and data["refreshToken"]
    assert data["onboardingCompleted"] is True
    assert data["linkedUser"]["userId"] == 1
    assert data["linkedUser"]["name"] == "박순자"
    assert data["linkedUser"]["isPrimary"] is False

    # 홈이 바로 열린다.
    r = client.get(
        "/home?userId=1", headers={"Authorization": f"Bearer {data['accessToken']}"}
    )
    assert r.status_code == 200, r.text

    # 코드는 다 썼다.
    r = client.get(f"/invite-codes/{invite_code}")
    assert r.status_code == 400, r.text


def test_signup_without_code_stays_unfinished(monkeypatch):
    """'처음 시작해요' 로 들어온 사람은 아직 어르신이 없다."""
    r = _signup_with_code(monkeypatch, None)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["linkedUser"] is None
    assert data["onboardingCompleted"] is False


def test_signup_with_expired_code_keeps_otp_reusable(monkeypatch, invite_code):
    """기한 지난 코드면 400. 문자를 다시 받지 않고 곧바로 다시 시도할 수 있다."""
    db = TestSession()
    try:
        invite = db.scalars(select(InviteCode)).first()
        invite.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    r = _signup_with_code(monkeypatch, invite_code)
    assert r.status_code == 400, r.text
    assert "기한" in r.json()["message"]

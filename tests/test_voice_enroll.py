"""목소리 등록(voice-enroll) EC2 측 흐름 테스트.

CosyVoice 제로샷은 등록이 수 초라 EC2 가 동기로 /enroll 을 호출하고 결과를 바로 받는다.
- register_voice 가 CosyVoice 를 호출해 성공 시 ready(+speaker_id), 실패 시 failed 로 기록
- 상태 조회에 speakerId / errorMessage 가 실리는지
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Device, FamilyMember, Protector, User, Voice
from app.security import create_access_token
from app.services import cosyvoice
from app.services.storage import storage

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


def auth(protector_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(protector_id)}"}


@pytest.fixture
def world():
    """보호자(김지영) + 어르신(박순자) + 인형(모리) + 학습중 목소리 1개."""
    db = TestSession()
    try:
        me = Protector(phone_number="01011112222", display_name="김지영", user_handle=b"h-me")
        db.add(me)
        db.flush()

        user = User(name="박순자", gender="female")
        db.add(user)
        db.flush()
        db.add(FamilyMember(user_id=user.id, protector_id=me.id, is_primary=True))

        device = Device(user_id=user.id, name="모리", battery_level=80, volume=80)
        db.add(device)
        db.flush()

        voice = Voice(
            device_id=device.id, protector_id=me.id, name="딸 지영",
            status="training", progress=0, audio_url="/uploads/voices/x.wav",
        )
        db.add(voice)
        db.flush()

        db.commit()
        return {"me": me.id, "device": device.id, "voice": voice.id}
    finally:
        db.close()


def _upload(device_id: int, protector_id: int):
    return client.post(
        f"/devices/{device_id}/voices",
        headers=auth(protector_id),
        data={"name": "딸 지영"},
        files={"file": ("rec.wav", b"fake-audio-bytes", "audio/wav")},
    )


def test_register_enrolls_and_marks_ready(monkeypatch, world):
    """CosyVoice 등록 성공 → 201 + ready + speaker_id(spk_<voiceId>)."""
    monkeypatch.setattr(storage, "save", lambda *a, **k: "/uploads/voices/new.wav")
    monkeypatch.setattr(cosyvoice, "is_configured", lambda: True)

    called = {}

    async def fake_enroll(spk_id, audio, filename):
        called.update(spk_id=spk_id, filename=filename, size=len(audio))
        return spk_id  # CosyVoice 가 확정한 speaker_id

    monkeypatch.setattr(cosyvoice, "enroll", fake_enroll)

    r = _upload(world["device"], world["me"])
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert body["status"] == "ready"
    assert body["speakerId"] == f"spk_{body['voiceId']}"
    # 업로드한 파일이 그대로 CosyVoice 로 전달됐는지
    assert called["spk_id"] == f"spk_{body['voiceId']}"
    assert called["size"] == len(b"fake-audio-bytes")


def test_register_marks_failed_when_server_unreachable(monkeypatch, world):
    """CosyVoice 호출 실패 시 502 + 해당 voice 는 failed 로 남는다."""
    monkeypatch.setattr(storage, "save", lambda *a, **k: "/uploads/voices/new.wav")
    monkeypatch.setattr(cosyvoice, "is_configured", lambda: True)

    async def boom(spk_id, audio, filename):
        raise cosyvoice.CosyVoiceError("연결 실패")

    monkeypatch.setattr(cosyvoice, "enroll", boom)

    r = _upload(world["device"], world["me"])
    assert r.status_code == 502

    db = TestSession()
    try:
        failed = [v for v in db.query(Voice).all() if v.status == "failed"]
        assert len(failed) == 1
        assert failed[0].error_message
    finally:
        db.close()


def test_register_skips_when_not_configured(monkeypatch, world):
    """GPU_HOST 미설정이면 등록을 건너뛰고 training 으로 접수만 한다(데모)."""
    monkeypatch.setattr(storage, "save", lambda *a, **k: "/uploads/voices/new.wav")
    monkeypatch.setattr(cosyvoice, "is_configured", lambda: False)

    r = _upload(world["device"], world["me"])
    assert r.status_code == 201
    assert r.json()["data"]["status"] == "training"


def test_status_returns_speaker_and_error(world):
    """상태 조회가 speakerId / errorMessage 를 함께 준다."""
    db = TestSession()
    try:
        v = db.get(Voice, world["voice"])
        v.status = "ready"
        v.speaker_id = "spk_abc123"
        db.commit()
    finally:
        db.close()

    s = client.get(f"/voices/{world['voice']}/status", headers=auth(world["me"])).json()["data"]
    assert s["status"] == "ready"
    assert s["speakerId"] == "spk_abc123"
    assert "errorMessage" in s

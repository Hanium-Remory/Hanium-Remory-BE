"""대화방의 '읽음' 과 '인형이 어디까지 읽어드렸는지'."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ChatReadState, Device, FamilyMember, Protector, User, Voice
from app.security import create_access_token

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
DEVICE_TOKEN = "chat-device-token"


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
        a = Protector(phone_number="01011112222", display_name="김지영", user_handle=b"h1")
        b = Protector(phone_number="01033334444", display_name="김민수", user_handle=b"h2")
        db.add_all([a, b])
        db.flush()
        user = User(name="김순자", gender="female", birth_date=dt.date(1948, 3, 15))
        db.add(user)
        db.flush()
        db.add_all([
            FamilyMember(user_id=user.id, protector_id=a.id, is_primary=True),
            FamilyMember(user_id=user.id, protector_id=b.id),
        ])
        device = Device(user_id=user.id, name="모리", device_token=DEVICE_TOKEN)
        db.add(device)
        db.commit()
        return {"a": a.id, "b": b.id, "user": user.id, "device": device.id}
    finally:
        db.close()


def auth(pid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(pid)}"}


def data(r):
    assert r.status_code < 400, r.text
    return r.json()["data"]


def send(world, pid: int, text: str) -> int:
    return data(client.post(
        f"/users/{world['user']}/chat/messages", json={"content": text}, headers=auth(pid)
    ))["messageId"]


def room(world, pid: int) -> dict:
    """messageId → 메시지."""
    return {m["messageId"]: m for m in data(
        client.get(f"/users/{world['user']}/chat/messages", headers=auth(pid))
    )}


# ── 읽음 ─────────────────────────────────────────────
def test_my_own_message_is_not_read_until_someone_else_opens(world):
    mine = send(world, world["a"], "엄마 밥 드셨어요?")
    assert room(world, world["a"])[mine]["readCount"] == 0

    room(world, world["b"])                      # 김민수가 열어 본다
    assert room(world, world["a"])[mine]["readCount"] == 1


def test_sender_does_not_count_as_a_reader(world):
    """자기가 쓴 글을 읽었다고 하는 건 뜻이 없다."""
    mine = send(world, world["a"], "약 챙기셨어요?")
    # 보낸 사람이 아무리 다시 열어도 0 이다
    for _ in range(3):
        assert room(world, world["a"])[mine]["readCount"] == 0


def test_opening_the_room_reads_everything_before_it(world):
    first = send(world, world["a"], "첫 번째")
    second = send(world, world["a"], "두 번째")

    seen = room(world, world["b"])
    assert seen[first]["readCount"] == 1
    assert seen[second]["readCount"] == 1


def test_a_message_sent_after_you_left_stays_unread(world):
    room(world, world["b"])                      # 김민수가 먼저 훑고 나감
    later = send(world, world["a"], "나중에 보낸 말")
    assert room(world, world["a"])[later]["readCount"] == 0


def test_read_position_is_kept_once_per_person(world):
    """메시지가 쌓여도 사람마다 한 줄만 생긴다."""
    for i in range(5):
        send(world, world["a"], f"{i}번째")

    # 둘 다 여러 번 드나들어도 사람당 한 줄이다
    for _ in range(3):
        room(world, world["a"])
        room(world, world["b"])

    db = TestSession()
    try:
        states = db.scalars(select(ChatReadState)).all()
        assert len(states) == 2
        assert {s.protector_id for s in states} == {world["a"], world["b"]}
    finally:
        db.close()


# ── 인형이 어디까지 읽어드렸는지 ─────────────────────
def test_delivery_mark_follows_the_doll(world):
    first = send(world, world["a"], "첫 번째")
    second = send(world, world["a"], "두 번째")

    before = room(world, world["a"])
    assert before[first]["deliveredToDevice"] is False
    assert before[second]["deliveredToDevice"] is False

    # 인형이 켜져서 앞의 것만 읽어드렸다
    client.post(
        f"/devices/{world['device']}/chat/delivered",
        json={"messageIds": [first]},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )

    after = room(world, world["a"])
    assert after[first]["deliveredToDevice"] is True
    assert after[second]["deliveredToDevice"] is False


def test_messages_wait_while_the_doll_is_off(world):
    """인형이 꺼져 있어도 대화방은 그대로다. 켜지면 그 뒤부터 읽어준다."""
    first = send(world, world["a"], "꺼져 있을 때 보낸 말")
    second = send(world, world["b"], "그다음 말")

    pending = data(client.get(
        f"/devices/{world['device']}/chat/pending",
        headers={"X-Device-Token": DEVICE_TOKEN},
    ))["messages"]
    assert [m["messageId"] for m in pending] == [first, second]


# ── 인형 목소리는 가족이 함께 본다 ───────────────────
def test_a_voice_registered_by_one_family_member_is_seen_by_all(world):
    """등록한 사람 것이 아니라 그 인형 것이다."""
    db = TestSession()
    try:
        db.add(Voice(
            device_id=world["device"], protector_id=world["a"], name="김지영",
            status="ready", audio_url="https://b.s3.us-west-2.amazonaws.com/v.wav",
        ))
        db.commit()
    finally:
        db.close()

    for pid in (world["a"], world["b"]):
        settings = data(client.get(f"/devices/{world['device']}/settings", headers=auth(pid)))
        names = [v["name"] for v in settings["voices"]]
        assert "김지영" in names, f"protector {pid} 에게 안 보인다"


def test_settings_open_even_when_the_voice_file_cannot_be_signed(world, monkeypatch):
    """목소리 응답에는 audioUrl 이 들어간다. 서명이 안 돼도 목록은 보여야 한다."""
    from app.services import storage as storage_module

    class Boom:
        signs_urls = True

        def public_url(self, value):
            raise RuntimeError("Unable to locate credentials")

    monkeypatch.setattr(storage_module, "storage", Boom())

    db = TestSession()
    try:
        db.add(Voice(
            device_id=world["device"], protector_id=world["a"], name="김지영",
            status="ready", audio_url="https://b.s3.us-west-2.amazonaws.com/v.wav",
        ))
        db.commit()
    finally:
        db.close()

    settings = data(client.get(f"/devices/{world['device']}/settings", headers=auth(world["b"])))
    assert [v["name"] for v in settings["voices"]] == ["김지영"]

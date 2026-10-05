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


# ── 안 읽은 사람 수 ──────────────────────────────────
def test_a_fresh_message_counts_everyone_else_as_unread(world):
    """카카오톡처럼, 막 보낸 메시지에는 남은 사람 수가 떠야 한다."""
    mine = send(world, world["a"], "엄마 밥 드셨어요?")
    # 가족은 둘, 보낸 사람을 빼면 하나가 남는다
    assert room(world, world["a"])[mine]["unreadCount"] == 1

    room(world, world["b"])                      # 김민수가 열어 본다
    assert room(world, world["a"])[mine]["unreadCount"] == 0


def test_never_opened_the_room_still_counts_as_unread(world):
    """한 번도 안 들어와 본 가족은 읽은 자리가 없으니 안 읽은 쪽이다."""
    mine = send(world, world["a"], "약 챙기셨어요?")
    for _ in range(3):
        # 보낸 사람이 아무리 다시 열어도 김민수는 그대로 남아 있다
        assert room(world, world["a"])[mine]["unreadCount"] == 1


def test_the_sender_is_never_counted(world):
    """자기가 쓴 글을 안 읽었다고 세면 영영 0 이 되지 않는다."""
    mine = send(world, world["a"], "잘 주무셨어요?")
    room(world, world["b"])
    assert room(world, world["a"])[mine]["unreadCount"] == 0


def test_opening_the_room_reads_everything_before_it(world):
    first = send(world, world["a"], "첫 번째")
    second = send(world, world["a"], "두 번째")

    seen = room(world, world["b"])
    assert seen[first]["unreadCount"] == 0
    assert seen[second]["unreadCount"] == 0


def test_a_message_sent_after_you_left_stays_unread(world):
    room(world, world["b"])                      # 김민수가 먼저 훑고 나감
    later = send(world, world["a"], "나중에 보낸 말")
    assert room(world, world["a"])[later]["unreadCount"] == 1


def test_the_count_falls_one_by_one_as_family_reads(world):
    """가족이 셋이면 3 이 아니라 2 에서 시작한다 — 보낸 사람은 빼고 센다."""
    db = TestSession()
    try:
        c = Protector(phone_number="01055556666", display_name="김하늘", user_handle=b"h3")
        db.add(c)
        db.flush()
        db.add(FamilyMember(user_id=world["user"], protector_id=c.id))
        db.commit()
        third = c.id
    finally:
        db.close()

    mine = send(world, world["a"], "다들 잘 지내지?")
    assert room(world, world["a"])[mine]["unreadCount"] == 2

    room(world, world["b"])
    assert room(world, world["a"])[mine]["unreadCount"] == 1

    room(world, third)
    assert room(world, world["a"])[mine]["unreadCount"] == 0


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


def test_voice_carries_who_registered_it(world):
    """목소리는 등록한 사람 것이 아니라 그 인형 것이다.

    가족 모두에게 보이는데 이름만 있으면 '내가 올린 것' 으로 오해하기 쉽다.
    앱이 '딸 김지영 님이 등록' 이라고 적을 수 있게 등록자를 함께 준다.
    """
    db = TestSession()
    try:
        me = db.get(Protector, world["a"])
        me.relation = "딸"
        db.add(Voice(
            device_id=world["device"], protector_id=world["a"], name="김지영",
            status="ready", audio_url="https://b.s3.us-west-2.amazonaws.com/v.wav",
        ))
        # 인형에 들어 있는 기본 목소리는 등록자가 없다
        db.add(Voice(device_id=world["device"], protector_id=None,
                     name="기본 목소리", status="ready"))
        db.commit()
    finally:
        db.close()

    # 등록하지 않은 다른 가족이 봐도 등록자가 보인다
    voices = data(client.get(
        f"/devices/{world['device']}/settings", headers=auth(world["b"])
    ))["voices"]
    by_name = {v["name"]: v for v in voices}

    assert by_name["김지영"]["ownerName"] == "김지영"
    assert by_name["김지영"]["ownerRelation"] == "딸"
    assert by_name["기본 목소리"]["ownerName"] is None


# ── 다른 가족에게도 보이는지 ──────────────────────────
def test_home_badge_counts_what_the_other_family_member_sent(world):
    """지영이 보낸 메시지는 민수의 홈 배지에 떠야 하고, 민수가 열면 사라진다."""
    def badge(pid):
        return data(client.get(f"/home?userId={world['user']}", headers=auth(pid)))[
            "unreadChatCount"
        ]

    send(world, world["a"], "엄마 오늘 병원 다녀오셨어요")
    send(world, world["a"], "사진도 올릴게요")
    assert badge(world["b"]) == 2
    # 내가 보낸 건 내 배지에 뜨지 않는다.
    assert badge(world["a"]) == 0

    room(world, world["b"])
    assert badge(world["b"]) == 0


def test_a_reply_within_the_cooldown_still_alerts_the_first_sender(world):
    """지영이 보내 민수가 알림을 받은 직후 민수가 답해도, 지영은 알림을 받아야 한다.

    쿨다운은 '받는 사람' 마다 따로 센다. 어르신 단위로 세면 먼저 알림이 한 번
    나간 뒤로는 답장이 누구에게도 알려지지 않는다.
    """
    from app.models import Notification

    send(world, world["a"], "엄마 식사 잘 하셨대")
    send(world, world["b"], "다행이다")
    send(world, world["a"], "주말에 같이 가자")  # 지영의 두 번째 — 민수는 쿨다운 안

    db = TestSession()
    try:
        got = sorted(
            n.protector_id for n in db.scalars(select(Notification)).all()
        )
    finally:
        db.close()
    assert got == sorted([world["a"], world["b"]])


# ── 전달 완료 알림 · 어르신 답장 ─────────────────────
def _notifications(title: str) -> list:
    from app.models import Notification

    db = TestSession()
    try:
        return sorted(
            n.protector_id
            for n in db.scalars(
                select(Notification).where(Notification.title == title)
            ).all()
        )
    finally:
        db.close()


def _deliver(world, ids):
    return client.post(
        f"/devices/{world['device']}/chat/delivered",
        json={"messageIds": ids},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )


def test_delivery_alerts_only_the_sender_once(world):
    """인형이 읽어드리면 보낸 사람에게만 한 번 알린다. 다시 올려도 또 가지 않는다."""
    from app.models import NotificationSetting
    from app.services import notifications as notif

    db = TestSession()
    try:
        for pid in (world["a"], world["b"]):
            db.add(NotificationSetting(protector_id=pid, message_delivered=True))
        db.commit()
    finally:
        db.close()

    first = send(world, world["a"], "엄마 사랑해요")
    _deliver(world, [first])
    _deliver(world, [first])  # 인형이 응답을 못 받아 다시 올린 경우

    assert _notifications(notif.DELIVERED_TITLE) == [world["a"]]


def test_delivery_alert_respects_the_setting(world):
    """'메시지 전달 완료' 는 기본이 꺼짐이다. 손대지 않았으면 받지 않는다."""
    from app.services import notifications as notif

    _deliver(world, [send(world, world["a"], "밥 드셨어요?")])
    assert _notifications(notif.DELIVERED_TITLE) == []


def test_elder_reply_lands_in_the_room_for_everyone(world):
    """어르신 답장은 대화방에 어르신 이름으로 올라가고, 가족 모두 알림을 받는다."""
    from app.services import notifications as notif

    r = client.post(
        f"/devices/{world['device']}/chat/reply",
        data={"content": "  그래 고맙다 우리 딸  "},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )
    reply = data(r)
    assert r.status_code == 201
    assert reply["senderType"] == "user"
    assert reply["senderId"] is None
    assert reply["content"] == "그래 고맙다 우리 딸"

    # 두 가족 모두의 대화방에 같은 메시지가 보이고, 아직 둘 다 안 읽었다.
    for pid in (world["a"], world["b"]):
        assert room(world, pid)[reply["messageId"]]["content"] == "그래 고맙다 우리 딸"
    assert _notifications(notif.ELDER_REPLY_TITLE) == sorted([world["a"], world["b"]])

    # 인형이 자기가 받아 적은 말을 다시 읽어드리지 않는다.
    pending = data(client.get(
        f"/devices/{world['device']}/chat/pending",
        headers={"X-Device-Token": DEVICE_TOKEN},
    ))["messages"]
    assert pending == []


def test_elder_reply_counts_as_unread_for_every_family_member(world):
    r = client.post(
        f"/devices/{world['device']}/chat/reply",
        data={"content": "보고 싶구나"},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )
    mid = data(r)["messageId"]
    # 지영이 열어 보면 민수 한 명만 남는다.
    assert room(world, world["a"])[mid]["unreadCount"] == 1


def test_elder_reply_needs_the_device_token(world):
    r = client.post(
        f"/devices/{world['device']}/chat/reply", data={"content": "안녕"}
    )
    assert r.status_code in (401, 403)


def test_elder_reply_carries_the_voice(world, monkeypatch):
    """답장은 받아 적은 글과 말씀하신 목소리가 함께 올라간다."""
    from app.services.storage import storage

    saved = {}

    def fake_save(content, ext, prefix=""):
        saved.update(size=len(content), ext=ext, prefix=prefix)
        return "/uploads/chat-replies/r.wav"

    monkeypatch.setattr(storage, "save", fake_save)
    reply = data(client.post(
        f"/devices/{world['device']}/chat/reply",
        data={"content": "아이고, 많이 컸네 우리 손주."},
        files={"audio": ("reply.wav", b"RIFF-fake-wav", "audio/wav")},
        headers={"X-Device-Token": DEVICE_TOKEN},
    ))
    assert saved == {"size": len(b"RIFF-fake-wav"), "ext": ".wav", "prefix": "chat-replies"}
    assert reply["audioUrl"] == "/uploads/chat-replies/r.wav"
    # 가족 대화방에서도 같은 목소리를 들을 수 있다.
    assert room(world, world["b"])[reply["messageId"]]["audioUrl"] == reply["audioUrl"]


def test_elder_reply_without_voice_is_still_posted(world):
    """녹음이 없어도(올리기 실패 등) 글은 올라간다."""
    reply = data(client.post(
        f"/devices/{world['device']}/chat/reply",
        data={"content": "그래"},
        headers={"X-Device-Token": DEVICE_TOKEN},
    ))
    assert reply["audioUrl"] is None


def test_elder_reply_rejects_non_audio(world):
    r = client.post(
        f"/devices/{world['device']}/chat/reply",
        data={"content": "그래"},
        files={"audio": ("x.exe", b"MZ", "application/octet-stream")},
        headers={"X-Device-Token": DEVICE_TOKEN},
    )
    assert r.status_code == 400

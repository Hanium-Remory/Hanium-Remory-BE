"""알림 생성.

알림은 사람이 만드는 게 아니라 사건이 생길 때 서버가 만든다. 지금 다루는 사건:

  - 부정 감정이 이어질 때 (긴급)
  - 인형 연결이 끊겼다 돌아왔을 때 (긴급)
  - 가족이 대화방에 글·사진을 남겼을 때 (일반)
  - 데일리·주간 리포트가 만들어졌을 때 (리포트)

한 사건으로 알림이 쏟아지지 않게 종류별 쿨다운을 둔다. 같은 어르신·같은
종류의 알림이 쿨다운 안에 이미 있으면 새로 만들지 않는다.
"""

import datetime as dt
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Device, EmotionRecord, FamilyMember, Notification

# Notification.type — 앱의 알림 센터가 이 값으로 탭을 가른다.
TYPE_URGENT = 0
TYPE_REPORT = 1
TYPE_INFO = 2

# 이 감정이 이어지면 보호자에게 알린다.
NEGATIVE_EMOTIONS = {"sad", "angry", "anxious", "lonely"}

# 쿨다운을 사건별로 나누는 열쇠이기도 하다(_recently_sent 참고).
EMOTION_TITLE = "감정이 평소와 달라요"
RECONNECT_TITLE = "인형 연결이 잠시 끊겼어요"
CHAT_TITLE = "가족이 새 이야기를 남겼어요"
REPORT_TITLE = "오늘의 데일리 리포트가 준비됐어요"
WEEKLY_REPORT_TITLE = "이번 주 리포트가 준비됐어요"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(when: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if when is None:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _protector_ids(db: Session, user_id: int, exclude: Optional[int] = None) -> list[int]:
    """그 어르신에 연결된 보호자들. exclude 는 알림을 받지 않는다(보낸 본인 등)."""
    rows = db.scalars(
        select(FamilyMember.protector_id).where(FamilyMember.user_id == user_id)
    ).all()
    return [pid for pid in rows if pid != exclude]


def _recently_sent(db: Session, user_id: int, title: str, minutes: int) -> bool:
    """같은 어르신에게 같은 사건 알림이 쿨다운 안에 이미 있으면 True.

    type 이 아니라 title 로 본다. 감정 이상과 연결 끊김이 둘 다 긴급(0)이라
    type 으로 묶으면 한쪽이 다른 쪽을 막아버린다.
    """
    if minutes <= 0:
        return False
    since = _now() - dt.timedelta(minutes=minutes)
    found = db.scalars(
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.title == title,
            Notification.created_at >= since,
        )
        .limit(1)
    ).first()
    return found is not None


def _create(
    db: Session,
    *,
    user_id: int,
    type_: int,
    title: str,
    content: str,
    exclude_protector_id: Optional[int] = None,
) -> int:
    """연결된 보호자 전원에게 같은 알림을 만든다. 만든 개수를 준다."""
    protector_ids = _protector_ids(db, user_id, exclude=exclude_protector_id)
    if not protector_ids:
        return 0

    db.add_all(
        [
            Notification(
                protector_id=pid,
                user_id=user_id,
                type=type_,
                title=title,
                content=content,
            )
            for pid in protector_ids
        ]
    )
    db.commit()
    return len(protector_ids)


def notify_negative_emotion(db: Session, user_id: int, emotion: str) -> int:
    """부정 감정이 연속으로 이어지면 긴급 알림.

    한 번 나빴다고 알리면 시끄러우므로, 최근 기록이 연달아 부정일 때만 만든다.
    """
    if emotion not in NEGATIVE_EMOTIONS:
        return 0

    streak = settings.emotion_alert_streak
    recent = db.scalars(
        select(EmotionRecord.emotion)
        .where(EmotionRecord.user_id == user_id)
        .order_by(EmotionRecord.created_at.desc())
        .limit(streak)
    ).all()
    if len(recent) < streak or any(e not in NEGATIVE_EMOTIONS for e in recent):
        return 0

    if _recently_sent(db, user_id, EMOTION_TITLE, settings.emotion_alert_cooldown_min):
        return 0

    return _create(
        db,
        user_id=user_id,
        type_=TYPE_URGENT,
        title=EMOTION_TITLE,
        content=(
            f"최근 {streak}번의 기록이 이어서 좋지 않았어요. "
            "직접 전화 한 통 드려보시는 건 어떨까요?"
        ),
    )


def notify_reconnected(db: Session, device: Device, previous_heartbeat: Optional[dt.datetime]) -> int:
    """인형이 한동안 끊겼다가 다시 연결됐을 때 알린다.

    처음 켜는 경우(이전 기록 없음)는 알리지 않는다. 끊김 자체는 인형이 아무
    요청도 못 보내는 상태라 여기서 알 수 없고, 돌아왔을 때 비로소 알 수 있다.
    """
    previous = _aware(previous_heartbeat)
    if previous is None or device.user_id is None:
        return 0

    gap = (_now() - previous).total_seconds()
    if gap <= settings.device_offline_after_sec:
        return 0

    # 신호가 오락가락하면 재연결이 반복되므로 여기에도 쿨다운을 둔다.
    if _recently_sent(db, device.user_id, RECONNECT_TITLE, settings.reconnect_alert_cooldown_min):
        return 0

    minutes = int(gap // 60)
    return _create(
        db,
        user_id=device.user_id,
        type_=TYPE_URGENT,
        title=RECONNECT_TITLE,
        content=f"{minutes}분 만에 다시 연결되었어요. 와이파이 신호를 확인해보세요.",
    )


def notify_chat_message(
    db: Session,
    user_id: int,
    sender_protector_id: int,
    has_image: bool,
) -> int:
    """가족이 대화방에 남긴 글·사진을 나머지 가족에게 알린다.

    보낸 사람은 받지 않는다. 여러 개를 연달아 보내도 쿨다운 안에서는 한 번만
    알린다.
    """
    if _recently_sent(db, user_id, CHAT_TITLE, settings.chat_alert_cooldown_min):
        return 0

    return _create(
        db,
        user_id=user_id,
        type_=TYPE_INFO,
        title=CHAT_TITLE,
        content="사진을 보냈어요." if has_image else "대화방에서 확인해보세요.",
        exclude_protector_id=sender_protector_id,
    )


def notify_weekly_report_ready(db: Session, user_id: int, summary: str) -> int:
    """주간 리포트가 만들어졌을 때 알린다. 주에 한 번뿐이라 쿨다운이 없다."""
    return _create(
        db,
        user_id=user_id,
        type_=TYPE_REPORT,
        title=WEEKLY_REPORT_TITLE,
        content=summary,
    )


def notify_report_ready(db: Session, user_id: int, summary: str) -> int:
    """데일리 리포트가 만들어졌을 때 알린다.

    리포트는 하루에 한 번만 만들어지므로 따로 쿨다운을 두지 않는다.
    """
    return _create(
        db,
        user_id=user_id,
        type_=TYPE_REPORT,
        title=REPORT_TITLE,
        content=summary,
    )

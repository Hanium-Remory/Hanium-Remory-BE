"""홈 대시보드 통합 조회.

홈 화면 1회 호출로 필요한 걸 다 모아서 준다:
연결 상태·대화중 여부·배터리·현재 감정·감정 추이·활동 타임라인·미확인 알림 수·새 메시지 수.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import envelope
from ..models import (
    ActivityLog,
    Device,
    EmotionRecord,
    FamilyChatMessage,
    Notification,
    Protector,
)
from ..services.access import (
    activity_json,
    battery_hours_left,
    emotion_json,
    get_owned_user,
    is_connected,
)

router = APIRouter(tags=["home"])

EMOTION_TREND_LIMIT = 7
ACTIVITY_LIMIT = 10


@router.get("/home")
def get_home(
    userId: int = Query(..., description="조회할 어르신 id"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """홈 대시보드 통합 조회. 예) GET /home?userId=1"""
    user = get_owned_user(db, protector, userId)

    # 기기 상태 (해당 어르신의 대표 기기 1대)
    device = db.scalars(
        select(Device).where(Device.user_id == user.id).order_by(Device.created_at)
    ).first()
    device_info = None
    if device is not None:
        device_info = {
            "deviceId": device.id,
            "name": device.name,
            "connected": is_connected(device),
            # 인형이 음성인식을 시작하면 True 로 바뀐다(PATCH /devices/{id}/conversation).
            # 인형이 죽어(하트비트 끊김) 값이 남아 있어도 대화중으로 보지 않는다.
            "inConversation": device.in_conversation and is_connected(device),
            "batteryLevel": device.battery_level,
            "batteryHoursLeft": battery_hours_left(device),
        }

    # 감정 추이(최근 N개) — 첫 번째가 곧 현재 감정
    trend = db.scalars(
        select(EmotionRecord)
        .where(EmotionRecord.user_id == user.id)
        .order_by(EmotionRecord.created_at.desc())
        .limit(EMOTION_TREND_LIMIT)
    ).all()

    # 활동 타임라인(최근 N개)
    activities = db.scalars(
        select(ActivityLog)
        .where(ActivityLog.user_id == user.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(ACTIVITY_LIMIT)
    ).all()

    # 미확인 알림 수 (내 알림 중 안 읽고 안 지운 것)
    unread_notifications = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.protector_id == protector.id,
            Notification.is_read.is_(False),
            Notification.is_deleted.is_(False),
        )
    )

    # 새 가족 메시지 수 (보호자 본인이 보낸 건 제외)
    unread_chat = db.scalar(
        select(func.count(FamilyChatMessage.id)).where(
            FamilyChatMessage.user_id == user.id,
            FamilyChatMessage.sender_type != "protector",
            FamilyChatMessage.is_read.is_(False),
        )
    )

    return envelope(
        {
            "user": {"userId": user.id, "name": user.name},
            "device": device_info,
            "currentEmotion": emotion_json(trend[0]) if trend else None,
            "emotionTrend": [emotion_json(e) for e in trend],
            "activities": [activity_json(a) for a in activities],
            "unreadNotificationCount": unread_notifications or 0,
            "unreadChatCount": unread_chat or 0,
        },
        "OK",
        200,
    )

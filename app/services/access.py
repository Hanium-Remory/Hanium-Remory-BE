"""설정 API 공용: 소유권 검사와 응답 직렬화.

보호자는 자신이 가족 멤버로 연결된 어르신(User)과 그 인형(Device)만 조회·수정할 수 있다.
없는 리소스와 권한 없는 리소스를 구분하면 존재 여부가 새므로 둘 다 404로 응답한다.
"""

import datetime as dt
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..errors import APIError
from ..models import (
    ActivityLog,
    DailyReport,
    Device,
    DndSetting,
    EmotionRecord,
    FamilyChatMessage,
    FamilyMember,
    Medication,
    Memory,
    Notification,
    NotificationSetting,
    Protector,
    User,
    Voice,
    WeeklyReport,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(when: Optional[dt.datetime]) -> Optional[dt.datetime]:
    """SQLite에서 읽은 naive datetime을 UTC로 맞춘다."""
    if when is None:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def iso(when: Optional[dt.datetime]) -> Optional[str]:
    aware = _aware(when)
    return aware.isoformat() if aware else None


# ── 소유권 검사 ──────────────────────────────────────
def get_membership(db: Session, protector_id: int, user_id: int) -> FamilyMember:
    membership = db.scalars(
        select(FamilyMember).where(
            FamilyMember.user_id == user_id, FamilyMember.protector_id == protector_id
        )
    ).first()
    if membership is None:
        raise APIError(404, "연결된 사용자를 찾을 수 없습니다.")
    return membership


def get_owned_user(db: Session, protector: Protector, user_id: int) -> User:
    get_membership(db, protector.id, user_id)
    user = db.get(User, user_id)
    if user is None:
        raise APIError(404, "연결된 사용자를 찾을 수 없습니다.")
    return user


def get_owned_device(db: Session, protector: Protector, device_id: int) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise APIError(404, "인형을 찾을 수 없습니다.")
    membership = db.scalars(
        select(FamilyMember).where(
            FamilyMember.user_id == device.user_id, FamilyMember.protector_id == protector.id
        )
    ).first()
    if membership is None:
        raise APIError(404, "인형을 찾을 수 없습니다.")
    return device


def get_owned_medication(db: Session, protector: Protector, medication_id: int) -> Medication:
    medication = db.get(Medication, medication_id)
    if medication is None:
        raise APIError(404, "약을 찾을 수 없습니다.")
    get_owned_device(db, protector, medication.device_id)  # 권한 없으면 404
    return medication


def primary_membership(db: Session, user_id: int) -> Optional[FamilyMember]:
    return db.scalars(
        select(FamilyMember).where(
            FamilyMember.user_id == user_id, FamilyMember.is_primary.is_(True)
        )
    ).first()


# ── 기본값 보장 ──────────────────────────────────────
def ensure_notification_setting(db: Session, protector: Protector) -> NotificationSetting:
    setting = db.scalars(
        select(NotificationSetting).where(NotificationSetting.protector_id == protector.id)
    ).first()
    if setting is None:
        setting = NotificationSetting(protector_id=protector.id)
        db.add(setting)
        db.flush()
    return setting


DEFAULT_VOICE_NAME = "기본 목소리"


def ensure_default_voice(db: Session, device: Device) -> Voice:
    """기기의 기본 제공 목소리를 보장한다.

    가족이 아직 목소리를 학습시키지 않았어도 인형이 말할 수 있어야 하므로,
    특정 보호자에 속하지 않는(protector_id=None) 기본 음성을 하나 유지한다.
    """
    voice = db.scalars(
        select(Voice).where(Voice.device_id == device.id, Voice.protector_id.is_(None))
    ).first()
    if voice is None:
        voice = Voice(
            device_id=device.id,
            protector_id=None,
            name=DEFAULT_VOICE_NAME,
            status="ready",
            progress=100,
        )
        db.add(voice)
        db.flush()
    # 지정된 기본 음성이 없으면 이 목소리로 채워둔다.
    if device.default_voice_id is None:
        device.default_voice_id = voice.id
    return voice


def ensure_dnd(db: Session, device: Device) -> DndSetting:
    dnd = db.scalars(select(DndSetting).where(DndSetting.device_id == device.id)).first()
    if dnd is None:
        dnd = DndSetting(device_id=device.id)
        db.add(dnd)
        db.flush()
    return dnd


# ── 직렬화 ───────────────────────────────────────────
def notification_settings_json(setting: NotificationSetting) -> dict:
    return {
        "urgent": setting.urgent,
        "dailyReport": setting.daily_report,
        "chat": setting.chat,
        "marketing": setting.marketing,
        "emotionChange": setting.emotion_change,
        "deviceDisconnected": setting.device_disconnected,
        "medicationMissed": setting.medication_missed,
        "voiceRequest": setting.voice_request,
        "messageDelivered": setting.message_delivered,
        "voiceTrainingCompleted": setting.voice_training_completed,
        "weeklyReport": setting.weekly_report,
        "appUpdate": setting.app_update,
    }


def calc_age(birth_date: Optional[dt.date]) -> Optional[int]:
    """만 나이."""
    if birth_date is None:
        return None
    today = _now().date()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def user_json(user: User, device: Optional[Device] = None) -> dict:
    return {
        "userId": user.id,
        "name": user.name,
        "gender": user.gender,
        "birthDate": user.birth_date.isoformat() if user.birth_date else None,
        "age": calc_age(user.birth_date),
        "photoUrl": user.photo_url,
        "note": user.note,
        "deviceId": device.id if device else None,
        "createdAt": iso(user.created_at),
    }


def is_connected(device: Device) -> bool:
    """마지막 heartbeat가 임계 시간 안이면 연결된 것으로 본다."""
    last = _aware(device.last_heartbeat_at)
    if last is None:
        return False
    return (_now() - last).total_seconds() <= settings.device_offline_after_sec


def battery_hours_left(device: Device) -> int:
    return round(device.battery_level / 100 * settings.device_battery_full_hours)


def voice_json(voice: Voice, device: Device) -> dict:
    return {
        "voiceId": voice.id,
        "name": voice.name,
        "protectorId": voice.protector_id,
        "status": voice.status,
        "progress": voice.progress,
        "isDefault": device.default_voice_id == voice.id,
    }


def device_json(db: Session, device: Device) -> dict:
    voices = db.scalars(
        select(Voice).where(Voice.device_id == device.id).order_by(Voice.created_at)
    ).all()
    return {
        "deviceId": device.id,
        "userId": device.user_id,
        "name": device.name,
        "serial": device.serial,
        "connected": is_connected(device),
        "batteryLevel": device.battery_level,
        "batteryHoursLeft": battery_hours_left(device),
        "lastHeartbeatAt": iso(device.last_heartbeat_at),
        "volume": device.volume,
        "medicationCheck": device.medication_check,
        "defaultVoiceId": device.default_voice_id,
        "voices": [voice_json(v, device) for v in voices],
        "pairedAt": iso(device.created_at),
    }


def dnd_json(dnd: DndSetting) -> dict:
    return {
        "deviceId": dnd.device_id,
        "enabled": dnd.enabled,
        "startHour": dnd.start_hour,
        "endHour": dnd.end_hour,
        "allowUrgentAlert": dnd.allow_urgent_alert,
        "allowWakeWord": dnd.allow_wake_word,
    }


def medication_json(medication: Medication) -> dict:
    return {
        "medicationId": medication.id,
        "deviceId": medication.device_id,
        "name": medication.name,
        "time": medication.time,
        "timing": medication.timing,
        "enabled": medication.enabled,
        "createdAt": iso(medication.created_at),
    }


# ── 기능(홈·추억·대화·감정·활동·알림·리포트) 직렬화 ──────────
def memory_json(memory: Memory) -> dict:
    return {
        "memoryId": memory.id,
        "imageUrl": memory.image_url,
        "title": memory.title,
        "period": memory.period,
        "description": memory.description,
        "createdAt": iso(memory.created_at),
    }


def emotion_json(record: EmotionRecord) -> dict:
    return {
        "emotionId": record.id,
        "emotion": record.emotion,
        "createdAt": iso(record.created_at),
    }


def activity_json(log: ActivityLog) -> dict:
    return {
        "activityId": log.id,
        "activityType": log.activity_type,
        "content": log.content,
        "createdAt": iso(log.created_at),
    }


def notification_json(notification: Notification) -> dict:
    return {
        "notificationId": notification.id,
        "type": notification.type,
        "title": notification.title,
        "content": notification.content,
        "isRead": notification.is_read,
        "createdAt": iso(notification.created_at),
    }


def chat_message_json(message: FamilyChatMessage) -> dict:
    return {
        "messageId": message.id,
        "senderType": message.sender_type,
        "senderId": message.sender_id,
        "content": message.content,
        "imageUrl": message.image_url,
        "createdAt": iso(message.created_at),
    }


def daily_report_json(report: DailyReport) -> dict:
    return {
        "reportId": report.id,
        "conversationCount": report.conversation_count,
        "familyInteractionCount": report.family_interaction_count,
        "emotionSummary": report.emotion_summary,
        "summary": report.summary,
        "createdAt": iso(report.created_at),
    }


def weekly_report_json(report: WeeklyReport) -> dict:
    return {
        "reportId": report.id,
        "totalConversationCount": report.total_conversation_count,
        "familyInteractionCount": report.family_interaction_count,
        "avgEmotionScore": report.avg_emotion_score,
        "dominantEmotion": report.dominant_emotion,
        "emergencyAlertCount": report.emergency_alert_count,
        "weeklySummary": report.weekly_summary,
        "createdAt": iso(report.created_at),
    }

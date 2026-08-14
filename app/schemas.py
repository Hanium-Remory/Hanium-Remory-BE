import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CamelModel(BaseModel):
    """JSON은 camelCase(앱 관례), 내부는 그대로 접근."""

    model_config = ConfigDict(populate_by_name=True)


# ── 전화번호 인증 ────────────────────────────────────
class PhoneCodeRequest(CamelModel):
    phone_number: str = Field(alias="phoneNumber", min_length=9, max_length=20)


class PhoneVerifyRequest(CamelModel):
    phone_number: str = Field(alias="phoneNumber", min_length=9, max_length=20)
    code: str = Field(min_length=4, max_length=6)


# ── 패스키 등록 ──────────────────────────────────────
class RegistrationOptionsRequest(CamelModel):
    display_name: Optional[str] = Field(default=None, alias="displayName")


class RegistrationRequest(CamelModel):
    credential_id: str = Field(alias="credentialId")
    client_data_json: str = Field(alias="clientDataJSON")
    attestation_object: str = Field(alias="attestationObject")


# ── 패스키 로그인 ────────────────────────────────────
class AuthOptionsRequest(CamelModel):
    # 없으면 discoverable credential(usernameless) 로그인
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber")


class AuthenticationRequest(CamelModel):
    credential_id: str = Field(alias="credentialId")
    client_data_json: str = Field(alias="clientDataJSON")
    authenticator_data: str = Field(alias="authenticatorData")
    signature: str = Field(alias="signature")
    user_handle: Optional[str] = Field(default=None, alias="userHandle")


# ── 토큰 ─────────────────────────────────────────────
class RefreshRequest(CamelModel):
    refresh_token: str = Field(alias="refreshToken")


class LogoutRequest(CamelModel):
    refresh_token: str = Field(alias="refreshToken")


# ── 보호자 프로필 ────────────────────────────────────
RELATIONS = {"딸", "아들", "며느리", "사위", "손주", "손녀", "기타"}


class ProtectorUpdateRequest(CamelModel):
    """PUT /protectors/me. 보내지 않은 필드는 변경하지 않는다."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    relation: Optional[str] = Field(default=None, max_length=10)
    profile_image_url: Optional[str] = Field(
        default=None, alias="profileImageUrl", max_length=500
    )
    # 인증된 번호와 같을 때만 허용(변경은 전화번호 재인증 필요).
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber", max_length=20)

    @field_validator("relation")
    @classmethod
    def _check_relation(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in RELATIONS:
            raise ValueError(f"관계는 {', '.join(sorted(RELATIONS))} 중 하나여야 합니다.")
        return v


class NotificationSettingsRequest(CamelModel):
    """PATCH /protectors/me/notification-settings. 보낸 항목만 부분 수정."""

    urgent: Optional[bool] = None
    daily_report: Optional[bool] = Field(default=None, alias="dailyReport")
    chat: Optional[bool] = None
    marketing: Optional[bool] = None
    emotion_change: Optional[bool] = Field(default=None, alias="emotionChange")
    device_disconnected: Optional[bool] = Field(default=None, alias="deviceDisconnected")
    medication_missed: Optional[bool] = Field(default=None, alias="medicationMissed")
    voice_request: Optional[bool] = Field(default=None, alias="voiceRequest")
    message_delivered: Optional[bool] = Field(default=None, alias="messageDelivered")
    voice_training_completed: Optional[bool] = Field(
        default=None, alias="voiceTrainingCompleted"
    )
    weekly_report: Optional[bool] = Field(default=None, alias="weeklyReport")
    app_update: Optional[bool] = Field(default=None, alias="appUpdate")


# ── 어르신(User) 정보 ────────────────────────────────
GENDERS = {"female", "male"}
_GENDER_KO = {"여성": "female", "남성": "male", "여": "female", "남": "male"}


class UserUpdateRequest(CamelModel):
    """PUT /users/{userId}. 보내지 않은 필드는 변경하지 않는다."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    gender: Optional[str] = Field(default=None, max_length=10)
    birth_date: Optional[dt.date] = Field(default=None, alias="birthDate")
    photo_url: Optional[str] = Field(default=None, alias="photoUrl", max_length=500)
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("gender")
    @classmethod
    def _normalize_gender(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = _GENDER_KO.get(v, v).lower()
        if v not in GENDERS:
            raise ValueError("성별은 female 또는 male 이어야 합니다.")
        return v


# ── 인형(Device) 설정 ────────────────────────────────
class DeviceSettingsRequest(CamelModel):
    """PUT /devices/{deviceId}/settings."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=30)
    volume: Optional[int] = Field(default=None, ge=0, le=100)
    default_voice_id: Optional[int] = Field(default=None, alias="defaultVoiceId")
    medication_check: Optional[bool] = Field(default=None, alias="medicationCheck")


class DefaultVoiceRequest(CamelModel):
    """PATCH /devices/{deviceId}/settings/voice."""

    voice_id: int = Field(alias="voiceId")


class DndRequest(CamelModel):
    """PUT /devices/{deviceId}/dnd."""

    enabled: Optional[bool] = None
    start_hour: Optional[int] = Field(default=None, alias="startHour", ge=0, le=23)
    end_hour: Optional[int] = Field(default=None, alias="endHour", ge=0, le=23)
    allow_urgent_alert: Optional[bool] = Field(default=None, alias="allowUrgentAlert")
    allow_wake_word: Optional[bool] = Field(default=None, alias="allowWakeWord")


# ── 약 복용 ──────────────────────────────────────────
TIMINGS = {"식전", "식후", "공복", "아무때나"}
_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class MedicationCreateRequest(CamelModel):
    """POST /devices/{deviceId}/medications."""

    name: str = Field(min_length=1, max_length=50)
    time: str = Field(pattern=_TIME_PATTERN)  # "08:00"
    timing: str = Field(default="식후", max_length=10)
    enabled: bool = True

    @field_validator("timing")
    @classmethod
    def _check_timing(cls, v: str) -> str:
        if v not in TIMINGS:
            raise ValueError(f"복용 시점은 {', '.join(sorted(TIMINGS))} 중 하나여야 합니다.")
        return v


class MedicationUpdateRequest(CamelModel):
    """PUT /medications/{id}. 보내지 않은 필드는 변경하지 않는다."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    time: Optional[str] = Field(default=None, pattern=_TIME_PATTERN)
    timing: Optional[str] = Field(default=None, max_length=10)
    enabled: Optional[bool] = None

    @field_validator("timing")
    @classmethod
    def _check_timing(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in TIMINGS:
            raise ValueError(f"복용 시점은 {', '.join(sorted(TIMINGS))} 중 하나여야 합니다.")
        return v


# ── 기기 등록 ────────────────────────────────────────
class DevicePairRequest(CamelModel):
    """POST /devices. 인형을 어르신에게 연결한다."""

    user_id: int = Field(alias="userId")
    serial: Optional[str] = Field(default=None, max_length=64)
    name: Optional[str] = Field(default=None, max_length=30)


# ── 추억 ─────────────────────────────────────────────
class MemoryCreateRequest(CamelModel):
    """POST /users/{id}/memories."""

    image_url: str = Field(alias="imageUrl", max_length=500)
    title: str = Field(min_length=1, max_length=100)
    period: Optional[str] = Field(default=None, max_length=50)  # 예: "1980년대"
    description: Optional[str] = None


# ── 가족 대화 ────────────────────────────────────────
class ChatMessageCreateRequest(CamelModel):
    """POST /users/{id}/chat/messages. 글이나 사진 중 하나는 있어야 한다."""

    content: Optional[str] = None
    image_url: Optional[str] = Field(default=None, alias="imageUrl", max_length=500)


# ── 음성 ─────────────────────────────────────────────
class VoiceRegisterRequest(CamelModel):
    """POST /devices/{id}/voices (multipart 의 name 필드와 함께 사용)."""

    name: str = Field(min_length=1, max_length=50)

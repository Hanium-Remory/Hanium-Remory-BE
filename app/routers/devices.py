"""인형(모리) 상태·설정, 방해 금지 시간, 약 목록."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import secrets

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Device, Medication, Protector, Voice
from ..schemas import (
    DefaultVoiceRequest,
    DevicePairRequest,
    DeviceSettingsRequest,
    DndRequest,
    MedicationCreateRequest,
)
from ..services.access import (
    device_json,
    dnd_json,
    ensure_default_voice,
    ensure_dnd,
    get_owned_device,
    get_owned_user,
    medication_json,
)

router = APIRouter(prefix="/devices", tags=["devices"])


def _get_voice(db: Session, device_id: int, voice_id: int) -> Voice:
    voice = db.get(Voice, voice_id)
    if voice is None or voice.device_id != device_id:
        raise APIError(404, "목소리를 찾을 수 없습니다.")
    if voice.status != "ready":
        raise APIError(400, "아직 학습이 끝나지 않은 목소리입니다.")
    return voice


# ── 기기 등록 ────────────────────────────────────────
@router.post("", status_code=201)
def pair_device(
    body: DevicePairRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """인형(모리) 기기를 어르신에게 연결한다 (등록 3/3).

    등록과 동시에 기본 목소리를 만들어 두어, 가족이 목소리를 학습시키기 전에도
    인형이 말할 수 있게 한다.
    """
    user = get_owned_user(db, protector, body.user_id)

    if body.serial:
        exists = db.scalars(select(Device).where(Device.serial == body.serial)).first()
        if exists is not None:
            raise APIError(409, "이미 등록된 기기입니다.")

    device = Device(
        user_id=user.id,
        name=body.name or "모리",
        serial=body.serial,
        device_token=secrets.token_urlsafe(32),
    )
    db.add(device)
    db.flush()

    ensure_default_voice(db, device)  # 기본 목소리 + 기본 음성 지정
    ensure_dnd(db, device)
    db.commit()
    db.refresh(device)

    return envelope(device_json(db, device), "기기를 등록했습니다.", 201)


# ── 인형 상태·설정 ───────────────────────────────────
@router.get("/{device_id}/settings")
def get_device_settings(
    device_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """연결 상태·배터리·등록 음성·볼륨·기본 음성."""
    device = get_owned_device(db, protector, device_id)
    return envelope(device_json(db, device), "OK", 200)


@router.put("/{device_id}/settings")
def update_device_settings(
    device_id: int,
    body: DeviceSettingsRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """인형 이름·볼륨·기본 음성·복용 확인 여부 수정."""
    device = get_owned_device(db, protector, device_id)
    fields = body.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"] is not None:
        device.name = fields["name"].strip()
    if "volume" in fields and fields["volume"] is not None:
        device.volume = fields["volume"]
    if "medication_check" in fields and fields["medication_check"] is not None:
        device.medication_check = fields["medication_check"]
    if "default_voice_id" in fields:
        voice_id = fields["default_voice_id"]
        if voice_id is None:
            device.default_voice_id = None
        else:
            device.default_voice_id = _get_voice(db, device.id, voice_id).id

    db.commit()
    return envelope(device_json(db, device), "인형 설정을 저장했습니다.", 200)


@router.patch("/{device_id}/settings/voice")
def set_default_voice(
    device_id: int,
    body: DefaultVoiceRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """목록에서 특정 음성을 기본 음성으로 지정."""
    device = get_owned_device(db, protector, device_id)
    voice = _get_voice(db, device.id, body.voice_id)
    device.default_voice_id = voice.id
    db.commit()
    return envelope(
        {"deviceId": device.id, "defaultVoiceId": voice.id, "name": voice.name},
        "기본 목소리를 변경했습니다.",
        200,
    )


# ── 방해 금지 시간 ───────────────────────────────────
@router.get("/{device_id}/dnd")
def get_dnd(
    device_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """방해 금지 시간 조회. 설정한 적이 없으면 기본값(23시~7시)을 만들어 돌려준다."""
    device = get_owned_device(db, protector, device_id)
    dnd = ensure_dnd(db, device)
    db.commit()
    return envelope(dnd_json(dnd), "OK", 200)


@router.put("/{device_id}/dnd")
def update_dnd(
    device_id: int,
    body: DndRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """방해 금지 시간 수정. 시작·종료 시각이 같으면 종일이 되므로 막는다."""
    device = get_owned_device(db, protector, device_id)
    dnd = ensure_dnd(db, device)
    fields = body.model_dump(exclude_unset=True)

    for key in (
        "enabled",
        "start_hour",
        "end_hour",
        "allow_urgent_alert",
        "allow_wake_word",
    ):
        if key in fields and fields[key] is not None:
            setattr(dnd, key, fields[key])

    if dnd.start_hour == dnd.end_hour:
        raise APIError(400, "시작 시각과 종료 시각이 같을 수 없습니다.")

    db.commit()
    return envelope(dnd_json(dnd), "방해 금지 시간을 저장했습니다.", 200)


# ── 약 복용 시간 ─────────────────────────────────────
@router.get("/{device_id}/medications")
def list_medications(
    device_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """약 복용 목록 조회."""
    device = get_owned_device(db, protector, device_id)
    rows = db.scalars(
        select(Medication)
        .where(Medication.device_id == device.id)
        .order_by(Medication.time, Medication.id)
    ).all()
    return envelope(
        {
            "deviceId": device.id,
            "medicationCheck": device.medication_check,
            "medications": [medication_json(m) for m in rows],
        },
        "OK",
        200,
    )


@router.post("/{device_id}/medications", status_code=201)
def create_medication(
    device_id: int,
    body: MedicationCreateRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """약 추가."""
    device = get_owned_device(db, protector, device_id)
    medication = Medication(
        device_id=device.id,
        name=body.name.strip(),
        time=body.time,
        timing=body.timing,
        enabled=body.enabled,
    )
    db.add(medication)
    db.commit()
    return envelope(medication_json(medication), "약을 추가했습니다.", 201)

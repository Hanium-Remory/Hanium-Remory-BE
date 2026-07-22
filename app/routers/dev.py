"""개발 전용 유틸. settings.debug=True 일 때만 동작한다.

어르신·인형을 만드는 정식 경로는 첫 등록/초대 코드 플로우이지만 아직 구현 전이라,
설정 화면을 붙여볼 수 있도록 샘플 데이터를 만들어 주는 엔드포인트를 둔다.
"""

import datetime as dt
import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Device, FamilyMember, Medication, Protector, User, Voice

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/seed")
def seed_demo_data(
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """현재 보호자에게 샘플 어르신·인형·목소리·약을 연결한다(이미 있으면 그대로 반환)."""
    if not settings.debug:
        raise APIError(404, "찾을 수 없습니다.")

    membership = db.scalars(
        select(FamilyMember).where(FamilyMember.protector_id == protector.id)
    ).first()
    if membership is not None:
        device = db.scalars(select(Device).where(Device.user_id == membership.user_id)).first()
        return envelope(
            {"userId": membership.user_id, "deviceId": device.id if device else None},
            "이미 연결된 데이터가 있습니다.",
            200,
        )

    user = User(name="박순자", gender="female", birth_date=dt.date(1952, 3, 15))
    db.add(user)
    db.flush()

    db.add(FamilyMember(user_id=user.id, protector_id=protector.id, is_primary=True))

    device = Device(
        user_id=user.id,
        name="모리",
        serial=f"MORI-{secrets.token_hex(3).upper()}",
        device_token=secrets.token_urlsafe(32),
        battery_level=78,
        volume=80,
    )
    db.add(device)
    db.flush()

    my_voice = Voice(
        device_id=device.id,
        protector_id=protector.id,
        name=protector.display_name,
        status="ready",
        progress=100,
    )
    default_voice = Voice(device_id=device.id, name="기본 목소리", status="ready", progress=100)
    db.add_all([my_voice, default_voice])
    db.flush()
    device.default_voice_id = my_voice.id

    db.add_all(
        [
            Medication(device_id=device.id, name="아침 혈압약", time="08:00", timing="식후"),
            Medication(device_id=device.id, name="저녁 영양제", time="19:00", timing="식후"),
        ]
    )
    db.commit()

    return envelope(
        {"userId": user.id, "deviceId": device.id, "deviceToken": device.device_token},
        "샘플 데이터를 생성했습니다.",
        201,
    )

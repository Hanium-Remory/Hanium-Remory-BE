"""가족 멤버 제거."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Device, FamilyMember, Protector, Voice

router = APIRouter(prefix="/family-members", tags=["family-members"])


@router.delete("/{protector_id}")
def remove_family_member(
    protector_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """가족 구성원을 어르신 연결에서 제거한다(주보호자만 가능).

    제거된 가족이 등록했던 인형 목소리도 함께 지운다.
    """
    if protector_id == protector.id:
        raise APIError(400, "본인은 회원 탈퇴로 연결을 해제할 수 있습니다.")

    # 나와 대상이 함께 연결된 어르신을 찾는다(경로에 userId가 없으므로).
    my_user_ids = set(
        db.scalars(
            select(FamilyMember.user_id).where(FamilyMember.protector_id == protector.id)
        ).all()
    )
    targets = (
        db.scalars(
            select(FamilyMember).where(
                FamilyMember.protector_id == protector_id,
                FamilyMember.user_id.in_(my_user_ids),
            )
        ).all()
        if my_user_ids
        else []
    )
    if not targets:
        raise APIError(404, "가족 구성원을 찾을 수 없습니다.")

    for target in targets:
        me = db.scalars(
            select(FamilyMember).where(
                FamilyMember.user_id == target.user_id,
                FamilyMember.protector_id == protector.id,
            )
        ).first()
        if me is None or not me.is_primary:
            raise APIError(403, "주보호자만 가족을 제거할 수 있습니다.")
        if target.is_primary:
            raise APIError(400, "주보호자는 제거할 수 없습니다.")

        device_ids = db.scalars(select(Device.id).where(Device.user_id == target.user_id)).all()
        if device_ids:
            voices = db.scalars(
                select(Voice).where(
                    Voice.device_id.in_(device_ids), Voice.protector_id == protector_id
                )
            ).all()
            for voice in voices:
                device = db.get(Device, voice.device_id)
                if device is not None and device.default_voice_id == voice.id:
                    device.default_voice_id = None
                db.delete(voice)

        db.delete(target)

    db.commit()
    return envelope({"protectorId": protector_id}, "가족 구성원을 제거했습니다.", 200)

"""보호자 본인 정보·알림 설정·회원 탈퇴."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Device, FamilyMember, Protector, User
from ..schemas import NotificationSettingsRequest, ProtectorUpdateRequest
from ..services.access import (
    ensure_notification_setting,
    ensure_own_image,
    notification_settings_json,
    iso,
)

router = APIRouter(prefix="/protectors", tags=["protectors"])


def normalize_phone(phone: str) -> str:
    return phone.replace("-", "").replace(" ", "").strip()


def _linked_users(db: Session, protector: Protector) -> list[dict]:
    """내가 돌보는 어르신 목록. 앱이 userId·deviceId를 얻는 진입점."""
    rows = db.scalars(
        select(FamilyMember)
        .where(FamilyMember.protector_id == protector.id)
        .order_by(FamilyMember.created_at)
    ).all()
    result = []
    for membership in rows:
        user = db.get(User, membership.user_id)
        if user is None:
            continue
        device = db.scalars(
            select(Device).where(Device.user_id == user.id).order_by(Device.created_at)
        ).first()
        result.append(
            {
                "userId": user.id,
                "name": user.name,
                "deviceId": device.id if device else None,
                "isPrimary": membership.is_primary,
            }
        )
    return result


def _protector_json(db: Session, protector: Protector) -> dict:
    setting = ensure_notification_setting(db, protector)
    return {
        "protectorId": protector.id,
        "name": protector.display_name,
        "phoneNumber": protector.phone_number,
        "relation": protector.relation,
        "profileImageUrl": protector.profile_image_url,
        "onboardingCompleted": protector.onboarding_completed,
        "createdAt": iso(protector.created_at),
        "users": _linked_users(db, protector),
        "notificationSettings": notification_settings_json(setting),
    }


@router.get("/me")
def get_me(
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """보호자 본인 정보 + 내가 받는 알림 설정."""
    data = _protector_json(db, protector)
    db.commit()  # 알림 설정 기본값이 처음 생성됐다면 저장
    return envelope(data, "OK", 200)


@router.put("/me")
def update_me(
    body: ProtectorUpdateRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """이름·관계·프로필 사진 수정.

    전화번호는 여기서 바꿀 수 없다(SMS 재인증 필요). 현재 번호와 같은 값이면 무시한다.
    """
    fields = body.model_dump(exclude_unset=True)

    if "phone_number" in fields and fields["phone_number"] is not None:
        if normalize_phone(fields["phone_number"]) != (protector.phone_number or ""):
            raise APIError(400, "전화번호는 인증을 통해서만 변경할 수 있습니다.")

    if "name" in fields and fields["name"] is not None:
        protector.display_name = fields["name"].strip()
    if "relation" in fields:
        protector.relation = fields["relation"]
    if "profile_image_url" in fields:
        ensure_own_image(fields["profile_image_url"], protector.id)
        protector.profile_image_url = fields["profile_image_url"]

    data = _protector_json(db, protector)
    db.commit()
    return envelope(data, "프로필을 수정했습니다.", 200)


@router.patch("/me/notification-settings")
def update_notification_settings(
    body: NotificationSettingsRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """알림 수신 여부를 항목별로 부분 수정한다. 보낸 항목만 반영된다."""
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise APIError(400, "변경할 알림 항목이 없습니다.")

    setting = ensure_notification_setting(db, protector)
    for key, value in fields.items():
        if value is not None:
            setattr(setting, key, value)
    db.commit()
    return envelope(notification_settings_json(setting), "알림 설정을 저장했습니다.", 200)


@router.delete("/me")
def delete_me(
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """회원 탈퇴. 패스키·토큰·가족 연결이 함께 삭제된다.

    내가 마지막 가족 멤버였던 어르신은 인형·약 설정까지 함께 삭제하고,
    다른 가족이 남아 있는데 내가 주보호자였다면 가장 오래된 멤버에게 주보호자를 넘긴다.
    """
    memberships = db.scalars(
        select(FamilyMember).where(FamilyMember.protector_id == protector.id)
    ).all()

    removed_users = []
    for membership in memberships:
        others = db.scalars(
            select(FamilyMember)
            .where(
                FamilyMember.user_id == membership.user_id,
                FamilyMember.protector_id != protector.id,
            )
            .order_by(FamilyMember.created_at)
        ).all()
        if not others:
            user = db.get(User, membership.user_id)
            if user is not None:
                removed_users.append(user.id)
                db.delete(user)  # devices/medications/voices/invite_codes 까지 cascade
        elif membership.is_primary:
            others[0].is_primary = True

    db.delete(protector)
    db.commit()
    return envelope({"deletedUserIds": removed_users}, "회원 탈퇴가 완료되었습니다.", 200)

"""돌봄 대상(어르신) 정보와 가족 멤버 목록."""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Device, FamilyMember, InviteCode, Protector, User, Voice
from ..schemas import UserCreateRequest, UserUpdateRequest
from ..services.access import get_owned_user, iso, user_json

router = APIRouter(tags=["users"])


def _main_device(db: Session, user_id: int) -> Optional[Device]:
    return db.scalars(
        select(Device).where(Device.user_id == user_id).order_by(Device.created_at)
    ).first()


@router.post("/users", status_code=201)
def create_user(
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """어르신 등록. 만든 보호자가 주보호자로 함께 연결된다.

    앱은 보호자 한 명당 어르신 한 분을 전제로 만들어져 있다(가족 목록·홈이
    첫 어르신만 본다). 네트워크 오류로 같은 요청이 두 번 들어와 어르신이
    둘 생기는 쪽이 더 위험하므로, 이미 연결된 어르신이 있으면 막는다.
    """
    existing = db.scalars(
        select(FamilyMember).where(FamilyMember.protector_id == protector.id)
    ).first()
    if existing is not None:
        raise APIError(400, "이미 연결된 어르신이 있습니다.")

    user = User(
        name=body.name.strip(),
        gender=body.gender,
        birth_date=body.birth_date,
        photo_url=body.photo_url,
        note=body.note or "",
    )
    db.add(user)
    db.flush()
    db.add(FamilyMember(user_id=user.id, protector_id=protector.id, is_primary=True))
    db.commit()
    db.refresh(user)

    return envelope(user_json(user, None), "어르신을 등록했습니다.", 201)


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """어르신 기본 정보(이름·성별·생년월일·만 나이·메모)."""
    user = get_owned_user(db, protector, user_id)
    return envelope(user_json(user, _main_device(db, user.id)), "OK", 200)


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdateRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """어르신 정보 수정. 보내지 않은 필드는 그대로 둔다."""
    user = get_owned_user(db, protector, user_id)
    fields = body.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"] is not None:
        user.name = fields["name"].strip()
    if "gender" in fields:
        user.gender = fields["gender"]
    if "birth_date" in fields:
        user.birth_date = fields["birth_date"]
    if "photo_url" in fields:
        user.photo_url = fields["photo_url"]
    if "note" in fields and fields["note"] is not None:
        user.note = fields["note"]

    db.commit()
    return envelope(user_json(user, _main_device(db, user.id)), "정보를 수정했습니다.", 200)


@router.get("/users/{user_id}/family-members")
def list_family_members(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """연결된 가족 구성원 + 통계(가족 수, 음성 수, 생성 코드 수)."""
    user = get_owned_user(db, protector, user_id)

    memberships = db.scalars(
        select(FamilyMember)
        .where(FamilyMember.user_id == user.id)
        .order_by(FamilyMember.created_at)
    ).all()

    members = []
    for membership in memberships:
        member = db.get(Protector, membership.protector_id)
        if member is None:
            continue
        members.append(
            {
                "protectorId": member.id,
                "name": member.display_name,
                "relation": member.relation,
                "profileImageUrl": member.profile_image_url,
                "isPrimary": membership.is_primary,
                "isMe": member.id == protector.id,
                "joinedAt": iso(membership.created_at),
            }
        )

    # 가족이 등록해 학습을 마친 목소리만 센다(기본 음성 제외).
    device_ids = db.scalars(select(Device.id).where(Device.user_id == user.id)).all()
    voice_count = (
        db.scalar(
            select(func.count(Voice.id)).where(
                Voice.device_id.in_(device_ids),
                Voice.status == "ready",
                Voice.protector_id.is_not(None),
            )
        )
        if device_ids
        else 0
    )
    code_count = db.scalar(select(func.count(InviteCode.id)).where(InviteCode.user_id == user.id))

    return envelope(
        {
            "userId": user.id,
            "stats": {
                "familyCount": len(members),
                "voiceCount": voice_count or 0,
                "inviteCodeCount": code_count or 0,
            },
            "members": members,
        },
        "OK",
        200,
    )

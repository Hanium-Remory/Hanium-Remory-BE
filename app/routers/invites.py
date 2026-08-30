"""가족 초대 코드 발급·수락.

이미 연결된 보호자가 코드를 만들어 가족에게 알려주면, 그 가족이 코드를 넣어
같은 어르신에 연결된다. 코드는 한 번만 쓸 수 있고 기한이 지나면 못 쓴다.
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
from ..models import FamilyMember, InviteCode, Protector, User
from ..services.access import get_owned_user, iso

router = APIRouter(tags=["invites"])

# 0/O, 1/I 처럼 눈으로 헷갈리는 글자는 뺀다. 전화로 불러주는 일이 많다.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6
_MAX_TRIES = 10
# 초대 코드는 아무리 길어도 하루까지만 살아 있는다.
_MAX_TTL = dt.timedelta(hours=24)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(when: dt.datetime) -> dt.datetime:
    """DB 가 시간대 없이 돌려주는 경우가 있어 UTC 로 맞춘다."""
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _new_code(db: Session) -> str:
    for _ in range(_MAX_TRIES):
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
        if db.scalar(select(InviteCode.id).where(InviteCode.code == code)) is None:
            return code
    # 32^6 중에서 10번 연속 충돌은 사실상 없다. 나면 그냥 실패로 알린다.
    raise APIError(500, "초대 코드를 만들지 못했습니다. 잠시 후 다시 시도해 주세요.")


def _ttl() -> dt.timedelta:
    """초대 코드 유효 기간. 설정을 늘려 잡아도 24시간을 넘기지 않는다."""
    return min(dt.timedelta(hours=settings.invite_code_ttl_hours), _MAX_TTL)


def _code_json(invite: InviteCode) -> dict:
    return {
        "inviteCode": invite.code,
        "userId": invite.user_id,
        "expiresAt": iso(invite.expires_at),
        "createdAt": iso(invite.created_at),
    }


@router.post("/users/{user_id}/invite-codes", status_code=201)
def create_invite_code(
    user_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """가족에게 알려줄 초대 코드를 만든다. 연결된 보호자만 만들 수 있다."""
    user = get_owned_user(db, protector, user_id)

    invite = InviteCode(
        code=_new_code(db),
        user_id=user.id,
        created_by=protector.id,
        expires_at=_now() + _ttl(),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    return envelope(_code_json(invite), "초대 코드를 만들었습니다.", 201)


@router.post("/invite-codes/{code}/accept")
def accept_invite_code(
    code: str,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """초대 코드로 가족에 합류한다.

    코드는 한 번만 쓸 수 있다. 이미 그 어르신에 연결된 보호자가 다시 넣으면
    코드를 쓰지 않고 그대로 통과시킨다(같은 요청을 두 번 보내도 안전하게).
    """
    normalized = code.strip().upper()
    invite = db.scalars(
        select(InviteCode).where(InviteCode.code == normalized)
    ).first()
    if invite is None:
        raise APIError(404, "코드를 찾을 수 없습니다. 다시 확인해 주세요.")

    user = db.get(User, invite.user_id)
    if user is None:
        raise APIError(404, "코드를 찾을 수 없습니다. 다시 확인해 주세요.")

    already = db.scalars(
        select(FamilyMember).where(
            FamilyMember.user_id == invite.user_id,
            FamilyMember.protector_id == protector.id,
        )
    ).first()
    if already is not None:
        return envelope(
            {"userId": user.id, "name": user.name, "isPrimary": already.is_primary},
            "이미 연결된 가족입니다.",
            200,
        )

    if invite.used_by is not None:
        raise APIError(400, "이미 사용된 코드입니다.")
    if _aware(invite.expires_at) < _now():
        raise APIError(400, "기한이 지난 코드입니다. 새 코드를 받아주세요.")

    db.add(
        FamilyMember(user_id=user.id, protector_id=protector.id, is_primary=False)
    )
    invite.used_by = protector.id
    db.commit()

    return envelope(
        {"userId": user.id, "name": user.name, "isPrimary": False},
        "가족으로 연결되었습니다.",
        200,
    )

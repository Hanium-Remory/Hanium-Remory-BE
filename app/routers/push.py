"""보호자 폰의 푸시 토큰 등록·해제.

앱은 뜰 때마다 FCM 토큰을 올린다(토큰은 앱 재설치·복원 때 바뀐다).
로그아웃할 때는 지운다 — 지우지 않으면 폰을 넘겨받은 사람에게 남의 알림이 간다.
"""

from sqlalchemy import select
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import envelope
from ..models import Protector, PushToken, utcnow
from ..schemas import PushTokenRequest

router = APIRouter(prefix="/protectors/me/push-tokens", tags=["push"])


@router.post("", status_code=201)
def register_push_token(
    body: PushTokenRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """FCM 토큰을 등록한다. 이미 있으면 갱신만 한다."""
    row = db.scalars(select(PushToken).where(PushToken.token == body.token)).first()
    if row is None:
        row = PushToken(
            protector_id=protector.id, token=body.token, platform=body.platform
        )
        db.add(row)
    else:
        # 폰을 물려주거나 다른 계정으로 다시 로그인하면 같은 토큰의 주인이 바뀐다.
        row.protector_id = protector.id
        row.platform = body.platform
        row.last_seen_at = utcnow()
    db.commit()
    db.refresh(row)
    return envelope(
        {"pushTokenId": row.id, "protectorId": protector.id}, "푸시 토큰을 등록했습니다.", 201
    )


@router.delete("")
def unregister_push_token(
    body: PushTokenRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """로그아웃할 때 이 폰의 토큰을 지운다.

    없는 토큰이어도 200 이다 — 지우려는 결과는 이미 이루어져 있다.
    """
    row = db.scalars(
        select(PushToken).where(
            PushToken.token == body.token, PushToken.protector_id == protector.id
        )
    ).first()
    if row is not None:
        db.delete(row)
        db.commit()
    return envelope(None, "푸시 토큰을 해제했습니다.", 200)

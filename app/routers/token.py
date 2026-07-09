import jwt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Protector, RefreshToken
from ..schemas import LogoutRequest, RefreshRequest
from ..security import create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/auth", tags=["token"])


def _decode_refresh(token: str) -> dict:
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise APIError(401, "리프레시 토큰이 만료되었습니다. 다시 로그인해 주세요.")
    except jwt.PyJWTError:
        raise APIError(401, "유효하지 않은 토큰입니다.")
    if payload.get("type") != "refresh":
        raise APIError(401, "리프레시 토큰이 아닙니다.")
    return payload


@router.post("/token/refresh")
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    """리프레시 토큰으로 액세스 토큰을 재발급하고 리프레시 토큰을 로테이션한다."""
    payload = _decode_refresh(body.refresh_token)
    rec = db.scalars(select(RefreshToken).where(RefreshToken.jti == payload["jti"])).first()
    if rec is None or rec.revoked:
        raise APIError(401, "만료되었거나 회수된 토큰입니다. 다시 로그인해 주세요.")

    protector_id = int(payload["sub"])
    rec.revoked = True  # 로테이션: 기존 토큰 무효화

    access = create_access_token(protector_id)
    new_refresh, jti, exp = create_refresh_token(protector_id)
    db.add(RefreshToken(jti=jti, protector_id=protector_id, expires_at=exp))
    db.commit()

    return envelope({"accessToken": access, "refreshToken": new_refresh}, "OK", 200)


@router.post("/logout")
def logout(
    body: LogoutRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """리프레시 토큰을 회수한다. (액세스 토큰 필요)"""
    try:
        payload = decode_token(body.refresh_token)
    except jwt.PyJWTError:
        payload = None

    if payload and payload.get("type") == "refresh":
        rec = db.scalars(select(RefreshToken).where(RefreshToken.jti == payload["jti"])).first()
        if rec and rec.protector_id == protector.id:
            rec.revoked = True
            db.commit()

    return envelope(None, "로그아웃 되었습니다.", 200)

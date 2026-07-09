from typing import Optional

import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from .database import get_db
from .errors import APIError
from .models import Protector
from .security import decode_token


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(401, "인증 토큰이 필요합니다.")
    return authorization.split(" ", 1)[1].strip()


def _decode(token: str, expected_type: str) -> dict:
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise APIError(401, "토큰이 만료되었습니다.")
    except jwt.PyJWTError:
        raise APIError(401, "유효하지 않은 토큰입니다.")
    if payload.get("type") != expected_type:
        raise APIError(401, "토큰 종류가 올바르지 않습니다.")
    return payload


def require_register_token(authorization: Optional[str] = Header(default=None)) -> str:
    """전화번호 인증 성공 토큰. 등록 대상 전화번호(sub)를 반환."""
    payload = _decode(_bearer(authorization), "register")
    return payload["sub"]


def get_current_protector(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Protector:
    payload = _decode(_bearer(authorization), "access")
    protector = db.get(Protector, int(payload["sub"]))
    if protector is None:
        raise APIError(401, "존재하지 않는 계정입니다.")
    return protector

from typing import Optional

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .errors import APIError
from .models import Device, Protector
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


def optional_register_token(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """전화번호 인증 토큰이 있으면 전화번호(sub) 반환, 없으면 None(Face-ID-first)."""
    if not authorization:
        return None
    payload = _decode(_bearer(authorization), "register")
    return payload["sub"]


def optional_onboarding_protector_id(
    authorization: Optional[str] = Header(default=None),
) -> Optional[int]:
    """Face-ID-first: 패스키 등록 후 발급된 onboarding 토큰이 있으면 protector_id 반환."""
    if not authorization:
        return None
    payload = _decode(_bearer(authorization), "onboarding")
    return int(payload["sub"])


def get_current_protector(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Protector:
    payload = _decode(_bearer(authorization), "access")
    protector = db.get(Protector, int(payload["sub"]))
    if protector is None:
        raise APIError(401, "존재하지 않는 계정입니다.")
    return protector


def get_current_device(
    x_device_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Device:
    """인형(기기)이 보낸 X-Device-Token 을 확인하고 해당 기기를 반환한다.

    보호자(사람)는 JWT(Authorization: Bearer)로, 인형(기기)은 이 기기 토큰으로 인증한다.
    """
    if not x_device_token:
        raise APIError(401, "기기 토큰이 필요합니다.")

    device = db.scalars(
        select(Device).where(Device.device_token == x_device_token)
    ).first()
    if device is None:
        raise APIError(401, "유효하지 않은 기기 토큰입니다.")

    return device

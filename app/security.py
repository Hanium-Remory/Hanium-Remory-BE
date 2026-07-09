import datetime as dt
import uuid

import jwt

from .config import settings


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """만료/서명 검증. 실패 시 jwt 예외를 던진다."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def create_access_token(protector_id: int) -> str:
    now = _now()
    return _encode(
        {
            "sub": str(protector_id),
            "type": "access",
            "iat": now,
            "exp": now + dt.timedelta(minutes=settings.access_token_ttl_min),
        }
    )


def create_refresh_token(protector_id: int) -> tuple[str, str, dt.datetime]:
    """returns (token, jti, expires_at)"""
    now = _now()
    jti = uuid.uuid4().hex
    exp = now + dt.timedelta(days=settings.refresh_token_ttl_days)
    token = _encode(
        {"sub": str(protector_id), "type": "refresh", "jti": jti, "iat": now, "exp": exp}
    )
    return token, jti, exp


def create_register_token(phone_number: str) -> str:
    """전화번호 인증 성공 후 패스키 등록에만 쓰는 단기 토큰."""
    now = _now()
    return _encode(
        {
            "sub": phone_number,
            "type": "register",
            "iat": now,
            "exp": now + dt.timedelta(minutes=settings.register_token_ttl_min),
        }
    )

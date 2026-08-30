"""Firebase 가 발급한 ID 토큰 검증.

앱이 Firebase 로 전화번호 인증을 마치면 ID 토큰을 받는다. 서버는 그 토큰이
정말 우리 Firebase 프로젝트에서 나온 것인지 확인하고 전화번호만 꺼내 쓴다.

firebase-admin SDK 는 쓰지 않는다. ID 토큰은 구글이 공개한 키로 서명된
평범한 RS256 JWT 라, 이미 쓰고 있는 PyJWT 로 검증할 수 있다. 서비스 계정
키 파일을 서버에 두지 않아도 되고(유출 위험이 없다), 의존성도 늘지 않는다.
필요한 설정은 FIREBASE_PROJECT_ID 하나다.
"""

from __future__ import annotations

import logging
from typing import Optional

import jwt
from jwt import PyJWKClient

from ..config import settings

logger = logging.getLogger("remory.firebase")

# 구글이 ID 토큰 서명에 쓰는 공개키. 주기적으로 교체되므로 URL 로 받아 캐시한다.
_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)

_jwk_client: Optional[PyJWKClient] = None


class FirebaseAuthError(Exception):
    """토큰이 우리 프로젝트의 유효한 ID 토큰이 아니다."""


def _client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        # 키를 매 요청 받아오지 않도록 캐시한다.
        _jwk_client = PyJWKClient(_JWKS_URL, cache_keys=True)
    return _jwk_client


def verify_phone_id_token(id_token: str) -> str:
    """ID 토큰을 검증하고 전화번호(E.164)를 돌려준다.

    잘못된 토큰이면 FirebaseAuthError 를 낸다.
    """
    project_id = settings.firebase_project_id
    if not project_id:
        raise FirebaseAuthError("FIREBASE_PROJECT_ID 가 설정되지 않았습니다.")

    try:
        signing_key = _client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"https://securetoken.google.com/{project_id}",
        )
    except jwt.ExpiredSignatureError:
        raise FirebaseAuthError("인증이 만료되었습니다. 다시 시도해 주세요.")
    except jwt.InvalidTokenError as e:
        raise FirebaseAuthError(f"유효하지 않은 인증 토큰입니다: {e}")
    except Exception as e:
        # 키를 받아오지 못하는 등 검증 자체가 불가능한 경우.
        logger.error("Firebase 토큰 검증 실패: %s: %s", type(e).__name__, e)
        raise FirebaseAuthError("인증 토큰을 확인할 수 없습니다.")

    # sub 는 Firebase 사용자 uid. 비어 있으면 정상 토큰이 아니다.
    if not claims.get("sub"):
        raise FirebaseAuthError("유효하지 않은 인증 토큰입니다.")

    phone = claims.get("phone_number")
    if not phone:
        # 이메일·구글 로그인 토큰으로도 여기까지 올 수 있다. 우리는 전화번호만 쓴다.
        raise FirebaseAuthError("전화번호 인증으로 받은 토큰이 아닙니다.")

    return phone


def to_local_number(e164: str) -> str:
    """+821012345678 → 01012345678.

    Firebase 는 E.164 로 준다. DB 에는 지금까지 국내 형식으로 저장해 왔고
    기존 계정도 그 형식이라, 맞춰서 되돌린다.
    """
    digits = "".join(ch for ch in e164 if ch.isdigit())
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    return digits

"""py_webauthn 래퍼. challenge 생성 / attestation·assertion 검증."""

import base64
import json
import secrets
from typing import Optional

from webauthn import verify_authentication_response, verify_registration_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from ..config import settings


def new_challenge() -> str:
    """base64url challenge 문자열."""
    return bytes_to_base64url(secrets.token_bytes(32))


def to_b64url(raw: bytes) -> str:
    return bytes_to_base64url(raw)


def from_b64url(value: str) -> bytes:
    return base64url_to_bytes(value)


def challenge_from_client_data(client_data_json_b64url: str) -> str:
    """clientDataJSON(base64url) 안의 challenge 값(이미 base64url)을 추출."""
    raw = base64url_to_bytes(client_data_json_b64url)
    data = json.loads(raw.decode("utf-8"))
    return data["challenge"]


def _pad(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_registration(credential_id: str, client_data_json: str, attestation_object: str,
                        expected_challenge: str):
    """등록 attestation 검증. VerifiedRegistration 반환(실패 시 예외)."""
    return verify_registration_response(
        credential={
            "id": credential_id,
            "rawId": credential_id,
            "response": {
                "clientDataJSON": client_data_json,
                "attestationObject": attestation_object,
            },
            "type": "public-key",
            "clientExtensionResults": {},
        },
        expected_challenge=_pad(expected_challenge),
        expected_rp_id=settings.rp_id,
        expected_origin=settings.webauthn_origins,
        require_user_verification=True,
    )


def verify_authentication(credential_id: str, client_data_json: str, authenticator_data: str,
                          signature: str, public_key: bytes, sign_count: int,
                          expected_challenge: str, user_handle: Optional[str] = None):
    """로그인 assertion 검증. VerifiedAuthentication 반환(실패 시 예외)."""
    response = {
        "clientDataJSON": client_data_json,
        "authenticatorData": authenticator_data,
        "signature": signature,
    }
    if user_handle:
        response["userHandle"] = user_handle
    return verify_authentication_response(
        credential={
            "id": credential_id,
            "rawId": credential_id,
            "response": response,
            "type": "public-key",
            "clientExtensionResults": {},
        },
        expected_challenge=_pad(expected_challenge),
        expected_rp_id=settings.rp_id,
        expected_origin=settings.webauthn_origins,
        credential_public_key=public_key,
        credential_current_sign_count=sign_count,
        require_user_verification=True,
    )

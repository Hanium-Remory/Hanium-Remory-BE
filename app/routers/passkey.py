import datetime as dt
import logging
import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_register_token
from ..errors import APIError, envelope
from ..models import Credential, Protector, RefreshToken, WebAuthnChallenge
from ..schemas import AuthenticationRequest, AuthOptionsRequest, RegistrationOptionsRequest, RegistrationRequest
from ..security import create_access_token, create_refresh_token
from ..services import webauthn_service as wa
from .phone import is_expired, normalize_phone

logger = logging.getLogger("remory.passkey")
router = APIRouter(prefix="/auth/passkey", tags=["passkey"])


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _challenge_expiry() -> dt.datetime:
    return _now() + dt.timedelta(milliseconds=settings.webauthn_timeout_ms)


def _consume_challenge(db: Session, client_data_json: str, ceremony: str) -> WebAuthnChallenge:
    """clientDataJSON에서 challenge를 뽑아 저장된 미만료 challenge row를 찾는다."""
    try:
        challenge_val = wa.challenge_from_client_data(client_data_json)
    except Exception:
        raise APIError(400, "clientDataJSON 형식이 올바르지 않습니다.")
    ch = db.scalars(
        select(WebAuthnChallenge).where(
            WebAuthnChallenge.challenge == challenge_val,
            WebAuthnChallenge.ceremony == ceremony,
        )
    ).first()
    if ch is None:
        raise APIError(400, "인증 세션을 찾을 수 없습니다. 다시 시도해 주세요.")
    if is_expired(ch.expires_at):
        db.delete(ch)
        db.commit()
        raise APIError(400, "인증 세션이 만료되었습니다. 다시 시도해 주세요.")
    return ch


def _issue_tokens(db: Session, protector: Protector) -> dict:
    access = create_access_token(protector.id)
    refresh, jti, exp = create_refresh_token(protector.id)
    db.add(RefreshToken(jti=jti, protector_id=protector.id, expires_at=exp))
    return {
        "protectorId": protector.id,
        "accessToken": access,
        "refreshToken": refresh,
        "onboardingCompleted": protector.onboarding_completed,
    }


# ── 등록 ─────────────────────────────────────────────
@router.post("/registration/options")
def registration_options(
    body: RegistrationOptionsRequest,
    db: Session = Depends(get_db),
    phone: str = Depends(require_register_token),
):
    """WebAuthn 등록에 필요한 challenge 및 옵션을 발급한다. (가입 3단계)"""
    phone = normalize_phone(phone)
    if db.scalars(select(Protector).where(Protector.phone_number == phone)).first():
        raise APIError(409, "이미 가입된 전화번호입니다.")

    user_handle = secrets.token_bytes(16)
    challenge = wa.new_challenge()
    display_name = body.display_name or "보호자"

    db.add(
        WebAuthnChallenge(
            challenge=challenge,
            ceremony="registration",
            phone_number=phone,
            user_handle=user_handle,
            display_name=display_name,
            expires_at=_challenge_expiry(),
        )
    )
    db.commit()

    data = {
        "rp": {"id": settings.rp_id, "name": settings.rp_name},
        "user": {"id": wa.to_b64url(user_handle), "name": phone, "displayName": display_name},
        "challenge": challenge,
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},
            {"type": "public-key", "alg": -257},
        ],
        "timeout": settings.webauthn_timeout_ms,
        "authenticatorSelection": {
            "userVerification": "required",
            "residentKey": "preferred",
        },
    }
    return envelope(data, "OK", 200)


@router.post("/registration", status_code=201)
def registration(
    body: RegistrationRequest,
    db: Session = Depends(get_db),
    phone: str = Depends(require_register_token),
):
    """클라이언트가 생성한 attestation을 검증하고 보호자 계정 + credential을 저장한다."""
    phone = normalize_phone(phone)
    ch = _consume_challenge(db, body.client_data_json, "registration")

    try:
        verified = wa.verify_registration(
            body.credential_id, body.client_data_json, body.attestation_object, ch.challenge
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("attestation 검증 실패: %s", e)
        raise APIError(400, "패스키 검증에 실패했습니다.")

    if db.scalars(select(Protector).where(Protector.phone_number == phone)).first():
        raise APIError(409, "이미 가입된 전화번호입니다.")

    protector = Protector(
        phone_number=phone,
        display_name=ch.display_name or "보호자",
        user_handle=ch.user_handle,
        onboarding_completed=False,
    )
    db.add(protector)
    db.flush()  # protector.id 확보

    db.add(
        Credential(
            protector_id=protector.id,
            credential_id=body.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
        )
    )
    db.delete(ch)
    tokens = _issue_tokens(db, protector)
    db.commit()

    return envelope(tokens, "가입이 완료되었습니다.", 201)


# ── 로그인 ───────────────────────────────────────────
@router.post("/authentication/options")
def authentication_options(body: AuthOptionsRequest, db: Session = Depends(get_db)):
    """로그인 시 서명에 사용할 challenge를 발급한다."""
    challenge = wa.new_challenge()
    phone = normalize_phone(body.phone_number) if body.phone_number else None
    allow_credentials: list[dict] = []

    if phone:
        protector = db.scalars(select(Protector).where(Protector.phone_number == phone)).first()
        if protector is None:
            raise APIError(404, "가입되지 않은 전화번호입니다.")
        allow_credentials = [
            {"type": "public-key", "id": c.credential_id} for c in protector.credentials
        ]

    db.add(
        WebAuthnChallenge(
            challenge=challenge,
            ceremony="authentication",
            phone_number=phone,
            expires_at=_challenge_expiry(),
        )
    )
    db.commit()

    data = {
        "challenge": challenge,
        "rpId": settings.rp_id,
        "allowCredentials": allow_credentials,
        "userVerification": "required",
        "timeout": settings.webauthn_timeout_ms,
    }
    return envelope(data, "OK", 200)


@router.post("/authentication")
def authentication(body: AuthenticationRequest, db: Session = Depends(get_db)):
    """생체 인증(Face ID/지문) 서명을 검증하고 JWT를 발급한다. sign_count를 갱신한다."""
    ch = _consume_challenge(db, body.client_data_json, "authentication")

    cred = db.scalars(
        select(Credential).where(Credential.credential_id == body.credential_id)
    ).first()
    if cred is None:
        raise APIError(404, "등록되지 않은 패스키입니다.")

    try:
        verified = wa.verify_authentication(
            credential_id=body.credential_id,
            client_data_json=body.client_data_json,
            authenticator_data=body.authenticator_data,
            signature=body.signature,
            public_key=cred.public_key,
            sign_count=cred.sign_count,
            expected_challenge=ch.challenge,
            user_handle=body.user_handle,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("assertion 검증 실패: %s", e)
        raise APIError(401, "패스키 인증에 실패했습니다.")

    cred.sign_count = verified.new_sign_count
    cred.last_used_at = _now()
    protector = cred.protector
    db.delete(ch)
    tokens = _issue_tokens(db, protector)
    db.commit()

    return envelope(tokens, "로그인 되었습니다.", 200)

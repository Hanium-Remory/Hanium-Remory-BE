import datetime as dt
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import optional_onboarding_protector_id
from ..errors import APIError, envelope
from ..models import PhoneVerification, Protector, RefreshToken
from ..schemas import PhoneCodeRequest, PhoneVerifyRequest
from ..security import create_access_token, create_refresh_token, create_register_token
from ..services.sms import SMSError, send_verification_sms

logger = logging.getLogger("remory.phone")
router = APIRouter(prefix="/auth/phone", tags=["phone"])


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def is_expired(when: dt.datetime) -> bool:
    """DB에서 읽은 값이 naive(SQLite)일 수 있으므로 UTC로 맞춰 비교."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when < _now()


def normalize_phone(phone: str) -> str:
    return phone.replace("-", "").replace(" ", "").strip()


@router.post("/verification-code")
def send_verification_code(body: PhoneCodeRequest, db: Session = Depends(get_db)):
    """가입 첫 단계. 입력한 전화번호로 6자리 SMS 인증번호를 발송한다."""
    phone = normalize_phone(body.phone_number)
    code = f"{secrets.randbelow(1_000_000):06d}"

    rec = PhoneVerification(
        phone_number=phone,
        code=code,
        expires_at=_now() + dt.timedelta(seconds=settings.otp_ttl_sec),
    )
    db.add(rec)
    db.commit()

    try:
        send_verification_sms(phone, code)
    except SMSError as e:
        logger.error("SMS 발송 실패: %s", e)
        raise APIError(502, "인증번호 발송에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    return envelope({"expiresInSec": settings.otp_ttl_sec}, "인증번호를 발송했습니다.", 200)


@router.post("/verify")
def verify_code(
    body: PhoneVerifyRequest,
    db: Session = Depends(get_db),
    onboarding_pid: Optional[int] = Depends(optional_onboarding_protector_id),
):
    """발송된 인증번호를 검증한다.

    - onboarding 토큰이 있으면(Face-ID-first) 이 번호를 패스키 계정에 연결하고
      정식 access/refresh 토큰을 발급한다.
    - 없으면(번호 먼저 인증하는 기존 흐름) 패스키 등록용 registrationToken을 발급한다.
    """
    phone = normalize_phone(body.phone_number)
    rec = db.scalars(
        select(PhoneVerification)
        .where(PhoneVerification.phone_number == phone, PhoneVerification.verified.is_(False))
        .order_by(PhoneVerification.created_at.desc())
    ).first()

    if rec is None:
        raise APIError(400, "인증번호를 먼저 요청해 주세요.")
    if is_expired(rec.expires_at):
        raise APIError(400, "인증번호가 만료되었습니다. 다시 요청해 주세요.")
    if rec.attempts >= settings.otp_max_attempts:
        raise APIError(429, "인증 시도 횟수를 초과했습니다. 다시 요청해 주세요.")
    if rec.code != body.code:
        rec.attempts += 1
        db.commit()
        raise APIError(400, "인증번호가 일치하지 않습니다.")

    rec.verified = True

    # ── Face-ID-first: 이미 패스키로 만든 계정에 번호를 연결하고 로그인 완료 ──
    if onboarding_pid is not None:
        protector = db.get(Protector, onboarding_pid)
        if protector is None:
            raise APIError(401, "유효하지 않은 온보딩 세션입니다.")
        taken = db.scalars(
            select(Protector).where(Protector.phone_number == phone)
        ).first()
        if taken is not None and taken.id != protector.id:
            raise APIError(409, "이미 가입된 전화번호입니다.")
        protector.phone_number = phone
        access = create_access_token(protector.id)
        refresh, jti, exp = create_refresh_token(protector.id)
        db.add(RefreshToken(jti=jti, protector_id=protector.id, expires_at=exp))
        db.commit()
        return envelope(
            {
                "protectorId": protector.id,
                "accessToken": access,
                "refreshToken": refresh,
                "onboardingCompleted": protector.onboarding_completed,
            },
            "전화번호 인증이 완료되었습니다.",
            200,
        )

    db.commit()
    already_registered = (
        db.scalars(select(Protector).where(Protector.phone_number == phone)).first() is not None
    )
    token = create_register_token(phone)
    return envelope(
        {"registrationToken": token, "alreadyRegistered": already_registered},
        "전화번호 인증이 완료되었습니다.",
        200,
    )


@router.get("/dev/latest-code")
def dev_latest_code(phoneNumber: str, db: Session = Depends(get_db)):
    """개발 전용: 최근 발송된 인증번호를 반환한다(mock SMS 로그 대체).

    settings.debug=True 일 때만 동작. 운영에서는 반드시 DEBUG=false 로 비활성화할 것.
    """
    if not settings.debug:
        raise APIError(404, "찾을 수 없습니다.")
    phone = normalize_phone(phoneNumber)
    rec = db.scalars(
        select(PhoneVerification)
        .where(PhoneVerification.phone_number == phone)
        .order_by(PhoneVerification.created_at.desc())
    ).first()
    return envelope({"code": rec.code if rec else None}, "OK", 200)

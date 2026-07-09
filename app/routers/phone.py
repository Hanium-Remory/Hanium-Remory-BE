import datetime as dt
import logging
import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..errors import APIError, envelope
from ..models import PhoneVerification, Protector
from ..schemas import PhoneCodeRequest, PhoneVerifyRequest
from ..security import create_register_token
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
def verify_code(body: PhoneVerifyRequest, db: Session = Depends(get_db)):
    """발송된 인증번호를 검증한다. 성공 시 패스키 등록에 사용할 임시 토큰을 발급한다."""
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

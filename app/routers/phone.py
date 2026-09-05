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
from ..schemas import FirebaseVerifyRequest, PhoneCodeRequest, PhoneVerifyRequest
from ..security import create_access_token, create_refresh_token, create_register_token
from ..services.firebase import (
    FirebaseAuthError,
    to_local_number,
    verify_phone_id_token,
)
from ..services.sms import SMSError, send_verification_sms
from .invites import join_by_code

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


def _aware(when: dt.datetime) -> dt.datetime:
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _guard_resend(db: Session, phone: str) -> None:
    """인증번호 재발송을 막는다.

    이 엔드포인트는 인증 없이 열려 있고 실제 발송은 건당 요금이 나간다.
    막지 않으면 남의 번호로 문자를 계속 보내게 만들 수도 있다.
    """
    now = _now()
    recent = db.scalars(
        select(PhoneVerification)
        .where(
            PhoneVerification.phone_number == phone,
            PhoneVerification.created_at >= now - dt.timedelta(hours=1),
        )
        .order_by(PhoneVerification.created_at.desc())
    ).all()
    if not recent:
        return

    waited = (now - _aware(recent[0].created_at)).total_seconds()
    if waited < settings.otp_send_cooldown_sec:
        left = int(settings.otp_send_cooldown_sec - waited) or 1
        raise APIError(429, f"{left}초 후에 다시 요청해 주세요.")

    if len(recent) >= settings.otp_send_max_per_hour:
        raise APIError(429, "인증번호 요청이 너무 많습니다. 1시간 뒤에 다시 시도해 주세요.")


@router.post("/verification-code")
def send_verification_code(body: PhoneCodeRequest, db: Session = Depends(get_db)):
    """가입 첫 단계. 입력한 전화번호로 6자리 SMS 인증번호를 발송한다."""
    phone = normalize_phone(body.phone_number)
    _guard_resend(db, phone)
    code = f"{secrets.randbelow(1_000_000):06d}"

    rec = PhoneVerification(
        phone_number=phone,
        code=code,
        expires_at=_now() + dt.timedelta(seconds=settings.otp_ttl_sec),
    )
    db.add(rec)
    db.commit()

    # 지정한 테스트 번호는 문자를 거치지 않고 코드를 그대로 돌려준다.
    # 발신번호 심사 전에도 실기기 흐름을 끝까지 태우려는 것이다.
    if phone in {normalize_phone(p) for p in settings.otp_test_phone_numbers}:
        logger.warning("테스트 번호라 문자를 보내지 않고 코드를 응답에 담는다: %s", phone)
        return envelope(
            {"expiresInSec": settings.otp_ttl_sec, "testCode": code},
            "테스트 번호입니다. 인증번호를 응답에 담아 보냅니다.",
            200,
        )

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
    return _finish_verification(db, phone, onboarding_pid, body.invite_code)


def _finish_verification(
    db: Session,
    phone: str,
    onboarding_pid: Optional[int],
    invite_code: Optional[str] = None,
):
    """번호 인증이 끝난 뒤 공통 처리.

    문자로 받은 코드를 맞췄든 Firebase 토큰을 검증했든, 이 뒤는 같다.
    """
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
        # 초대 코드로 들어온 가입이면 여기서 가족 연결까지 끝낸다.
        # 어르신을 등록할 필요가 없으니 앱은 바로 홈으로 갈 수 있다.
        linked = None
        if invite_code:
            linked, _ = join_by_code(db, protector, invite_code)
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
                # 초대 코드로 붙은 어르신. 없으면 null(어르신 등록 화면으로).
                "linkedUser": linked,
            },
            "가족으로 연결되었습니다." if linked else "전화번호 인증이 완료되었습니다.",
            200,
        )

    db.commit()
    already_registered = (
        db.scalars(select(Protector).where(Protector.phone_number == phone)).first() is not None
    )
    token = create_register_token(phone)
    # 번호를 먼저 인증하는 흐름에서는 아직 계정이 없다. 초대 코드는 계정이
    # 생기는 다음 단계(패스키 등록)로 앱이 그대로 들고 간다.
    return envelope(
        {"registrationToken": token, "alreadyRegistered": already_registered},
        "전화번호 인증이 완료되었습니다.",
        200,
    )


@router.post("/verify-firebase")
def verify_firebase(
    body: FirebaseVerifyRequest,
    db: Session = Depends(get_db),
    onboarding_pid: Optional[int] = Depends(optional_onboarding_protector_id),
):
    """Firebase 로 받은 전화번호 인증 결과를 받아들인다.

    문자를 우리가 보내지 않는 경로다. 앱이 Firebase 로 인증번호를 받고
    확인까지 끝낸 뒤 ID 토큰을 보내면, 서버는 그 토큰만 검증한다.
    인증 뒤 처리는 /verify 와 똑같다.
    """
    try:
        e164 = verify_phone_id_token(body.id_token)
    except FirebaseAuthError as e:
        logger.warning("Firebase 토큰 거절: %s", e)
        raise APIError(401, str(e))

    phone = normalize_phone(to_local_number(e164))
    logger.info("Firebase 전화번호 인증 완료: %s", phone)
    return _finish_verification(db, phone, onboarding_pid, body.invite_code)


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

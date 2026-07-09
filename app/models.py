import datetime as dt
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Protector(Base):
    """보호자 계정."""

    __tablename__ = "protectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Face-ID-first 가입에서는 패스키 등록 시점엔 번호가 없으므로 nullable.
    # 전화번호 인증 단계에서 채워진다. (unique은 NULL 다중 허용)
    phone_number: Mapped[Optional[str]] = mapped_column(
        String(20), unique=True, index=True, nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(50), default="보호자")
    # WebAuthn user handle (user.id). 전화번호와 무관한 안정적 식별자.
    user_handle: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    credentials: Mapped[List["Credential"]] = relationship(
        back_populates="protector", cascade="all, delete-orphan"
    )


class Credential(Base):
    """등록된 패스키(WebAuthn credential)."""

    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    protector_id: Mapped[int] = mapped_column(
        ForeignKey("protectors.id", ondelete="CASCADE"), index=True
    )
    credential_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)  # base64url
    public_key: Mapped[bytes] = mapped_column(LargeBinary)  # COSE public key
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    protector: Mapped["Protector"] = relationship(back_populates="credentials")


class PhoneVerification(Base):
    """전화번호 인증(OTP) 발송 기록."""

    __tablename__ = "phone_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    code: Mapped[str] = mapped_column(String(6))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebAuthnChallenge(Base):
    """등록/로그인 ceremony 동안 발급한 challenge 임시 저장."""

    __tablename__ = "webauthn_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # base64url
    ceremony: Mapped[str] = mapped_column(String(20))  # registration | authentication
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    user_handle: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    """발급된 refresh token (회수/로테이션용)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    protector_id: Mapped[int] = mapped_column(
        ForeignKey("protectors.id", ondelete="CASCADE"), index=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

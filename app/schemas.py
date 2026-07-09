from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CamelModel(BaseModel):
    """JSON은 camelCase(앱 관례), 내부는 그대로 접근."""

    model_config = ConfigDict(populate_by_name=True)


# ── 전화번호 인증 ────────────────────────────────────
class PhoneCodeRequest(CamelModel):
    phone_number: str = Field(alias="phoneNumber", min_length=9, max_length=20)


class PhoneVerifyRequest(CamelModel):
    phone_number: str = Field(alias="phoneNumber", min_length=9, max_length=20)
    code: str = Field(min_length=4, max_length=6)


# ── 패스키 등록 ──────────────────────────────────────
class RegistrationOptionsRequest(CamelModel):
    display_name: Optional[str] = Field(default=None, alias="displayName")


class RegistrationRequest(CamelModel):
    credential_id: str = Field(alias="credentialId")
    client_data_json: str = Field(alias="clientDataJSON")
    attestation_object: str = Field(alias="attestationObject")


# ── 패스키 로그인 ────────────────────────────────────
class AuthOptionsRequest(CamelModel):
    # 없으면 discoverable credential(usernameless) 로그인
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber")


class AuthenticationRequest(CamelModel):
    credential_id: str = Field(alias="credentialId")
    client_data_json: str = Field(alias="clientDataJSON")
    authenticator_data: str = Field(alias="authenticatorData")
    signature: str = Field(alias="signature")
    user_handle: Optional[str] = Field(default=None, alias="userHandle")


# ── 토큰 ─────────────────────────────────────────────
class RefreshRequest(CamelModel):
    refresh_token: str = Field(alias="refreshToken")


class LogoutRequest(CamelModel):
    refresh_token: str = Field(alias="refreshToken")

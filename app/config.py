from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "ReMory Auth API"
    debug: bool = True

    # Database
    database_url: str = "postgresql+psycopg2://remory:remory@localhost:5432/remory"

    # JWT
    jwt_secret: str = "dev-only-change-me-in-production-0000000000"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 30
    refresh_token_ttl_days: int = 30
    register_token_ttl_min: int = 10

    # WebAuthn
    rp_id: str = "remory.app"
    rp_name: str = "ReMory"
    webauthn_origins: list[str] = ["https://remory.app", "http://localhost"]
    webauthn_timeout_ms: int = 60000

    # 앱-도메인 연결(Associated Domains / Digital Asset Links).
    # 실기기 패스키 테스트 시 rp_id 도메인이 아래 파일들을 HTTPS로 서빙해야 한다.
    # iOS: "TEAMID.com.example.remory" 형식(Apple Developer 팀ID + 번들ID)
    ios_app_ids: list[str] = []
    # Android: 앱 패키지명과 서명 인증서 SHA-256 지문(colon 구분 hex)
    android_package_name: str = ""
    android_sha256_fingerprints: list[str] = []

    # 전화번호 인증(OTP)
    otp_ttl_sec: int = 180
    otp_max_attempts: int = 5

    # SMS provider: mock | aligo | ncp
    sms_provider: str = "mock"
    sms_sender_number: str = ""
    aligo_api_key: str = ""
    aligo_user_id: str = ""
    ncp_access_key: str = ""
    ncp_secret_key: str = ""
    ncp_service_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

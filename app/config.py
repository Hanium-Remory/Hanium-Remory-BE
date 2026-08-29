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

    # 알림 생성
    # 부정 감정이 이 횟수만큼 연달아 기록되면 긴급 알림을 만든다.
    emotion_alert_streak: int = 3
    # 같은 종류 알림을 이 시간 안에는 다시 만들지 않는다(쿨다운).
    emotion_alert_cooldown_min: int = 60
    chat_alert_cooldown_min: int = 10
    # 신호가 오락가락할 때 재연결 알림이 반복되지 않게.
    reconnect_alert_cooldown_min: int = 30

    # 가족 초대 코드
    invite_code_ttl_days: int = 7

    # 인형(Device)
    # 마지막 heartbeat 이후 이 시간이 지나면 '연결 끊김'으로 본다.
    device_offline_after_sec: int = 600
    # 완충 시 예상 사용 시간(배터리 잔여 시간 표시용).
    device_battery_full_hours: int = 18

    # 서비스 정보(GET /service/info)
    service_version: str = "1.0.2"
    service_min_supported_version: str = "1.0.0"
    terms_url: str = "https://remory.app/terms"
    privacy_url: str = "https://remory.app/privacy"
    support_email: str = "support@remory.app"
    support_phone: str = ""

    # 업로드 저장소: local | s3
    # 컨테이너 배포에서는 로컬 디스크가 재시작 시 사라지므로 운영은 s3 를 쓴다.
    storage_backend: str = "local"
    s3_bucket: str = ""
    # 배포 대상 리전(오리건). presigned URL 이 이 리전 엔드포인트로 발급되므로
    # 버킷 리전과 반드시 같아야 한다.
    s3_region: str = "us-west-2"
    # 버킷 안에서 쓸 상위 폴더(예: "prod"). 비워두면 버킷 루트에 올린다.
    s3_key_prefix: str = ""
    # CloudFront·커스텀 도메인을 앞에 둘 때만 채운다.
    # 비우면 https://<버킷>.s3.<리전>.amazonaws.com 을 쓴다.
    s3_public_base_url: str = ""
    # 버킷을 비공개로 두고 조회 응답에만 만료되는 presigned URL 을 내려준다.
    # 끄면 버킷을 퍼블릭 읽기로 열어야 앱이 파일을 받을 수 있다.
    s3_presign: bool = True
    s3_presign_ttl_sec: int = 3600

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

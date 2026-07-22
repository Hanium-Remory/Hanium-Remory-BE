"""서비스 정보(앱 버전·약관·문의처). 인증 없이 조회 가능."""

from fastapi import APIRouter

from ..config import settings
from ..errors import envelope

router = APIRouter(prefix="/service", tags=["service"])


@router.get("/info")
def get_service_info():
    """ReMory 정보 화면에 표시할 값들. .env 로 관리한다."""
    return envelope(
        {
            "appName": settings.rp_name,
            "version": settings.service_version,
            "minSupportedVersion": settings.service_min_supported_version,
            "termsUrl": settings.terms_url,
            "privacyUrl": settings.privacy_url,
            "supportEmail": settings.support_email,
            "supportPhone": settings.support_phone or None,
        },
        "OK",
        200,
    )

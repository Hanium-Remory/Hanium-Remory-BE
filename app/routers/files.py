"""이미지 업로드. 추억·대화·프로필 사진 공통 API.

업로드 후 돌려주는 URL을 각 리소스 생성 시 imageUrl 로 넣어 쓴다.
저장 위치(로컬/S3)는 STORAGE_BACKEND 설정에 따라 services.storage 가 정한다.
"""

import os

from fastapi import APIRouter, Depends, File, UploadFile

from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Protector
from ..services.storage import storage

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_BYTES = 10 * 1024 * 1024  # 10MB


@router.post("/images")
async def upload_image(
    file: UploadFile = File(...),
    protector: Protector = Depends(get_current_protector),
):
    """이미지 1장 업로드 → 접근 가능한 URL 반환."""
    if not file.filename:
        raise APIError(400, "파일 이름이 없습니다.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise APIError(400, "이미지 파일만 올릴 수 있습니다.")

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise APIError(400, "10MB 이하의 이미지만 올릴 수 있습니다.")

    url = storage.save(content, ext)

    return envelope({"imageUrl": url}, "업로드했습니다.", 200)

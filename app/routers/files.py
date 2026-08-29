"""이미지 업로드. 추억·대화·프로필 사진 공통 API.

업로드 후 돌려주는 URL을 각 리소스 생성 시 imageUrl 로 넣어 쓴다.
저장 위치(로컬/S3)는 STORAGE_BACKEND 설정에 따라 services.storage 가 정한다.

저장 키는 어르신별로, 그 아래 올린 보호자별로 나뉜다(services.storage.image_prefix).
누구 사진인지는 userId 로 받는다. 프로필 사진처럼 어르신이 없는 이미지는 생략한다.
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Protector
from ..services.access import get_owned_user
from ..services.storage import image_prefix, storage

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_BYTES = 10 * 1024 * 1024  # 10MB


@router.post("/images")
async def upload_image(
    file: UploadFile = File(...),
    user_id: Optional[int] = Form(default=None, alias="userId"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """이미지 1장 업로드 → 접근 가능한 URL 반환.

    userId 는 사진의 주인이 될 어르신. 연결되지 않은 어르신을 넣으면 404 다.
    프로필 사진처럼 어르신이 정해지지 않는 경우에만 생략한다.
    """
    if user_id is not None:
        # 권한 없는 어르신 폴더에 파일을 넣지 못하게 여기서 막는다.
        get_owned_user(db, protector, user_id)

    if not file.filename:
        raise APIError(400, "파일 이름이 없습니다.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise APIError(400, "이미지 파일만 올릴 수 있습니다.")

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise APIError(400, "10MB 이하의 이미지만 올릴 수 있습니다.")

    url = storage.save(content, ext, prefix=image_prefix(user_id, protector.id))

    return envelope({"imageUrl": url}, "업로드했습니다.", 200)

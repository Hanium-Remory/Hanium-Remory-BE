"""가족 목소리 등록(보이스 클로닝 학습 시작)·상태 조회·삭제.

흐름: 가족이 녹음 업로드 → status=training → (외부 AI 학습) → status=ready
      → 학습된 목소리를 PATCH /devices/{id}/settings/voice 로 기본 음성 지정.
음성은 기기(device)에 묶이고, 누가 녹음했는지는 protector_id 로 남는다.
"""

import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Protector, Voice
from ..services.access import ensure_default_voice, get_owned_device, voice_json
from ..services.storage import storage

router = APIRouter(tags=["voices"])

VOICE_PREFIX = "voices"
ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".webm", ".ogg"}
MAX_BYTES = 30 * 1024 * 1024  # 30MB


@router.post("/devices/{device_id}/voices", status_code=201)
async def register_voice(
    device_id: int,
    name: str = Form(..., description="음성 이름 (예: '딸 지영')"),
    file: UploadFile = File(..., description="녹음된 음성 파일"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """음성 녹음 등록 → 보이스 클로닝 학습 시작."""
    device = get_owned_device(db, protector, device_id)

    if not file.filename:
        raise APIError(400, "파일 이름이 없습니다.")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise APIError(400, "음성 파일만 올릴 수 있습니다.")

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise APIError(400, "30MB 이하의 음성만 올릴 수 있습니다.")

    audio_url = storage.save(content, ext, prefix=VOICE_PREFIX)

    voice = Voice(
        device_id=device.id,
        protector_id=protector.id,
        name=name.strip(),
        status="training",
        progress=0,
        audio_url=audio_url,
    )
    db.add(voice)
    db.commit()
    db.refresh(voice)

    # TODO(AI 담당): 여기서 보이스 클로닝 학습을 시작하고,
    #   진행률을 progress 에, 완료 시 status 를 ready/failed 로 갱신한다.
    return envelope(voice_json(voice, device), "음성 학습을 시작했습니다.", 201)


@router.get("/devices/{device_id}/voices")
def list_voices(
    device_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """등록된 음성 목록 (인형 목소리 선택·학습 상태 표시용)."""
    device = get_owned_device(db, protector, device_id)
    voices = db.scalars(
        select(Voice).where(Voice.device_id == device.id).order_by(Voice.created_at)
    ).all()
    return envelope([voice_json(v, device) for v in voices], "OK", 200)


@router.get("/voices/{voice_id}/status")
def get_voice_status(
    voice_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """음성 학습 상태 조회 (진행 상태 폴링용)."""
    voice = db.get(Voice, voice_id)
    if voice is None:
        raise APIError(404, "음성을 찾을 수 없습니다.")
    device = get_owned_device(db, protector, voice.device_id)  # 권한 없으면 404
    return envelope(
        {"voiceId": voice.id, "status": voice.status, "progress": voice.progress},
        "OK",
        200,
    )


@router.delete("/voices/{voice_id}")
def delete_voice(
    voice_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """음성 삭제. 기본 음성으로 지정돼 있었다면 지정도 해제한다."""
    voice = db.get(Voice, voice_id)
    if voice is None:
        raise APIError(404, "음성을 찾을 수 없습니다.")
    device = get_owned_device(db, protector, voice.device_id)  # 권한 없으면 404

    # 기본 목소리는 인형이 말할 수단이 없어지므로 지우지 못하게 막는다.
    if voice.protector_id is None:
        raise APIError(400, "기본 목소리는 삭제할 수 없습니다.")

    # 업로드된 녹음 파일도 함께 정리
    if voice.audio_url:
        storage.delete(voice.audio_url)

    was_default = device.default_voice_id == voice.id
    db.delete(voice)
    db.flush()

    # 쓰던 목소리를 지웠으면 기본 목소리로 되돌린다 (인형이 벙어리가 되지 않게).
    if was_default:
        device.default_voice_id = None
        ensure_default_voice(db, device)

    db.commit()
    return envelope({"voiceId": voice_id}, "음성을 삭제했습니다.", 200)

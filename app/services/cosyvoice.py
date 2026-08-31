"""CosyVoice2 음성 서버(2080ti, Tailscale 경유) 호출 — 목소리 등록(제로샷 화자 추가).

앱은 2080ti 에 직접 못 붙는다(Tailscale 사설망). 그래서 EC2(이 코드)가 다리 역할로
CosyVoice 서버의 /enroll 을 호출한다. 제로샷이라 등록이 수 초라, 결과(spk_id)를
그 자리에서 받는다(동기). 별도 학습 큐·콜백이 필요 없다.
"""

import logging

import httpx

from ..config import settings

logger = logging.getLogger("remory.cosyvoice")


class CosyVoiceError(Exception):
    """CosyVoice 서버 호출 실패(연결 불가·타임아웃·비정상 응답)."""


def is_configured() -> bool:
    """GPU_HOST(CosyVoice 서버 주소)가 있으면 등록을 시도한다.

    비어 있으면 등록을 건너뛴다(녹음만 받고 status=training 유지 — 데모/미연동).
    """
    return bool(settings.gpu_host)


async def enroll(spk_id: str, audio: bytes, filename: str) -> str:
    """참조 음성을 CosyVoice /enroll 로 보내 화자를 등록하고 spk_id 를 확정한다.

    CosyVoice 가 add_zero_shot_spk 로 화자를 캐싱하고 speaker_id 를 돌려준다.
    실패하면 CosyVoiceError 를 던진다.
    """
    if not is_configured():
        raise CosyVoiceError("CosyVoice 서버 주소(GPU_HOST)가 설정되지 않았습니다.")

    url = f"{settings.gpu_host.rstrip('/')}/enroll"
    try:
        async with httpx.AsyncClient(timeout=settings.gpu_enroll_timeout_sec) as client:
            resp = await client.post(
                url,
                data={"spk_id": spk_id},
                files={"file": (filename, audio)},
                headers={"X-API-Key": settings.tts_api_key},
            )
    except httpx.HTTPError as e:
        logger.error("CosyVoice /enroll 호출 실패 spk_id=%s: %s", spk_id, e)
        raise CosyVoiceError(f"등록 서버 연결 실패: {e}") from e

    if resp.status_code != 200:
        logger.error(
            "CosyVoice /enroll 비정상 응답 spk_id=%s status=%s body=%s",
            spk_id,
            resp.status_code,
            resp.text[:300],
        )
        raise CosyVoiceError(f"등록 서버가 거부했습니다(status={resp.status_code}).")

    try:
        return resp.json().get("speaker_id") or spk_id
    except ValueError:
        return spk_id

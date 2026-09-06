"""FCM 푸시 발송 (HTTP v1).

firebase-admin SDK 는 쓰지 않는다. 필요한 건 서비스 계정으로 액세스 토큰을
받아 REST 를 한 번 부르는 것뿐이라, google-auth 만 있으면 된다. ID 토큰
검증(firebase.py)이 PyJWT 로 되어 있는 것과 같은 이유다.

키가 설정돼 있지 않으면 조용히 아무것도 하지 않는다. 개발·테스트에서
푸시 없이 그대로 돌아가야 하고, 알림 자체(DB 줄)는 어차피 만들어진다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional

import httpx

from ..config import settings

logger = logging.getLogger("remory.fcm")

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"

# 알림 하나에 붙는 보호자가 많아 봐야 가족 몇 명이라, 요청을 하나씩 보낸다.
# 그래도 사용자 요청 안에서 도는 경로(가족 메시지 보내기 등)가 있으니
# 한 건이 오래 붙잡지 않게 짧게 끊는다.
_TIMEOUT_SEC = 5.0

_lock = threading.Lock()
_credentials = None


class FcmError(Exception):
    """보낼 수 없었다. 부르는 쪽은 무시하고 지나가도 된다."""


def _load_credentials():
    """서비스 계정 자격증명. 없으면 None.

    FCM_SERVICE_ACCOUNT_FILE(경로)을 먼저 보고, 없으면
    FCM_SERVICE_ACCOUNT_JSON(내용 그대로)을 본다. 컨테이너 배포에서는
    파일을 마운트하는 쪽이 안전하지만, .env 하나로 굴리는 환경도 있어 둘 다 받는다.
    """
    global _credentials
    with _lock:
        if _credentials is not None:
            return _credentials

        try:
            from google.oauth2 import service_account
        except ImportError:
            logger.warning("google-auth 가 설치되어 있지 않아 푸시를 보내지 않는다.")
            return None

        info: Optional[dict] = None
        path = settings.fcm_service_account_file
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                info = json.load(f)
        elif settings.fcm_service_account_json:
            try:
                info = json.loads(settings.fcm_service_account_json)
            except json.JSONDecodeError as e:
                logger.error("FCM_SERVICE_ACCOUNT_JSON 을 읽을 수 없다: %s", e)
                return None

        if info is None:
            return None

        _credentials = service_account.Credentials.from_service_account_info(
            info, scopes=[_SCOPE]
        )
        return _credentials


def _project_id() -> str:
    """메시지를 보낼 Firebase 프로젝트. 서비스 계정 쪽을 우선한다."""
    creds = _load_credentials()
    return getattr(creds, "project_id", "") or settings.firebase_project_id


def enabled() -> bool:
    """푸시를 보낼 수 있는 상태인지. 설정이 없으면 False 다."""
    return _load_credentials() is not None and bool(_project_id())


def _access_token() -> str:
    from google.auth.transport.requests import Request

    creds = _load_credentials()
    if creds is None:
        raise FcmError("서비스 계정이 설정되지 않았습니다.")
    # 만료됐을 때만 새로 받는다(google-auth 가 알아서 판단한다).
    if not creds.valid:
        creds.refresh(Request())
    return creds.token


def send(token: str, title: str, body: str, data: Optional[dict] = None) -> bool:
    """한 기기로 보낸다. 보냈으면 True.

    토큰이 죽었으면(앱 삭제·재설치) FcmError 대신 False 를 주고, 부르는 쪽이
    그 토큰을 지운다. 그 밖의 실패는 로그만 남기고 False 다 — 푸시가 안 갔다고
    알림 생성이나 사용자 요청을 실패시키지는 않는다.
    """
    message = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            # 앱이 탭했을 때 어디로 갈지 판단할 값. 문자열만 담을 수 있다.
            "data": {k: str(v) for k, v in (data or {}).items()},
            "android": {"priority": "high"},
        }
    }

    try:
        response = httpx.post(
            _ENDPOINT.format(project=_project_id()),
            headers={"Authorization": f"Bearer {_access_token()}"},
            json=message,
            timeout=_TIMEOUT_SEC,
        )
    except Exception as e:
        logger.warning("푸시 발송 실패(%s: %s)", type(e).__name__, e)
        return False

    if response.status_code == 200:
        return True

    # 404 UNREGISTERED, 400 INVALID_ARGUMENT — 이 토큰은 다시 써도 소용없다.
    if response.status_code in (400, 404):
        logger.info("죽은 푸시 토큰을 버린다: %s", response.text[:200])
        raise FcmError("토큰이 더 이상 유효하지 않습니다.")

    logger.warning("푸시 발송 실패 %s: %s", response.status_code, response.text[:200])
    return False

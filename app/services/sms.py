"""SMS 발송 추상화.

provider를 .env의 SMS_PROVIDER로 교체:
  - mock  : 실제 발송 없이 콘솔에 코드 출력 (개발/테스트 기본값)
  - aligo : 알리고(https://smartsms.aligo.in) 문자 API
  - ncp   : 네이버 클라우드 SENS SMS API

키/발신번호는 .env로 주입한다. 실제 발송 실패 시 SMSError를 던진다.
"""

import base64
import hashlib
import hmac
import logging
import time

import httpx

from ..config import settings

logger = logging.getLogger("remory.sms")


class SMSError(Exception):
    pass


def send_verification_sms(phone_number: str, code: str) -> None:
    message = f"[ReMory] 인증번호 [{code}] 를 입력해 주세요."
    provider = settings.sms_provider.lower()
    senders = {"mock": _send_mock_, "aligo": _send_aligo, "ncp": _send_ncp}
    send = senders.get(provider)
    if send is None:
        raise SMSError(f"알 수 없는 SMS provider: {provider}")

    try:
        send(phone_number, message)
    except SMSError:
        raise
    except Exception as e:
        # 타임아웃·연결 실패·JSON 아닌 응답 등. 여기서 안 잡으면 라우터의
        # except SMSError 를 빠져나가 500 이 되고, 사용자는 이유를 못 본다.
        raise SMSError(f"{provider} 발송 중 오류: {type(e).__name__}: {e}") from e


def _send_mock_(phone_number: str, message: str) -> None:
    # 코드는 message 안에 들어 있다. 로그에서 찾아 쓰라고 눈에 띄게 남긴다.
    logger.warning("📱 [MOCK SMS] to=%s | %s", phone_number, message)


def _send_mock(phone_number: str, code: str, message: str) -> None:
    logger.warning("📱 [MOCK SMS] to=%s | %s (code=%s)", phone_number, message, code)


def _send_aligo(phone_number: str, message: str) -> None:
    if not (settings.aligo_api_key and settings.aligo_user_id and settings.sms_sender_number):
        raise SMSError("Aligo 설정(ALIGO_API_KEY/ALIGO_USER_ID/SMS_SENDER_NUMBER)이 비어 있습니다.")
    data = {
        "key": settings.aligo_api_key,
        "user_id": settings.aligo_user_id,
        "sender": settings.sms_sender_number,
        "receiver": phone_number,
        "msg": message,
    }
    if settings.aligo_test_mode:
        # 실제로 보내지 않고 요청만 검증한다. 잔액도 차감되지 않는다.
        data["testmode_yn"] = "Y"

    resp = httpx.post("https://apis.aligo.in/send/", data=data, timeout=10)
    resp.raise_for_status()
    try:
        body = resp.json()
    except ValueError:
        # 점검 중이면 HTML 이 온다.
        raise SMSError(f"Aligo 응답을 읽을 수 없습니다: {resp.text[:200]}")

    # 알리고: result_code 1 이면 성공, 음수면 실패
    if str(body.get("result_code")) != "1":
        raise SMSError(
            f"Aligo 발송 실패 (result_code={body.get('result_code')}): {body.get('message')}"
        )
    logger.info(
        "SMS 발송 완료(aligo%s) to=%s", " · 테스트모드" if settings.aligo_test_mode else "", phone_number
    )


def _send_ncp(phone_number: str, message: str) -> None:
    ak, sk, sid = settings.ncp_access_key, settings.ncp_secret_key, settings.ncp_service_id
    if not (ak and sk and sid and settings.sms_sender_number):
        raise SMSError("NCP SENS 설정(NCP_ACCESS_KEY/NCP_SECRET_KEY/NCP_SERVICE_ID/SMS_SENDER_NUMBER)이 비어 있습니다.")
    timestamp = str(int(time.time() * 1000))
    uri = f"/sms/v2/services/{sid}/messages"
    sig_str = f"POST {uri}\n{timestamp}\n{ak}"
    signature = base64.b64encode(
        hmac.new(sk.encode(), sig_str.encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "x-ncp-apigw-timestamp": timestamp,
        "x-ncp-iam-access-key": ak,
        "x-ncp-apigw-signature-v2": signature,
    }
    payload = {
        "type": "SMS",
        "from": settings.sms_sender_number,
        "content": message,
        "messages": [{"to": phone_number}],
    }
    resp = httpx.post(
        f"https://sens.apigw.ntruss.com{uri}", json=payload, headers=headers, timeout=10
    )
    if resp.status_code not in (200, 202):
        raise SMSError(f"NCP SENS 발송 실패: {resp.status_code} {resp.text[:200]}")
    logger.info("SMS 발송 완료(ncp) to=%s", phone_number)

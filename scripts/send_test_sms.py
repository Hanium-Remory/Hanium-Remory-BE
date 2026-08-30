"""설정된 제공자로 문자를 실제로 보내 본다.

키를 받은 뒤 앱을 거치지 않고 발송 설정만 따로 확인할 때 쓴다.
가입 흐름을 태우면 실패 원인이 앱인지 문자인지 가리기 어렵다.

  python scripts/send_test_sms.py --check          # 안 보내고 키만 확인(솔라피)
  python scripts/send_test_sms.py 010-1234-5678
  python scripts/send_test_sms.py 01012345678 --code 999999

솔라피는 잔액 조회로 키를 확인할 수 있어 문자를 안 보내도 된다.
알리고는 ALIGO_TEST_MODE=true 로 두면 실제 발송·과금 없이 요청만 검증된다.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.services.sms import SMSError, check_credentials, send_verification_sms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phone", nargs="?", help="받는 번호. 하이픈은 있어도 된다")
    ap.add_argument("--check", action="store_true", help="보내지 않고 키만 확인한다")
    ap.add_argument("--code", default="123456", help="문자에 넣을 인증번호 (기본 123456)")
    args = ap.parse_args()

    if args.check:
        try:
            print(check_credentials())
        except Exception as e:
            print(f"❌ 확인 실패: {type(e).__name__}: {e}")
            raise SystemExit(1)
        return

    if not args.phone:
        ap.error("받는 번호가 필요하다 (또는 --check)")
    phone = args.phone.replace("-", "").replace(" ", "").strip()

    print(f"provider : {settings.sms_provider}")
    print(f"발신번호 : {settings.sms_sender_number or '(비어 있음)'}")
    if settings.sms_provider == "aligo":
        print(f"테스트모드: {'예 (실제 발송 안 됨)' if settings.aligo_test_mode else '아니오 — 실제로 발송된다'}")
    if settings.sms_provider == "solapi":
        print("참고    : --check 로 보내지 않고 키만 확인할 수 있다")
    print(f"받는 번호: {phone}")
    print()

    if settings.sms_provider == "mock":
        print("⚠️  provider 가 mock 이다. 실제로는 가지 않고 로그에만 찍힌다.")
        print("   실제 발송을 보려면 SMS_PROVIDER 를 solapi/aligo/ncp 중 하나로 두고 다시 실행할 것.")
        print()

    try:
        send_verification_sms(phone, args.code)
    except SMSError as e:
        print(f"❌ 실패: {e}")
        raise SystemExit(1)

    print("✅ 발송 요청 성공")
    if settings.sms_provider != "mock":
        print("   실제 도착 여부는 해당 번호에서 확인할 것.")


if __name__ == "__main__":
    main()

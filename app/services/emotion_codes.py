"""인형이 보내는 감정 라벨을 앱·리포트가 쓰는 코드로 맞춘다.

인형은 HSEmotion(AffectNet 8감정) 결과를 한글 라벨로 보내는데
(device/emotion/config.py 의 EMOTION_KO), 앱 그래프와 리포트 문구,
부정 감정 알림은 모두 아래 6개 영문 코드를 쓴다. 둘이 어긋나 있으면
감정이 저장돼도 그래프가 평평하게만 나오고 알림도 영영 안 울린다.
인형을 다시 배포하지 않아도 되도록 받는 쪽에서 맞춘다.
"""

from __future__ import annotations

from typing import Optional

# 앱(home_and_alert_center.dart)과 리포트 배치가 아는 코드.
CANONICAL = {"happy", "calm", "sad", "angry", "anxious", "lonely"}

# 8감정을 6개로 줄이므로 겹치는 것이 생긴다. 못마땅함·불쾌는 화남으로,
# 두려움·놀람은 불안으로 모은다 — 보호자에게 보이는 단위가 그 정도다.
_ALIASES = {
    # 인형이 지금 보내는 한글 라벨
    "기쁨": "happy",
    "중립": "calm",
    "평온": "calm",
    "슬픔": "sad",
    "분노": "angry",
    "못마땅함": "angry",
    "불쾌": "angry",
    "두려움": "anxious",
    "불안": "anxious",
    "놀람": "anxious",
    "외로움": "lonely",
    # 같은 모델의 영문 라벨(config 를 영문 블록으로 바꿔 보낼 때)
    "happiness": "happy",
    "neutral": "calm",
    "sadness": "sad",
    "anger": "angry",
    "contempt": "angry",
    "disgust": "angry",
    "fear": "anxious",
    "surprise": "anxious",
}


def normalize_emotion(raw: Optional[str]) -> Optional[str]:
    """감정 라벨을 6개 코드 중 하나로 바꾼다. 못 알아보면 None.

    '알수없음'처럼 감정이 아닌 값도 None 이라 그래프에 섞이지 않는다.
    """
    value = (raw or "").strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered in CANONICAL:
        return lowered
    return _ALIASES.get(value) or _ALIASES.get(lowered)

"""리포트 문구를 LLM 으로 만든다 (Groq).

숫자를 문장으로 바꾸는 일은 규칙으로 짜면 금방 어색해진다(가족과 0번,
대화만 1번 같은 조합이 계속 늘어난다). 요약과 제안 두 문장만 모델에게 맡긴다.

키가 없거나 호출이 실패하면 None 을 준다. 부르는 쪽이 규칙 기반 문구로
물러나므로 배치가 멈추지 않는다 — 리포트가 아예 안 만들어지는 것보다
문구가 덜 자연스러운 편이 낫다.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from ..config import settings

logger = logging.getLogger("remory.llm")

SYSTEM = """너는 치매 어르신을 돌보는 가족에게 하루 요약을 전하는 도우미다.

지켜야 할 것:
- 존댓말로, 따뜻하지만 담담하게 쓴다. 과장하거나 걱정을 부추기지 않는다.
- 주어진 숫자 말고 다른 사실을 지어내지 않는다. 인형이 무슨 이야기를 했는지,
  어르신이 무엇을 드셨는지 같은 건 알 수 없으므로 쓰지 않는다.
- 기록이 적은 날은 적은 대로 담백하게 쓴다. 억지로 좋게 포장하지 않는다.
- 각 문장은 한국어로 두 문장을 넘기지 않는다.

반드시 아래 형태의 JSON 하나만 출력한다. 다른 말은 붙이지 않는다.
{"summary": "오늘 하루 요약", "suggestion": "보호자가 오늘 해볼 만한 것"}"""


class ReportText(BaseModel):
    """모델이 채워 줄 두 문장."""

    summary: str = Field(min_length=1, max_length=400)
    suggestion: str = Field(min_length=1, max_length=400)


def _prompt(
    name: str, conversations: int, family: int, emotion_label: Optional[str]
) -> str:
    return (
        f"어르신 성함: {name}\n"
        f"인형과 나눈 대화: {conversations}번\n"
        f"가족이 대화방에 남긴 메시지: {family}번\n"
        f"오늘 가장 많이 기록된 감정: {emotion_label or '기록 없음'}\n\n"
        "위 기록만 가지고 요약과 제안을 JSON 으로 써 줘."
    )


def write_report_text(
    name: str,
    conversations: int,
    family: int,
    emotion_label: Optional[str],
) -> Optional[ReportText]:
    """요약·제안 문구를 만든다. 못 만들면 None."""
    if not settings.groq_api_key:
        return None

    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.llm_model,
            # JSON 모드. 스키마 강제까지는 모델마다 달라서, 형태는 아래에서 검증한다.
            response_format={"type": "json_object"},
            temperature=0.4,
            max_completion_tokens=500,
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": _prompt(name, conversations, family, emotion_label),
                },
            ],
        )
        raw = response.choices[0].message.content or ""
        return ReportText.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        # JSON 모드라도 형태가 어긋날 수 있다. 그때는 기본 문구로 간다.
        logger.warning("리포트 문구 형식이 어긋남(%s). 기본 문구를 쓴다.", e)
        return None
    except Exception as e:
        # 배치를 멈추지 않는다. 부르는 쪽이 규칙 기반 문구로 물러난다.
        logger.warning("리포트 문구 생성 실패(%s: %s). 기본 문구를 쓴다.", type(e).__name__, e)
        return None

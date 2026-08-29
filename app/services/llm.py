"""리포트 문구를 Claude 로 만든다.

숫자를 문장으로 바꾸는 일은 규칙으로 짜면 금방 어색해진다(가족과 0번,
대화만 1번 같은 조합이 계속 늘어난다). 요약과 제안 두 문장만 모델에게 맡긴다.

키가 없거나 호출이 실패하면 None 을 준다. 부르는 쪽이 규칙 기반 문구로
물러나므로 배치가 멈추지 않는다 — 리포트가 아예 안 만들어지는 것보다
문구가 덜 자연스러운 편이 낫다.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..config import settings

logger = logging.getLogger("remory.llm")

SYSTEM = """너는 치매 어르신을 돌보는 가족에게 하루 요약을 전하는 도우미다.

지켜야 할 것:
- 존댓말로, 따뜻하지만 담담하게 쓴다. 과장하거나 걱정을 부추기지 않는다.
- 주어진 숫자 말고 다른 사실을 지어내지 않는다. 인형이 무슨 이야기를 했는지,
  어르신이 무엇을 드셨는지 같은 건 알 수 없으므로 쓰지 않는다.
- 기록이 적은 날은 적은 대로 담백하게 쓴다. 억지로 좋게 포장하지 않는다.
- 각 문장은 한국어로 두 문장을 넘기지 않는다."""


class ReportText(BaseModel):
    """모델이 채워 줄 두 문장."""

    summary: str = Field(description="오늘 하루가 어땠는지 요약. 1~2문장.")
    suggestion: str = Field(
        description="보호자가 오늘 해볼 만한 구체적인 행동 제안. 1~2문장."
    )


def _prompt(
    name: str, conversations: int, family: int, emotion_label: Optional[str]
) -> str:
    return (
        f"어르신 성함: {name}\n"
        f"인형과 나눈 대화: {conversations}번\n"
        f"가족이 대화방에 남긴 메시지: {family}번\n"
        f"오늘 가장 많이 기록된 감정: {emotion_label or '기록 없음'}\n\n"
        "위 기록만 가지고 요약과 제안을 써 줘."
    )


def write_report_text(
    name: str,
    conversations: int,
    family: int,
    emotion_label: Optional[str],
) -> Optional[ReportText]:
    """요약·제안 문구를 만든다. 못 만들면 None."""
    if not settings.anthropic_api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.parse(
            model=settings.llm_model,
            max_tokens=4000,
            # 짧은 문구라 깊게 생각할 일이 없다.
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[
                {"role": "user", "content": _prompt(name, conversations, family, emotion_label)}
            ],
            output_format=ReportText,
        )
        return response.parsed_output
    except Exception as e:
        # 배치를 멈추지 않는다. 부르는 쪽이 규칙 기반 문구로 물러난다.
        logger.warning("리포트 문구 생성 실패(%s: %s). 기본 문구를 쓴다.", type(e).__name__, e)
        return None

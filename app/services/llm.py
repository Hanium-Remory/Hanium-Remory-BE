"""리포트 문구를 LLM 으로 만든다 (Groq). 데일리와 주간 둘 다 여기서 쓴다.

숫자를 문장으로 바꾸는 일은 규칙으로 짜면 금방 어색해진다(가족과 0번,
대화만 1번 같은 조합이 계속 늘어난다). 요약과 제안 두 문장만 모델에게 맡긴다.

키가 없거나 호출이 실패하면 None 을 준다. 부르는 쪽이 규칙 기반 문구로
물러나므로 배치가 멈추지 않는다 — 리포트가 아예 안 만들어지는 것보다
문구가 덜 자연스러운 편이 낫다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from ..config import settings

logger = logging.getLogger("remory.llm")

# 한 번에 받아 올 최대 출력 토큰.
#
# 추론형 모델은 답을 내기 전에 토큰을 꽤 쓴다. 500 으로 뒀더니 JSON 을 다
# 못 만들고 잘려서 실패했다. 그래서 1500 으로 올렸는데, 이번엔 Groq 무료
# 등급의 분당 출력 한도(OTPM 1000)를 넘어 요청 자체가 429 로 막혔다
# ("Requested 1110 > Limit 1000"). 그러면 리포트 문구가 늘 규칙 기반으로
# 떨어지는데, 로그를 보지 않으면 알아채기 어렵다.
#
# 한도 아래이면서 JSON 을 다 만들 만큼은 되는 값으로 둔다. 등급을 올리면
# 이 값을 키워도 된다.
MAX_OUTPUT_TOKENS = 900

# 마지막으로 모델을 부른 시각. 잇따라 부르지 않으려고 든다.
_last_call_at = 0.0
_call_lock = threading.Lock()


def _wait_turn() -> None:
    """지난번 호출로부터 llm_min_gap_sec 이 지날 때까지 기다린다.

    무료 등급은 분당 출력 토큰이 정해져 있어 잇따라 부르면 뒤엣것이 429 로
    막힌다. 어르신이 여럿이면 첫 사람 것만 모델이 쓰고 나머지는 규칙 기반으로
    떨어지는데, 로그를 보지 않으면 알아채기 어렵다. 리포트는 밤에 도는
    배치라 빨리 끝날 이유가 없으므로 쉬어 가며 부른다.
    """
    gap = settings.llm_min_gap_sec
    if gap <= 0:
        return
    with _call_lock:
        global _last_call_at
        remain = gap - (time.monotonic() - _last_call_at)
        if remain > 0:
            logger.info("한도에 걸리지 않게 %.0f초 쉰다.", remain)
            time.sleep(remain)
        _last_call_at = time.monotonic()


def _is_rate_limited(error: Exception) -> bool:
    text = str(error).lower()
    return "rate_limit" in text or "429" in text or "too large" in text


def _ask(system: str, user: str, schema, temperature: float):
    """모델에게 한 번 묻고 [schema] 로 받아 온다. 못 받으면 None.

    부르는 쪽은 모두 규칙 기반 문구로 물러날 수 있으므로, 여기서 나는 문제는
    로그만 남기고 None 을 준다. 배치가 멈추지 않는 편이 낫다.
    """
    if not settings.groq_api_key:
        return None

    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
    except Exception as e:
        logger.warning("Groq 준비 실패(%s: %s).", type(e).__name__, e)
        return None

    for attempt in (1, 2):
        _wait_turn()
        try:
            response = client.chat.completions.create(
                model=settings.llm_model,
                response_format={"type": "json_object"},
                temperature=temperature,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            raw = response.choices[0].message.content or ""
            return schema.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as e:
            # JSON 모드라도 형태가 어긋날 수 있다. 다시 물어도 같을 가능성이 커서
            # 한 번만 하고 물러난다.
            logger.warning("응답 형식이 어긋남(%s). 기본 문구를 쓴다.", e)
            return None
        except Exception as e:
            if attempt == 1 and _is_rate_limited(e):
                logger.info("한도에 걸렸다. 쉬었다가 한 번 더 해 본다.")
                continue                      # _wait_turn 이 다시 쉬어 준다
            logger.warning("호출 실패(%s: %s). 기본 문구를 쓴다.", type(e).__name__, e)
            return None
    return None

SYSTEM = """너는 치매 어르신을 돌보는 가족에게 하루 요약을 전하는 도우미다.

지켜야 할 것:
- 존댓말로, 따뜻하지만 담담하게 쓴다. 과장하거나 걱정을 부추기지 않는다.
- 주어진 것 말고 다른 사실을 지어내지 않는다. 대화 내용이 주어지지 않은 날은
  무슨 이야기를 했는지 알 수 없으므로 쓰지 않는다.
- '짚어야 할 일' 이 주어지면 반드시 요약에 담되, 진단하듯 단정하지 말고
  가족이 오늘 살펴볼 만한 일로 담담히 적는다.
- 대화 내용이 주어지면 거기서 드러난 것만 쓴다. 말 그대로 옮기지 말고 한 마디로
  간추린다. 병·증상을 진단하듯 단정하지 않는다.
- 기록이 적은 날은 적은 대로 담백하게 쓴다. 억지로 좋게 포장하지 않는다.
- 각 문장은 한국어로 두 문장을 넘기지 않는다.
- 성함은 주어진 그대로 쓴다. 성을 빼거나 줄이지 않는다.

반드시 아래 형태의 JSON 하나만 출력한다. 다른 말은 붙이지 않는다.
{"summary": "오늘 하루 요약", "suggestion": "보호자가 오늘 해볼 만한 것"}"""


class ReportText(BaseModel):
    """모델이 채워 줄 두 문장."""

    summary: str = Field(min_length=1, max_length=400)
    suggestion: str = Field(min_length=1, max_length=400)


def _prompt(
    name: str,
    conversations: int,
    family: int,
    emotion_label: Optional[str],
    transcript: Optional[str],
    safety_note: Optional[str] = None,
) -> str:
    body = (
        f"어르신 성함: {name}\n"
        f"인형과 나눈 대화: {conversations}번\n"
        f"가족이 대화방에 남긴 메시지: {family}번\n"
        f"오늘 가장 많이 기록된 감정: {emotion_label or '기록 없음'}\n"
    )
    if transcript:
        body += f"\n오늘 나눈 대화:\n{transcript}\n"
    if safety_note:
        body += f"\n짚어야 할 일: {safety_note}\n"
    return body + "\n위 기록만 가지고 요약과 제안을 JSON 으로 써 줘."


def write_report_text(
    name: str,
    conversations: int,
    family: int,
    emotion_label: Optional[str],
    transcript: Optional[str] = None,
    safety_note: Optional[str] = None,
) -> Optional[ReportText]:
    """요약·제안 문구를 만든다. 못 만들면 None.

    [transcript] 는 그날 인형과 나눈 대화를 "어르신: ...", "모리: ..." 로
    붙여 놓은 글이다. 있으면 숫자만 세는 대신 무슨 이야기를 했는지까지
    반영한다. 없으면 예전처럼 숫자만 가지고 쓴다.
    """
    return _ask(
        SYSTEM,
        _prompt(name, conversations, family, emotion_label, transcript, safety_note),
        ReportText,
        temperature=0.4,
    )


WEEKLY_SYSTEM = """너는 치매 어르신을 돌보는 가족에게 한 주 요약을 전하는 도우미다.

지켜야 할 것:
- 존댓말로, 따뜻하지만 담담하게 쓴다. 과장하거나 걱정을 부추기지 않는다.
- 주어진 숫자 말고 다른 사실을 지어내지 않는다.
- 한 주 동안의 흐름(늘었는지 줄었는지, 어떤 감정이 잦았는지)을 짚어 준다.
- 기록이 적은 주는 적은 대로 담백하게 쓴다. 억지로 좋게 포장하지 않는다.
- 한국어로 세 문장을 넘기지 않는다.
- 성함은 주어진 그대로 쓴다. 성을 빼거나 줄이지 않는다.

반드시 아래 형태의 JSON 하나만 출력한다. 다른 말은 붙이지 않는다.
{"summary": "한 주 요약"}"""


class WeeklyText(BaseModel):
    """모델이 채워 줄 한 주 요약."""

    summary: str = Field(min_length=1, max_length=600)


def _weekly_prompt(
    name: str,
    conversations: int,
    family: int,
    emotion_label: Optional[str],
    urgent: int,
    daily_lines: str,
) -> str:
    return (
        f"어르신 성함: {name}\n"
        f"이번 주 인형과 나눈 대화: {conversations}번\n"
        f"이번 주 가족이 남긴 메시지: {family}번\n"
        f"이번 주 가장 많이 기록된 감정: {emotion_label or '기록 없음'}\n"
        f"이번 주 긴급 알림: {urgent}번\n\n"
        f"날짜별 기록:\n{daily_lines or '기록 없음'}\n\n"
        "위 기록만 가지고 한 주 요약을 JSON 으로 써 줘."
    )


def write_weekly_text(
    name: str,
    conversations: int,
    family: int,
    emotion_label: Optional[str],
    urgent: int,
    daily_lines: str,
) -> Optional[WeeklyText]:
    """주간 요약 문구를 만든다. 못 만들면 None (부르는 쪽이 기본 문구로 간다)."""
    return _ask(
        WEEKLY_SYSTEM,
        _weekly_prompt(name, conversations, family, emotion_label, urgent, daily_lines),
        WeeklyText,
        temperature=0.4,
    )


EXCERPT_SYSTEM = """너는 치매 어르신이 인형과 나눈 하루치 대화를 읽고, 가족에게
보여줄 대목을 골라 주는 도우미다.

번호가 붙은 대화가 주어진다. 그중 가족이 보면 좋을 대목을 최대 3개 고르고,
고른 번호와 함께 그 말을 다듬어 돌려준다.

고르는 기준:
- 그날 어르신이 어떻게 지내셨는지 드러나는 대목. 몸 상태, 가족 이야기, 드신
  것, 기분이 드러난 말.
- "응", "그래" 같은 맞장구만 있는 대목은 고르지 않는다.
- 뜻을 알아볼 수 없는 대목은 고르지 않는다.

다듬는 규칙:
- 이 글은 받아쓴 것이라 잘못 적힌 말이 섞여 있다. 앞뒤로 보아 분명한 오타는
  바로잡는다(예: "무릅" → "무릎").
- 그 밖에는 하신 말을 그대로 둔다. 말투와 어미를 바꾸지 말고, 요약하지도
  말고, 없는 말을 보태지도 마라.
- 너무 길면 뒤를 자르되 뜻이 끊기지 않는 데까지만 둔다.
- 고칠 것이 없으면 원문 그대로 돌려준다.

고를 만한 대목이 하나도 없으면 빈 배열을 준다.

반드시 아래 형태의 JSON 하나만 출력한다. 다른 말은 붙이지 않는다.
{"picks": [{"no": 1, "user": "어르신이 하신 말", "mori": "모리가 한 답"}]}"""


class ExcerptPick(BaseModel):
    """고른 대목 하나."""

    no: int
    user: str = Field(min_length=1, max_length=200)
    mori: str = Field(default="", max_length=200)


class ExcerptPicks(BaseModel):
    picks: list[ExcerptPick] = Field(max_length=6)


def write_conversation_excerpt(name: str, numbered: str) -> Optional[list[dict]]:
    """보여줄 대목을 고르고 다듬어 준다. 못 만들면 None.

    [numbered] 는 "1. 어르신: ... / 모리: ..." 처럼 번호를 붙인 그날 대화다.
    시각은 모델에게 맡기지 않는다 — 번호만 고르게 하고, 부르는 쪽이 그 번호로
    실제 시각을 되찾아 붙인다. 모델이 시각을 지어낼 자리를 아예 없앤다.
    """
    if not settings.groq_api_key or not numbered:
        return None

    if not numbered:
        return None
    parsed = _ask(
        EXCERPT_SYSTEM,
        f"어르신 성함: {name}\n\n오늘 나눈 대화:\n{numbered}",
        ExcerptPicks,
        temperature=0.2,
    )
    if parsed is None:
        return None
    return [p.model_dump() for p in parsed.picks] or None


STORY_SYSTEM = """너는 치매 어르신을 돌보는 가족에게 오늘 하루가 어땠는지
들려주는 도우미다.

머리말이 하나 주어진다. 화면 맨 위에 이미 크게 걸려 있는 글이므로 같은 말을
되풀이하지 마라. 너는 그 아래에서 하루를 이어서 들려준다.

지켜야 할 것:
- 존댓말로, 따뜻하지만 담담하게 쓴다. 과장하거나 걱정을 부추기지 않는다.
- 주어진 기록에 있는 것만 쓴다. 없는 일을 지어내지 않는다. 숫자를 다시
  늘어놓지 말고, 어떤 하루였는지가 드러나게 쓴다.
- 세 문장에서 다섯 문장 사이로 쓴다. 한 문단이면 된다.
- 아침·낮·저녁처럼 시간이 드러나면 그 흐름을 따라 쓴다.
- 받아쓴 글이라 잘못 적힌 말이 섞여 있다. 분명하지 않은 대목은 넘긴다.
- 진단하듯 단정하지 않는다("치매가 악화되었습니다" 같은 말은 쓰지 않는다).
- 기록이 적은 날은 적은 대로 짧게 쓴다. 억지로 채우지 않는다.

반드시 아래 형태의 JSON 하나만 출력한다. 다른 말은 붙이지 않는다.
{"story": "하루 이야기"}"""


class DayStory(BaseModel):
    """하루를 풀어 쓴 한 문단."""

    story: str = Field(min_length=1, max_length=800)


def write_day_story(
    name: str,
    headline: Optional[str],
    transcript: Optional[str],
    emotion_label: Optional[str],
    activities: Optional[str] = None,
    safety_note: Optional[str] = None,
) -> Optional[str]:
    """오늘 하루가 어땠는지 한 문단으로. 못 만들면 None.

    [headline] 은 화면 맨 위에 걸리는 요약이다. 같은 말을 되풀이하지 않도록
    모델에게 함께 준다. 요약과 따로 부르는 이유는, 한 번에 다 받으면 출력이
    길어져 JSON 이 잘리는 일이 생기기 때문이다 — 그러면 요약까지 함께 잃는다.
    """
    if not transcript and not activities:
        return None

    body = f"어르신 성함: {name}\n"
    if headline:
        body += f"이미 걸려 있는 머리말: {headline}\n"
    if emotion_label:
        body += f"오늘 가장 많이 기록된 감정: {emotion_label}\n"
    if activities:
        body += f"\n오늘의 일과:\n{activities}\n"
    if transcript:
        body += f"\n오늘 나눈 대화:\n{transcript}\n"
    if safety_note:
        body += f"\n짚어야 할 일: {safety_note}\n"
    body += "\n위 기록만 가지고 하루 이야기를 JSON 으로 써 줘."

    parsed = _ask(STORY_SYSTEM, body, DayStory, temperature=0.4)
    return parsed.story.strip() if parsed else None

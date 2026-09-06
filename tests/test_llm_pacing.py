"""모델을 잇따라 부르지 않고 쉬어 가는지.

무료 등급은 분당 출력 토큰이 정해져 있어 연달아 부르면 뒤엣것이 429 로 막힌다.
어르신이 여럿이면 첫 사람 것만 모델이 쓰고 나머지는 규칙 기반으로 떨어지는데,
로그를 보지 않으면 알아채기 어렵다.
"""

import pytest
from pydantic import BaseModel

from app.services import llm


class Answer(BaseModel):
    ok: bool


@pytest.fixture(autouse=True)
def reset_clock(monkeypatch):
    monkeypatch.setattr(llm, "_last_call_at", 0.0)


@pytest.fixture
def clock(monkeypatch):
    """시간을 손으로 돌린다. 진짜로 기다리면 테스트가 그만큼 느려진다."""
    state = {"now": 1000.0, "slept": []}
    monkeypatch.setattr(llm.time, "monotonic", lambda: state["now"])

    def fake_sleep(seconds):
        state["slept"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(llm.time, "sleep", fake_sleep)
    return state


def _stub_groq(monkeypatch, replies):
    """Groq 대신 미리 정한 답(또는 예외)을 내놓는다."""
    calls = []

    class Message:
        def __init__(self, content): self.content = content

    class Choice:
        def __init__(self, content): self.message = Message(content)

    class Response:
        def __init__(self, content): self.choices = [Choice(content)]

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return Response(reply)

    class Chat:
        completions = Completions()

    class FakeGroq:
        def __init__(self, api_key=None): self.chat = Chat()

    import groq
    monkeypatch.setattr(groq, "Groq", FakeGroq)
    monkeypatch.setattr(llm.settings, "groq_api_key", "test-key")
    return calls


def test_first_call_does_not_wait(clock, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 65.0)
    _stub_groq(monkeypatch, ['{"ok": true}'])

    assert llm._ask("s", "u", Answer, temperature=0.4).ok is True
    assert clock["slept"] == [], "첫 호출부터 기다릴 이유가 없다"


def test_second_call_waits_out_the_gap(clock, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 65.0)
    _stub_groq(monkeypatch, ['{"ok": true}', '{"ok": true}'])

    llm._ask("s", "u", Answer, temperature=0.4)
    llm._ask("s", "u", Answer, temperature=0.4)
    assert clock["slept"] == [65.0]


def test_no_wait_when_the_gap_already_passed(clock, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 65.0)
    _stub_groq(monkeypatch, ['{"ok": true}', '{"ok": true}'])

    llm._ask("s", "u", Answer, temperature=0.4)
    clock["now"] += 100                      # 그 사이 다른 일로 시간이 흘렀다
    llm._ask("s", "u", Answer, temperature=0.4)
    assert clock["slept"] == []


def test_pacing_can_be_turned_off(clock, monkeypatch):
    """등급을 올렸으면 쉴 이유가 없다."""
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 0)
    _stub_groq(monkeypatch, ['{"ok": true}', '{"ok": true}'])

    llm._ask("s", "u", Answer, temperature=0.4)
    llm._ask("s", "u", Answer, temperature=0.4)
    assert clock["slept"] == []


def test_rate_limit_is_retried_once(clock, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 65.0)
    boom = RuntimeError("Error code: 429 - rate_limit_exceeded")
    calls = _stub_groq(monkeypatch, [boom, '{"ok": true}'])

    assert llm._ask("s", "u", Answer, temperature=0.4).ok is True
    assert len(calls) == 2
    assert clock["slept"] == [65.0], "다시 부르기 전에 쉬어야 뜻이 있다"


def test_other_errors_do_not_retry(clock, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 65.0)
    calls = _stub_groq(monkeypatch, [RuntimeError("연결이 끊겼습니다")])

    assert llm._ask("s", "u", Answer, temperature=0.4) is None
    assert len(calls) == 1, "한도 문제가 아니면 다시 불러도 같다"


def test_broken_json_falls_back_without_retry(clock, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 65.0)
    calls = _stub_groq(monkeypatch, ["이건 JSON 이 아니다"])

    assert llm._ask("s", "u", Answer, temperature=0.4) is None
    assert len(calls) == 1


def test_no_key_means_no_call(monkeypatch):
    monkeypatch.setattr(llm.settings, "groq_api_key", "")
    assert llm._ask("s", "u", Answer, temperature=0.4) is None


def test_output_tokens_stay_under_the_limit(clock, monkeypatch):
    """1500 을 요청했다가 분당 한도(1000)에 막혔던 적이 있다."""
    monkeypatch.setattr(llm.settings, "llm_min_gap_sec", 0)
    calls = _stub_groq(monkeypatch, ['{"ok": true}'])

    llm._ask("s", "u", Answer, temperature=0.4)
    assert calls[0]["max_completion_tokens"] == llm.MAX_OUTPUT_TOKENS
    assert llm.MAX_OUTPUT_TOKENS < 1000

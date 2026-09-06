"""한국 시간 기준 '하루'를 다루는 공용 헬퍼.

리포트도 일과 조회도 '어느 날'이 한국 시간 기준이어야 한다. DB 는 UTC 로
담고 있으므로, 날짜 하나를 받아 UTC 구간으로 바꿔 주는 곳을 한 군데로 둔다.
"""

from __future__ import annotations

import datetime as dt

# 한국은 서머타임이 없어 고정 오프셋이 정확하다. slim 이미지에 tzdata 가
# 없을 수 있어 zoneinfo 대신 쓴다.
KST = dt.timezone(dt.timedelta(hours=9))


def today() -> dt.date:
    """한국 시간 기준 오늘."""
    return dt.datetime.now(KST).date()


def week_start_of(day: dt.date) -> dt.date:
    """그 날이 속한 주의 월요일. 주간 리포트는 월~일을 한 주로 본다."""
    return day - dt.timedelta(days=day.weekday())


def week_bounds(monday: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """월요일부터 이레의 시작·끝을 UTC 로 준다. 끝은 포함하지 않는다."""
    start, _ = day_bounds(monday)
    _, end = day_bounds(monday + dt.timedelta(days=6))
    return start, end


def day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """한국 시간 기준 하루의 시작·끝을 UTC 로 준다. 끝은 포함하지 않는다."""
    start = dt.datetime.combine(day, dt.time.min, tzinfo=KST)
    return (
        start.astimezone(dt.timezone.utc),
        (start + dt.timedelta(days=1)).astimezone(dt.timezone.utc),
    )

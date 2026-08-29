"""하루치 데일리 리포트를 만든다.

systemd timer 가 매일 한 번 부른다(deploy/remory-report.service·timer).

  python scripts/generate_daily_reports.py              # 어제(한국 시간)
  python scripts/generate_daily_reports.py --date 2026-08-29
  python scripts/generate_daily_reports.py --today      # 오늘 것을 미리
  python scripts/generate_daily_reports.py --dry-run    # 확인만

같은 날을 다시 돌려도 안전하다. 이미 있으면 값을 새로 계산해 덮어쓴다.
그날 아무 기록도 없는 어르신은 건너뛴다 — 빈 리포트를 만들고 알림까지
보내면 성가시다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ActivityLog, DailyReport, EmotionRecord, FamilyChatMessage, User
from app.services.notifications import notify_report_ready

# 한국은 서머타임이 없어 고정 오프셋이 정확하다. slim 이미지에 tzdata 가
# 없을 수 있어 zoneinfo 대신 쓴다.
KST = dt.timezone(dt.timedelta(hours=9))

# 리포트의 '감정' 칸에 그대로 들어가는 짧은 말.
EMOTION_LABELS = {
    "happy": "기뻐요",
    "calm": "평온해요",
    "sad": "슬퍼요",
    "angry": "화나요",
    "anxious": "불안해요",
    "lonely": "외로워요",
}

# 요약 문장에 붙일 서술형. 위 라벨을 문장에 끼워 넣으면 말이 안 돼서 따로 둔다.
EMOTION_PHRASES = {
    "happy": "기분 좋게 지내셨어요",
    "calm": "평온하게 지내셨어요",
    "sad": "조금 가라앉아 계셨어요",
    "angry": "화가 나신 때가 있었어요",
    "anxious": "불안해하신 때가 있었어요",
    "lonely": "외로워하신 때가 있었어요",
}

# 활동 코드가 자유 문자열이라 대화로 볼 것을 이름으로 가린다.
CONVERSATION_MARKERS = ("CONVERSATION", "CHAT", "TALK")


def day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """한국 시간 기준 하루의 시작·끝을 UTC 로 준다."""
    start = dt.datetime.combine(day, dt.time.min, tzinfo=KST)
    return start.astimezone(dt.timezone.utc), (start + dt.timedelta(days=1)).astimezone(
        dt.timezone.utc
    )


def build_summary(name: str, conversations: int, family: int, emotion_code: str | None) -> str:
    parts = []
    if conversations:
        parts.append(f"인형과 {conversations}번 이야기")
    if family:
        parts.append(f"가족과 {family}번 소통")

    if parts:
        body = f"{name}님은 " + ", ".join(parts) + "하셨어요."
    else:
        body = f"{name}님의 대화 기록은 없었어요."

    phrase = EMOTION_PHRASES.get(emotion_code or "")
    if phrase:
        body += f" 감정은 대체로 {phrase}."
    return body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (한국 시간 기준). 기본은 어제")
    ap.add_argument("--today", action="store_true", help="오늘 것을 만든다")
    ap.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    args = ap.parse_args()

    today_kst = dt.datetime.now(KST).date()
    if args.date:
        day = dt.date.fromisoformat(args.date)
    elif args.today:
        day = today_kst
    else:
        day = today_kst - dt.timedelta(days=1)

    start, end = day_bounds(day)
    print(f"대상 날짜: {day} (한국 시간)  |  UTC {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M}")
    if args.dry_run:
        print("모드: 확인만\n")

    made = updated = skipped = 0
    db = SessionLocal()
    try:
        for user in db.scalars(select(User)).all():
            activities = db.scalars(
                select(ActivityLog.activity_type).where(
                    ActivityLog.user_id == user.id,
                    ActivityLog.created_at >= start,
                    ActivityLog.created_at < end,
                )
            ).all()
            conversations = sum(
                1
                for a in activities
                if any(m in (a or "").upper() for m in CONVERSATION_MARKERS)
            )

            family = len(
                db.scalars(
                    select(FamilyChatMessage.id).where(
                        FamilyChatMessage.user_id == user.id,
                        FamilyChatMessage.sender_type == "protector",
                        FamilyChatMessage.created_at >= start,
                        FamilyChatMessage.created_at < end,
                    )
                ).all()
            )

            emotions = db.scalars(
                select(EmotionRecord.emotion).where(
                    EmotionRecord.user_id == user.id,
                    EmotionRecord.created_at >= start,
                    EmotionRecord.created_at < end,
                )
            ).all()
            emotion_code = None
            emotion_label = None
            if emotions:
                emotion_code, _ = Counter(emotions).most_common(1)[0]
                emotion_label = EMOTION_LABELS.get(emotion_code, emotion_code)

            if not activities and not family and not emotions:
                print(f"  건너뜀  {user.name}(id={user.id}) — 그날 기록 없음")
                skipped += 1
                continue

            summary = build_summary(user.name, conversations, family, emotion_code)
            print(
                f"  {user.name}(id={user.id}): 대화 {conversations}, 가족 {family}, "
                f"감정 {emotion_label or '-'}"
            )
            print(f"    → {summary}")
            if args.dry_run:
                continue

            report = db.scalars(
                select(DailyReport).where(
                    DailyReport.user_id == user.id, DailyReport.report_date == day
                )
            ).first()
            is_new = report is None
            if is_new:
                report = DailyReport(user_id=user.id, report_date=day)
                db.add(report)

            report.conversation_count = conversations
            report.family_interaction_count = family
            report.emotion_summary = emotion_label
            report.summary = summary
            db.commit()

            if is_new:
                # 다시 돌렸을 때 같은 알림을 또 보내지 않는다.
                notify_report_ready(db, user.id, summary)
                made += 1
            else:
                updated += 1
    finally:
        db.close()

    print(f"\n새로 만듦 {made}건, 갱신 {updated}건, 건너뜀 {skipped}건")


if __name__ == "__main__":
    main()

"""시연용 데일리·주간 리포트를 한 주치 넣는다.

배치(generate_daily_reports.py·generate_weekly_reports.py)는 실제 대화·감정
기록이 쌓여 있어야 숫자가 나온다. 시연 자리에서는 그 기록이 없으니 화면이
'리포트가 아직 없습니다' 로만 뜬다. 그때 한 주치를 만들어 넣는 용도다.

  python scripts/seed_demo_reports.py --dry-run        # 확인만
  python scripts/seed_demo_reports.py                  # 이번 주(월~오늘)
  python scripts/seed_demo_reports.py --week 2026-08-24 --user-id 3

문구와 라벨은 배치와 같은 표를 쓴다(EMOTION_LABELS·build_summary). 시연 화면과
실제 운영 화면이 달라 보이면 시연의 의미가 없다.

배치와 다른 점은 둘뿐이다.
  - 대화·감정 기록 대신 아래 DEMO_WEEK 의 정해진 값을 쓴다.
  - 보호자 푸시를 보내지 않는다. 시연 데이터로 알림까지 울릴 이유가 없다.
    실제와 똑같이 알림도 보이게 하려면 --notify 를 준다.

같은 주를 다시 돌려도 안전하다. 이미 있으면 값을 덮어쓴다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import DailyReport, User, WeeklyReport
from app.services.kst import today, week_start_of
from app.services.notifications import notify_report_ready, notify_weekly_report_ready

# 배치와 같은 표를 쓴다. 여기서 따로 정의하면 시연 문구만 슬그머니 달라진다.
from generate_daily_reports import EMOTION_LABELS, build_summary as build_daily_summary
from generate_weekly_reports import EMOTION_SCORES, build_summary as build_weekly_summary

# 월요일부터 이레치. 감정은 6개 코드 중 하나(app/services/emotion_codes.py).
# 하루하루 조금씩 다르게 두어야 주간 그래프가 평평하지 않다.
DEMO_WEEK = [
    # (대화, 가족 소통, 감정 코드, 보호자 제안)
    (4, 1, "calm", "오후에 짧게 통화 한 번 어떠세요."),
    (6, 2, "happy", "좋아하시는 옛날 노래 이야기를 꺼내 보세요."),
    (3, 0, "lonely", "이틀째 가족 소통이 없었어요. 안부 전화를 권해요."),
    (5, 1, "happy", "산책 다녀오신 이야기를 물어봐 주세요."),
    (7, 2, "happy", "이번 주 대화가 가장 많았던 날이에요."),
    (2, 1, "anxious", "잠자리가 불편하신지 여쭤봐 주세요."),
    (5, 3, "calm", "주말 가족 소통이 많았어요. 다음 주도 이어가 보세요."),
]


def pick_user(db, user_id: int | None) -> User:
    """대상 어르신을 고른다. 여럿인데 지정이 없으면 멈추고 목록을 보여 준다."""
    if user_id is not None:
        user = db.get(User, user_id)
        if user is None:
            sys.exit(f"어르신 id={user_id} 이 없습니다.")
        return user

    users = db.scalars(select(User).order_by(User.id)).all()
    if not users:
        sys.exit("등록된 어르신이 없습니다. 먼저 어르신을 만들어 주세요.")
    if len(users) > 1:
        lines = "\n".join(f"  --user-id {u.id}   {u.name}" for u in users)
        sys.exit(f"어르신이 여러 명입니다. 하나를 지정해 주세요.\n{lines}")
    return users[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, help="대상 어르신. 한 명뿐이면 생략 가능")
    ap.add_argument("--week", help="그 주에 속한 아무 날짜 YYYY-MM-DD. 기본은 이번 주")
    ap.add_argument("--urgent", type=int, default=0, help="주간 리포트의 긴급 알림 횟수")
    ap.add_argument("--notify", action="store_true", help="보호자 알림도 만든다(푸시 발송)")
    ap.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    args = ap.parse_args()

    monday = week_start_of(dt.date.fromisoformat(args.week) if args.week else today())
    # 아직 오지 않은 날의 리포트는 만들지 않는다. 이번 주를 시연하면 보통
    # 주 중간이라, 일요일치까지 넣으면 앱이 미래 날짜를 보여 준다.
    last_day = min(monday + dt.timedelta(days=6), today())
    days = (last_day - monday).days + 1

    db = SessionLocal()
    try:
        user = pick_user(db, args.user_id)
        print(f"대상: {user.name}(id={user.id})")
        print(f"주간: {monday} ~ {monday + dt.timedelta(days=6)} — 데일리 {days}일치 (한국 시간)")
        if args.dry_run:
            print("모드: 확인만\n")

        made = updated = 0
        for offset in range(days):
            day = monday + dt.timedelta(days=offset)
            conversations, family, emotion_code, suggestion = DEMO_WEEK[offset]
            label = EMOTION_LABELS[emotion_code]
            summary = build_daily_summary(user.name, conversations, family, emotion_code)

            print(f"  {day}  대화 {conversations}, 가족 {family}, 감정 {label}")
            print(f"    요약: {summary}")
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
            report.emotion_summary = label
            report.summary = summary
            report.suggestion = suggestion
            db.commit()

            if is_new:
                made += 1
                if args.notify:
                    notify_report_ready(db, user.id, summary)
            else:
                updated += 1

        # 주간은 위에 넣은 데일리를 그대로 더한다. 배치가 하는 것과 같은
        # 계산이라 앱의 두 화면이 다른 숫자를 말하지 않는다.
        used = DEMO_WEEK[:days]
        conversations = sum(row[0] for row in used)
        family = sum(row[1] for row in used)
        codes = [row[2] for row in used]
        dominant_code = max(set(codes), key=codes.count)
        dominant = EMOTION_LABELS[dominant_code]
        avg_score = round(sum(EMOTION_SCORES[c] for c in codes) / len(codes))
        weekly_summary = build_weekly_summary(
            user.name, conversations, family, dominant, args.urgent
        )

        print(
            f"\n  주간  대화 {conversations}, 가족 {family}, 감정 {dominant}, "
            f"점수 {avg_score}, 긴급 {args.urgent}"
        )
        print(f"    요약: {weekly_summary}")

        if not args.dry_run:
            weekly = db.scalars(
                select(WeeklyReport).where(
                    WeeklyReport.user_id == user.id, WeeklyReport.week_start == monday
                )
            ).first()
            weekly_is_new = weekly is None
            if weekly_is_new:
                weekly = WeeklyReport(user_id=user.id, week_start=monday)
                db.add(weekly)

            weekly.total_conversation_count = conversations
            weekly.family_interaction_count = family
            weekly.avg_emotion_score = avg_score
            weekly.dominant_emotion = dominant
            weekly.emergency_alert_count = args.urgent
            weekly.weekly_summary = weekly_summary
            db.commit()

            if weekly_is_new and args.notify:
                notify_weekly_report_ready(db, user.id, weekly_summary)

            print(
                f"\n데일리 새로 {made}건·갱신 {updated}건, "
                f"주간 {'새로 1건' if weekly_is_new else '갱신 1건'}"
            )
            if not args.notify:
                print("보호자 알림은 만들지 않았다(--notify 로 켤 수 있다).")
    finally:
        db.close()


if __name__ == "__main__":
    main()

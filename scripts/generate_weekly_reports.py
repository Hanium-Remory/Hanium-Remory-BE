"""한 주치 주간 리포트를 만든다.

systemd timer 가 주에 한 번 부른다(deploy/remory-weekly.service·timer).

  python scripts/generate_weekly_reports.py                 # 지난주(월~일, 한국 시간)
  python scripts/generate_weekly_reports.py --week 2026-09-01
  python scripts/generate_weekly_reports.py --this-week     # 이번 주를 미리
  python scripts/generate_weekly_reports.py --dry-run       # 확인만

같은 주를 다시 돌려도 안전하다. 이미 있으면 값을 새로 계산해 덮어쓴다.
그 주에 아무 기록도 없는 어르신은 건너뛴다.

대화·가족 소통 횟수는 이미 만들어진 데일리 리포트를 더해서 낸다. 발화는
7일이 지나면 지워지지만(scripts/generate_daily_reports.py) 데일리 리포트는
남으므로, 주간이 늦게 돌아도 숫자가 비지 않는다.

요약 문구는 Claude 가 쓴다(app/services/llm.py). 키가 없거나 호출이 실패하면
규칙 기반 문구로 물러난다.
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
from app.models import DailyReport, EmotionRecord, Notification, User, WeeklyReport
from app.services.kst import today, week_bounds, week_start_of
from app.services.llm import write_week_story, write_weekly_text
from app.services.notifications import TYPE_URGENT, notify_weekly_report_ready

# 리포트의 '감정' 칸에 그대로 들어가는 짧은 말.
EMOTION_LABELS = {
    "happy": "기뻐요",
    "calm": "평온해요",
    "sad": "슬퍼요",
    "angry": "화나요",
    "anxious": "불안해요",
    "lonely": "외로워요",
}

# 감정 코드 → 0~100 점수. 앱의 감정 그래프 높이와 같은 기준을 쓴다
# (lib/4. home/home_and_alert_center.dart 의 _emotionHeights × 100).
# 앱 그래프와 주간 점수가 따로 놀면 같은 주를 두 화면이 다르게 말한다.
EMOTION_SCORES = {
    "happy": 85,
    "calm": 65,
    "lonely": 40,
    "anxious": 32,
    "sad": 25,
    "angry": 20,
}


def build_summary(
    name: str, conversations: int, family: int, emotion_label: str | None, urgent: int
) -> str:
    parts = []
    if conversations:
        parts.append(f"인형과 {conversations}번 이야기")
    if family:
        parts.append(f"가족과 {family}번 소통")

    if parts:
        body = f"{name}님은 이번 주 " + ", ".join(parts) + "하셨어요."
    else:
        body = f"{name}님의 이번 주 대화 기록은 없었어요."

    if emotion_label:
        body += f" 감정은 '{emotion_label}' 가 가장 잦았어요."
    if urgent:
        body += f" 긴급 알림이 {urgent}번 있었어요."
    return body


def count_urgent_alerts(db, user_id: int, start: dt.datetime, end: dt.datetime) -> int:
    """그 주 긴급 알림이 몇 번 있었는지.

    알림은 보호자 한 사람마다 한 줄씩 만들어지므로 그냥 세면 가족 수만큼
    부풀려진다. 한 사건에서 나온 줄은 제목이 같고 시각이 사실상 같으니
    그걸로 묶는다.

    시각을 초 단위로 잘라서 본다. 같은 사건이라도 줄마다 기본값이 따로
    매겨져 마이크로초가 어긋나기 때문이다(실제로 ...299554 와 ...299555 로
    갈려 한 사건이 두 번으로 세어졌다).
    """
    rows = db.execute(
        select(Notification.title, Notification.created_at).where(
            Notification.user_id == user_id,
            Notification.type == TYPE_URGENT,
            Notification.created_at >= start,
            Notification.created_at < end,
        )
    ).all()
    return len({(title, when.replace(microsecond=0)) for title, when in rows})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="그 주에 속한 아무 날짜 YYYY-MM-DD. 기본은 지난주")
    ap.add_argument("--this-week", action="store_true", help="이번 주 것을 만든다")
    ap.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    args = ap.parse_args()

    this_monday = week_start_of(today())
    if args.week:
        monday = week_start_of(dt.date.fromisoformat(args.week))
    elif args.this_week:
        monday = this_monday
    else:
        monday = this_monday - dt.timedelta(days=7)

    sunday = monday + dt.timedelta(days=6)
    start, end = week_bounds(monday)
    print(f"대상 주: {monday} ~ {sunday} (한국 시간)")
    if args.dry_run:
        print("모드: 확인만\n")

    made = updated = skipped = 0
    db = SessionLocal()
    try:
        for user in db.scalars(select(User)).all():
            dailies = db.scalars(
                select(DailyReport)
                .where(
                    DailyReport.user_id == user.id,
                    DailyReport.report_date >= monday,
                    DailyReport.report_date <= sunday,
                )
                .order_by(DailyReport.report_date)
            ).all()

            conversations = sum(d.conversation_count for d in dailies)
            family = sum(d.family_interaction_count for d in dailies)

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

            # 점수를 매길 수 없는 코드는 평균에서 빼고, 하나도 없으면 비워 둔다.
            scored = [EMOTION_SCORES[e] for e in emotions if e in EMOTION_SCORES]
            avg_score = round(sum(scored) / len(scored)) if scored else None

            urgent = count_urgent_alerts(db, user.id, start, end)

            if not dailies and not emotions and not urgent:
                print(f"  건너뜀  {user.name}(id={user.id}) — 그 주 기록 없음")
                skipped += 1
                continue

            daily_lines = "\n".join(
                f"- {d.report_date}: 대화 {d.conversation_count}번, "
                f"가족 {d.family_interaction_count}번, 감정 {d.emotion_summary or '-'}"
                for d in dailies
            )
            written = write_weekly_text(
                user.name, conversations, family, emotion_label, urgent, daily_lines
            )
            summary = written.summary if written else build_summary(
                user.name, conversations, family, emotion_label, urgent
            )

            print(
                f"  {user.name}(id={user.id}): 대화 {conversations}, 가족 {family}, "
                f"감정 {emotion_label or '-'}, 점수 {avg_score if avg_score is not None else '-'}, "
                f"긴급 {urgent}, 데일리 {len(dailies)}일치  "
                f"[{'LLM' if written else '기본 문구'}]"
            )
            print(f"    요약: {summary}")
            if args.dry_run:
                continue

            report = db.scalars(
                select(WeeklyReport).where(
                    WeeklyReport.user_id == user.id, WeeklyReport.week_start == monday
                )
            ).first()
            is_new = report is None
            if is_new:
                report = WeeklyReport(user_id=user.id, week_start=monday)
                db.add(report)

            report.total_conversation_count = conversations
            report.family_interaction_count = family
            report.avg_emotion_score = avg_score
            report.dominant_emotion = emotion_label
            report.emergency_alert_count = urgent
            report.weekly_summary = summary
            report.week_story = write_week_story(
                user.name,
                headline=summary,
                daily_lines=daily_lines,
                emotion_label=emotion_label,
                urgent=urgent,
            )
            db.commit()

            if is_new:
                # 다시 돌렸을 때 같은 알림을 또 보내지 않는다.
                notify_weekly_report_ready(db, user.id, summary)
                made += 1
            else:
                updated += 1
    finally:
        db.close()

    print(f"\n새로 만듦 {made}건, 갱신 {updated}건, 건너뜀 {skipped}건")


if __name__ == "__main__":
    main()

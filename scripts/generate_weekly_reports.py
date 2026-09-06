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

리포트를 다 만들고 나면 그 주 발화를 지운다. 발화는 리포트를 만드는 재료일
뿐이라 옮겨 담은 뒤에는 들고 있을 이유가 없다. 지우는 자리가 주간에 있는
이유는, 주간이 그 주 발화를 아직 쓸 수 있어야 하기 때문이다 — 데일리에서
먼저 지우면 주간이 볼 것이 남지 않는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import (
    DailyReport,
    EmotionRecord,
    Notification,
    User,
    Utterance,
    WeeklyReport,
)
from app.services.kst import KST, day_bounds, today, week_bounds, week_start_of
from app.services.llm import (
    write_week_keywords,
    write_week_story,
    write_weekly_text,
)
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


WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

# 키워드에 넣지 않을 만큼 짧은 말(띄어쓰기 제외). 맞장구는 이야깃거리가 아니다.
KEYWORD_MIN_CHARS = 5


def build_daily_emotions(db, user_id: int, monday: dt.date) -> str:
    """요일별 감정. 월요일부터 이레를 늘 일곱 칸으로 준다.

    기록이 없는 날도 칸을 비워 둔 채로 넣는다. 화면이 요일 축을 그리려면
    빠진 날이 어디인지 알아야 한다.
    """
    days = []
    for offset in range(7):
        day = monday + dt.timedelta(days=offset)
        start, end = day_bounds(day)
        codes = db.scalars(
            select(EmotionRecord.emotion).where(
                EmotionRecord.user_id == user_id,
                EmotionRecord.created_at >= start,
                EmotionRecord.created_at < end,
            )
        ).all()
        entry = {
            "date": day.isoformat(),
            "weekday": WEEKDAY_NAMES[offset],
            "emotion": None,
            "score": None,
        }
        if codes:
            code, _ = Counter(codes).most_common(1)[0]
            scored = [EMOTION_SCORES[c] for c in codes if c in EMOTION_SCORES]
            entry["emotion"] = code
            entry["score"] = round(sum(scored) / len(scored)) if scored else None
        days.append(entry)
    return json.dumps(days, ensure_ascii=False)


def build_keywords(name: str, rows: list) -> str | None:
    """그 주에 자주 나온 이야깃거리. 없으면 None.

    발화는 이 배치가 끝나면 지워지므로 여기서 뽑아 두어야 한다.

    횟수는 모델이 세지 않는다. 모델은 몇 번째 대화에 나왔는지만 짚고, 세는
    일은 여기서 한다. 없는 번호는 버린다 — 모델이 지어낸 숫자를 그대로
    화면에 '12번' 이라고 내걸 수는 없다.
    """
    said = []
    for row in rows:
        if row.speaker != "user":
            continue
        text = " ".join((row.content or "").split())
        if len(text.replace(" ", "")) >= KEYWORD_MIN_CHARS:
            said.append(text)
    if len(said) < 2:                     # 한 번뿐이면 '자주' 라 할 것이 없다
        return None

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(said))
    picks = write_week_keywords(name, numbered)
    if not picks:
        return None

    counted = []
    for pick in picks:
        turns = {t for t in pick.get("turns", []) if 1 <= t <= len(said)}
        if len(turns) < 2:                # 한 번 나온 것은 싣지 않는다
            continue
        counted.append({"word": pick["word"].strip(), "count": len(turns)})
    counted.sort(key=lambda k: k["count"], reverse=True)
    return json.dumps(counted[:5], ensure_ascii=False) if counted else None


def purge_utterances_before(db, cutoff: dt.datetime) -> int:
    """그 시각 이전의 발화를 모두 지우고 지운 줄 수를 준다.

    그 주 것만이 아니라 이전 것까지 함께 치운다. 지난주에 배치가 걸렀더라도
    이번에 따라잡는다.
    """
    result = db.execute(
        delete(Utterance).where(Utterance.created_at < cutoff),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    return result.rowcount or 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="그 주에 속한 아무 날짜 YYYY-MM-DD. 기본은 지난주")
    ap.add_argument("--this-week", action="store_true", help="이번 주 것을 만든다")
    ap.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    ap.add_argument(
        "--keep-utterances",
        action="store_true",
        help="리포트를 만든 뒤에도 그 주 발화를 지우지 않는다(확인용)",
    )
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

            # 이 배치가 끝나면 지워지므로, 키워드는 지금 뽑아 두어야 한다.
            utterances = db.scalars(
                select(Utterance)
                .where(
                    Utterance.user_id == user.id,
                    Utterance.created_at >= start,
                    Utterance.created_at < end,
                )
                .order_by(Utterance.created_at, Utterance.id)
            ).all()

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
                f"긴급 {urgent}, 데일리 {len(dailies)}일치, 발화 {len(utterances)}줄  "
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
            report.daily_emotions = build_daily_emotions(db, user.id, monday)
            report.keywords = build_keywords(user.name, utterances)
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
        # 리포트로 옮겨 담았으니 그 주 발화는 지운다.
        #
        # 아직 끝나지 않은 주는 건드리지 않는다. --this-week 로 미리 만들어
        # 볼 때, 아직 리포트에 담기지 않은 오늘·내일 발화까지 지워질 수 있다.
        now = dt.datetime.now(dt.timezone.utc)
        if args.dry_run or args.keep_utterances:
            pass
        elif end > now:
            print(f"\n아직 끝나지 않은 주라 발화를 그대로 둡니다({sunday} 까지 기다립니다).")
        else:
            purged = purge_utterances_before(db, end)
            if purged:
                print(f"\n{sunday} 까지의 발화 {purged}줄을 지웠습니다.")
    finally:
        db.close()

    print(f"\n새로 만듦 {made}건, 갱신 {updated}건, 건너뜀 {skipped}건")


if __name__ == "__main__":
    main()

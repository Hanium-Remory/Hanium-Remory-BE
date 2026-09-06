"""하루치 데일리 리포트를 만든다.

systemd timer 가 매일 한 번 부른다(deploy/remory-report.service·timer).

  python scripts/generate_daily_reports.py              # 어제(한국 시간)
  python scripts/generate_daily_reports.py --date 2026-08-29
  python scripts/generate_daily_reports.py --today      # 오늘 것을 미리
  python scripts/generate_daily_reports.py --dry-run    # 확인만

같은 날을 다시 돌려도 안전하다. 이미 있으면 값을 새로 계산해 덮어쓴다.
그날 아무 기록도 없는 어르신은 건너뛴다 — 빈 리포트를 만들고 알림까지
보내면 성가시다.

요약과 제안 문구는 Claude 가 쓴다(app/services/llm.py). 키가 없거나 호출이
실패하면 규칙 기반 문구로 물러나고 제안은 비워 둔다.

리포트를 다 만들고 나면 UTTERANCE_RETENTION_DAYS 가 지난 발화를 지운다.
발화는 리포트 재료일 뿐이라 오래 들고 있을 이유가 없다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from sqlalchemy import delete

from app.database import SessionLocal
from app.models import (
    ActivityLog,
    DailyReport,
    EmotionRecord,
    FamilyChatMessage,
    User,
    Utterance,
)
from app.services.kst import KST, day_bounds
from app.services.llm import write_report_text
from app.services.notifications import notify_report_ready

# 발화를 며칠까지 두는지. 리포트를 만들고 나면 쓸 데가 없어 지운다.
UTTERANCE_RETENTION_DAYS = 7

# 리포트 문구를 쓸 때 모델에게 넘길 대화의 최대 길이. 하루 종일 이야기한 날은
# 프롬프트가 너무 길어져서 뒤(최근)부터 이만큼만 자른다.
TRANSCRIPT_MAX_LINES = 60
TRANSCRIPT_MAX_CHARS = 4000

SPEAKER_LABELS = {"user": "어르신", "mori": "모리"}

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


def build_transcript(rows: list[Utterance]) -> str:
    """그날 나눈 말을 "어르신: ...", "모리: ..." 로 붙인다. 없으면 빈 글."""
    lines = [
        f"{SPEAKER_LABELS.get(r.speaker, r.speaker)}: {(r.content or '').strip()}"
        for r in rows
        if (r.content or "").strip()
    ]
    # 긴 날은 최근 쪽을 남긴다 — 하루 끝의 상태가 요약에 더 중요하다.
    lines = lines[-TRANSCRIPT_MAX_LINES:]
    text = "\n".join(lines)
    if len(text) > TRANSCRIPT_MAX_CHARS:
        text = text[-TRANSCRIPT_MAX_CHARS:]
        # 잘린 첫 줄은 문장 중간부터 시작하므로 버린다.
        text = text.split("\n", 1)[-1]
    return text


def purge_old_utterances(db, keep_days: int) -> int:
    """보관 기간이 지난 발화를 지우고 지운 건수를 준다."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=keep_days)
    # synchronize_session=False: 세션이 들고 있는 객체를 맞춰 볼 필요가 없다.
    # 맞춰 보게 두면 SQLAlchemy 가 조건을 파이썬에서 다시 따지는데, SQLite 에서
    # 읽은 시각에는 시간대가 없어 cutoff 와 비교하다 터진다. 곧 세션을 닫는다.
    result = db.execute(
        delete(Utterance).where(Utterance.created_at < cutoff),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    return result.rowcount or 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (한국 시간 기준). 기본은 어제")
    ap.add_argument("--today", action="store_true", help="오늘 것을 만든다")
    ap.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    ap.add_argument(
        "--keep-days",
        type=int,
        default=UTTERANCE_RETENTION_DAYS,
        help=f"발화를 며칠까지 두는지 (기본 {UTTERANCE_RETENTION_DAYS}일). 0 이면 지우지 않는다",
    )
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

            utterances = db.scalars(
                select(Utterance)
                .where(
                    Utterance.user_id == user.id,
                    Utterance.created_at >= start,
                    Utterance.created_at < end,
                )
                .order_by(Utterance.created_at)
            ).all()
            transcript = build_transcript(utterances)

            # '대화 N번'은 인형이 대화 한 판마다 남기는 활동 로그로 센다.
            # 그 로그가 없는데 발화만 있으면(인형이 활동 기록을 아직 안 보내는
            # 버전) 어르신이 말한 횟수로 대신 센다 — 0번으로 두는 것보단 낫다.
            if not conversations and utterances:
                conversations = sum(1 for u in utterances if u.speaker == "user")

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

            if not activities and not family and not emotions and not utterances:
                print(f"  건너뜀  {user.name}(id={user.id}) — 그날 기록 없음")
                skipped += 1
                continue

            written = write_report_text(
                user.name, conversations, family, emotion_label, transcript
            )
            summary = written.summary if written else build_summary(
                user.name, conversations, family, emotion_code
            )
            suggestion = written.suggestion if written else None

            print(
                f"  {user.name}(id={user.id}): 대화 {conversations}, 가족 {family}, "
                f"감정 {emotion_label or '-'}, 발화 {len(utterances)}줄  "
                f"[{'LLM' if written else '기본 문구'}]"
            )
            print(f"    요약: {summary}")
            if suggestion:
                print(f"    제안: {suggestion}")
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
            report.suggestion = suggestion
            db.commit()

            if is_new:
                # 다시 돌렸을 때 같은 알림을 또 보내지 않는다.
                notify_report_ready(db, user.id, summary)
                made += 1
            else:
                updated += 1
        # 리포트를 다 만든 뒤에 지운다 — 오늘치를 만들기 전에 지우면 안 된다.
        if args.keep_days > 0 and not args.dry_run:
            purged = purge_old_utterances(db, args.keep_days)
            if purged:
                print(f"\n{args.keep_days}일 지난 발화 {purged}줄을 지웠습니다.")
    finally:
        db.close()

    print(f"\n새로 만듦 {made}건, 갱신 {updated}건, 건너뜀 {skipped}건")


if __name__ == "__main__":
    main()

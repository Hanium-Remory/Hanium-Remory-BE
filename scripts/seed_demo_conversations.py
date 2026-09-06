"""시연용 대화 기록을 만든다. 리포트를 채워 보기 위한 것이다.

인형이 실제로 돌지 않아도 리포트·발췌·감정 흐름·일과를 눈으로 볼 수 있게,
며칠치 발화와 감정·일과를 넣는다.

  python scripts/seed_demo_conversations.py --user 1            # 최근 5일
  python scripts/seed_demo_conversations.py --user 1 --days 3
  python scripts/seed_demo_conversations.py --user 1 --clear    # 넣은 것을 지운다

넣은 뒤에는 리포트를 만들어야 화면에 보인다:
  python scripts/generate_daily_reports.py --date 2026-09-05
  python scripts/generate_weekly_reports.py --this-week

⚠️ 지어낸 자료다. 실제 어르신 기록과 섞이면 리포트가 사실과 달라진다.
   시연용 계정에서만 쓸 것.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import ActivityLog, EmotionRecord, User, Utterance
from app.services.kst import KST, today

# 하루치 대화. (시각, 어르신 말, 모리 답) 이며 감정도 함께 적어 둔다.
# 받아쓰기가 늘 깔끔하지는 않으므로 오타를 일부러 섞었다 — 모델이 발췌를
# 고르며 바로잡는지 눈으로 보기 위해서다.
DAYS = [
    {
        "emotions": [("calm", 9), ("calm", 13), ("happy", 17)],
        "activities": [("MEDICATION", "아침 혈압약", 8)],
        "turns": [
            (9, "응", "네, 어르신."),
            (9, "오늘 아침에 무릅이 좀 시큰거려서 병원에 다녀왔어. 별거 아니라더라",
                "다행이에요. 무리하지 마시고 천천히 다니세요."),
            (13, "점심에 된장찌개를 끓여 먹었는데 옛날 우리 어머니 맛이 나더라",
                 "어머님 손맛이 생각나셨군요. 어떤 재료를 넣으셨어요?"),
            (17, "손녀가 다음 주에 온다고 전화가 왔어. 벌써부터 기다려져",
                 "기다려지시겠어요. 오면 뭐 해주고 싶으세요?"),
        ],
    },
    {
        "emotions": [("calm", 10), ("lonely", 15)],
        "activities": [],
        "turns": [
            (10, "비가 와서 그런지 종일 몸이 무겁네", "비 오는 날은 더 그러시죠. 따뜻하게 계세요."),
            (15, "그래", "네."),
            (15, "영감 생각이 자꾸 나. 이맘때면 같이 마당에 나가 앉아 있었는데",
                 "그런 날이 있으셨군요. 어떤 이야기를 나누셨어요?"),
        ],
    },
    {
        "emotions": [("happy", 11), ("happy", 16)],
        "activities": [("MEDICATION", "저녁 혈압약", 19)],
        "turns": [
            (11, "아들이 아침에 전화를 했더라고. 목소리 들으니까 좋더라",
                 "반가우셨겠어요. 무슨 이야기 하셨어요?"),
            (16, "마당에 나가서 화분에 물을 줬어. 상추가 제법 컸더라",
                 "잘 크고 있네요. 상추는 어떻게 드시는 걸 좋아하세요?"),
        ],
    },
    {
        "emotions": [("calm", 9), ("anxious", 14), ("calm", 18)],
        "activities": [],
        "turns": [
            (9, "밤에 자꾸 깨서 잠을 설쳤어", "많이 피곤하시겠어요. 낮에 조금 걸어보시는 건 어떠세요?"),
            (14, "약을 먹었는지 안 먹었는지 자꾸 헷갈려",
                 "그러실 수 있어요. 가족분들께 여쭤보시면 좋겠어요."),
            (18, "응 맞아", "네."),
        ],
    },
    {
        "emotions": [("happy", 12), ("calm", 17)],
        "activities": [],
        "turns": [
            (12, "며느리가 반찬을 해다 줬어. 고맙더라고", "마음이 따뜻해지셨겠어요."),
            (17, "옛날에 부산 살 때 자갈치 시장 자주 갔었지. 그때가 좋았어",
                 "부산에 계셨군요. 시장에서 뭘 즐겨 사셨어요?"),
        ],
    },
]


# 턴마다 몇 분씩 벌린다. 같은 시각에 두 턴이 겹치면 어느 답이 어느 말에
# 붙는지 정해지지 않는다.
TURN_GAP_MIN = 7


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=KST).astimezone(
        dt.timezone.utc
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, required=True, help="어르신 userId")
    ap.add_argument("--days", type=int, default=len(DAYS), help=f"며칠치 (최대 {len(DAYS)})")
    ap.add_argument("--clear", action="store_true", help="발화·감정·일과를 지우고 끝낸다")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        user = db.get(User, args.user)
        if user is None:
            print(f"userId={args.user} 인 어르신이 없습니다.")
            raise SystemExit(1)

        if args.clear:
            for model in (Utterance, EmotionRecord, ActivityLog):
                n = db.execute(
                    delete(model).where(model.user_id == user.id),
                    execution_options={"synchronize_session": False},
                ).rowcount
                print(f"  {model.__tablename__}: {n or 0}줄 지움")
            db.commit()
            print("\n지웠습니다. 리포트는 그대로 남아 있습니다.")
            return

        days = min(args.days, len(DAYS))
        base = today()
        print(f"{user.name}(id={user.id}) 에게 {days}일치를 넣습니다.\n")

        for offset in range(days):
            day = base - dt.timedelta(days=offset + 1)   # 어제부터 거슬러
            plan = DAYS[offset]

            seen_hours: dict[int, int] = {}
            for hour, said, replied in plan["turns"]:
                # 같은 시간대에 여러 턴이면 뒤엣것을 몇 분 뒤로 민다.
                nth = seen_hours.get(hour, 0)
                seen_hours[hour] = nth + 1
                minute = nth * TURN_GAP_MIN
                db.add(Utterance(user_id=user.id, speaker="user", content=said,
                                 created_at=at(day, hour, minute)))
                db.add(Utterance(user_id=user.id, speaker="mori", content=replied,
                                 created_at=at(day, hour, minute + 1)))
            for code, hour in plan["emotions"]:
                db.add(EmotionRecord(user_id=user.id, emotion=code,
                                     created_at=at(day, hour)))
            for kind, content, hour in plan["activities"]:
                db.add(ActivityLog(user_id=user.id, activity_type=kind, content=content,
                                   created_at=at(day, hour)))
            # 리포트의 '대화 N번' 은 대화 활동 수로 센다. 화면에 보이는 대목 수와
            # 어긋나지 않게, 맞장구가 아닌 턴마다 하나씩 남긴다.
            for hour, said, _ in plan["turns"]:
                if len(said.replace(" ", "")) < 5:
                    continue
                db.add(ActivityLog(user_id=user.id, activity_type="DAILY_CONVERSATION",
                                   content="이야기를 나눴어요", created_at=at(day, hour, 3)))

            print(f"  {day}: 발화 {len(plan['turns'])*2}줄, "
                  f"감정 {len(plan['emotions'])}건, 일과 {len(plan['activities'])}건")
        db.commit()

        first = base - dt.timedelta(days=days)
        last = base - dt.timedelta(days=1)
        print("\n이제 리포트를 만들면 화면에 보입니다:")
        print(f"  for d in $(seq {days} -1 1); do \\")
        print("    python scripts/generate_daily_reports.py \\")
        print('      --date $(date -v-${d}d +%Y-%m-%d); done')
        print("  python scripts/generate_weekly_reports.py --this-week")
        print(f"\n(넣은 기간: {first} ~ {last})")
    finally:
        db.close()


if __name__ == "__main__":
    main()

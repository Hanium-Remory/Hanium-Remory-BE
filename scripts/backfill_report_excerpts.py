"""이미 만들어진 데일리 리포트에 '오늘 나눈 이야기'를 채운다.

발췌 기능이 들어오기 전에 만들어진 리포트는 이 칸이 비어 있다. 그날 발화가
아직 남아 있으면(기본 7일) 여기서 뽑아 채운다.

  python scripts/backfill_report_excerpts.py              # 비어 있는 것만
  python scripts/backfill_report_excerpts.py --overwrite  # 이미 있는 것도 다시
  python scripts/backfill_report_excerpts.py --dry-run    # 확인만

리포트를 다시 만드는 게 아니라 발췌 칸만 채운다. generate_daily_reports.py 를
과거 날짜로 다시 돌려도 되지만, 그러면 요약·제안까지 모델을 다시 불러
문구가 바뀌고 토큰도 그만큼 든다.

발화가 이미 지워진 날은 건너뛴다. 채울 재료가 없는 것이지 잘못이 아니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import DailyReport, User, Utterance
from app.services.kst import day_bounds

from generate_daily_reports import build_excerpt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true", help="이미 채워진 것도 다시 만든다")
    ap.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    args = ap.parse_args()

    if args.dry_run:
        print("모드: 확인만\n")

    filled = skipped_had = skipped_empty = 0
    db = SessionLocal()
    try:
        reports = db.scalars(
            select(DailyReport).order_by(DailyReport.report_date)
        ).all()
        print(f"리포트 {len(reports)}건을 살펴본다\n")

        for report in reports:
            day = report.report_date
            label = f"{day} (reportId={report.id})"

            if report.excerpt and not args.overwrite:
                skipped_had += 1
                continue
            if day is None:
                print(f"  건너뜀  {label} — 어느 날인지 모른다")
                skipped_empty += 1
                continue

            start, end = day_bounds(day)
            utterances = db.scalars(
                select(Utterance)
                .where(
                    Utterance.user_id == report.user_id,
                    Utterance.created_at >= start,
                    Utterance.created_at < end,
                )
                .order_by(Utterance.created_at, Utterance.id)
            ).all()
            if not utterances:
                print(f"  건너뜀  {label} — 그날 발화가 남아 있지 않다")
                skipped_empty += 1
                continue

            user = db.get(User, report.user_id)
            excerpt = build_excerpt(user.name if user else "어르신", utterances)
            if excerpt is None:
                print(f"  건너뜀  {label} — 옮겨 둘 만한 이야기가 없다")
                skipped_empty += 1
                continue

            picked = json.loads(excerpt)
            print(f"  채움    {label} — {len(picked)}대목")
            for p in picked:
                print(f"            · {p['user']}")
            if args.dry_run:
                continue

            report.excerpt = excerpt
            db.commit()
            filled += 1
    finally:
        db.close()

    print(
        f"\n채움 {filled}건, 이미 있어 건너뜀 {skipped_had}건, "
        f"재료가 없어 건너뜀 {skipped_empty}건"
    )


if __name__ == "__main__":
    main()

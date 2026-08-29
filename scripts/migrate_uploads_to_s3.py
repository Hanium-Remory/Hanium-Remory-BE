"""로컬 디스크에 쌓인 업로드 파일을 S3 로 옮기고 DB 의 URL 을 갱신한다.

STORAGE_BACKEND 를 local 에서 s3 로 바꾸기 전에 한 번 돌린다.
그냥 백엔드만 바꾸면 DB 에 남은 "/uploads/xxx.jpg" 로는 파일을 받을 수 없다.

  # 확인만 (아무것도 바꾸지 않는다)
  docker compose -f docker-compose.prod.yml --env-file .env.prod \
      exec -e STORAGE_BACKEND=s3 api python scripts/migrate_uploads_to_s3.py

  # 실제 이전
  docker compose -f docker-compose.prod.yml --env-file .env.prod \
      exec -e STORAGE_BACKEND=s3 api python scripts/migrate_uploads_to_s3.py --apply

앱이 아직 local 모드로 떠 있어도 된다. -e 로 이 프로세스만 s3 를 보게 하면
파일을 먼저 옮겨두고, 그 다음에 .env.prod 를 고쳐 재기동할 수 있다.

로컬 파일은 지우지 않는다. S3 쪽을 확인한 뒤 직접 지운다.
여러 번 돌려도 안전하다. 이미 옮긴 행은 URL 이 /uploads/ 로 시작하지 않아 건너뛴다.
"""

import argparse
import os
import sys

# scripts/ 에서 실행해도 app 패키지를 찾게 한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.services.storage import S3Storage, _content_type

# (테이블, URL 컬럼). 저장소 URL 이 들어가는 곳 전부.
TARGETS = [
    ("protectors", "profile_image_url"),
    ("memories", "image_url"),
    ("family_chat_messages", "image_url"),
    ("voices", "audio_url"),
]

LOCAL_PREFIX = "/uploads/"
LOCAL_DIR = "uploads"


def build_s3() -> S3Storage:
    if settings.storage_backend != "s3":
        sys.exit(
            "STORAGE_BACKEND 가 s3 가 아닙니다. 이 스크립트는 S3 설정을 읽어야 합니다.\n"
            "docker compose ... exec -e STORAGE_BACKEND=s3 api python "
            "scripts/migrate_uploads_to_s3.py 처럼 넘겨 주세요."
        )
    return S3Storage(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        key_prefix=settings.s3_key_prefix,
        public_base_url=settings.s3_public_base_url,
        presign=settings.s3_presign,
        presign_ttl_sec=settings.s3_presign_ttl_sec,
    )


def upload(s3: S3Storage, local_url: str, apply: bool):
    """로컬 URL 하나를 S3 로 올리고 새 표준 URL 을 준다.

    파일이 없으면 (None, 사유) 를 준다. 이 경우 DB 는 건드리지 않는다.
    """
    key = local_url[len(LOCAL_PREFIX):]
    if ".." in key.split("/"):
        return None, "경로에 .. 가 있어 건너뜀"

    path = os.path.join(LOCAL_DIR, key)
    if not os.path.exists(path):
        return None, "디스크에 파일 없음"

    # 키를 그대로 유지한다. 파일 이름이 uuid 라 충돌하지 않는다.
    full_key = s3._full_key(key)
    new_url = f"{s3.base_url}/{full_key}"
    if not apply:
        return new_url, None

    ext = os.path.splitext(key)[1].lower()
    with open(path, "rb") as f:
        s3.client.put_object(
            Bucket=s3.bucket,
            Key=full_key,
            Body=f.read(),
            ContentType=_content_type(ext),
        )
    return new_url, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply",
        action="store_true",
        help="실제로 업로드하고 DB 를 갱신한다. 없으면 무엇을 할지 보여주기만 한다.",
    )
    args = ap.parse_args()

    s3 = build_s3()
    print(f"대상 버킷: {s3.base_url}")
    print(f"모드: {'실제 이전' if args.apply else '확인만 (--apply 를 붙이면 실행)'}\n")

    moved = skipped = 0
    db = SessionLocal()
    try:
        for table, column in TARGETS:
            rows = db.execute(
                text(
                    f"SELECT id, {column} AS url FROM {table} "
                    f"WHERE {column} LIKE :p"
                ),
                {"p": f"{LOCAL_PREFIX}%"},
            ).all()
            if not rows:
                print(f"{table}.{column}: 옮길 행 없음")
                continue

            print(f"{table}.{column}: {len(rows)}건")
            for row in rows:
                new_url, reason = upload(s3, row.url, args.apply)
                if new_url is None:
                    print(f"  건너뜀 id={row.id} ({reason}): {row.url}")
                    skipped += 1
                    continue
                if args.apply:
                    db.execute(
                        text(f"UPDATE {table} SET {column} = :u WHERE id = :i"),
                        {"u": new_url, "i": row.id},
                    )
                print(f"  id={row.id}: {row.url} → {new_url}")
                moved += 1

        if args.apply:
            # 테이블 전체가 끝난 뒤 한 번에 커밋한다.
            # 중간에 실패하면 파일만 올라가고 DB 는 그대로라, 다시 돌리면 된다.
            db.commit()
    finally:
        db.close()

    print(f"\n옮김 {moved}건, 건너뜀 {skipped}건")
    if not args.apply and moved:
        print("실제로 옮기려면 --apply 를 붙여 다시 실행하세요.")
    if args.apply and moved:
        print("S3 에서 파일을 확인한 뒤 uploads 볼륨을 정리하세요.")


if __name__ == "__main__":
    main()

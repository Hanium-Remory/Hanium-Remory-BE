import logging
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """예전에는 여기서 create_all 로 표를 만들었다.

    지금은 Alembic 이 스키마를 관리한다. create_all 은 기존 표의 컬럼 변경을
    반영하지 못해서(emotion_records.score 가 지운 뒤에도 운영 DB 에 남아 있었다)
    마이그레이션으로 옮겼다.

        alembic upgrade head

    컨테이너는 기동할 때 위 명령을 먼저 실행한다(Dockerfile 참고).
    로컬에서 직접 uvicorn 을 띄울 때는 한 번 실행해 주어야 한다.
    """
    return None

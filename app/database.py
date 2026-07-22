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


# 이미 만들어진 테이블에 나중에 추가된 컬럼. create_all은 기존 테이블을 건드리지
# 않으므로, 기존 계정을 지우지 않고 넘어가려면 여기서 채워 준다.
# (임시 조치 — 스키마가 더 늘어나면 Alembic으로 옮길 것)
_ADDED_COLUMNS = {
    "protectors": {
        "relation": "VARCHAR(10)",
        "profile_image_url": "VARCHAR(500)",
    },
}


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl_type in columns.items():
                if name in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
                logging.getLogger("remory.db").info("컬럼 추가: %s.%s", table, name)


def init_db() -> None:
    """개발 편의용: 시작 시 테이블 생성. 운영에서는 Alembic 마이그레이션 권장."""
    from . import models  # noqa: F401  (모델 등록)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()

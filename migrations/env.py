"""Alembic 실행 환경.

접속 문자열과 모델 메타데이터는 앱 설정에서 그대로 가져온다.
alembic.ini 에 URL 을 적어두면 운영 비밀번호가 저장소에 들어가므로 쓰지 않는다.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
from app import models  # noqa: F401  (모델을 메타데이터에 등록)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# %(percent)s 이스케이프 문제를 피하려고 ini 대신 여기서 넣는다.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """DB 에 붙지 않고 SQL 만 뽑는다 (alembic upgrade head --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 컬럼 타입 변경도 자동 감지 대상에 넣는다.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

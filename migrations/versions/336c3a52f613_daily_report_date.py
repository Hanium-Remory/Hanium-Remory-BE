"""daily_reports.report_date 추가

리포트가 어느 날 것인지 남긴다(한국 시간 기준). 예전에는 created_at 만 있어서
"가장 최근" 말고는 고를 수 없었고, 배치를 두 번 돌리면 같은 날 리포트가 두 건
생겼다. (user_id, report_date) 유니크로 막는다.

기존 행은 report_date 가 비어 있다. 유니크 제약에서 NULL 은 서로 충돌하지
않으므로 그대로 둬도 된다.


Revision ID: 336c3a52f613
Revises: a1b2c3d4e5f6
Create Date: 2026-08-30 01:17:48.155526

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '336c3a52f613'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 는 제약 추가에 테이블 재작성이 필요해서 batch 로 감싼다.
    with op.batch_alter_table("daily_reports") as batch:
        batch.add_column(sa.Column("report_date", sa.Date(), nullable=True))
        batch.create_unique_constraint("uq_daily_report_day", ["user_id", "report_date"])


def downgrade() -> None:
    with op.batch_alter_table("daily_reports") as batch:
        batch.drop_constraint("uq_daily_report_day", type_="unique")
        batch.drop_column("report_date")

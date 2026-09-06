"""weekly_reports.week_start 컬럼 추가

어느 주의 요약인지(그 주 월요일, 한국 시간)를 담는다. 배치가 같은 주를
두 번 만들지 않도록 (user_id, week_start) 유니크도 함께 건다.
예전 행에는 값이 없으므로 nullable 이다.


Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-09-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch:
        batch.add_column(sa.Column("week_start", sa.Date(), nullable=True))
        batch.create_unique_constraint(
            "uq_weekly_report_week", ["user_id", "week_start"]
        )


def downgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch:
        batch.drop_constraint("uq_weekly_report_week", type_="unique")
        batch.drop_column("week_start")

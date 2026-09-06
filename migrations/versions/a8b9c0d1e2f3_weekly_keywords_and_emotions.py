"""weekly_reports 에 keywords · daily_emotions 추가

한 주에 자주 나온 이야깃거리와 요일별 감정을 담는다. 발화는 주간 리포트를
만든 뒤 지우므로, 키워드는 지우기 전에 뽑아 여기 남겨야 한다.


Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch:
        batch.add_column(sa.Column("keywords", sa.Text(), nullable=True))
        batch.add_column(sa.Column("daily_emotions", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch:
        batch.drop_column("daily_emotions")
        batch.drop_column("keywords")

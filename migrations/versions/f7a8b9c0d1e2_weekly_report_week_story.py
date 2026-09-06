"""weekly_reports.week_story 컬럼 추가

한 주가 어떻게 흘렀는지 풀어 쓴 글. weekly_summary 는 맨 위에 걸리는
머리말이고, 이쪽은 아래에서 한 주를 돌아보며 들려준다.


Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-07 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch:
        batch.add_column(sa.Column("week_story", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch:
        batch.drop_column("week_story")

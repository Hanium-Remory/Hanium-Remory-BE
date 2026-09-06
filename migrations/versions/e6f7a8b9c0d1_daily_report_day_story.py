"""daily_reports.day_story 컬럼 추가

하루가 어떻게 흘렀는지 풀어 쓴 글. summary 는 화면 맨 위에 크게 걸리는
한 줄 머리말이고, 이쪽은 그 아래에서 하루를 이어서 들려준다.


Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("daily_reports") as batch:
        batch.add_column(sa.Column("day_story", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("daily_reports") as batch:
        batch.drop_column("day_story")

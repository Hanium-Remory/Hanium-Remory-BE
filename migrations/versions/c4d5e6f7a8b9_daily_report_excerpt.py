"""daily_reports.excerpt 컬럼 추가

그날 나눈 이야기에서 몇 대목을 JSON 으로 담는다. 발화는 7일 뒤 지워지므로
리포트를 만들 때 뽑아 두지 않으면 지난 리포트는 발췌를 영영 못 보여준다.


Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-06 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("daily_reports") as batch:
        batch.add_column(sa.Column("excerpt", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("daily_reports") as batch:
        batch.drop_column("excerpt")

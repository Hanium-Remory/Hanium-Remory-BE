"""devices.in_conversation 컬럼 추가

어르신이 인형과 실제로 대화 중인지(웨이크워드~대화 종료)를 담는다.
인형이 대화 시작/종료 시 갱신하며, 앱은 '연결됨'과 '대화중'을 구분해 표시한다.
기존 행은 False 로 채운다.


Revision ID: c1d2e3f4a5b6
Revises: d1e2f3a4b5c6
Create Date: 2026-09-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.add_column(
            sa.Column(
                "in_conversation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("in_conversation")

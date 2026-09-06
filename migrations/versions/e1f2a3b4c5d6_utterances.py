"""utterances 테이블 추가

인형과 어르신이 주고받은 말을 리포트 재료로 담아 둔다. 오래 쌓지 않고
7일이 지나면 데일리 배치가 지우므로, 조회·삭제가 함께 쓰는
(user_id, created_at) 인덱스를 같이 만든다.


Revision ID: e1f2a3b4c5d6
Revises: c1d2e3f4a5b6
Create Date: 2026-09-06 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "utterances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_utterances_user_created", "utterances", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_utterances_user_created", table_name="utterances")
    op.drop_table("utterances")

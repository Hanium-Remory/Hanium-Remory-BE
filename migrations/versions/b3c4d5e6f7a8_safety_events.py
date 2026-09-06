"""safety_events 테이블 추가

인형이 대화에서 가려낸 위험 신호(자해·의료·학대·거친 말)를 담는다.
발췌는 민감해서 오래 두지 않는다 — 발화와 같은 기간만 두고 데일리 배치가
함께 지운다.


Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-06 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "safety_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_safety_events_user_created", "safety_events", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_safety_events_user_created", table_name="safety_events")
    op.drop_table("safety_events")

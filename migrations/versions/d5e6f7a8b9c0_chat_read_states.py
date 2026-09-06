"""chat_read_states 테이블 추가

보호자가 대화방을 어디까지 읽었는지 사람마다 한 줄로 둔다. 메시지가 쌓여도
가족 수만큼만 줄이 생긴다.


Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-06 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_read_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("protector_id", sa.Integer(), nullable=False),
        sa.Column("last_read_message_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["protector_id"], ["protectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "protector_id", name="uq_chat_read_state"),
    )
    op.create_index("ix_chat_read_states_user_id", "chat_read_states", ["user_id"])
    op.create_index(
        "ix_chat_read_states_protector_id", "chat_read_states", ["protector_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_read_states_protector_id", table_name="chat_read_states")
    op.drop_index("ix_chat_read_states_user_id", table_name="chat_read_states")
    op.drop_table("chat_read_states")

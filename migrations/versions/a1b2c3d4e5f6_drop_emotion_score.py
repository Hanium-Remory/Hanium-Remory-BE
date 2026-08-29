"""emotion_records.score 제거

모델에서 score 를 뺐지만 create_all 은 기존 표의 컬럼을 지우지 못해
운영 DB 에 그대로 남아 있었다(2026-08-30 확인). 여기서 맞춘다.

빈 DB 에서는 기준선이 애초에 score 를 만들지 않으므로 할 일이 없다.

Revision ID: a1b2c3d4e5f6
Revises: 59f764af5cc9
Create Date: 2026-08-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "59f764af5cc9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_score() -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("emotion_records"):
        return False
    return any(c["name"] == "score" for c in inspector.get_columns("emotion_records"))


def upgrade() -> None:
    if _has_score():
        op.drop_column("emotion_records", "score")


def downgrade() -> None:
    if not _has_score():
        op.add_column(
            "emotion_records",
            sa.Column("score", sa.Integer(), nullable=True),
        )

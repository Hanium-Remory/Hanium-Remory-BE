"""family_chat_messages.audio_url 컬럼 추가

어르신이 인형에게 말씀하신 답장을 글과 함께 목소리로도 남긴다. 가족에게
보낸 답장만 보관하고, 평소 대화 녹음은 인형 밖으로 나가지 않는다.


Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-10-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("family_chat_messages") as batch:
        batch.add_column(sa.Column("audio_url", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("family_chat_messages") as batch:
        batch.drop_column("audio_url")

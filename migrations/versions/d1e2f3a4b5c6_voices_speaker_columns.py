"""voices 화자 등록 결과 컬럼 추가

CosyVoice 제로샷 화자 등록 결과를 담는다.
- speaker_id: 등록이 끝나면 부여되는 화자 식별자(합성 시 이 값으로 목소리를 지목)
- error_message: 등록 실패 사유

기존 행(기본 음성·등록 전)은 둘 다 NULL 로 둔다.


Revision ID: d1e2f3a4b5c6
Revises: deeccd9ed0d3
Create Date: 2026-08-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'deeccd9ed0d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 는 컬럼 추가에도 batch 로 감싸는 편이 안전하다.
    with op.batch_alter_table("voices") as batch:
        batch.add_column(sa.Column("speaker_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("error_message", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("voices") as batch:
        batch.drop_column("error_message")
        batch.drop_column("speaker_id")

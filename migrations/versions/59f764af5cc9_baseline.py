"""기준선: 지금까지 create_all 로 만들어 온 스키마

이 프로젝트는 원래 앱 기동 시 Base.metadata.create_all 로 테이블을 만들었다.
그래서 이 리비전은 두 가지 DB 를 모두 만나게 된다.

  - 이미 테이블이 있는 DB(운영): 아무것도 하지 않고 적용된 것으로만 기록한다.
    수동 stamp 없이 alembic upgrade head 한 번으로 넘어가게 하려는 것이다.
  - 빈 DB(새 환경·로컬): 여기서 표를 전부 만든다.


Revision ID: 59f764af5cc9
Revises: 
Create Date: 2026-08-30 01:00:59.510000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '59f764af5cc9'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 이미 만들어진 DB 면 기준선만 찍고 넘어간다.
    if sa.inspect(op.get_bind()).has_table("protectors"):
        return

    op.create_table('phone_verifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('phone_number', sa.String(length=20), nullable=False),
    sa.Column('code', sa.String(length=6), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_phone_verifications_phone_number'), 'phone_verifications', ['phone_number'], unique=False)
    op.create_table('protectors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('phone_number', sa.String(length=20), nullable=True),
    sa.Column('display_name', sa.String(length=50), nullable=False),
    sa.Column('relation', sa.String(length=10), nullable=True),
    sa.Column('profile_image_url', sa.String(length=500), nullable=True),
    sa.Column('user_handle', sa.LargeBinary(), nullable=False),
    sa.Column('onboarding_completed', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_handle')
    )
    op.create_index(op.f('ix_protectors_phone_number'), 'protectors', ['phone_number'], unique=True)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('gender', sa.String(length=10), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('photo_url', sa.String(length=500), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('webauthn_challenges',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('challenge', sa.String(length=255), nullable=False),
    sa.Column('ceremony', sa.String(length=20), nullable=False),
    sa.Column('phone_number', sa.String(length=20), nullable=True),
    sa.Column('user_handle', sa.LargeBinary(), nullable=True),
    sa.Column('display_name', sa.String(length=50), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_webauthn_challenges_challenge'), 'webauthn_challenges', ['challenge'], unique=True)
    op.create_table('activity_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('activity_type', sa.String(length=30), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activity_logs_user_id'), 'activity_logs', ['user_id'], unique=False)
    op.create_table('credentials',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('protector_id', sa.Integer(), nullable=False),
    sa.Column('credential_id', sa.String(length=512), nullable=False),
    sa.Column('public_key', sa.LargeBinary(), nullable=False),
    sa.Column('sign_count', sa.Integer(), nullable=False),
    sa.Column('transports', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['protector_id'], ['protectors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credentials_credential_id'), 'credentials', ['credential_id'], unique=True)
    op.create_index(op.f('ix_credentials_protector_id'), 'credentials', ['protector_id'], unique=False)
    op.create_table('daily_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('conversation_count', sa.Integer(), nullable=False),
    sa.Column('family_interaction_count', sa.Integer(), nullable=False),
    sa.Column('emotion_summary', sa.String(length=50), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_daily_reports_user_id'), 'daily_reports', ['user_id'], unique=False)
    op.create_table('devices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=30), nullable=False),
    sa.Column('serial', sa.String(length=64), nullable=True),
    sa.Column('device_token', sa.String(length=64), nullable=True),
    sa.Column('battery_level', sa.Integer(), nullable=False),
    sa.Column('volume', sa.Integer(), nullable=False),
    sa.Column('default_voice_id', sa.Integer(), nullable=True),
    sa.Column('medication_check', sa.Boolean(), nullable=False),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('serial')
    )
    op.create_index(op.f('ix_devices_device_token'), 'devices', ['device_token'], unique=True)
    op.create_index(op.f('ix_devices_user_id'), 'devices', ['user_id'], unique=False)
    op.create_table('emotion_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('emotion', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_emotion_records_user_id'), 'emotion_records', ['user_id'], unique=False)
    op.create_table('family_chat_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('sender_type', sa.String(length=10), nullable=False),
    sa.Column('sender_id', sa.Integer(), nullable=True),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('delivered_to_device', sa.Boolean(), nullable=False),
    sa.Column('displayed_on_device', sa.Boolean(), nullable=False),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['sender_id'], ['protectors.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_family_chat_messages_user_id'), 'family_chat_messages', ['user_id'], unique=False)
    op.create_table('family_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('protector_id', sa.Integer(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['protector_id'], ['protectors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'protector_id', name='uq_family_user_protector')
    )
    op.create_index(op.f('ix_family_members_protector_id'), 'family_members', ['protector_id'], unique=False)
    op.create_index(op.f('ix_family_members_user_id'), 'family_members', ['user_id'], unique=False)
    op.create_table('invite_codes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('used_by', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['protectors.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['used_by'], ['protectors.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invite_codes_code'), 'invite_codes', ['code'], unique=True)
    op.create_index(op.f('ix_invite_codes_user_id'), 'invite_codes', ['user_id'], unique=False)
    op.create_table('memories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('image_url', sa.String(length=500), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('period', sa.String(length=50), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memories_user_id'), 'memories', ['user_id'], unique=False)
    op.create_table('notification_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('protector_id', sa.Integer(), nullable=False),
    sa.Column('urgent', sa.Boolean(), nullable=False),
    sa.Column('daily_report', sa.Boolean(), nullable=False),
    sa.Column('chat', sa.Boolean(), nullable=False),
    sa.Column('marketing', sa.Boolean(), nullable=False),
    sa.Column('emotion_change', sa.Boolean(), nullable=False),
    sa.Column('device_disconnected', sa.Boolean(), nullable=False),
    sa.Column('medication_missed', sa.Boolean(), nullable=False),
    sa.Column('voice_request', sa.Boolean(), nullable=False),
    sa.Column('message_delivered', sa.Boolean(), nullable=False),
    sa.Column('voice_training_completed', sa.Boolean(), nullable=False),
    sa.Column('weekly_report', sa.Boolean(), nullable=False),
    sa.Column('app_update', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['protector_id'], ['protectors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_settings_protector_id'), 'notification_settings', ['protector_id'], unique=True)
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('protector_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=50), nullable=True),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['protector_id'], ['protectors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_protector_id'), 'notifications', ['protector_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('jti', sa.String(length=64), nullable=False),
    sa.Column('protector_id', sa.Integer(), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['protector_id'], ['protectors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_tokens_jti'), 'refresh_tokens', ['jti'], unique=True)
    op.create_index(op.f('ix_refresh_tokens_protector_id'), 'refresh_tokens', ['protector_id'], unique=False)
    op.create_table('weekly_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('total_conversation_count', sa.Integer(), nullable=False),
    sa.Column('family_interaction_count', sa.Integer(), nullable=False),
    sa.Column('avg_emotion_score', sa.Integer(), nullable=True),
    sa.Column('dominant_emotion', sa.String(length=20), nullable=True),
    sa.Column('emergency_alert_count', sa.Integer(), nullable=False),
    sa.Column('weekly_summary', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_weekly_reports_user_id'), 'weekly_reports', ['user_id'], unique=False)
    op.create_table('dnd_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('start_hour', sa.Integer(), nullable=False),
    sa.Column('end_hour', sa.Integer(), nullable=False),
    sa.Column('allow_urgent_alert', sa.Boolean(), nullable=False),
    sa.Column('allow_wake_word', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dnd_settings_device_id'), 'dnd_settings', ['device_id'], unique=True)
    op.create_table('medications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('time', sa.String(length=5), nullable=False),
    sa.Column('timing', sa.String(length=10), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_medications_device_id'), 'medications', ['device_id'], unique=False)
    op.create_table('voices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('protector_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('audio_url', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['protector_id'], ['protectors.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_voices_device_id'), 'voices', ['device_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """표를 전부 지운다. 기준선이라 되돌릴 일은 사실상 없다."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_voices_device_id'), table_name='voices')
    op.drop_table('voices')
    op.drop_index(op.f('ix_medications_device_id'), table_name='medications')
    op.drop_table('medications')
    op.drop_index(op.f('ix_dnd_settings_device_id'), table_name='dnd_settings')
    op.drop_table('dnd_settings')
    op.drop_index(op.f('ix_weekly_reports_user_id'), table_name='weekly_reports')
    op.drop_table('weekly_reports')
    op.drop_index(op.f('ix_refresh_tokens_protector_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_jti'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_notifications_protector_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_notification_settings_protector_id'), table_name='notification_settings')
    op.drop_table('notification_settings')
    op.drop_index(op.f('ix_memories_user_id'), table_name='memories')
    op.drop_table('memories')
    op.drop_index(op.f('ix_invite_codes_user_id'), table_name='invite_codes')
    op.drop_index(op.f('ix_invite_codes_code'), table_name='invite_codes')
    op.drop_table('invite_codes')
    op.drop_index(op.f('ix_family_members_user_id'), table_name='family_members')
    op.drop_index(op.f('ix_family_members_protector_id'), table_name='family_members')
    op.drop_table('family_members')
    op.drop_index(op.f('ix_family_chat_messages_user_id'), table_name='family_chat_messages')
    op.drop_table('family_chat_messages')
    op.drop_index(op.f('ix_emotion_records_user_id'), table_name='emotion_records')
    op.drop_table('emotion_records')
    op.drop_index(op.f('ix_devices_user_id'), table_name='devices')
    op.drop_index(op.f('ix_devices_device_token'), table_name='devices')
    op.drop_table('devices')
    op.drop_index(op.f('ix_daily_reports_user_id'), table_name='daily_reports')
    op.drop_table('daily_reports')
    op.drop_index(op.f('ix_credentials_protector_id'), table_name='credentials')
    op.drop_index(op.f('ix_credentials_credential_id'), table_name='credentials')
    op.drop_table('credentials')
    op.drop_index(op.f('ix_activity_logs_user_id'), table_name='activity_logs')
    op.drop_table('activity_logs')
    op.drop_index(op.f('ix_webauthn_challenges_challenge'), table_name='webauthn_challenges')
    op.drop_table('webauthn_challenges')
    op.drop_table('users')
    op.drop_index(op.f('ix_protectors_phone_number'), table_name='protectors')
    op.drop_table('protectors')
    op.drop_index(op.f('ix_phone_verifications_phone_number'), table_name='phone_verifications')
    op.drop_table('phone_verifications')
    # ### end Alembic commands ###

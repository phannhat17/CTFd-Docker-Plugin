"""
Migration: Create Container Plugin Tables

Run this with: flask db upgrade
Or manually: python -c "from CTFd import create_app; app = create_app(); app.db.create_all()"
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql, postgresql, sqlite


def upgrade():
    """Create container plugin tables"""
    
    # ContainerChallenge is handled by polymorphic inheritance from Challenges table
    # No separate table needed
    
    # Create container_instances table
    op.create_table(
        'container_instances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('container_id', sa.String(length=64), nullable=True),
        sa.Column('connection_host', sa.String(length=255), nullable=True),
        sa.Column('connection_port', sa.Integer(), nullable=True),
        sa.Column('connection_info', sa.JSON(), nullable=True),
        sa.Column('flag_encrypted', sa.Text(), nullable=False),
        sa.Column('flag_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.Enum('pending', 'provisioning', 'running', 'stopping', 'stopped', 'solved', 'error', name='instance_status'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('stopped_at', sa.DateTime(), nullable=True),
        sa.Column('solved_at', sa.DateTime(), nullable=True),
        sa.Column('last_accessed_at', sa.DateTime(), nullable=True),
        sa.Column('renewal_count', sa.Integer(), nullable=True, default=0),
        sa.Column('extra_data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid')
    )
    
    # Indexes for container_instances
    op.create_index('idx_active_instance', 'container_instances', ['challenge_id', 'account_id', 'status'])
    op.create_index('idx_expiration', 'container_instances', ['status', 'expires_at'])
    op.create_index(op.f('ix_container_instances_account_id'), 'container_instances', ['account_id'])
    op.create_index(op.f('ix_container_instances_challenge_id'), 'container_instances', ['challenge_id'])
    op.create_index(op.f('ix_container_instances_container_id'), 'container_instances', ['container_id'])
    op.create_index(op.f('ix_container_instances_flag_hash'), 'container_instances', ['flag_hash'])
    op.create_index(op.f('ix_container_instances_uuid'), 'container_instances', ['uuid'])
    
    # Create container_flags table
    op.create_table(
        'container_flags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instance_id', sa.Integer(), nullable=False),
        sa.Column('flag_hash', sa.String(length=64), nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('flag_status', sa.Enum('temporary', 'submitted_correct', 'invalidated', name='flag_status'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_by_user_id', sa.Integer(), nullable=True),
        sa.Column('submitted_from_ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('invalidated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['instance_id'], ['container_instances.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('flag_hash')
    )
    
    # Indexes for container_flags
    op.create_index('idx_owner_flags', 'container_flags', ['account_id', 'challenge_id', 'flag_status'])
    op.create_index(op.f('ix_container_flags_account_id'), 'container_flags', ['account_id'])
    op.create_index(op.f('ix_container_flags_challenge_id'), 'container_flags', ['challenge_id'])
    op.create_index(op.f('ix_container_flags_flag_hash'), 'container_flags', ['flag_hash'])
    op.create_index(op.f('ix_container_flags_instance_id'), 'container_flags', ['instance_id'])
    
    # Create container_flag_attempts table
    op.create_table(
        'container_flag_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('submitted_flag_hash', sa.String(length=64), nullable=True),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.Column('is_cheating', sa.Boolean(), nullable=True),
        sa.Column('flag_owner_account_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes for container_flag_attempts
    op.create_index('idx_attempts_timeline', 'container_flag_attempts', ['account_id', 'challenge_id', 'timestamp'])
    op.create_index(op.f('ix_container_flag_attempts_account_id'), 'container_flag_attempts', ['account_id'])
    op.create_index(op.f('ix_container_flag_attempts_challenge_id'), 'container_flag_attempts', ['challenge_id'])
    op.create_index(op.f('ix_container_flag_attempts_submitted_flag_hash'), 'container_flag_attempts', ['submitted_flag_hash'])
    op.create_index(op.f('ix_container_flag_attempts_timestamp'), 'container_flag_attempts', ['timestamp'])
    
    # Create container_audit_logs table
    op.create_table(
        'container_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('instance_id', sa.Integer(), nullable=True),
        sa.Column('challenge_id', sa.Integer(), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('severity', sa.Enum('info', 'warning', 'error', 'critical', name='log_severity'), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['instance_id'], ['container_instances.id']),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes for container_audit_logs
    op.create_index('idx_audit_account', 'container_audit_logs', ['account_id', 'timestamp'])
    op.create_index('idx_audit_search', 'container_audit_logs', ['event_type', 'timestamp'])
    op.create_index(op.f('ix_container_audit_logs_account_id'), 'container_audit_logs', ['account_id'])
    op.create_index(op.f('ix_container_audit_logs_challenge_id'), 'container_audit_logs', ['challenge_id'])
    op.create_index(op.f('ix_container_audit_logs_event_type'), 'container_audit_logs', ['event_type'])
    op.create_index(op.f('ix_container_audit_logs_severity'), 'container_audit_logs', ['severity'])
    op.create_index(op.f('ix_container_audit_logs_timestamp'), 'container_audit_logs', ['timestamp'])
    
    # Create container_config table
    op.create_table(
        'container_config',
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    """Drop container plugin tables"""
    op.drop_table('container_config')
    op.drop_table('container_audit_logs')
    op.drop_table('container_flag_attempts')
    op.drop_table('container_flags')
    op.drop_table('container_instances')

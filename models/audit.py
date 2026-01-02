"""
Container Audit Log Model
"""
from datetime import datetime
from CTFd.models import db


class ContainerAuditLog(db.Model):
    """
    Audit log cho tất cả container events
    
    Event types:
    - instance_created, instance_started, instance_accessed, instance_renewed
    - instance_stopped_manual, instance_expired, instance_error
    - flag_generated, flag_submitted_correct, flag_submitted_incorrect
    - flag_reuse_detected, flag_invalidated
    """
    __tablename__ = 'container_audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    
    event_type = db.Column(db.String(50), nullable=False, index=True)
    
    # Context
    instance_id = db.Column(db.Integer, db.ForeignKey('container_instances.id'))
    challenge_id = db.Column(db.Integer, index=True)
    account_id = db.Column(db.Integer, index=True)
    user_id = db.Column(db.Integer, index=True)
    
    # Details (JSON for flexibility)
    details = db.Column(db.JSON)
    
    # Request context
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    
    # Severity
    severity = db.Column(
        db.Enum('info', 'warning', 'error', 'critical', name='log_severity'),
        default='info',
        index=True
    )
    
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        db.Index('idx_audit_search', 'event_type', 'timestamp'),
        db.Index('idx_audit_account', 'account_id', 'timestamp'),
    )

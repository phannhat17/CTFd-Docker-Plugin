"""
Container Flag Models - Flag tracking and anti-cheat
"""
from datetime import datetime
from CTFd.models import db


class ContainerFlag(db.Model):
    """
    Track flags for anti-cheat
    
    Flag lifecycle:
    - temporary: Flag just generated, not submitted yet
    - submitted_correct: Flag submitted correctly → KEEP FOREVER
    - invalidated: Flag invalidated (container expired before submission)
    """
    __tablename__ = 'container_flags'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Link to instance
    instance_id = db.Column(
        db.Integer,
        db.ForeignKey('container_instances.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Flag hash (SHA256) - unique to detect reuse
    flag_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    
    # Owner
    challenge_id = db.Column(db.Integer, nullable=False, index=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Status
    flag_status = db.Column(
        db.Enum('temporary', 'submitted_correct', 'invalidated', name='flag_status'),
        nullable=False,
        default='temporary',
        index=True
    )
    
    # Submission tracking
    submitted_at = db.Column(db.DateTime)
    submitted_by_user_id = db.Column(db.Integer)  # User thực tế submit
    submitted_from_ip = db.Column(db.String(45))
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    invalidated_at = db.Column(db.DateTime)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_owner_flags', 'account_id', 'challenge_id', 'flag_status'),
    )
    
    def mark_as_submitted(self, user_id, ip_address):
        """Mark flag as correctly submitted"""
        self.flag_status = 'submitted_correct'
        self.submitted_at = datetime.utcnow()
        self.submitted_by_user_id = user_id
        self.submitted_from_ip = ip_address
    
    def invalidate(self):
        """Invalidate flag (container expired without submission)"""
        if self.flag_status == 'temporary':
            self.flag_status = 'invalidated'
            self.invalidated_at = datetime.utcnow()


class ContainerFlagAttempt(db.Model):
    """
    Log every flag submission attempt (correct or wrong)
    To detect brute force and flag reuse
    """
    __tablename__ = 'container_flag_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Challenge & User
    challenge_id = db.Column(db.Integer, nullable=False, index=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False)
    
    # Submitted flag (hashed)
    submitted_flag_hash = db.Column(db.String(64), index=True)
    
    # Result
    is_correct = db.Column(db.Boolean, nullable=False)
    is_cheating = db.Column(db.Boolean, default=False)
    
    # If cheating, who owned the flag
    flag_owner_account_id = db.Column(db.Integer)
    
    # Context
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relationships
    challenge = db.relationship(
        'Challenges',
        foreign_keys=[challenge_id],
        primaryjoin='ContainerFlagAttempt.challenge_id == Challenges.id',
        backref='flag_attempts',
        lazy='select'
    )
    
    submitter = db.relationship(
        'Users',
        foreign_keys=[user_id],
        primaryjoin='ContainerFlagAttempt.user_id == Users.id',
        lazy='select'
    )
    
    __table_args__ = (
        db.Index('idx_attempts_timeline', 'account_id', 'challenge_id', 'timestamp'),
    )

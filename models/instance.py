"""
Container Instance Model - Tracks running/stopped containers
"""
import uuid
from datetime import datetime, timedelta
from CTFd.models import db


class ContainerInstance(db.Model):
    """
    Represents a container instance
    
    Lifecycle:
    - pending: Creating DB record
    - provisioning: Calling Docker API
    - running: Container is running
    - stopping: Stopping container
    - stopped: Container has stopped
    - solved: User has solved (flag submitted correct)
    - error: An error occurred
    """
    __tablename__ = 'container_instances'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, index=True, default=lambda: str(uuid.uuid4()))
    
    # Challenge reference
    challenge_id = db.Column(
        db.Integer,
        db.ForeignKey('challenges.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Owner - account_id is team_id (team mode) or user_id (user mode)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Docker container info
    container_id = db.Column(db.String(64), index=True)  # Docker container ID
    
    # Connection info
    connection_host = db.Column(db.String(255))  # Host to connect (IP/hostname)
    connection_port = db.Column(db.Integer)  # Exposed port
    connection_ports = db.Column(db.JSON)  # Mapping of internal to external ports: {"80": 30001, "22": 30002}
    connection_info = db.Column(db.JSON)  # Extra connection details
    
    # Flag management (encrypted)
    flag_encrypted = db.Column(db.Text, nullable=False)
    flag_hash = db.Column(db.String(64), nullable=False, index=True)
    
    # Lifecycle status
    status = db.Column(
        db.Enum('pending', 'provisioning', 'running', 'stopping', 'stopped', 'solved', 'error', name='instance_status'),
        nullable=False,
        default='pending',
        index=True
    )
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)  # Khi container actually started
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    stopped_at = db.Column(db.DateTime)
    solved_at = db.Column(db.DateTime)
    last_accessed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Renewal tracking
    renewal_count = db.Column(db.Integer, default=0)
    
    # Extra data (JSON for flexibility) - renamed from 'metadata' to avoid SQLAlchemy conflict
    extra_data = db.Column(db.JSON)
    
    # Indexes
    __table_args__ = (
        # Find active instance of account for challenge
        db.Index('idx_active_instance', 'challenge_id', 'account_id', 'status'),
        # Find instances that need expiration
        db.Index('idx_expiration', 'status', 'expires_at'),
        # Note: Unique constraint with partial index not supported in SQLite
        # Will handle "1 running instance per account" logic in application layer
    )
    
    # Relationships
    challenge = db.relationship(
        'ContainerChallenge',
        foreign_keys=[challenge_id],
        backref=db.backref('instances', lazy='dynamic', cascade='all, delete-orphan')
    )
    
    def is_active(self):
        """Instance is active"""
        return self.status in ('running', 'provisioning')
    
    def is_expired(self):
        """Instance has expired"""
        return datetime.utcnow() > self.expires_at
    
    def should_cleanup(self):
        """Should this record be cleaned up"""
        now = datetime.utcnow()
        
        # Do not cleanup solved instances
        if self.status == 'solved':
            return False
        
        # Cleanup stopped instances after 24h
        if self.status == 'stopped' and self.stopped_at:
            return now - self.stopped_at > timedelta(hours=24)
        
        # Cleanup error instances after 1h
        if self.status == 'error' and self.created_at:
            return now - self.created_at > timedelta(hours=1)
        
        return False
    
    def extend_expiration(self, minutes):
        """Extend expiration time"""
        self.expires_at = datetime.utcnow() + timedelta(minutes=minutes)
        self.renewal_count += 1

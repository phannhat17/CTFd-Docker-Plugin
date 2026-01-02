"""
Container Challenge Model
"""
from CTFd.models import db, Challenges


class ContainerChallenge(Challenges):
    """
    Challenge loại container - spawn Docker container cho mỗi team/user
    """
    __mapper_args__ = {"polymorphic_identity": "container"}
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(
        db.Integer, 
        db.ForeignKey("challenges.id", ondelete="CASCADE"), 
        primary_key=True
    )
    
    # Docker configuration
    image = db.Column(db.String(255), nullable=False)
    internal_port = db.Column(db.Integer, nullable=False, default=22)
    command = db.Column(db.Text, default="")
    
    # Connection info for users
    container_connection_type = db.Column(
        db.String(20), 
        default="ssh",
        name="connection_type"
    )  # ssh, http, nc, custom
    container_connection_info = db.Column(
        db.Text, 
        default="",
        name="connection_info"
    )  # Extra info to display
    
    # Resource limits
    memory_limit = db.Column(db.String(20), default="512m")  # e.g., "512m", "1g"
    cpu_limit = db.Column(db.Float, default=0.5)  # e.g., 0.5 = 50% of one core
    pids_limit = db.Column(db.Integer, default=100)
    
    # Container lifecycle
    timeout_minutes = db.Column(db.Integer, default=60)  # Container auto-expire after N minutes
    max_renewals = db.Column(db.Integer, default=3)  # Số lần renew tối đa
    
    # Flag configuration
    flag_mode = db.Column(
        db.String(20), 
        default="random"
    )  # "random" or "static"
    flag_prefix = db.Column(db.String(50), default="CTF{")
    flag_suffix = db.Column(db.String(50), default="}")
    random_flag_length = db.Column(db.Integer, default=16)
    
    # Dynamic scoring (like CTFd dynamic challenges)
    container_initial = db.Column(db.Integer, default=500, name="initial")
    container_minimum = db.Column(db.Integer, default=100, name="minimum")
    container_decay = db.Column(db.Integer, default=20, name="decay")
    
    def __init__(self, *args, **kwargs):
        super(ContainerChallenge, self).__init__(**kwargs)
        # Set initial value
        if "container_initial" in kwargs:
            self.value = kwargs["container_initial"]
        elif "initial" in kwargs:
            self.value = kwargs["initial"]

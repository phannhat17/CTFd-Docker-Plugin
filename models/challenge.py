"""
Container Challenge Model
"""
import logging

from CTFd.models import db, Challenges

logger = logging.getLogger(__name__)

#: Challenge types that the subdomain/Traefik router can front.
WEB_CONNECTION_TYPES = ('http', 'https', 'web')


class ContainerChallenge(Challenges):
    """
    Container challenge type - spawns Docker container for each team/user
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
    internal_ports = db.Column(db.Text, default="")  # Comma separated list of ports: "80,22"
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

    # Resource limits (deprecated - use global config)
    # Kept for backward compatibility, but values are ignored
    memory_limit = db.Column(db.String(20), nullable=True)
    cpu_limit = db.Column(db.Float, nullable=True)
    pids_limit = db.Column(db.Integer, default=100)

    # Container lifecycle (deprecated - use global config)
    # Kept for backward compatibility, but values are ignored
    timeout_minutes = db.Column(db.Integer, nullable=True)
    max_renewals = db.Column(db.Integer, nullable=True)

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
    decay_function = db.Column(db.String(32), default="logarithmic")  # linear or logarithmic

    def __init__(self, *args, **kwargs):
        super(ContainerChallenge, self).__init__(**kwargs)
        # Set initial value
        if kwargs.get("container_initial") is not None:
            self.value = kwargs["container_initial"]
        elif kwargs.get("initial") is not None:
            self.value = kwargs["initial"]

    # ------------------------------------------------------------------
    # Global-config backed limits
    # ------------------------------------------------------------------
    @staticmethod
    def _config_int(key, default):
        from ..models.config import ContainerConfig
        try:
            return int(ContainerConfig.get(key, default) or default)
        except (TypeError, ValueError):
            logger.warning("Invalid value for config %s, using %s", key, default)
            return int(default)

    def get_timeout_minutes(self):
        """Get timeout from global config"""
        return max(1, self._config_int('default_timeout', 60))

    def get_max_renewals(self):
        """Get max renewals from global config"""
        return max(0, self._config_int('max_renewals', 3))

    def get_memory_limit(self):
        """Get memory limit from global config"""
        from ..models.config import ContainerConfig
        return ContainerConfig.get('max_memory', '512m') or '512m'

    def get_cpu_limit(self):
        """Get CPU limit from global config"""
        from ..models.config import ContainerConfig
        try:
            return float(ContainerConfig.get('max_cpu', 0.5) or 0.5)
        except (TypeError, ValueError):
            return 0.5

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------
    def subdomain_base_domain(self):
        from ..models.config import ContainerConfig
        if (ContainerConfig.get('subdomain_enabled', 'false') or 'false').lower() != 'true':
            return ''
        return (ContainerConfig.get('subdomain_base_domain', '') or '').strip()

    def uses_subdomain_routing(self) -> bool:
        """
        True when this challenge is served through the Traefik subdomain
        router instead of a published host port.
        """
        if not self.subdomain_base_domain():
            return False
        return (self.container_connection_type or '').lower() in WEB_CONNECTION_TYPES

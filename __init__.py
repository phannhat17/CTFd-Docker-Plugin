"""
Container Challenge Plugin

Spawns a Docker container per team/user for CTF challenges, with per-instance
flags, anti-cheat tracking, dynamic scoring and automatic expiry.
"""
import atexit
import logging
import math
import os

from flask import Flask

from CTFd.models import Flags, Solves, db
from CTFd.exceptions.challenges import ChallengeCreateException, ChallengeUpdateException
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.utils import get_config
from CTFd.utils.modes import get_model
from CTFd.utils.user import get_current_user

from .models import (
    ContainerChallenge,
    ContainerInstance,
    ContainerConfig,
)
from .services import (
    DockerService,
    FlagService,
    ContainerService,
    AntiCheatService,
    PortManager,
    NotificationService,
    RedisExpirationService,
)
from .utils import parse_flag_pattern
from .routes import user_bp, admin_bp
from .routes.user import set_services as set_user_services
from .routes.admin import set_services as set_admin_services

logger = logging.getLogger(__name__)

DUMMY_FLAG_CONTENT = '[Container flag - auto-generated per instance]'

#: Challenge fields the admin UI is allowed to set. Anything else in the
#: request body is ignored, so a crafted POST cannot reach arbitrary columns.
EDITABLE_FIELDS = {
    'name', 'category', 'description', 'attribution', 'state', 'max_attempts',
    'requirements', 'next_id', 'value',
    'image', 'internal_port', 'internal_ports', 'command',
    'connection_type', 'connection_info',
    'flag_mode', 'flag_prefix', 'flag_suffix', 'random_flag_length',
    'container_initial', 'container_minimum', 'container_decay', 'decay_function',
    'pids_limit',
}

#: Fields whose values must land on a differently named column.
FIELD_ALIASES = {
    'initial': 'container_initial',
    'minimum': 'container_minimum',
    'decay': 'container_decay',
    'connection_type': 'container_connection_type',
    'connection_info': 'container_connection_info',
}

#: UI-only fields that never belong in the model.
UI_ONLY_FIELDS = {'scoring_type', 'flag_pattern', 'current_value'}

INT_FIELDS = {
    'internal_port', 'timeout_minutes', 'max_renewals', 'random_flag_length',
    'pids_limit', 'max_attempts', 'container_initial', 'container_minimum',
    'container_decay', 'value',
}
FLOAT_FIELDS = {'cpu_limit'}


def _coerce(field, value):
    """Coerce a submitted value to the type of its column."""
    if value is None or value == '':
        return None
    if field in INT_FIELDS:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            raise ValueError(f"'{field}' must be a number")
    if field in FLOAT_FIELDS:
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"'{field}' must be a number")
    return value


class ContainerChallengeType(BaseChallenge):
    """
    Container Challenge Type for CTFd

    Spawns Docker containers for players with:
    - Random or static flags
    - Auto-expiration
    - Anti-cheat detection
    - Resource limits
    """
    id = "container"
    name = "container"
    templates = {
        "create": "/plugins/containers/assets/create.html",
        "update": "/plugins/containers/assets/update.html",
        "view": "/plugins/containers/assets/view.html",
    }
    scripts = {
        "create": "/plugins/containers/assets/create.js",
        "update": "/plugins/containers/assets/update.js",
        "view": "/plugins/containers/assets/view.js",
    }
    route = "/plugins/containers/assets/"
    blueprint = None
    challenge_model = ContainerChallenge

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @classmethod
    def _apply_payload(cls, challenge, data, creating=False):
        """
        Apply a validated subset of the request payload to a challenge.

        Raises:
            ValueError: when a value cannot be coerced.
        """
        # Flag pattern is submitted as a single human friendly field; expand it
        # first so explicit flag_mode/prefix/suffix values win if both are sent.
        pattern = data.get('flag_pattern')
        if pattern is not None:
            parsed = parse_flag_pattern(pattern)
            for key, value in parsed.items():
                data.setdefault(key, value)

        for key, raw_value in data.items():
            if key in UI_ONLY_FIELDS:
                continue
            target = FIELD_ALIASES.get(key, key)
            if target not in EDITABLE_FIELDS:
                continue
            value = _coerce(target, raw_value)
            if value is None and not creating:
                # Empty input on update means "leave as is" (matches CTFd).
                continue
            setattr(challenge, target, value)

        # internal_port always mirrors the first entry of internal_ports
        ports = cls._normalise_ports(challenge.internal_ports) or []
        if ports:
            challenge.internal_port = ports[0]
            challenge.internal_ports = ','.join(str(p) for p in ports)
        elif challenge.internal_port:
            challenge.internal_ports = str(challenge.internal_port)

        if not challenge.flag_mode:
            challenge.flag_mode = 'static' if not challenge.random_flag_length else 'random'

        # Scoring mode has to be made explicit. The columns for dynamic scoring
        # carry defaults (initial 500, decay 20), and those defaults are applied
        # by the database on INSERT, so a challenge the admin created with
        # Standard scoring ends up with decay=20. calculate_value() then treats
        # it as dynamic and the value jumps to initial on the first solve.
        cls._apply_scoring_mode(challenge, data)

        # Dynamic challenges keep value == initial
        if challenge.container_decay and challenge.container_decay > 0 and challenge.container_initial:
            challenge.value = challenge.container_initial
        return challenge

    @classmethod
    def _apply_scoring_mode(cls, challenge, data):
        """
        Normalise the scoring fields.

        A standard challenge is stored with decay 0 so solve() never recalculates
        its value. A dynamic challenge must carry an initial value, a decay and a
        minimum.
        """
        scoring_type = str(data.get('scoring_type') or '').strip().lower()
        supplied_decay = data.get('decay', data.get('container_decay'))

        if scoring_type == 'dynamic':
            if not challenge.container_initial or not challenge.container_decay:
                raise ValueError("Dynamic scoring needs an initial value and a decay")
            if challenge.container_minimum is None:
                challenge.container_minimum = 0
            return challenge

        if scoring_type == 'standard':
            challenge.container_decay = 0
            return challenge

        # No explicit mode: treat a challenge with no decay as standard so the
        # column default cannot silently make it dynamic.
        if not supplied_decay and not challenge.container_decay:
            challenge.container_decay = 0
        return challenge

    @staticmethod
    def _sync_connection_info(challenge):
        """
        Keep the base Challenges.connection_info column in sync with the
        plugin's own container_connection_info.

        CTFd's challenge view wraps the `connection_info` block in
        `{% if challenge.connection_info %}` and the plugin's whole instance
        panel (Fetch instance / Extend / Terminate) lives inside that block, so
        the column must be truthy or the panel is never rendered at all.
        The plugin overrides the block body, so whatever is stored here is not
        shown to players - it only acts as the render switch.
        """
        text = (challenge.container_connection_info or '').strip()
        # Zero-width space: truthy for the template, invisible to players.
        challenge.connection_info = text or '\u200b'

    @staticmethod
    def _normalise_ports(raw):
        """Parse "80,22, 8080" into a clean list of ints."""
        ports = []
        for chunk in str(raw or '').split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                port = int(chunk)
            except ValueError:
                raise ValueError(f"Invalid port: {chunk}")
            if not 0 < port < 65536:
                raise ValueError(f"Port out of range: {port}")
            if port not in ports:
                ports.append(port)
        return ports

    @classmethod
    def create(cls, request):
        """Handle challenge creation from the admin UI / API."""
        data = dict(request.form or request.get_json() or {})

        challenge = cls.challenge_model()
        try:
            cls._apply_payload(challenge, data, creating=True)
        except ValueError as e:
            raise ChallengeCreateException(str(e))

        if not challenge.image:
            raise ChallengeCreateException("A Docker image is required")
        if not challenge.internal_port:
            challenge.internal_port = 80
            challenge.internal_ports = str(challenge.internal_port)
        if challenge.value is None:
            challenge.value = challenge.container_initial or 100

        cls._sync_connection_info(challenge)

        db.session.add(challenge)
        db.session.flush()

        cls._ensure_placeholder_flag(challenge)
        db.session.commit()

        return challenge

    @classmethod
    def read(cls, challenge):
        """Serialize a challenge for the frontend."""
        return {
            "id": challenge.id,
            "name": challenge.name,
            "value": challenge.value,
            "description": challenge.description,
            "attribution": challenge.attribution,
            "category": challenge.category,
            "state": challenge.state,
            "max_attempts": challenge.max_attempts,
            "type": challenge.type,
            # Static text shown above the flag box. Deliberately NOT the
            # per-instance data (that lives in ContainerInstance).
            "connection_info": challenge.container_connection_info,
            "type_data": {
                "id": cls.id,
                "name": cls.name,
                "templates": cls.templates,
                "scripts": cls.scripts,
            },
            "image": challenge.image,
            "internal_port": challenge.internal_port,
            "internal_ports": challenge.internal_ports,
            "connection_type": challenge.container_connection_type,
            "connection_type_info": challenge.container_connection_info,
            "timeout_minutes": challenge.get_timeout_minutes(),
            "max_renewals": challenge.get_max_renewals(),
            "flag_mode": challenge.flag_mode,
            "initial": challenge.container_initial,
            "minimum": challenge.container_minimum,
            "decay": challenge.container_decay,
            "decay_function": challenge.decay_function,
        }

    @classmethod
    def update(cls, challenge, request):
        """Handle challenge updates."""
        data = dict(request.form or request.get_json() or {})
        try:
            cls._apply_payload(challenge, data, creating=False)
        except ValueError as e:
            raise ChallengeUpdateException(str(e))

        if not challenge.internal_port:
            challenge.internal_port = 80

        cls._sync_connection_info(challenge)
        cls._ensure_placeholder_flag(challenge)
        db.session.commit()
        return challenge

    @classmethod
    def delete(cls, challenge):
        """
        Stop the containers belonging to a challenge before deleting it.

        Without this the containers kept running after the challenge was gone,
        with no row left to manage them from the dashboard.
        """
        container_service = globals().get('container_service')
        instances = ContainerInstance.query.filter(
            ContainerInstance.challenge_id == challenge.id,
            ContainerInstance.status.in_(['pending', 'provisioning', 'running', 'stopping']),
        ).all()

        stopped = 0
        for instance in instances:
            if not container_service:
                logger.warning(
                    "Container service unavailable; instance %s left behind", instance.uuid
                )
                continue
            try:
                if container_service.stop_instance(instance, user_id=None, reason='challenge_deleted'):
                    stopped += 1
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to stop instance {instance.uuid} on challenge delete: {e}")

        if instances:
            # Persist the status changes and audit rows *before* the challenge
            # (and its instances, via ON DELETE CASCADE) disappear.
            db.session.commit()
            logger.info(
                "Challenge %s deleted: stopped %s/%s container(s)",
                challenge.id, stopped, len(instances),
            )

        super().delete(challenge)

    @staticmethod
    def _ensure_placeholder_flag(challenge):
        """
        Keep a placeholder flag row on the challenge.

        CTFd's challenge list renders a "Missing Flags" warning otherwise, but
        this placeholder is never used for validation (attempt() is overridden).
        """
        if Flags.query.filter_by(challenge_id=challenge.id).count() == 0:
            db.session.add(Flags(
                challenge_id=challenge.id,
                type='static',
                content=DUMMY_FLAG_CONTENT,
                data='',
            ))

    # ------------------------------------------------------------------
    # Solving
    # ------------------------------------------------------------------
    @classmethod
    def solve(cls, user, team, challenge, request):
        """Called by CTFd when a solve is created."""
        super().solve(user, team, challenge, request)

        if challenge.container_decay and challenge.container_decay > 0:
            cls.calculate_value(challenge)

    @classmethod
    def attempt(cls, challenge, request):
        """
        Validate a submitted flag.

        Returns:
            (is_correct: bool, message: str)
        """
        user = get_current_user()
        if not user:
            return False, "You must be logged in"

        mode = get_config('user_mode')
        is_team_mode = (mode == 'teams')

        if is_team_mode:
            if not user.team_id:
                return False, "You must be on a team"
            account_id = user.team_id
        else:
            account_id = user.id

        data = request.form or request.get_json() or {}
        submitted_flag = str(data.get("submission", "")).strip()

        if not submitted_flag:
            return False, "No flag provided"

        anticheat_service = globals().get('anticheat_service')
        if anticheat_service is None:
            logger.error("Anti-cheat service unavailable, rejecting submission")
            return False, "Flag validation is temporarily unavailable"

        is_correct, message, is_cheating = anticheat_service.validate_flag(
            challenge_id=challenge.id,
            account_id=account_id,
            user_id=user.id,
            submitted_flag=submitted_flag,
        )

        if is_correct:
            instance = ContainerInstance.query.filter_by(
                challenge_id=challenge.id,
                account_id=account_id,
            ).filter(
                ContainerInstance.status.in_(['running', 'provisioning', 'pending'])
            ).first()

            container_service = globals().get('container_service')
            if instance and container_service:
                try:
                    container_service.stop_instance(instance, user.id, reason='solved')
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Failed to stop instance {instance.uuid} after solve: {e}")

        return is_correct, message

    @classmethod
    def calculate_value(cls, challenge):
        """
        Calculate dynamic challenge value based on solves.

        Only applies to dynamic challenges (where container_decay > 0).
        """
        if not challenge.container_decay or challenge.container_decay == 0:
            return challenge
        if not challenge.container_initial or not challenge.container_minimum:
            return challenge

        Model = get_model()

        solve_count = (
            Solves.query.join(Model, Solves.account_id == Model.id)
            .filter(
                Solves.challenge_id == challenge.id,
                Model.hidden == False,  # noqa: E712
                Model.banned == False,  # noqa: E712
            )
            .count()
        )

        # Subtract 1 so the first solver gets max points
        if solve_count != 0:
            solve_count -= 1

        decay_func = getattr(challenge, 'decay_function', 'logarithmic')

        if decay_func == 'linear':
            value = challenge.container_initial - (challenge.container_decay * solve_count)
        else:
            decay = challenge.container_decay if challenge.container_decay > 0 else 1
            value = (
                ((challenge.container_minimum - challenge.container_initial) / (decay ** 2))
                * (solve_count ** 2)
            ) + challenge.container_initial

        value = math.ceil(value)
        if value < challenge.container_minimum:
            value = challenge.container_minimum

        challenge.value = value
        db.session.commit()
        return challenge


# ----------------------------------------------------------------------
# Global service instances (populated by load())
# ----------------------------------------------------------------------
docker_service = None
flag_service = None
container_service = None
anticheat_service = None
port_manager = None
redis_expiration_service = None
notification_service = None


def get_services():
    """Return the live service objects (used by routes/admin helpers)."""
    return {
        'docker': docker_service,
        'flag': flag_service,
        'container': container_service,
        'anticheat': anticheat_service,
        'ports': port_manager,
        'redis': redis_expiration_service,
        'notifications': notification_service,
    }


# ----------------------------------------------------------------------
# Plugin entry point
# ----------------------------------------------------------------------
def load(app: Flask):
    """Plugin entry point."""
    global docker_service, flag_service, container_service, anticheat_service
    global port_manager, redis_expiration_service, notification_service

    logger.info("Loading Container Challenge Plugin")

    app.db.create_all()
    _initialize_default_config()

    docker_socket = ContainerConfig.get('docker_socket', 'unix://var/run/docker.sock')

    # Docker service - never fatal: the plugin must load so an admin can fix
    # the configuration from the UI.
    try:
        docker_service = DockerService(base_url=docker_socket)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Docker service initialization failed: {e}")
        docker_service = None

    if docker_service and docker_service.is_connected():
        logger.info(f"Docker service connected: {docker_socket}")
    else:
        logger.warning(
            "Docker is not reachable (%s). Configure it in Admin -> Containers -> Settings",
            docker_socket,
        )

    flag_service = FlagService()
    notification_service = NotificationService()

    port_manager = PortManager(
        int(ContainerConfig.get('port_range_start', 30000) or 30000),
        int(ContainerConfig.get('port_range_end', 31000) or 31000),
    )

    container_service = ContainerService(
        docker_service, flag_service, port_manager, notification_service
    )
    anticheat_service = AntiCheatService(flag_service, notification_service)

    redis_expiration_service = RedisExpirationService(
        app=app,
        container_service_getter=lambda: container_service,
    )
    redis_expiration_service.start_listener()

    # Register challenge type
    CHALLENGE_CLASSES["container"] = ContainerChallengeType

    # Register plugin assets + templates
    register_plugin_assets_directory(app, base_path="/plugins/containers/assets/")
    _register_template_folder(app)
    _register_template_globals(app)

    # Inject services into routes
    set_user_services(container_service, flag_service, anticheat_service)
    set_admin_services(docker_service, container_service, anticheat_service)

    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)

    _setup_background_jobs(app)

    logger.info("Container Challenge Plugin loaded successfully")


def _register_template_folder(app):
    """Make the plugin's templates importable by bare name."""
    from jinja2 import ChoiceLoader, FileSystemLoader

    template_folder = os.path.join(os.path.dirname(__file__), 'templates')
    loader = FileSystemLoader(template_folder)

    if isinstance(app.jinja_loader, ChoiceLoader):
        loaders = list(app.jinja_loader.loaders)
        loaders.insert(0, loader)
        app.jinja_loader = ChoiceLoader(loaders)
    else:
        app.jinja_loader = ChoiceLoader([loader, app.jinja_loader])

    logger.debug("Registered plugin template folder: %s", template_folder)


#: Values the plugin's templates need but CTFd does not pass into the context.
#: CTFd renders the challenge view itself (api/v1/challenges.py), so a context
#: processor is the only place to inject them.
def _register_template_globals(app):
    @app.context_processor
    def inject_container_settings():
        try:
            renew_minutes = int(ContainerConfig.get('renew_extension_minutes', 5) or 5)
        except (TypeError, ValueError):
            renew_minutes = 5
        return {'renew_minutes': renew_minutes}


def _initialize_default_config():
    """Initialize default configuration if not exists."""
    defaults = {
        'docker_type': 'local',
        'docker_socket': 'unix://var/run/docker.sock',
        'connection_host': 'localhost',
        # Optional: publish challenge ports on one interface only instead of
        # 0.0.0.0 (recommended when the challenge host is reachable directly).
        'port_bind_ip': '',
        'port_range_start': '30000',
        'port_range_end': '31000',
        'default_timeout': '60',
        'max_renewals': '3',
        'renew_extension_minutes': '5',
        'max_memory': '512m',
        'max_cpu': '0.5',
        'container_max_concurrent_count': '3',
        'subdomain_enabled': 'false',
        'subdomain_base_domain': '',
        'subdomain_network': 'ctfd-challenges',
        'subdomain_entrypoint': 'web',
        'subdomain_tls': 'false',
        'isolated_network': 'ctfd-isolated',
        'container_discord_webhook_url': '',
        # 0 = never auto-ban on flag reuse (see AntiCheatService)
        'anticheat_autoban_threshold': '0',
        'anticheat_log_all_attempts': 'true',
        'audit_retention_days': '7',
        'background_jobs_enabled': 'true',
    }

    for key, value in defaults.items():
        if ContainerConfig.get(key) is None:
            ContainerConfig.set(key, value)
            logger.debug(f"Set default config: {key}={value}")


def _setup_background_jobs(app):
    """
    Setup background jobs for cleanup.

    In a multi-worker deployment each worker runs its own scheduler; both jobs
    are written to be idempotent and to skip work that another worker already
    did, so the duplicate schedule is harmless.
    """
    if str(ContainerConfig.get('background_jobs_enabled', 'true')).lower() == 'false':
        logger.warning("Background jobs disabled by configuration")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler not installed, background jobs disabled")
        return

    try:
        scheduler = BackgroundScheduler(
            job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 60}
        )

        scheduler.add_job(
            func=lambda: _run_with_app_context(
                app, lambda: container_service and container_service.cleanup_expired_instances()
            ),
            trigger="interval",
            seconds=30,
            id='cleanup_expired',
            replace_existing=True,
        )
        scheduler.add_job(
            func=lambda: _run_with_app_context(
                app, lambda: container_service and container_service.cleanup_old_instances()
            ),
            trigger="interval",
            hours=1,
            id='cleanup_old',
            replace_existing=True,
        )
        scheduler.add_job(
            func=lambda: _run_with_app_context(
                app, lambda: anticheat_service and anticheat_service.prune_attempts()
            ),
            trigger="interval",
            hours=6,
            id='prune_attempts',
            replace_existing=True,
        )

        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))
        logger.info("Background jobs started (expiry sweep every 30s)")

    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to setup background jobs: {e}")


def _run_with_app_context(app, func):
    """Run a job inside an application context, never raising."""
    with app.app_context():
        try:
            func()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error in background job: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass

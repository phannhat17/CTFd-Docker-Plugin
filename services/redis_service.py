"""
Redis Service - accurate container expiration using Redis TTL keyspace events.

When Redis is available we set ``container:expire:<uuid>`` with a TTL. The
expiry event kills the container at the exact second. The APScheduler sweep in
``__init__.py`` remains as a backstop, so a deployment without Redis (or with
keyspace notifications disabled) still expires containers, just less precisely.
"""
import json
import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

KEY_PREFIX = 'container:expire:'
DEFAULT_REDIS_DB = 0

#: Reconnect backoff for the keyspace-notification listener.
LISTENER_BACKOFF_SECONDS = 15


class RedisExpirationService:
    """
    Service to handle container expiration using Redis keyspace notifications
    """

    def __init__(self, app, container_service_getter):
        """
        Args:
            app: Flask application instance
            container_service_getter: Callable returning the ContainerService
        """
        self.app = app
        self.container_service_getter = container_service_getter
        self._listener_thread = None
        self._running = False
        self.redis = None
        self.db_index = DEFAULT_REDIS_DB
        self._resolve_client()

    # ------------------------------------------------------------------
    # Client discovery
    # ------------------------------------------------------------------
    def _resolve_client(self):
        """
        Find a usable Redis client.

        CTFd only gives us a flask-caching backend, and that backend is a
        plain filesystem/null cache when REDIS_URL is not configured. Resolve
        it once and refuse to pretend we have Redis when we do not.
        """
        self.redis = None
        try:
            from CTFd.cache import cache

            backend = getattr(cache, 'cache', None)
            if backend is None:
                logger.info("No CTFd cache backend available, Redis expiration disabled")
                return

            client = (
                getattr(backend, '_write_client', None)
                or getattr(backend, '_client', None)
            )
            if client is None or not hasattr(client, 'setex'):
                logger.info(
                    "CTFd cache backend is %s (not Redis): exact expiration disabled, "
                    "the scheduler sweep will expire containers instead",
                    type(backend).__name__,
                )
                return

            self.redis = client
            self.db_index = self._detect_db_index()
            logger.info("Redis expiration service ready (db=%s)", self.db_index)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to resolve Redis client: {e}")

    def _detect_db_index(self) -> int:
        """Best-effort detection of the Redis database index in use."""
        try:
            from CTFd.config import CACHE_REDIS_URL
            if CACHE_REDIS_URL and CACHE_REDIS_URL.rstrip('/').count('/') >= 3:
                tail = CACHE_REDIS_URL.rstrip('/').rsplit('/', 1)[-1]
                return int(tail)
        except Exception:  # noqa: BLE001
            pass
        try:
            connection = getattr(self.redis, 'connection_pool', None)
            if connection is not None and getattr(connection, 'connection_kwargs', None):
                return int(connection.connection_kwargs.get('db', DEFAULT_REDIS_DB))
        except Exception:  # noqa: BLE001
            pass
        return DEFAULT_REDIS_DB

    @property
    def available(self) -> bool:
        return self.redis is not None

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    def schedule_expiration(self, instance_uuid: str, expires_in_seconds: int):
        """Schedule a container to be killed when it expires."""
        if not self.available:
            return False
        try:
            self.redis.setex(
                f"{KEY_PREFIX}{instance_uuid}",
                max(1, int(expires_in_seconds)),
                json.dumps({
                    'instance_uuid': instance_uuid,
                    'scheduled_at': datetime.utcnow().isoformat(),
                })
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to schedule expiration for {instance_uuid}: {e}")
            return False

    def cancel_expiration(self, instance_uuid: str):
        """Cancel a scheduled expiration."""
        if not self.available:
            return False
        try:
            self.redis.delete(f"{KEY_PREFIX}{instance_uuid}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to cancel expiration for {instance_uuid}: {e}")
            return False

    def extend_expiration(self, instance_uuid: str, additional_seconds: int):
        """
        Extend a scheduled expiration.

        If the key is gone (expired or never created) re-create it with the
        requested TTL instead of silently doing nothing.
        """
        if not self.available:
            return False
        key = f"{KEY_PREFIX}{instance_uuid}"
        try:
            current_ttl = self.redis.ttl(key)
            if current_ttl and current_ttl > 0:
                self.redis.expire(key, current_ttl + int(additional_seconds))
            else:
                self.schedule_expiration(instance_uuid, additional_seconds)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to extend expiration for {instance_uuid}: {e}")
            return False

    # ------------------------------------------------------------------
    # Listener
    # ------------------------------------------------------------------
    def start_listener(self):
        """Start the keyspace-notification listener thread."""
        if not self.available:
            logger.info(
                "Redis unavailable: container expiry relies on the scheduler sweep"
            )
            return False
        if self._running:
            return True

        if not self._ensure_keyspace_notifications():
            logger.warning(
                "Redis keyspace notifications unavailable; the scheduler sweep "
                "will expire containers instead"
            )
            return False

        self._running = True
        self._listener_thread = threading.Thread(
            target=self._listen_forever,
            daemon=True,
            name='RedisExpirationListener',
        )
        self._listener_thread.start()
        logger.info("Redis expiration listener started")
        return True

    def _ensure_keyspace_notifications(self) -> bool:
        """
        Make sure the server emits expired-key events.

        Only enable them when the deployment can: CONFIG SET is disabled on
        most managed Redis services, and the README already tells operators to
        start redis with ``--notify-keyspace-events Ex``.
        """
        try:
            current = self.redis.config_get('notify-keyspace-events')
            flags = (current or {}).get('notify-keyspace-events', '') or ''
            if 'E' in flags and 'x' in flags:
                return True
        except Exception:  # noqa: BLE001
            pass

        try:
            self.redis.config_set('notify-keyspace-events', 'Ex')
            logger.info("Enabled Redis keyspace notifications (Ex)")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not enable Redis keyspace notifications: {e}")
            return False

    def stop_listener(self):
        """Stop the listener thread."""
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
            self._listener_thread = None
            logger.info("Stopped Redis expiration listener")

    def _listen_forever(self):
        """Reconnecting subscribe loop."""
        channel = f"__keyevent@{self.db_index}__:expired"
        while self._running:
            try:
                pubsub = self.redis.pubsub()
                pubsub.psubscribe(channel)
                logger.info(f"Listening for Redis key expirations on {channel}")

                for message in pubsub.listen():
                    if not self._running:
                        break
                    if message.get('type') != 'pmessage':
                        continue
                    raw = message.get('data')
                    expired_key = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
                    if expired_key.startswith(KEY_PREFIX):
                        instance_uuid = expired_key[len(KEY_PREFIX):]
                        logger.info(f"Container {instance_uuid} expired, stopping it")
                        self._handle_expiration(instance_uuid)
            except Exception as e:  # noqa: BLE001
                if not self._running:
                    break
                logger.error(f"Redis listener error, retrying in {LISTENER_BACKOFF_SECONDS}s: {e}")
                time.sleep(LISTENER_BACKOFF_SECONDS)

    def _handle_expiration(self, instance_uuid: str):
        """Stop the container behind an expired Redis key."""
        with self.app.app_context():
            try:
                container_service = self.container_service_getter()
                if not container_service:
                    logger.error("Container service not available")
                    return

                from ..models.instance import ContainerInstance

                instance = ContainerInstance.query.filter_by(uuid=instance_uuid).first()
                if not instance:
                    logger.info(f"Instance {instance_uuid} not found in database")
                    return

                if instance.status not in ('running', 'provisioning', 'pending'):
                    logger.info(f"Instance {instance_uuid} already stopped ({instance.status})")
                    return

                container_service.stop_instance(instance, user_id=None, reason='expired')
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error handling expiration for {instance_uuid}: {e}", exc_info=True)
                try:
                    from CTFd.models import db
                    db.session.rollback()
                except Exception:  # noqa: BLE001
                    pass

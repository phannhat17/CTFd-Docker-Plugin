"""
Port Manager - Manage the host port pool used for container challenges.

Allocation has to be safe across gunicorn workers, so it is backed by an
atomic Redis lock (``port_lock:<port>``) and cross-checked against the
database rows of live instances.
"""
import logging
import random
import socket

from ..models.config import ContainerConfig

logger = logging.getLogger(__name__)

#: How long a port stays reserved while a container is being provisioned.
#: Long enough to cover a slow ``docker run``, short enough that a crashed
#: worker does not leak the port forever.
PORT_LOCK_TTL = 120


class PortManager:
    """
    Manage the port pool described by the ``port_range_start`` /
    ``port_range_end`` plugin config values.
    """

    def __init__(self, port_range_start=30000, port_range_end=31000):
        self._default_start = port_range_start
        self._default_end = port_range_end

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _get_port_range(self):
        """Get current port range from config (re-read on every call)."""
        config_start = ContainerConfig.get('port_range_start')
        config_end = ContainerConfig.get('port_range_end')

        try:
            start = int(config_start) if config_start else self._default_start
            end = int(config_end) if config_end else self._default_end
        except (TypeError, ValueError):
            logger.warning("Invalid port range config, falling back to defaults")
            start, end = self._default_start, self._default_end

        if start > end:
            start, end = end, start
        return start, end

    @property
    def port_range_start(self):
        start, _ = self._get_port_range()
        return start

    @property
    def port_range_end(self):
        _, end = self._get_port_range()
        return end

    def get_available_count(self) -> int:
        """Get number of available ports"""
        start, end = self._get_port_range()
        used_ports = self._get_used_ports()
        return max(0, (end - start + 1) - len(used_ports))

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------
    def _get_used_ports(self) -> set:
        """Ports referenced by instances that may still hold a mapping."""
        from ..models.instance import ContainerInstance

        instances = ContainerInstance.query.filter(
            ContainerInstance.status.in_(['running', 'provisioning', 'stopping'])
        ).all()

        used_ports = set()
        for instance in instances:
            if instance.connection_port:
                used_ports.add(int(instance.connection_port))
            if instance.connection_ports:
                try:
                    for _internal, ext_port in instance.connection_ports.items():
                        used_ports.add(int(ext_port))
                except (TypeError, ValueError, AttributeError):
                    continue
        return used_ports

    # ------------------------------------------------------------------
    # Redis locking
    # ------------------------------------------------------------------
    def get_redis_client(self):
        """Get the raw Redis client backing CTFd's cache, or None."""
        try:
            from CTFd.cache import cache

            client = getattr(cache, 'cache', None)
            if client is None:
                return None
            raw = getattr(client, '_write_client', None) or getattr(client, '_client', None)
            if raw is None or not hasattr(raw, 'set'):
                return None
            return raw
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to get Redis client: {e}")
            return None

    def lock_port(self, port: int, ttl: int = PORT_LOCK_TTL) -> bool:
        """
        Try to reserve a port atomically.

        Returns True when the caller now owns ``port``.
        """
        redis = self.get_redis_client()
        if redis is None:
            # No Redis: fall back to the DB-only view. Allocation is still
            # protected by the per-account unique instance and by
            # create_instance() retrying on Docker bind conflicts.
            return True

        key = f"port_lock:{port}"
        try:
            return bool(redis.set(key, "locked", ex=ttl, nx=True))
        except Exception as e:  # noqa: BLE001
            logger.error(f"Redis error locking port {port}: {e}")
            return True

    def is_locked(self, port: int) -> bool:
        """Return True when the port is currently reserved in Redis."""
        redis = self.get_redis_client()
        if redis is None:
            return False
        try:
            return bool(redis.exists(f"port_lock:{port}"))
        except Exception:  # noqa: BLE001
            return False

    def release_port(self, port: int):
        """Release a previously reserved port."""
        if not port:
            return
        redis = self.get_redis_client()
        if redis is None:
            return
        try:
            redis.delete(f"port_lock:{port}")
            logger.debug(f"Released port {port}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to release port {port}: {e}")

    def release_ports(self, ports):
        """Release several ports at once."""
        for port in set(p for p in (ports or []) if p):
            self.release_port(port)

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------
    def _candidates(self, start, end, used_ports):
        """Ports that look free, in randomized order to spread usage."""
        candidates = [p for p in range(start, end + 1) if p not in used_ports]
        random.shuffle(candidates)
        return candidates

    def allocate_ports(self, count: int) -> list:
        """
        Allocate ``count`` distinct ports.

        Raises:
            Exception: when the pool cannot satisfy the request.
        """
        if count <= 0:
            return []

        start, end = self._get_port_range()
        used_ports = self._get_used_ports()
        allocated = []

        for port in self._candidates(start, end, used_ports):
            if not self.lock_port(port):
                continue
            if not self._probe_available(port):
                # Something on the CTFd host already listens there.
                self.release_port(port)
                continue
            allocated.append(port)
            if len(allocated) == count:
                logger.info(f"Allocated ports {allocated}")
                return allocated

        # Roll back partial allocations so a failure does not leak locks.
        self.release_ports(allocated)

        raise Exception(
            f"Not enough available ports in range {start}-{end} "
            f"(requested {count})"
        )

    def allocate_port(self) -> int:
        """Allocate a single port."""
        return self.allocate_ports(1)[0]

    @staticmethod
    def _probe_available(port: int) -> bool:
        """
        Cheap check that the CTFd host itself is not already bound to ``port``.

        Ports published by the Docker daemon live in a different namespace, so
        this is only an extra guard; the authoritative check is the Docker
        "port is already allocated" error handled by ContainerService.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('127.0.0.1', port))
                return True
            except OSError:
                return False

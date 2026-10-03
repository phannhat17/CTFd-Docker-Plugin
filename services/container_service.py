"""
Container Service - Business logic for container lifecycle
"""
import logging
import random
import re
import time
import uuid as uuid_module
from datetime import datetime, timedelta

from flask import has_request_context, request

from CTFd.models import db, Solves
from ..models.instance import ContainerInstance
from ..models.challenge import ContainerChallenge
from ..models.config import ContainerConfig
from ..models.audit import ContainerAuditLog
from .docker_service import DockerService
from .flag_service import FlagService
from .port_manager import PortManager

logger = logging.getLogger(__name__)

#: Hard cap on how many expired instances a single cleanup pass will handle.
CLEANUP_BATCH_SIZE = 100

#: How long stopped/errored/solved records are kept for the audit trail.
DEFAULT_AUDIT_RETENTION_DAYS = 7


class ContainerService:
    """
    Service to manage container lifecycle
    """

    def __init__(self, docker_service: DockerService, flag_service: FlagService,
                 port_manager: PortManager, notification_service=None):
        self.docker = docker_service
        self.flag_service = flag_service
        self.port_manager = port_manager
        self.notification_service = notification_service
        self._cleanup_running = False  # Prevent overlapping cleanup jobs

    # ==================================================================
    # Instance creation
    # ==================================================================
    def get_active_instance(self, challenge_id: int, account_id: int):
        """Return the instance that is currently occupying the slot, if any."""
        return ContainerInstance.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id,
        ).filter(
            ContainerInstance.status.in_(['pending', 'provisioning', 'running'])
        ).order_by(ContainerInstance.created_at.desc()).first()

    def _generate_unique_flag(self, challenge, account_id):
        """Generate a flag that is not already stored, retrying on collision."""
        from ..models.flag import ContainerFlag

        for _ in range(5):
            flag = self.flag_service.generate_flag(challenge, account_id=account_id)
            flag_hash = self.flag_service.hash_flag(flag)
            if ContainerFlag.query.filter_by(flag_hash=flag_hash).first() is None:
                return flag
        # Extremely unlikely; fall back to a much longer random part.
        logger.warning("Repeated flag collisions, extending entropy")
        extra = uuid_module.uuid4().hex
        return f"{flag}{extra}"

    def create_instance(self, challenge_id: int, account_id: int, user_id: int) -> ContainerInstance:
        """
        Create new container instance

        Args:
            challenge_id: Challenge ID
            account_id: Team ID (team mode) or User ID (user mode)
            user_id: Actual user ID creating container

        Returns:
            ContainerInstance object

        Raises:
            Exception if error occurs
        """
        challenge = ContainerChallenge.query.get(challenge_id)
        if not challenge:
            raise Exception("Challenge not found")

        # Already solved? No new instance.
        already_solved = Solves.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id
        ).first()
        if already_solved:
            raise Exception("Challenge already solved - cannot create new instance")

        # Already running (or being provisioned)?
        existing = self.get_active_instance(challenge_id, account_id)
        if existing:
            if not existing.is_expired() or existing.status in ('pending', 'provisioning'):
                logger.info(
                    "Account %s already has instance %s for challenge %s",
                    account_id, existing.uuid, challenge_id,
                )
                return existing
            logger.info(f"Replacing expired instance {existing.uuid}")
            self.stop_instance(existing, user_id, reason='expired')

        expires_at = datetime.utcnow() + timedelta(minutes=challenge.get_timeout_minutes())
        flag_plaintext = self._generate_unique_flag(challenge, account_id)
        flag_encrypted = self.flag_service.encrypt_flag(flag_plaintext)
        flag_hash = self.flag_service.hash_flag(flag_plaintext)

        instance = ContainerInstance(
            challenge_id=challenge_id,
            account_id=account_id,
            flag_encrypted=flag_encrypted,
            flag_hash=flag_hash,
            status='pending',
            expires_at=expires_at
        )

        db.session.add(instance)
        db.session.flush()  # Get instance ID

        if challenge.flag_mode == 'random':
            self.flag_service.create_flag_record(instance, challenge, account_id, flag_plaintext)

        self._create_audit_log(
            'instance_created',
            instance_id=instance.id,
            challenge_id=challenge_id,
            account_id=account_id,
            user_id=user_id,
            details={'expires_at': expires_at.isoformat()}
        )

        db.session.commit()

        try:
            self._provision_container(instance, challenge, flag_plaintext)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to provision container: {e}")
            self._mark_error(instance, str(e))
            raise

        return instance

    # ==================================================================
    # Provisioning
    # ==================================================================
    def _plan_ports(self, challenge) -> dict:
        """
        Decide which host ports to publish.

        Subdomain/Traefik routing reaches containers over the shared Docker
        network, so no host port is published at all in that mode (this used
        to burn a port per instance for nothing).
        """
        internal_ports = self._internal_ports(challenge)
        if challenge.uses_subdomain_routing():
            return {}
        allocated = self.port_manager.allocate_ports(len(internal_ports))
        return {str(internal): int(external) for internal, external in zip(internal_ports, allocated)}

    @staticmethod
    def _internal_ports(challenge):
        """Parsed, de-duplicated list of internal ports for a challenge."""
        ports = []
        if challenge.internal_ports:
            for raw in str(challenge.internal_ports).split(','):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    port = int(raw)
                except ValueError:
                    continue
                if 0 < port < 65536 and port not in ports:
                    ports.append(port)
        if not ports:
            primary = int(challenge.internal_port or 0)
            ports = [primary if primary else 80]
        return ports

    def _release_instance_ports(self, instance):
        """Release every host port an instance may hold (idempotent)."""
        ports = set()
        if instance.connection_port:
            ports.add(int(instance.connection_port))
        if instance.connection_ports:
            try:
                for _internal, external in instance.connection_ports.items():
                    ports.add(int(external))
            except (TypeError, ValueError, AttributeError):
                pass
        if ports:
            self.port_manager.release_ports(ports)
        instance.connection_port = None
        instance.connection_ports = None

    def _provision_container(self, instance: ContainerInstance, challenge: ContainerChallenge, flag: str):
        """
        Provision the Docker container for an instance.

        Raises:
            Exception: when every attempt failed (instance is marked 'error').
        """
        instance.status = 'provisioning'
        db.session.commit()

        subdomain_enabled = challenge.uses_subdomain_routing()
        subdomain_base_domain = ContainerConfig.get('subdomain_base_domain', '')
        subdomain_network = ContainerConfig.get('subdomain_network', 'ctfd-challenges')
        connection_host = ContainerConfig.get('connection_host', 'localhost')

        # Networks: strict isolation for host:port challenges, shared network
        # for subdomain routing (Traefik has to reach the containers).
        if subdomain_enabled:
            target_network = subdomain_network
            self.docker.create_network(name=subdomain_network, internal=False)
        else:
            target_network = ContainerConfig.get('isolated_network', 'ctfd-isolated')
            self.docker.create_network(
                name=target_network,
                internal=False,  # must allow outbound internet for most challenges
                driver='bridge',
                options={'com.docker.network.bridge.enable_icc': 'false'}
            )

        # Make sure the image exists before we start burning retries on it.
        self.docker.pull_image(challenge.image)

        container_name = self._container_name(challenge, instance.account_id)
        command = challenge.command or None
        if command and '{FLAG}' in command:
            command = command.replace('{FLAG}', flag)

        labels = {
            'ctfd.instance_uuid': instance.uuid,
            'ctfd.challenge_id': str(challenge.id),
            'ctfd.account_id': str(instance.account_id),
            'ctfd.expires_at': str(int(instance.expires_at.timestamp()) if instance.expires_at else 0),
        }

        internal_ports = self._internal_ports(challenge)
        primary_internal = internal_ports[0]

        subdomain = None
        if subdomain_enabled:
            # Random single-level subdomain (Cloudflare free SSL compatible)
            subdomain = f"c-{uuid_module.uuid4().hex[:16]}"
            labels.update({
                'traefik.enable': 'true',
                'traefik.docker.network': subdomain_network,
            })
            for port in internal_ports:
                router_name = f"ctfd-{instance.uuid[:8]}-{port}"
                service_name = f"{router_name}-service"
                host_for_port = (
                    f"{subdomain}.{subdomain_base_domain}"
                    if port == primary_internal
                    else f"{subdomain}-{port}.{subdomain_base_domain}"
                )
                labels.update({
                    f'traefik.http.routers.{router_name}.rule': f'Host(`{host_for_port}`)',
                    f'traefik.http.routers.{router_name}.entrypoints':
                        ContainerConfig.get('subdomain_entrypoint', 'web'),
                    f'traefik.http.routers.{router_name}.service': service_name,
                    f'traefik.http.services.{service_name}.loadbalancer.server.port': str(port),
                })
                if ContainerConfig.get('subdomain_tls', 'false').lower() == 'true':
                    labels[f'traefik.http.routers.{router_name}.tls'] = 'true'

        max_retries = 5
        last_error = None

        for attempt in range(max_retries):
            ports_map = None
            try:
                ports_map = self._plan_ports(challenge)

                result = self.docker.create_container(
                    image=challenge.image,
                    internal_port=primary_internal,
                    host_port=ports_map.get(str(primary_internal)) if ports_map else None,
                    ports=ports_map or None,
                    command=command,
                    environment={'FLAG': flag},
                    memory_limit=challenge.get_memory_limit(),
                    cpu_limit=challenge.get_cpu_limit(),
                    pids_limit=challenge.pids_limit,
                    name=container_name,
                    labels=labels,
                    network=target_network,
                    use_traefik=subdomain_enabled,
                )

                instance.container_id = result['container_id']
                instance.connection_port = ports_map.get(str(primary_internal)) if ports_map else None
                instance.connection_ports = ports_map or None

                if subdomain_enabled:
                    scheme = 'https' if ContainerConfig.get('subdomain_tls', 'false').lower() == 'true' else 'http'
                    urls = []
                    for port in internal_ports:
                        host_for_port = (
                            f"{subdomain}.{subdomain_base_domain}"
                            if port == primary_internal
                            else f"{subdomain}-{port}.{subdomain_base_domain}"
                        )
                        urls.append({
                            'port': port,
                            'url': f"{scheme}://{host_for_port}",
                        })
                    instance.connection_host = f"{subdomain}.{subdomain_base_domain}"
                    instance.connection_info = {
                        'type': 'url_list',
                        'urls': urls,
                        'subdomain': subdomain,
                        'info': challenge.container_connection_info,
                    }
                else:
                    instance.connection_host = connection_host
                    instance.connection_info = {
                        'type': challenge.container_connection_type,
                        'info': challenge.container_connection_info,
                    }

                instance.status = 'running'
                instance.started_at = datetime.utcnow()
                instance.extra_data = None
                db.session.commit()

                self._schedule_redis_expiration(instance)

                self._create_audit_log(
                    'instance_started',
                    instance_id=instance.id,
                    challenge_id=challenge.id,
                    account_id=instance.account_id,
                    details={
                        'container_id': result['container_id'],
                        'ports': ports_map,
                        'subdomain': subdomain,
                    }
                )
                db.session.commit()

                logger.info(
                    "Provisioned container %s for instance %s",
                    result['container_id'][:12], instance.uuid,
                )
                return

            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.warning(f"Provisioning attempt {attempt + 1}/{max_retries} failed: {e}")

                # A failed docker run can still leave a named container behind.
                self._remove_named_container(container_name, instance.container_id)
                instance.container_id = None

                # Give the ports back and let the next attempt pick new ones:
                # the usual failure here is "port is already allocated".
                self._release_instance_ports(instance)

                if attempt < max_retries - 1:
                    time.sleep(0.2 + random.random() * 0.3)

        logger.error(f"Error provisioning container after {max_retries} attempts: {last_error}")
        if self.notification_service:
            self.notification_service.notify_error("Container Provisioning", str(last_error))
        self._mark_error(instance, str(last_error))
        raise Exception(f"Failed to provision container: {last_error}")

    def _remove_named_container(self, name: str, container_id: str = None):
        """Best-effort removal of a half-created container."""
        try:
            if container_id:
                self.docker.stop_container(container_id)
                return
            if not name:
                return
            for container in self.docker.list_managed_containers():
                if container.name == name:
                    self.docker.stop_container(container.id)
                    return
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Cleanup of {name} failed: {e}")

    @staticmethod
    def _container_name(challenge, account_id) -> str:
        safe_name = re.sub(r'[^a-zA-Z0-9-]', '', str(challenge.name).replace(' ', '-').lower())
        safe_name = safe_name[:40] or 'challenge'
        # Include the challenge id so two challenges with the same name (or
        # two accounts in one challenge) can never collide.
        return f"{safe_name}-{challenge.id}_{account_id}"

    def _mark_error(self, instance, message: str):
        try:
            instance.status = 'error'
            instance.extra_data = {'error': message}
            instance.connection_port = None
            instance.connection_ports = None
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Could not mark instance {instance.uuid} as error: {e}")
            db.session.rollback()

    # ==================================================================
    # Renewal / stop
    # ==================================================================
    def renew_instance(self, instance: ContainerInstance, user_id: int) -> ContainerInstance:
        """Renew (extend) container expiration"""
        challenge = ContainerChallenge.query.get(instance.challenge_id)
        if challenge is None:
            raise Exception("Challenge not found")

        max_renewals = challenge.get_max_renewals()
        if instance.renewal_count >= max_renewals:
            raise Exception(f"Maximum renewals ({max_renewals}) reached")

        if instance.is_expired():
            raise Exception("Container has already expired")

        extend_minutes = int(ContainerConfig.get('renew_extension_minutes', 5) or 5)

        # Add time to the *current* expiry, do not restart the clock from now
        # (the old behaviour could shorten an instance's life).
        instance.expires_at = instance.expires_at + timedelta(minutes=extend_minutes)
        instance.renewal_count = (instance.renewal_count or 0) + 1
        instance.last_accessed_at = datetime.utcnow()
        db.session.commit()

        self._extend_redis_expiration(instance.uuid, extend_minutes * 60)

        self._create_audit_log(
            'instance_renewed',
            instance_id=instance.id,
            challenge_id=instance.challenge_id,
            account_id=instance.account_id,
            user_id=user_id,
            details={
                'new_expires_at': instance.expires_at.isoformat(),
                'renewal_count': instance.renewal_count,
            }
        )
        db.session.commit()

        logger.info(f"Renewed instance {instance.uuid} (renewal {instance.renewal_count})")
        return instance

    def stop_instance(self, instance: ContainerInstance, user_id: int, reason='manual') -> bool:
        """
        Stop a container instance.

        Args:
            reason: 'manual', 'expired', 'solved', 'admin', ...

        Returns:
            True if the instance ended in a clean terminal state.
        """
        if instance.status not in ('running', 'provisioning', 'pending'):
            return False

        instance.status = 'stopping'
        db.session.commit()

        self._cancel_redis_expiration(instance.uuid)

        try:
            if instance.container_id:
                self.docker.stop_container(instance.container_id)

            self._release_instance_ports(instance)

            if reason == 'solved':
                instance.status = 'solved'
                instance.solved_at = datetime.utcnow()
            else:
                instance.status = 'stopped'
            instance.stopped_at = datetime.utcnow()

            # Retire the flag record when the container goes away without being
            # solved. The record is kept (not deleted) so the anti-cheat trail
            # survives and a later instance cannot collide with the same hash.
            if reason != 'solved':
                challenge = ContainerChallenge.query.get(instance.challenge_id)
                if challenge and challenge.flag_mode == 'random':
                    from ..models.flag import ContainerFlag
                    flag = ContainerFlag.query.filter_by(instance_id=instance.id).first()
                    if flag:
                        flag.invalidate()

            db.session.commit()

            self._create_audit_log(
                f'instance_stopped_{reason}',
                instance_id=instance.id,
                challenge_id=instance.challenge_id,
                account_id=instance.account_id,
                user_id=user_id,
                details={'reason': reason}
            )
            db.session.commit()

            logger.info(f"Stopped instance {instance.uuid} (reason: {reason})")
            return True

        except Exception as e:  # noqa: BLE001
            logger.error(f"Error stopping instance {instance.uuid}: {e}", exc_info=True)
            self._mark_error(instance, str(e))
            return False

    # ==================================================================
    # Redis expiration helpers (all no-ops when Redis is unavailable)
    # ==================================================================
    def _redis_service(self):
        try:
            from .. import redis_expiration_service
            return redis_expiration_service
        except Exception:  # noqa: BLE001
            return None

    def _schedule_redis_expiration(self, instance):
        service = self._redis_service()
        if not service:
            return
        try:
            seconds = int((instance.expires_at - datetime.utcnow()).total_seconds())
            service.schedule_expiration(instance.uuid, max(seconds, 1))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to schedule Redis expiration: {e}")

    def _extend_redis_expiration(self, instance_uuid, seconds):
        service = self._redis_service()
        if not service:
            return
        try:
            service.extend_expiration(instance_uuid, seconds)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to extend Redis expiration: {e}")

    def _cancel_redis_expiration(self, instance_uuid):
        service = self._redis_service()
        if not service:
            return
        try:
            service.cancel_expiration(instance_uuid)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to cancel Redis expiration: {e}")

    # ==================================================================
    # Background jobs
    # ==================================================================
    def cleanup_expired_instances(self, batch_size: int = CLEANUP_BATCH_SIZE) -> int:
        """
        Background job: stop instances whose expiry has passed.

        Safe to run from any thread: no request context is required and it
        never touches the process-wide SIGALRM handler (which is main-thread
        only and raised ValueError in every APScheduler worker).
        """
        if self._cleanup_running:
            logger.warning("Cleanup job already running, skipping this run")
            return 0

        self._cleanup_running = True
        cleaned = 0
        failed = 0
        try:
            expired = ContainerInstance.query.filter(
                ContainerInstance.status.in_(['running', 'provisioning']),
                ContainerInstance.expires_at < datetime.utcnow()
            ).order_by(ContainerInstance.expires_at.asc()).limit(batch_size).all()

            if not expired:
                return 0

            logger.info(f"Cleanup: {len(expired)} expired instance(s) to stop")

            for instance in expired:
                try:
                    if self.stop_instance(instance, user_id=None, reason='expired'):
                        cleaned += 1
                    else:
                        failed += 1
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Error cleaning up instance {instance.uuid}: {e}", exc_info=True)
                    failed += 1
                    db.session.rollback()

            logger.info(f"Cleanup completed: {cleaned} cleaned, {failed} failed")
            return cleaned
        finally:
            self._cleanup_running = False

    def cleanup_old_instances(self, retention_days: int = None) -> int:
        """
        Background job: delete old stopped/error/solved instance records and
        reap orphaned containers that no longer have a live instance row.
        """
        if retention_days is None:
            try:
                retention_days = int(
                    ContainerConfig.get('audit_retention_days', DEFAULT_AUDIT_RETENTION_DAYS)
                )
            except (TypeError, ValueError):
                retention_days = DEFAULT_AUDIT_RETENTION_DAYS

        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        deleted = 0

        old = ContainerInstance.query.filter(
            ContainerInstance.status.in_(['stopped', 'error', 'solved']),
            ContainerInstance.created_at < cutoff,
        ).limit(CLEANUP_BATCH_SIZE).all()

        for instance in old:
            try:
                from ..models.flag import ContainerFlag
                ContainerFlag.query.filter_by(
                    instance_id=instance.id,
                    flag_status='invalidated'
                ).delete(synchronize_session=False)
                db.session.delete(instance)
                db.session.commit()
                deleted += 1
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error deleting instance {instance.uuid}: {e}")
                db.session.rollback()

        # Reap containers whose instance row disappeared (crash, manual DB edit)
        try:
            live_uuids = [
                row[0] for row in
                db.session.query(ContainerInstance.uuid).filter(
                    ContainerInstance.status.in_(['running', 'provisioning'])
                ).all()
            ]
            self.docker.cleanup_orphaned_containers(live_uuids)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Orphan container cleanup failed: {e}")

        if deleted:
            logger.info(f"Deleted {deleted} old instance record(s)")
        return deleted

    # ==================================================================
    # Audit log
    # ==================================================================
    def _create_audit_log(self, event_type, **kwargs):
        """
        Create an audit log entry.

        Works both inside a request and from background threads/schedulers:
        the request-derived fields are only read when a request actually
        exists. (Reading ``request.remote_addr`` from a scheduler thread used
        to raise, which turned every background cleanup into a failed
        container kill.)
        """
        if has_request_context():
            kwargs.setdefault('ip_address', request.remote_addr)
            kwargs.setdefault('user_agent', request.headers.get('User-Agent'))
        else:
            kwargs.setdefault('ip_address', None)
            kwargs.setdefault('user_agent', None)

        details = kwargs.get('details')
        if details is not None:
            kwargs['details'] = self._json_safe(details)

        log = ContainerAuditLog(event_type=event_type, **kwargs)
        db.session.add(log)

    @staticmethod
    def _json_safe(value):
        """Make a details payload safe for a JSON column."""
        if isinstance(value, dict):
            return {str(k): ContainerService._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ContainerService._json_safe(v) for v in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

"""
Container Service - Business logic for container lifecycle
"""
import logging
from datetime import datetime, timedelta
from flask import request
from CTFd.models import db
from CTFd.utils import get_config
from ..models.instance import ContainerInstance
from ..models.challenge import ContainerChallenge
from ..models.audit import ContainerAuditLog
from .docker_service import DockerService
from .flag_service import FlagService
from .port_manager import PortManager

logger = logging.getLogger(__name__)


class ContainerService:
    """
    Service to manage container lifecycle
    """
    
    def __init__(self, docker_service: DockerService, flag_service: FlagService, port_manager: PortManager):
        self.docker = docker_service
        self.flag_service = flag_service
        self.port_manager = port_manager
        self._cleanup_running = False  # Prevent overlapping cleanup jobs
    
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
        # 1. Validate challenge exists
        challenge = ContainerChallenge.query.get(challenge_id)
        if not challenge:
            raise Exception("Challenge not found")
        
        # 2. Check if already solved (prevent creating instance after solve)
        from CTFd.models import Solves
        already_solved = Solves.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id
        ).first()
        
        if already_solved:
            raise Exception("Challenge already solved - cannot create new instance")
        
        # 3. Check if already has running instance
        existing = ContainerInstance.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id,
            status='running'
        ).first()
        
        if existing and not existing.is_expired():
            logger.info(f"Account {account_id} already has running instance for challenge {challenge_id}")
            return existing
        
        # 4. Stop any existing expired instances
        if existing and existing.is_expired():
            logger.info(f"Stopping expired instance {existing.uuid}")
            self.stop_instance(existing, user_id, reason='expired')
        
        # 5. Create instance record (status=pending)
        # Set expiration based on global timeout setting
        expires_at = datetime.utcnow() + timedelta(minutes=challenge.get_timeout_minutes())
        
        # Generate flag
        flag_plaintext = self.flag_service.generate_flag(challenge)
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
        
        # 6. Create flag record (only for random flag mode - anti-cheat tracking)
        if challenge.flag_mode == 'random':
            self.flag_service.create_flag_record(instance, challenge, account_id, flag_plaintext)
        
        # 7. Audit log
        self._create_audit_log(
            'instance_created',
            instance_id=instance.id,
            challenge_id=challenge_id,
            account_id=account_id,
            user_id=user_id,
            details={'expires_at': expires_at.isoformat()}
        )
        
        db.session.commit()
        
        # 8. Provision container (async)
        try:
            self._provision_container(instance, challenge, flag_plaintext)
        except Exception as e:
            logger.error(f"Failed to provision container: {e}")
            instance.status = 'error'
            instance.extra_data = {'error': str(e)}
            db.session.commit()
            raise
        
        return instance
    
    def _provision_container(self, instance: ContainerInstance, challenge: ContainerChallenge, flag: str):
        """
        Provision Docker container
        
        Args:
            instance: ContainerInstance object
            challenge: ContainerChallenge object
            flag: Plain text flag
        """
        import uuid as uuid_module
        
        # Update status
        instance.status = 'provisioning'
        db.session.commit()
        
        try:
            # Get config
            from ..models.config import ContainerConfig
            
            # Check if subdomain routing is enabled
            subdomain_enabled = ContainerConfig.get('subdomain_enabled', 'false').lower() == 'true'
            subdomain_base_domain = ContainerConfig.get('subdomain_base_domain', '')
            subdomain_network = ContainerConfig.get('subdomain_network', 'ctfd-network')
            
            # Determine if this challenge should use subdomain routing
            # Only for HTTP/web challenges
            use_subdomain = (
                subdomain_enabled and 
                subdomain_base_domain and
                challenge.container_connection_type in ('http', 'https', 'web')
            )
            
            # Retry loop for race conditions (max 5 retries)
            max_retries = 5
            import time
            
            for attempt in range(max_retries):
                try:
                    # 1. Allocate ports
                    host_port = None
                    ports_map = None
                    
                    if challenge.internal_ports:
                        try:
                            int_ports = [int(p.strip()) for p in challenge.internal_ports.split(',') if p.strip()]
                            if int_ports:
                                allocated = self.port_manager.allocate_ports(len(int_ports))
                                ports_map = dict(zip([str(p) for p in int_ports], allocated))
                                # Use the first one as primary for fallback/compatibility
                                host_port = allocated[0]
                        except Exception as e:
                            logger.error(f"Failed to parse/allocate internal_ports: {e}")
                            raise
                    
                    if not ports_map:
                        # Fallback to single port
                        host_port = self.port_manager.allocate_port()
                        ports_map = {str(challenge.internal_port): host_port}

                    
                    # 2. Get connection host
                    connection_host = ContainerConfig.get('connection_host', 'localhost')
                    
                    # 3. Generate subdomain if enabled
                    subdomain = None
                    full_hostname = None
                    if use_subdomain:
                        # Generate random 16-char subdomain with prefix format for Cloudflare Free SSL
                        # Format: c-{random}.domain.com (single level, compatible with free SSL)
                        subdomain = f"c-{uuid_module.uuid4().hex[:16]}"
                        full_hostname = f"{subdomain}.{subdomain_base_domain}"
                        logger.info(f"Generated subdomain: {full_hostname}")
                    
                    # 4. Create Docker container
                    # Generate container name: challengename_accountid
                    import re
                    # Sanitize challenge name (only alphanumeric and hyphens)
                    safe_name = re.sub(r'[^a-zA-Z0-9-]', '', challenge.name.replace(' ', '-').lower())
                    container_name = f"{safe_name}_{instance.account_id}"
                    
                    # Replace {FLAG} placeholder in command if present
                    command = challenge.command if challenge.command else None
                    if command and '{FLAG}' in command:
                        command = command.replace('{FLAG}', flag)
                    
                    # Base labels
                    labels = {
                        'ctfd.instance_uuid': instance.uuid,
                        'ctfd.challenge_id': str(challenge.id),
                        'ctfd.account_id': str(instance.account_id),
                        'ctfd.expires_at': str(instance.expires_at.timestamp())
                    }
                    
                    # Add Traefik labels if subdomain routing is enabled
                    if use_subdomain:
                        router_name = f"ctfd-{instance.uuid[:8]}"
                        labels.update({
                            'traefik.enable': 'true',
                            f'traefik.http.routers.{router_name}.rule': f'Host(`{full_hostname}`)',
                            f'traefik.http.routers.{router_name}.entrypoints': 'web',
                            f'traefik.http.services.{router_name}.loadbalancer.server.port': str(challenge.internal_port),
                            'traefik.docker.network': subdomain_network,
                        })
                    
                    result = self.docker.create_container(
                        image=challenge.image,
                        internal_port=challenge.internal_port,
                        host_port=host_port,
                        ports=ports_map,
                        command=command,
                        environment={'FLAG': flag},
                        memory_limit=challenge.get_memory_limit(),
                        cpu_limit=challenge.get_cpu_limit(),
                        pids_limit=challenge.pids_limit,
                        name=container_name,
                        labels=labels,
                        network=subdomain_network if use_subdomain else None,
                        use_traefik=use_subdomain
                    )
                    
                    # 5. Update instance
                    instance.container_id = result['container_id']
                    instance.connection_port = host_port
                    instance.connection_ports = ports_map
                    
                    if use_subdomain:
                        # For subdomain routing: store URL
                        instance.connection_host = full_hostname
                        instance.connection_info = {
                            'type': 'url',
                            'url': f"https://{full_hostname}",
                            'subdomain': subdomain,
                            'info': challenge.container_connection_info
                        }
                    else:
                        # For port-based routing: store host:port
                        instance.connection_host = connection_host
                        instance.connection_info = {
                            'type': challenge.container_connection_type,
                            'info': challenge.container_connection_info
                        }
                    
                    instance.status = 'running'
                    instance.started_at = datetime.utcnow()
                    
                    db.session.commit()
                    
                    # 6. Schedule expiration in Redis (for accurate killing)
                    try:
                        from .. import redis_expiration_service
                        if redis_expiration_service:
                            expires_in_seconds = int((instance.expires_at - datetime.utcnow()).total_seconds())
                            redis_expiration_service.schedule_expiration(
                                instance.uuid,
                                expires_in_seconds
                            )
                    except Exception as e:
                        logger.warning(f"Failed to schedule Redis expiration: {e}")
                    
                    logger.info(f"Provisioned container {result['container_id'][:12]} for instance {instance.uuid}")
                    if use_subdomain:
                        logger.info(f"Subdomain routing: https://{subdomain}.{subdomain_base_domain}")
                    
                    # Audit log
                    self._create_audit_log(
                        'instance_started',
                        instance_id=instance.id,
                        challenge_id=challenge.id,
                        account_id=instance.account_id,
                        details={
                            'container_id': result['container_id'],
                            'port': host_port,
                            'ports': ports_map,
                            'subdomain': subdomain if use_subdomain else None
                        }
                    )
                    
                    # Success: break loop
                    break
                    
                except Exception as e:
                    logger.warning(f"Attempt {attempt+1}/{max_retries} failed: {e}")
                    # If this was the last attempt, re-raise the exception
                    if attempt == max_retries - 1:
                        logger.error(f"Error provisioning container after {max_retries} attempts: {e}")
                        instance.status = 'error'
                        instance.extra_data = {'error': str(e)}
                        db.session.commit()
                        raise
                    
                    # Wait before retrying (exponential backoff not really needed here, just jitter)
                    import random
                    time.sleep(0.1 + random.random() * 0.2)

            
        except Exception as e:
            logger.error(f"Error provisioning container: {e}")
            instance.status = 'error'
            instance.extra_data = {'error': str(e)}
            db.session.commit()
            raise
    
    def renew_instance(self, instance: ContainerInstance, user_id: int) -> ContainerInstance:
        """
        Renew (extend) container expiration
        
        Args:
            instance: ContainerInstance object
            user_id: User requesting renewal
        
        Returns:
            Updated instance
        """
        challenge = ContainerChallenge.query.get(instance.challenge_id)
        
        # Check renewal limit
        max_renewals = challenge.get_max_renewals()
        if instance.renewal_count >= max_renewals:
            raise Exception(f"Maximum renewals ({max_renewals}) reached")
        
        # Extend expiration by 5 minutes (fixed)
        extend_minutes = 5
        instance.extend_expiration(extend_minutes)
        instance.last_accessed_at = datetime.utcnow()
        
        db.session.commit()
        
        # Extend Redis TTL
        try:
            from .. import redis_expiration_service
            if redis_expiration_service:
                redis_expiration_service.extend_expiration(
                    instance.uuid,
                    extend_minutes * 60  # 5 minutes = 300 seconds
                )
        except Exception as e:
            logger.warning(f"Failed to extend Redis expiration: {e}")
        
        # Audit log
        self._create_audit_log(
            'instance_renewed',
            instance_id=instance.id,
            challenge_id=instance.challenge_id,
            account_id=instance.account_id,
            user_id=user_id,
            details={
                'new_expires_at': instance.expires_at.isoformat(),
                'renewal_count': instance.renewal_count
            }
        )
        
        logger.info(f"Renewed instance {instance.uuid} (renewal {instance.renewal_count})")
        
        return instance
    
    def stop_instance(self, instance: ContainerInstance, user_id: int, reason='manual') -> bool:
        """
        Stop container instance
        
        Args:
            instance: ContainerInstance object
            user_id: User stopping the container
            reason: Reason for stopping ('manual', 'expired', 'solved')
        
        Returns:
            True if successful
        """
        if instance.status not in ('running', 'provisioning'):
            return False
        
        instance.status = 'stopping'
        db.session.commit()
        
        # Cancel Redis expiration
        try:
            from .. import redis_expiration_service
            if redis_expiration_service:
                redis_expiration_service.cancel_expiration(instance.uuid)
        except Exception as e:
            logger.warning(f"Failed to cancel Redis expiration: {e}")
        
        try:
            # Stop Docker container
            if instance.container_id:
                self.docker.stop_container(instance.container_id)
            
            # Release port back to pool
            if instance.connection_port:
                self.port_manager.release_port(instance.connection_port)
                logger.info(f"Released port {instance.connection_port}")
            
            if instance.connection_ports:
                for int_p, ext_p in instance.connection_ports.items():
                    self.port_manager.release_port(ext_p)
            
            # Update instance based on reason
            if reason == 'solved':
                instance.status = 'solved'
                instance.solved_at = datetime.utcnow()
            else:
                instance.status = 'stopped'
            
            instance.stopped_at = datetime.utcnow()
            
            # Handle flag based on reason (only for random flag mode)
            if reason != 'solved':
                # Get challenge to check flag mode
                challenge = ContainerChallenge.query.get(instance.challenge_id)
                if challenge and challenge.flag_mode == 'random':
                    from ..models.flag import ContainerFlag
                    flag = ContainerFlag.query.filter_by(instance_id=instance.id).first()
                    if flag:
                        # Delete flag instead of invalidating to prevent duplicate hash issues
                        # when user recreates container
                        db.session.delete(flag)
                        logger.info(f"Deleted temporary flag for instance {instance.uuid}")
            
            db.session.commit()
            
            # Audit log
            self._create_audit_log(
                f'instance_stopped_{reason}',
                instance_id=instance.id,
                challenge_id=instance.challenge_id,
                account_id=instance.account_id,
                user_id=user_id,
                details={'reason': reason}
            )
            
            logger.info(f"Stopped instance {instance.uuid} (reason: {reason})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error stopping instance: {e}")
            instance.status = 'error'
            instance.extra_data = {'error': str(e)}
            db.session.commit()
            return False
    
    def cleanup_expired_instances(self):
        """
        Background job: Cleanup expired instances
        
        Optimized for high volume (100+ containers):
        - Prevent overlapping runs
        - Batch processing (max 50 per run)
        - Timeout per container
        - Continue on error
        """
        # Prevent overlapping cleanup jobs
        if self._cleanup_running:
            logger.warning("Cleanup job already running, skipping this run")
            return
        
        self._cleanup_running = True
        
        try:
            import signal
            from contextlib import contextmanager
            
            @contextmanager
            def timeout(seconds):
                """Timeout context manager"""
                def timeout_handler(signum, frame):
                    raise TimeoutError(f"Operation timed out after {seconds}s")
                
                # Set alarm (Unix only)
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(seconds)
                try:
                    yield
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
            
            # Get expired instances (limit to 50 per run to prevent overload)
            expired = ContainerInstance.query.filter(
                ContainerInstance.status == 'running',
                ContainerInstance.expires_at < datetime.utcnow()
            ).limit(50).all()
            
            if not expired:
                return
            
            logger.warning(f"⚠️ [APSCHEDULER CLEANUP] Found {len(expired)} expired instances (Redis backup cleanup)")
            
            cleaned = 0
            failed = 0
            
            for instance in expired:
                try:
                    # Timeout after 10 seconds per container
                    with timeout(10):
                        logger.warning(f"🟡 [APSCHEDULER KILL] Cleaning up expired instance {instance.uuid}")
                        self.stop_instance(instance, user_id=None, reason='expired')
                        cleaned += 1
                except TimeoutError:
                    logger.error(f"Timeout cleaning up instance {instance.uuid}")
                    # Mark as error so it gets cleaned up later
                    instance.status = 'error'
                    db.session.commit()
                    failed += 1
                except Exception as e:
                    logger.error(f"Error cleaning up instance {instance.uuid}: {e}")
                    failed += 1
            
            logger.info(f"Cleanup completed: {cleaned} cleaned, {failed} failed")
        
        finally:
            self._cleanup_running = False
    
    def cleanup_old_instances(self):
        """
        Background job: Delete old stopped/error instances
        """
        instances = ContainerInstance.query.filter(
            ContainerInstance.status.in_(['stopped', 'error'])
        ).all()
        
        for instance in instances:
            if instance.should_cleanup():
                logger.info(f"Deleting old instance {instance.uuid}")
                try:
                    # Delete associated flags if invalidated
                    from ..models.flag import ContainerFlag
                    ContainerFlag.query.filter_by(
                        instance_id=instance.id,
                        flag_status='invalidated'
                    ).delete()
                    
                    db.session.delete(instance)
                    db.session.commit()
                except Exception as e:
                    logger.error(f"Error deleting instance: {e}")
                    db.session.rollback()
    
    def _create_audit_log(self, event_type, **kwargs):
        """Create audit log entry"""
        log = ContainerAuditLog(
            event_type=event_type,
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None,
            **kwargs
        )
        db.session.add(log)

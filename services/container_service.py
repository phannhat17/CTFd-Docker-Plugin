"""
Container Service - Business logic cho container lifecycle
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
    Service quản lý container lifecycle
    """
    
    def __init__(self, docker_service: DockerService, flag_service: FlagService, port_manager: PortManager):
        self.docker = docker_service
        self.flag_service = flag_service
        self.port_manager = port_manager
    
    def create_instance(self, challenge_id: int, account_id: int, user_id: int) -> ContainerInstance:
        """
        Tạo container instance mới
        
        Args:
            challenge_id: Challenge ID
            account_id: Team ID (team mode) hoặc User ID (user mode)
            user_id: User ID thực tế tạo container
        
        Returns:
            ContainerInstance object
        
        Raises:
            Exception nếu có lỗi
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
        expires_at = datetime.utcnow() + timedelta(minutes=challenge.timeout_minutes)
        
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
        # Update status
        instance.status = 'provisioning'
        db.session.commit()
        
        try:
            # 1. Allocate port
            host_port = self.port_manager.allocate_port()
            
            # 2. Get connection host
            from ..models.config import ContainerConfig
            connection_host = ContainerConfig.get('connection_host', 'localhost')
            
            # 3. Create Docker container
            # Replace {FLAG} placeholder in command if present
            command = challenge.command if challenge.command else None
            if command and '{FLAG}' in command:
                command = command.replace('{FLAG}', flag)
            
            result = self.docker.create_container(
                image=challenge.image,
                internal_port=challenge.internal_port,
                host_port=host_port,
                command=command,
                environment={'FLAG': flag},
                memory_limit=challenge.memory_limit,
                cpu_limit=challenge.cpu_limit,
                pids_limit=challenge.pids_limit,
                labels={
                    'ctfd.instance_uuid': instance.uuid,
                    'ctfd.challenge_id': str(challenge.id),
                    'ctfd.account_id': str(instance.account_id),
                    'ctfd.expires_at': str(instance.expires_at.timestamp())
                }
            )
            
            # 4. Update instance
            instance.container_id = result['container_id']
            instance.connection_host = connection_host
            instance.connection_port = host_port
            instance.connection_info = {
                'type': challenge.container_connection_type,
                'info': challenge.container_connection_info
            }
            instance.status = 'running'
            instance.started_at = datetime.utcnow()
            
            db.session.commit()
            
            logger.info(f"Provisioned container {result['container_id'][:12]} for instance {instance.uuid}")
            
            # Audit log
            self._create_audit_log(
                'instance_started',
                instance_id=instance.id,
                challenge_id=challenge.id,
                account_id=instance.account_id,
                details={
                    'container_id': result['container_id'],
                    'port': host_port
                }
            )
            
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
        if instance.renewal_count >= challenge.max_renewals:
            raise Exception(f"Maximum renewals ({challenge.max_renewals}) reached")
        
        # Extend expiration
        instance.extend_expiration(challenge.timeout_minutes)
        instance.last_accessed_at = datetime.utcnow()
        
        db.session.commit()
        
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
        
        try:
            # Stop Docker container
            if instance.container_id:
                self.docker.stop_container(instance.container_id)
            
            # Release port back to pool
            if instance.connection_port:
                self.port_manager.release_port(instance.connection_port)
                logger.info(f"Released port {instance.connection_port}")
            
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
        """
        expired = ContainerInstance.query.filter(
            ContainerInstance.status == 'running',
            ContainerInstance.expires_at < datetime.utcnow()
        ).all()
        
        for instance in expired:
            logger.info(f"Cleaning up expired instance {instance.uuid}")
            try:
                self.stop_instance(instance, user_id=None, reason='expired')
            except Exception as e:
                logger.error(f"Error cleaning up instance {instance.uuid}: {e}")
    
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

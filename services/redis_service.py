"""
Redis Service - Handle container expiration with Redis TTL
"""
import logging
import json
import threading
from datetime import datetime, timedelta
from CTFd.cache import cache

logger = logging.getLogger(__name__)


class RedisExpirationService:
    """
    Service to handle container expiration using Redis keyspace notifications
    
    This is more accurate than polling database every minute:
    - Containers are killed EXACTLY when they expire
    - No polling overhead
    - Survives CTFd restarts (Redis is persistent)
    """
    
    def __init__(self, app, container_service_getter):
        """
        Args:
            app: Flask application instance
            container_service_getter: Callable that returns ContainerService
                                     (needed to avoid circular dependency)
        """
        self.app = app
        self.container_service_getter = container_service_getter
        self._listener_thread = None
        self._running = False
        
        # Get Redis client from CTFd's cache
        try:
            self.redis = cache.cache._write_client if hasattr(cache.cache, '_write_client') else cache.cache
            logger.info("Redis client initialized for expiration service")
        except Exception as e:
            logger.error(f"Failed to get Redis client: {e}")
            self.redis = None
    
    def schedule_expiration(self, instance_uuid: str, expires_in_seconds: int):
        """
        Schedule a container to be killed when it expires
        
        Args:
            instance_uuid: Container instance UUID
            expires_in_seconds: How many seconds until expiration
        """
        if not self.redis:
            logger.warning("Redis not available, falling back to database polling")
            return
        
        try:
            key = f"container:expire:{instance_uuid}"
            
            # Set key with TTL - when it expires, we get notification
            self.redis.setex(
                key,
                expires_in_seconds,
                json.dumps({
                    'instance_uuid': instance_uuid,
                    'scheduled_at': datetime.utcnow().isoformat()
                })
            )
            
            logger.warning(f"✅ [REDIS SCHEDULE] Container {instance_uuid} will expire in {expires_in_seconds}s ({expires_in_seconds//60}m {expires_in_seconds%60}s)")
        except Exception as e:
            logger.error(f"Failed to schedule expiration for {instance_uuid}: {e}")
    
    def cancel_expiration(self, instance_uuid: str):
        """
        Cancel scheduled expiration (when container is manually stopped)
        
        Args:
            instance_uuid: Container instance UUID
        """
        if not self.redis:
            return
        
        try:
            key = f"container:expire:{instance_uuid}"
            self.redis.delete(key)
            logger.info(f"Cancelled expiration for {instance_uuid}")
        except Exception as e:
            logger.error(f"Failed to cancel expiration for {instance_uuid}: {e}")
    
    def extend_expiration(self, instance_uuid: str, additional_seconds: int):
        """
        Extend expiration time (when container is renewed)
        
        Args:
            instance_uuid: Container instance UUID
            additional_seconds: How many more seconds to add
        """
        if not self.redis:
            return
        
        try:
            key = f"container:expire:{instance_uuid}"
            
            # Get current TTL
            current_ttl = self.redis.ttl(key)
            if current_ttl > 0:
                # Extend TTL
                new_ttl = current_ttl + additional_seconds
                self.redis.expire(key, new_ttl)
                logger.info(f"Extended expiration for {instance_uuid} by {additional_seconds}s (new TTL: {new_ttl}s)")
            else:
                logger.warning(f"Cannot extend {instance_uuid}: key expired or not found")
        except Exception as e:
            logger.error(f"Failed to extend expiration for {instance_uuid}: {e}")
    
    def start_listener(self):
        """
        Start listening for Redis keyspace notifications
        
        This runs in a background thread and triggers container cleanup
        when Redis keys expire
        """
        if not self.redis:
            logger.warning("Redis not available, listener not started")
            return
        
        if self._running:
            logger.warning("Listener already running")
            return
        
        # Enable keyspace notifications for expired events
        try:
            self.redis.config_set('notify-keyspace-events', 'Ex')
            logger.warning("✅ [REDIS LISTENER] Enabled keyspace notifications (Ex)")
        except Exception as e:
            logger.error(f"❌ [REDIS LISTENER] Could not enable keyspace notifications: {e}")
        
        # Start listener thread
        self._running = True
        self._listener_thread = threading.Thread(
            target=self._listen_for_expirations,
            daemon=True,
            name='RedisExpirationListener'
        )
        self._listener_thread.start()
        logger.warning("✅ [REDIS LISTENER] Started background thread - listening for expirations...")
    
    def stop_listener(self):
        """Stop the listener thread"""
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
            logger.info("Stopped Redis expiration listener")
    
    def _listen_for_expirations(self):
        """
        Background thread that listens for expired keys
        
        When a key expires, this triggers the container cleanup
        """
        if not self.redis:
            return
        
        try:
            # Subscribe to keyspace notifications for expired events
            pubsub = self.redis.pubsub()
            pubsub.psubscribe('__keyevent@0__:expired')
            
            logger.info("Listening for Redis key expirations...")
            
            for message in pubsub.listen():
                if not self._running:
                    break
                
                if message['type'] == 'pmessage':
                    expired_key = message['data'].decode('utf-8') if isinstance(message['data'], bytes) else message['data']
                    
                    logger.info(f"[REDIS] Received expiration event: {expired_key}")
                    
                    # Check if this is a container expiration key
                    if expired_key.startswith('container:expire:'):
                        instance_uuid = expired_key.replace('container:expire:', '')
                        logger.warning(f"🔴 [REDIS KILL] Container {instance_uuid} expired - killing now!")
                        
                        # Kill the container
                        self._handle_expiration(instance_uuid)
        
        except Exception as e:
            logger.error(f"Error in Redis listener: {e}", exc_info=True)
        finally:
            logger.info("Redis listener thread stopped")
    
    def _handle_expiration(self, instance_uuid: str):
        """
        Handle container expiration
        
        Args:
            instance_uuid: Container instance UUID to kill
        """
        # Run in app context
        with self.app.app_context():
            try:
                # Get container service
                container_service = self.container_service_getter()
                if not container_service:
                    logger.error("Container service not available")
                    return
                
                # Import here to avoid circular dependency
                from ..models.instance import ContainerInstance
                
                # Find instance
                instance = ContainerInstance.query.filter_by(uuid=instance_uuid).first()
                
                if not instance:
                    logger.warning(f"Instance {instance_uuid} not found in database")
                    return
                
                if instance.status not in ('running', 'provisioning'):
                    logger.info(f"Instance {instance_uuid} already stopped (status: {instance.status})")
                    return
                
                # Stop the container
                logger.info(f"Stopping expired container {instance_uuid}")
                container_service.stop_instance(instance, user_id=None, reason='expired')
                logger.warning(f"✅ [REDIS KILL SUCCESS] Container {instance_uuid} stopped")
            
            except Exception as e:
                logger.error(f"Error handling expiration for {instance_uuid}: {e}", exc_info=True)

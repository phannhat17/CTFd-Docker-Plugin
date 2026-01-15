"""
Port Manager - Manage port allocation
"""
import logging
from CTFd.models import db
from ..models.config import ContainerConfig

logger = logging.getLogger(__name__)


class PortManager:
    """
    Manage port pool
    
    Ports are configured in config (e.g., 30000-31000)
    This service tracks which ports are in use
    """
    
    def __init__(self, port_range_start=30000, port_range_end=31000):
        """
        Initialize port manager
        
        Args:
            port_range_start: Start of port range (fallback if config not set)
            port_range_end: End of port range (fallback if config not set)
        """
        self._default_start = port_range_start
        self._default_end = port_range_end
    
    def _get_port_range(self):
        """
        Get current port range from config
        
        This is called on each operation to ensure admin changes
        take effect immediately without restart
        """
        config_start = ContainerConfig.get('port_range_start')
        config_end = ContainerConfig.get('port_range_end')
        
        start = int(config_start) if config_start else self._default_start
        end = int(config_end) if config_end else self._default_end
        
        return start, end
    
    @property
    def port_range_start(self):
        """Get current port range start from config"""
        start, _ = self._get_port_range()
        return start
    
    @property
    def port_range_end(self):
        """Get current port range end from config"""
        _, end = self._get_port_range()
        return end
    
    def _get_used_ports(self):
        """Get set of ports currently in use"""
        from ..models.instance import ContainerInstance
        
        # Get all active instances
        instances = db.session.query(ContainerInstance).filter(
            ContainerInstance.status.in_(['running', 'provisioning', 'stopping'])
        ).all()
        
        used_ports = set()
        for instance in instances:
            # Check main port
            if instance.connection_port:
                used_ports.add(instance.connection_port)
            
            # Check extra ports
            if instance.connection_ports:
                try:
                    # connection_ports is {"internal": external}
                    for _, ext_port in instance.connection_ports.items():
                        used_ports.add(int(ext_port))
                except:
                    pass
                    
        return used_ports

    def get_redis_client(self):
        """Get Redis client from CTFd cache"""
        try:
            from CTFd.cache import cache
            return cache.cache._write_client if hasattr(cache.cache, '_write_client') else cache.cache
        except Exception as e:
            logger.warning(f"Failed to get Redis client: {e}")
            return None

    def lock_port(self, port: int, ttl: int = 5) -> bool:
        """
        Try to lock a port using Redis
        
        Args:
            port: Port to lock
            ttl: Lock TTL in seconds
        
        Returns:
            True if locked successfully, False if already locked
        """
        redis = self.get_redis_client()
        if not redis:
            return True  # If no Redis, assume we can use it (fallback to DB check only)
            
        key = f"port_lock:{port}"
        try:
            # setnx (set if not exists)
            return redis.set(key, "locked", ex=ttl, nx=True)
        except Exception as e:
            logger.error(f"Redis error locking port {port}: {e}")
            return True  # Fail open if Redis errors

    def allocate_port(self) -> int:
        """
        Allocate next available port with Redis locking
        """
        start, end = self._get_port_range()
        used_ports = self._get_used_ports()
        
        # Try to find available port
        for port in range(start, end + 1):
            if port not in used_ports:
                # Try to claim with Redis
                if self.lock_port(port):
                    logger.info(f"Allocated port {port}")
                    return port
        
        raise Exception(f"No available ports in range {start}-{end}")

    def allocate_ports(self, count: int) -> list:
        """
        Allocate multiple available ports with Redis locking
        """
        start, end = self._get_port_range()
        used_ports = self._get_used_ports()
        allocated = []
        
        # Try to find available ports
        for port in range(start, end + 1):
            if port not in used_ports:
                if self.lock_port(port):
                    allocated.append(port)
                    if len(allocated) == count:
                        logger.info(f"Allocated ports {allocated}")
                        return allocated
        
        # Release if we couldn't get enough
        # (Though current implementation relies on TTL expiry)
        raise Exception(f"Not enough available ports in range {start}-{end}")
    
    def release_port(self, port: int):
        """Release port lock"""
        logger.info(f"Released port {port}")
        # Lock expires automatically via TTL, but we could explicitly delete
        # Redis key if we wanted. Since TTL is short (5s), auto-expire is fine.
    
    def get_available_count(self) -> int:
        """Get number of available ports"""
        start, end = self._get_port_range()
        used_ports = self._get_used_ports()
        
        total_ports = end - start + 1
        return total_ports - len(used_ports)

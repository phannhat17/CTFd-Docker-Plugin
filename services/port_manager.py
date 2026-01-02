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
            port_range_start: Start of port range
            port_range_end: End of port range
        """
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end
        
        # Load from config
        config_start = ContainerConfig.get('port_range_start')
        config_end = ContainerConfig.get('port_range_end')
        
        if config_start:
            self.port_range_start = int(config_start)
        if config_end:
            self.port_range_end = int(config_end)
    
    def allocate_port(self) -> int:
        """
        Allocate next available port
        
        Returns:
            Port number
        
        Raises:
            Exception if no ports available
        """
        from ..models.instance import ContainerInstance
        
        # Get all ports currently in use by running instances
        used_ports = db.session.query(ContainerInstance.connection_port).filter(
            ContainerInstance.status.in_(['running', 'provisioning', 'stopping']),
            ContainerInstance.connection_port.isnot(None)
        ).all()
        
        used_ports_set = {port[0] for port in used_ports if port[0]}
        
        # Find first available port
        for port in range(self.port_range_start, self.port_range_end + 1):
            if port not in used_ports_set:
                logger.info(f"Allocated port {port}")
                return port
        
        raise Exception(f"No available ports in range {self.port_range_start}-{self.port_range_end}")
    
    def release_port(self, port: int):
        """
        Release a port (currently this is implicit when instance status changes)
        
        Args:
            port: Port to release
        """
        logger.info(f"Released port {port}")
        # Port is automatically released when instance status changes
        # No explicit action needed
    
    def get_available_count(self) -> int:
        """Get number of available ports"""
        from ..models.instance import ContainerInstance
        
        used_count = db.session.query(ContainerInstance).filter(
            ContainerInstance.status.in_(['running', 'provisioning', 'stopping']),
            ContainerInstance.connection_port.isnot(None)
        ).count()
        
        total_ports = self.port_range_end - self.port_range_start + 1
        return total_ports - used_count

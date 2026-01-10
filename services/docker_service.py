"""
Docker Service - Manage Docker containers
"""
import docker
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DockerService:
    """
    Service to interact with Docker daemon
    """
    
    def __init__(self, base_url='unix://var/run/docker.sock'):
        """
        Initialize Docker client
        
        Args:
            base_url: Docker daemon URL
                     - Unix socket: 'unix://var/run/docker.sock' (default)
                     - TCP: 'tcp://192.168.1.100:2376'
                     - SSH: 'ssh://user@host:port' or 'ssh://user@host' (default port 22)
        """
        self.base_url = base_url
        self.client = None
        self._connect()
    
    def _connect(self):
        """Connect to Docker daemon - Don't raise exception, just log warning"""
        try:
            # Handle SSH connection
            if self.base_url.startswith('ssh://'):
                logger.info(f"Attempting SSH connection to Docker: {self.base_url}")
                # docker-py supports ssh:// URLs directly
                # Format: ssh://user@host:port or ssh://user@host (default port 22)
                # SSH keys will be used from ~/.ssh/ or SSH agent
                self.client = docker.DockerClient(base_url=self.base_url, timeout=30)
            else:
                # Regular connection (Unix socket or TCP)
                self.client = docker.DockerClient(base_url=self.base_url, timeout=10)
            
            self.client.ping()
            logger.info(f"Connected to Docker daemon at {self.base_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Docker: {e}")
            logger.warning("Docker connection will be retried when needed. Configure in plugin settings.")
            self.client = None
            # Don't raise - allow plugin to load even if Docker is unavailable
    
    def is_connected(self) -> bool:
        """Check if Docker is connected"""
        if not self.client:
            return False
        try:
            self.client.ping()
            return True
        except:
            return False
    
    def create_container(
        self,
        image: str,
        internal_port: int,
        host_port: int,
        command: str = None,
        environment: Dict[str, str] = None,
        memory_limit: str = "512m",
        cpu_limit: float = 0.5,
        pids_limit: int = 100,
        labels: Dict[str, str] = None,
        name: str = None,
        network: str = None,  # Network to connect for Traefik routing
        use_traefik: bool = False  # If True, don't expose host port (Traefik handles routing)
    ) -> Dict[str, Any]:
        """
        Create and start a container
        
        Args:
            image: Docker image name
            internal_port: Port inside container
            host_port: Port on host to expose (ignored if use_traefik=True)
            command: Command to run
            environment: Environment variables
            memory_limit: Memory limit (e.g., "512m", "1g")
            cpu_limit: CPU limit (0.5 = 50% of one core)
            pids_limit: Max number of processes
            labels: Labels for the container
            name: Container name (optional)
            network: Docker network to connect (for Traefik routing)
            use_traefik: If True, use Traefik for routing instead of host port
        
        Returns:
            {
                'container_id': str,
                'status': str,
                'port': int
            }
        """
        if not self.is_connected():
            raise Exception("Docker is not connected")
        
        try:
            # CPU quota calculation
            cpu_period = 100000  # Docker default
            cpu_quota = int(cpu_limit * cpu_period)
            
            # Labels for management
            container_labels = labels or {}
            container_labels.update({
                'ctfd.managed': 'true',
                'ctfd.plugin': 'containers'
            })
            
            # Port mapping - only if not using Traefik
            ports = None if use_traefik else {f'{internal_port}/tcp': host_port}
            
            # Network mode
            network_mode = None
            if use_traefik and network:
                # Will connect to network after creation
                network_mode = None
            else:
                network_mode = 'bridge'
            
            # Create container
            container = self.client.containers.run(
                image=image,
                name=name,
                command=command,
                detach=True,
                auto_remove=True,  # Auto remove when container stops/fails
                ports=ports,
                environment=environment or {},
                mem_limit=memory_limit,
                cpu_quota=cpu_quota,
                cpu_period=cpu_period,
                pids_limit=pids_limit,
                labels=container_labels,
                network_mode=network_mode,
                # Security options
                cap_drop=['ALL'],  # Drop all capabilities
                cap_add=['CHOWN', 'SETUID', 'SETGID'],  # Add back minimal caps
                security_opt=['no-new-privileges'],
            )
            
            # Connect to custom network if specified (for Traefik)
            if network:
                try:
                    docker_network = self.client.networks.get(network)
                    docker_network.connect(container)
                    logger.info(f"Connected container {container.id[:12]} to network {network}")
                except Exception as e:
                    logger.warning(f"Failed to connect to network {network}: {e}")
            
            logger.info(f"Created container {container.id[:12]} from image {image}")
            
            return {
                'container_id': container.id,
                'status': container.status,
                'port': host_port
            }
            
        except docker.errors.ImageNotFound:
            logger.error(f"Docker image not found: {image}")
            raise Exception(f"Docker image '{image}' not found")
        except docker.errors.APIError as e:
            logger.error(f"Docker API error: {e}")
            raise Exception(f"Failed to create container: {e}")
        except Exception as e:
            logger.error(f"Unexpected error creating container: {e}")
            raise
    
    def stop_container(self, container_id: str) -> bool:
        """
        Stop and remove a container
        
        Args:
            container_id: Container ID
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning("Docker not connected, cannot stop container")
            return False
        
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove()
            logger.info(f"Stopped and removed container {container_id[:12]}")
            return True
        except docker.errors.NotFound:
            logger.info(f"Container {container_id[:12]} not found (already removed)")
            return True
        except Exception as e:
            logger.error(f"Error stopping container {container_id[:12]}: {e}")
            return False
    
    def get_container_status(self, container_id: str) -> Optional[str]:
        """
        Get container status
        
        Returns:
            Status string ('running', 'exited', etc.) or None if not found
        """
        if not self.is_connected():
            return None
        
        try:
            container = self.client.containers.get(container_id)
            return container.status
        except docker.errors.NotFound:
            return None
        except Exception as e:
            logger.error(f"Error getting container status: {e}")
            return None
    
    def is_container_running(self, container_id: str) -> bool:
        """Check if container is running"""
        status = self.get_container_status(container_id)
        return status == 'running'
    
    def list_managed_containers(self):
        """
        List all containers managed by this plugin
        
        Returns:
            List of container objects
        """
        if not self.is_connected():
            return []
        
        try:
            return self.client.containers.list(
                all=True,
                filters={'label': 'ctfd.managed=true'}
            )
        except Exception as e:
            logger.error(f"Error listing containers: {e}")
            return []
    
    def list_images(self):
        """
        List all available Docker images
        
        Returns:
            List of image objects
        """
        if not self.is_connected():
            raise Exception("Docker is not connected")
        
        try:
            images = self.client.images.list()
            return images
        except Exception as e:
            logger.error(f"Failed to list images: {e}")
            raise Exception(f"Failed to list Docker images: {e}")
    
    def get_container_logs(self, container_id: str, tail: int = 100) -> Optional[str]:
        """
        Get container logs
        
        Args:
            container_id: Container ID
            tail: Number of lines to return
        
        Returns:
            Logs as string or None
        """
        if not self.is_connected():
            return None
        
        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail).decode('utf-8', errors='ignore')
            return logs
        except Exception as e:
            logger.error(f"Error getting container logs: {e}")
            return None
    
    def cleanup_expired_containers(self, instance_uuids: list):
        """
        Cleanup containers không còn trong database
        
        Args:
            instance_uuids: List of valid instance UUIDs from database
        """
        if not self.is_connected():
            return
        
        try:
            containers = self.list_managed_containers()
            for container in containers:
                instance_uuid = container.labels.get('ctfd.instance_uuid')
                if instance_uuid and instance_uuid not in instance_uuids:
                    logger.info(f"Cleaning up orphaned container {container.id[:12]}")
                    try:
                        container.stop(timeout=5)
                        container.remove()
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

"""
Docker Service - Manage Docker containers
"""
import logging
from typing import Optional, Dict, Any, List

import docker

logger = logging.getLogger(__name__)


class DockerService:
    """
    Service to interact with Docker daemon
    """

    #: Default timeout (seconds) for control-plane calls (ping, list, inspect)
    CONTROL_TIMEOUT = 15
    #: Timeout (seconds) for long running calls such as image pulls
    PULL_TIMEOUT = 600

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
                self.client = docker.DockerClient(base_url=self.base_url, timeout=self.CONTROL_TIMEOUT)

            self.client.ping()
            logger.info(f"Connected to Docker daemon at {self.base_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Docker: {e}")
            logger.warning("Docker connection will be retried when needed. Configure in plugin settings.")
            self.client = None

    def reconnect(self, base_url: Optional[str] = None):
        """Reconnect (used after an admin changes the connection settings)."""
        if base_url:
            self.base_url = base_url
        self.client = None
        self._connect()
        return self.is_connected()

    def is_connected(self) -> bool:
        """Check if Docker is connected"""
        if not self.client:
            return False
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    def image_exists(self, image: str) -> bool:
        """Return True when the image reference is present locally."""
        if not self.is_connected():
            raise Exception("Docker is not connected")
        try:
            self.client.images.get(image)
            return True
        except docker.errors.ImageNotFound:
            return False
        except docker.errors.NotFound:
            return False
        except Exception as e:
            logger.warning(f"Could not check for image {image}: {e}")
            return False

    def pull_image(self, image: str):
        """
        Pull an image if it is not available locally.

        Calling ``containers.run`` with a missing image makes the daemon pull it
        implicitly while the HTTP request is still open, which is what used to
        make "Fetch Instance" hang for minutes. Pulling explicitly lets us use a
        long dedicated timeout and produce a useful error message instead.
        """
        if not self.is_connected():
            raise Exception("Docker is not connected")

        if self.image_exists(image):
            return False

        logger.info(f"Image {image} missing locally, pulling (this can take a while)")
        try:
            self.client.images.pull(image)
            logger.info(f"Pulled image {image}")
            return True
        except docker.errors.NotFound:
            raise Exception(f"Docker image '{image}' not found in any registry")
        except docker.errors.APIError as e:
            raise Exception(f"Failed to pull image '{image}': {e}")

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------
    def create_container(
        self,
        image: str,
        internal_port: int = None,
        host_port: int = None,
        ports: Dict[str, int] = None,  # New: {'80': 30001, '22': 30002}
        command: str = None,
        environment: Dict[str, str] = None,
        memory_limit: str = "512m",
        cpu_limit: float = 0.5,
        pids_limit: int = 100,
        labels: Dict[str, str] = None,
        name: str = None,
        network: str = None,  # Network to connect for Traefik routing
        use_traefik: bool = False,  # If True, don't expose host port (Traefik handles routing)
        bind_ip: str = None,  # Host IP to publish ports on (None => 0.0.0.0)
        host_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Create and start a container

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
            cpu_quota = int(float(cpu_limit) * cpu_period)

            # Labels for management
            container_labels = dict(labels or {})
            container_labels.update({
                'ctfd.managed': 'true',
                'ctfd.plugin': 'containers'
            })

            # Port mapping - only if not using Traefik
            ports_config = None
            if not use_traefik:
                if ports:
                    # New multi-port mode: ports = {'80': 30001, '22': 30002}
                    ports_config = {}
                    for internal, external in ports.items():
                        # Optionally bind to a specific interface instead of 0.0.0.0
                        if bind_ip:
                            ports_config[f'{internal}/tcp'] = (bind_ip, int(external))
                        else:
                            ports_config[f'{internal}/tcp'] = int(external)
                else:
                    # Legacy single port mode
                    internal_port = internal_port or 0
                    if bind_ip:
                        ports_config = {f'{internal_port}/tcp': (bind_ip, int(host_port))}
                    else:
                        ports_config = {f'{internal_port}/tcp': int(host_port)}

            # Network configuration
            network_arg = network if network else 'bridge'

            extra_host_config = dict(host_config or {})

            container = self.client.containers.run(
                image=image,
                name=name,
                command=command,
                detach=True,
                auto_remove=True,  # Auto remove when container stops/fails
                ports=ports_config,
                environment=environment or {},
                mem_limit=memory_limit,
                cpu_quota=cpu_quota,
                cpu_period=cpu_period,
                pids_limit=pids_limit,
                labels=container_labels,
                network=network_arg,
                # Security options
                cap_drop=['ALL'],  # Drop all capabilities
                cap_add=['CHOWN', 'SETUID', 'SETGID'],  # Add back minimal caps
                security_opt=['no-new-privileges'],
                **extra_host_config,
            )

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

    def get_container(self, container_id: str):
        """Return a container object or None when it no longer exists."""
        if not self.is_connected() or not container_id:
            return None
        try:
            return self.client.containers.get(container_id)
        except docker.errors.NotFound:
            return None
        except Exception as e:
            logger.error(f"Error getting container {container_id[:12]}: {e}")
            return None

    def stop_container(self, container_id: str) -> bool:
        """
        Stop and remove a container

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning("Docker not connected, cannot stop container")
            return False

        if not container_id:
            return True

        try:
            container = self.client.containers.get(container_id)
        except docker.errors.NotFound:
            logger.info(f"Container {container_id[:12]} not found (already removed)")
            return True
        except Exception as e:
            logger.error(f"Error looking up container {container_id[:12]}: {e}")
            return False

        try:
            try:
                container.stop(timeout=3)
            except docker.errors.APIError as e:
                message = str(e).lower()
                if 'not running' in message or '304' in message or 'is already stopped' in message:
                    logger.info(f"Container {container_id[:12]} already stopped")
                elif 'removal of container' in message and 'already in progress' in message:
                    # auto_remove already took it away
                    logger.info(f"Container {container_id[:12]} already being removed")
                    return True
                else:
                    raise
            try:
                container.remove(force=True)
            except docker.errors.NotFound:
                pass
            except docker.errors.APIError as e:
                # The daemon removes the container itself when auto_remove=true,
                # and two concurrent stops race with each other. Both surface as
                # a 409 conflict, which is success for our purposes.
                message = str(e).lower()
                if 'already in progress' in message or 'no such container' in message:
                    logger.info(f"Container {container_id[:12]} is already being removed")
                else:
                    raise
            logger.info(f"Stopped and removed container {container_id[:12]}")
            return True
        except docker.errors.NotFound:
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
        return self.get_container_status(container_id) == 'running'

    def list_managed_containers(self) -> List[Any]:
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
            return self.client.images.list()
        except Exception as e:
            logger.error(f"Failed to list images: {e}")
            raise Exception(f"Failed to list Docker images: {e}")

    def get_container_logs(self, container_id: str, tail: int = 100) -> Optional[str]:
        """Get container logs"""
        if not self.is_connected():
            return None

        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail).decode('utf-8', errors='ignore')
            return logs
        except Exception as e:
            logger.error(f"Error getting container logs: {e}")
            return None

    def cleanup_orphaned_containers(self, live_instance_uuids) -> int:
        """
        Remove managed containers that have no matching live instance row.

        Args:
            live_instance_uuids: iterable of instance UUIDs still tracked in the DB
        """
        if not self.is_connected():
            return 0

        live = set(live_instance_uuids or [])
        removed = 0
        try:
            for container in self.list_managed_containers():
                instance_uuid = container.labels.get('ctfd.instance_uuid')
                if instance_uuid and instance_uuid not in live:
                    logger.info(f"Cleaning up orphaned container {container.id[:12]}")
                    try:
                        container.stop(timeout=5)
                    except Exception:
                        pass
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
                    removed += 1
        except Exception as e:
            logger.error(f"Error during orphan cleanup: {e}")
        return removed

    # Backwards compatible alias
    cleanup_expired_containers = cleanup_orphaned_containers

    # ------------------------------------------------------------------
    # Networks
    # ------------------------------------------------------------------
    def create_network(self, name: str, internal: bool = False, driver: str = 'bridge',
                       options: Dict[str, str] = None) -> bool:
        """
        Create a Docker network

        Returns:
            True if created or already exists, False on error
        """
        if not self.is_connected():
            return False

        try:
            try:
                self.client.networks.get(name)
                return True
            except docker.errors.NotFound:
                pass

            self.client.networks.create(
                name=name,
                driver=driver,
                internal=internal,
                options=options,
                check_duplicate=True,
                labels={'ctfd.managed': 'true'}
            )
            logger.info(f"Created network {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create network {name}: {e}")
            return False

    def remove_network(self, name: str) -> bool:
        """Remove a Docker network"""
        if not self.is_connected():
            return False

        try:
            network = self.client.networks.get(name)
            network.remove()
            logger.info(f"Removed network {name}")
            return True
        except docker.errors.NotFound:
            return True
        except Exception as e:
            # Often fails if network is in use, which is expected during race conditions
            logger.warning(f"Failed to remove network {name} (might be in use): {e}")
            return False

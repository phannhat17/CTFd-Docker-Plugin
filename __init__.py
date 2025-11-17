"""
CTFd Docker Plugin - Multi-Port Support Implementation

This module provides multi-port container support for CTFd challenges.
It extends the base Docker plugin to handle multiple port mappings and
connection types (http, https, tcp, ssh).

Author: Loot The Crab Team
Version: 2.0.0
"""

import docker
from flask import Blueprint
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.models import db, Challenges, Solves, Fails, Flags, Tags, Hints


class DockerChallengeType(BaseChallenge):
    """
    Docker challenge type with multi-port support
    """
    id = "docker"
    name = "docker"
    templates = {
        "create": "/plugins/docker_plugin/assets/create.html",
        "update": "/plugins/docker_plugin/assets/update.html",
        "view": "/plugins/docker_plugin/assets/view.html",
    }
    scripts = {
        "create": "/plugins/docker_plugin/assets/create.js",
        "update": "/plugins/docker_plugin/assets/update.js",
        "view": "/plugins/docker_plugin/assets/view.js",
    }


class DockerContainerManager:
    """Manages Docker containers for challenges with multi-port support"""

    def __init__(self):
        self.client = docker.from_env()

    def parse_port_config(self, challenge_data):
        """
        Parse port configuration from challenge data.
        Supports both old single-port format and new multi-port format.

        Args:
            challenge_data: Dictionary containing challenge configuration

        Returns:
            List of port configurations
        """
        ports = []

        # Check for new multi-port format
        if 'ports' in challenge_data and challenge_data['ports']:
            # New format - array of port configs
            ports = challenge_data['ports']

        # Check for old single-port format (backward compatibility)
        elif 'port' in challenge_data and 'protocol' in challenge_data:
            # Convert old format to new format
            ports = [{
                'port': int(challenge_data.get('port', 80)),
                'protocol': challenge_data.get('protocol', 'tcp'),
                'name': challenge_data.get('protocol', 'tcp').upper(),
                'connection_info': challenge_data.get('connection_info', ''),
                'primary': True
            }]

        return ports

    def create_port_bindings(self, port_configs):
        """
        Create Docker port bindings from port configurations.

        Args:
            port_configs: List of port configuration dictionaries

        Returns:
            Tuple of (exposed_ports, port_bindings) for Docker API
        """
        exposed_ports = {}
        port_bindings = {}

        for port_config in port_configs:
            internal_port = port_config['port']
            port_key = f"{internal_port}/tcp"

            # Expose the port
            exposed_ports[port_key] = {}

            # Let Docker assign random external port
            port_bindings[port_key] = None

        return exposed_ports, port_bindings

    def create_container(self, challenge_id, user_id, challenge_data):
        """
        Create a Docker container for a challenge with multi-port support.

        Args:
            challenge_id: ID of the challenge
            user_id: ID of the user
            challenge_data: Dictionary containing challenge configuration

        Returns:
            Docker container object
        """
        # Parse port configuration
        port_configs = self.parse_port_config(challenge_data)

        if not port_configs:
            raise ValueError("No port configuration found in challenge data")

        # Create port bindings
        exposed_ports, port_bindings = self.create_port_bindings(port_configs)

        # Get image name
        image_name = challenge_data.get('image', 'ubuntu:latest')

        # Container name
        container_name = f"ctfd_challenge_{challenge_id}_user_{user_id}"

        # Create and start container
        try:
            container = self.client.containers.run(
                image=image_name,
                detach=True,
                ports=port_bindings,
                name=container_name,
                remove=False,
                network_mode='bridge',
                # Add resource limits
                mem_limit='512m',
                cpu_quota=50000,
                # Store challenge metadata
                labels={
                    'ctfd.challenge_id': str(challenge_id),
                    'ctfd.user_id': str(user_id),
                    'ctfd.port_count': str(len(port_configs))
                }
            )
            return container

        except docker.errors.APIError as e:
            raise Exception(f"Failed to create container: {str(e)}")

    def get_container(self, challenge_id, user_id):
        """
        Get existing container for a user's challenge instance.

        Args:
            challenge_id: ID of the challenge
            user_id: ID of the user

        Returns:
            Docker container object or None
        """
        container_name = f"ctfd_challenge_{challenge_id}_user_{user_id}"

        try:
            container = self.client.containers.get(container_name)
            return container
        except docker.errors.NotFound:
            return None

    def stop_container(self, challenge_id, user_id):
        """
        Stop and remove a container.

        Args:
            challenge_id: ID of the challenge
            user_id: ID of the user

        Returns:
            Boolean indicating success
        """
        container = self.get_container(challenge_id, user_id)

        if container:
            try:
                container.stop(timeout=10)
                container.remove()
                return True
            except docker.errors.APIError:
                return False

        return False

    def get_connection_info(self, container, port_configs, hostname=None):
        """
        Generate connection information for all exposed ports.

        Args:
            container: Docker container object
            port_configs: List of port configurations
            hostname: Optional hostname override (defaults to localhost)

        Returns:
            List of connection information dictionaries
        """
        if hostname is None:
            hostname = 'localhost'  # Should be configured from settings

        # Reload container to get current port mappings
        container.reload()
        port_mappings = container.attrs['NetworkSettings']['Ports']

        connections = []

        for port_config in port_configs:
            internal_port = port_config['port']
            protocol = port_config.get('protocol', 'tcp')
            name = port_config.get('name', protocol.upper())
            template = port_config.get('connection_info', '')
            is_primary = port_config.get('primary', False)

            # Get external port mapping
            port_key = f"{internal_port}/tcp"

            if port_key in port_mappings and port_mappings[port_key]:
                external_port = port_mappings[port_key][0]['HostPort']

                # Replace placeholders in connection template
                connection_string = template.replace('{{HOSTNAME}}', hostname)
                connection_string = connection_string.replace('{{PORT}}', external_port)
                connection_string = connection_string.replace('{{SERVICE_NAME}}', name)

                connections.append({
                    'name': name,
                    'protocol': protocol,
                    'connection': connection_string,
                    'primary': is_primary,
                    'internal_port': internal_port,
                    'external_port': external_port
                })

        # Sort connections to put primary first
        connections.sort(key=lambda x: (not x['primary'], x['internal_port']))

        return connections


# Global container manager instance
container_manager = DockerContainerManager()


def load(app):
    """
    Plugin entry point - called when CTFd loads the plugin.

    Args:
        app: Flask application instance
    """
    # Register challenge type
    CHALLENGE_CLASSES["docker"] = DockerChallengeType

    # Register plugin assets
    register_plugin_assets_directory(
        app, base_path="/plugins/docker_plugin/assets/"
    )

    # Register blueprints for API endpoints
    docker_bp = Blueprint(
        "docker_plugin",
        __name__,
        template_folder="templates",
        static_folder="assets",
        url_prefix="/docker"
    )

    @docker_bp.route("/start/<int:challenge_id>", methods=["POST"])
    def start_container(challenge_id):
        """API endpoint to start a container"""
        from flask import jsonify, request
        from CTFd.utils.user import get_current_user

        user = get_current_user()
        if not user:
            return jsonify({"success": False, "message": "Not authenticated"}), 401

        # Get challenge data
        challenge = Challenges.query.filter_by(id=challenge_id).first()
        if not challenge:
            return jsonify({"success": False, "message": "Challenge not found"}), 404

        challenge_data = challenge.extra  # Assuming extra field contains config

        try:
            # Create container
            container = container_manager.create_container(
                challenge_id,
                user.id,
                challenge_data
            )

            # Get port configs
            port_configs = container_manager.parse_port_config(challenge_data)

            # Get connection info
            connections = container_manager.get_connection_info(
                container,
                port_configs,
                hostname=request.host.split(':')[0]
            )

            return jsonify({
                "success": True,
                "container_id": container.id[:12],
                "connections": connections
            })

        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @docker_bp.route("/stop/<int:challenge_id>", methods=["POST"])
    def stop_container_endpoint(challenge_id):
        """API endpoint to stop a container"""
        from flask import jsonify
        from CTFd.utils.user import get_current_user

        user = get_current_user()
        if not user:
            return jsonify({"success": False, "message": "Not authenticated"}), 401

        success = container_manager.stop_container(challenge_id, user.id)

        return jsonify({"success": success})

    app.register_blueprint(docker_bp)

    print(" * CTFd Docker Plugin loaded with multi-port support")

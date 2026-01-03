"""
Admin Routes - Container management for admins
"""
from flask import Blueprint, request, jsonify, render_template
from CTFd.utils.decorators import admins_only
from CTFd.models import db
from ..models.instance import ContainerInstance
from ..models.challenge import ContainerChallenge
from ..models.flag import ContainerFlagAttempt
from ..models.audit import ContainerAuditLog
from ..models.config import ContainerConfig

admin_bp = Blueprint('containers_admin', __name__, url_prefix='/admin/containers')

# Global services
docker_service = None
container_service = None
anticheat_service = None


def set_services(d_service, c_service, a_service):
    """Inject services"""
    global docker_service, container_service, anticheat_service
    docker_service = d_service
    container_service = c_service
    anticheat_service = a_service


# ============================================================================
# Admin Pages
# ============================================================================

def _get_docker_status():
    """Helper function to get Docker status for all pages"""
    connected = False
    docker_info = None
    
    try:
        if docker_service and docker_service.is_connected():
            connected = True
            client = docker_service.client
            version_info = client.version()
            system_info = client.info()
            
            docker_info = {
                'version': version_info.get('Version', 'Unknown'),
                'api_version': version_info.get('ApiVersion', 'Unknown'),
                'containers_running': system_info.get('ContainersRunning', 0),
                'containers_stopped': system_info.get('ContainersStopped', 0),
                'images': system_info.get('Images', 0),
                'cpus': system_info.get('NCPU', 0),
                'memory_total': system_info.get('MemTotal', 0)
            }
    except:
        pass
    
    return connected, docker_info


@admin_bp.route('/dashboard')
@admins_only
def dashboard():
    """Admin dashboard - overview of all containers"""
    # Fetch instances grouped by status
    running_instances = ContainerInstance.query.filter_by(status='running').order_by(ContainerInstance.created_at.desc()).all()
    provisioning_instances = ContainerInstance.query.filter_by(status='provisioning').order_by(ContainerInstance.created_at.desc()).all()
    solved_instances = ContainerInstance.query.filter_by(status='solved').order_by(ContainerInstance.created_at.desc()).limit(20).all()
    stopped_instances = ContainerInstance.query.filter_by(status='stopped').order_by(ContainerInstance.created_at.desc()).limit(20).all()
    error_instances = ContainerInstance.query.filter_by(status='error').order_by(ContainerInstance.created_at.desc()).limit(10).all()
    
    # Get stats
    running_count = len(running_instances)
    total_count = ContainerInstance.query.count()
    
    # Get Docker status
    connected, docker_info = _get_docker_status()
    
    return render_template('container_dashboard.html',
                         running_instances=running_instances,
                         provisioning_instances=provisioning_instances,
                         solved_instances=solved_instances,
                         stopped_instances=stopped_instances,
                         error_instances=error_instances,
                         running_count=running_count,
                         total_count=total_count,
                         connected=connected,
                         docker_info=docker_info,
                         active_page='dashboard')


@admin_bp.route('/settings')
@admins_only
def settings():
    """Settings page"""
    # Get all config values
    settings_data = {
        'docker_base_url': ContainerConfig.get('docker_socket', ''),
        'docker_hostname': ContainerConfig.get('connection_host', ''),
        'container_expiration': ContainerConfig.get('default_timeout', '60'),
        'max_renewals': ContainerConfig.get('max_renewals', '3'),
        'container_maxmemory': ContainerConfig.get('max_memory', '512m'),
        'container_maxcpu': ContainerConfig.get('max_cpu', '0.5'),
    }
    
    # Get Docker status
    connected, docker_info = _get_docker_status()
    error_message = None
    
    return render_template('container_settings.html', 
                         settings=settings_data,
                         connected=connected,
                         docker_info=docker_info,
                         error_message=error_message,
                         active_page='settings')


@admin_bp.route('/cheats')
@admins_only
def cheats():
    """Cheat detection logs"""
    from CTFd.models import Users, Teams
    
    # Get all cheat attempts (flag reuse) with relationships loaded
    cheat_logs = ContainerFlagAttempt.query.filter(
        ContainerFlagAttempt.is_cheating == True
    ).order_by(ContainerFlagAttempt.timestamp.desc()).all()
    
    # Load owner info (user or team) for each log
    for log in cheat_logs:
        # Get submitter info
        submitter_user = Users.query.filter_by(id=log.user_id).first()
        if submitter_user:
            log.submitter_team = Teams.query.filter_by(id=submitter_user.team_id).first() if submitter_user.team_id else None
            log.submitter_user_obj = submitter_user
        
        # Get flag owner info
        if log.flag_owner_account_id:
            # Try to find owner (could be user or team)
            owner_user = Users.query.filter_by(id=log.flag_owner_account_id).first()
            if owner_user:
                log.owner_team = Teams.query.filter_by(id=owner_user.team_id).first() if owner_user.team_id else None
                log.owner_user_obj = owner_user
            else:
                # Might be team account
                owner_team = Teams.query.filter_by(id=log.flag_owner_account_id).first()
                if owner_team:
                    log.owner_team = owner_team
                    log.owner_user_obj = None
    
    # Get Docker status
    connected, docker_info = _get_docker_status()
    
    return render_template('container_cheat.html', 
                         cheat_logs=cheat_logs, 
                         connected=connected, 
                         docker_info=docker_info,
                         active_page='cheats')


# ============================================================================
# Admin APIs
# ============================================================================

@admin_bp.route('/api/instances', methods=['GET'], endpoint='api_instances')
@admins_only
def api_instances():
    """
    List all container instances
    
    Query params:
        status: Filter by status
        challenge_id: Filter by challenge
        account_id: Filter by account
        limit: Limit results (default 100)
    """
    try:
        query = ContainerInstance.query
        
        # Filters
        if request.args.get('status'):
            query = query.filter_by(status=request.args.get('status'))
        if request.args.get('challenge_id'):
            query = query.filter_by(challenge_id=request.args.get('challenge_id'))
        if request.args.get('account_id'):
            query = query.filter_by(account_id=request.args.get('account_id'))
        
        limit = min(int(request.args.get('limit', 100)), 500)
        
        instances = query.order_by(ContainerInstance.created_at.desc()).limit(limit).all()
        
        # Serialize
        result = []
        for instance in instances:
            challenge = ContainerChallenge.query.get(instance.challenge_id)
            result.append({
                'id': instance.id,
                'uuid': instance.uuid,
                'challenge_id': instance.challenge_id,
                'challenge_name': challenge.name if challenge else 'Unknown',
                'account_id': instance.account_id,
                'container_id': instance.container_id,
                'port': instance.connection_port,
                'status': instance.status,
                'created_at': instance.created_at.isoformat(),
                'expires_at': instance.expires_at.isoformat(),
                'stopped_at': instance.stopped_at.isoformat() if instance.stopped_at else None,
                'renewal_count': instance.renewal_count
            })
        
        return jsonify({'instances': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/instances/<int:instance_id>', methods=['DELETE'], endpoint='api_delete_instance')
@admins_only
def delete_instance(instance_id):
    """Delete a specific instance"""
    try:
        instance = ContainerInstance.query.get(instance_id)
        if not instance:
            return jsonify({'error': 'Instance not found'}), 404
        
        # Stop container if running
        if instance.status == 'running' and instance.container_id:
            container_service.stop_instance(instance, user_id=None, reason='admin_delete')
        
        # Delete from database
        db.session.delete(instance)
        db.session.commit()
        
        return jsonify({'success': True})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/instances/<int:instance_id>/stop', methods=['POST'], endpoint='api_stop_instance')
@admins_only
def stop_instance(instance_id):
    """Stop a specific instance"""
    try:
        instance = ContainerInstance.query.get(instance_id)
        if not instance:
            return jsonify({'error': 'Instance not found'}), 404
        
        success = container_service.stop_instance(instance, user_id=None, reason='admin')
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to stop instance'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/instances/<int:instance_id>/logs', methods=['GET'], endpoint='api_instance_logs')
@admins_only
def get_instance_logs(instance_id):
    """Get container logs"""
    try:
        instance = ContainerInstance.query.get(instance_id)
        if not instance:
            return jsonify({'error': 'Instance not found'}), 404
        
        if not instance.container_id:
            return jsonify({'error': 'No container ID'}), 404
        
        logs = docker_service.get_container_logs(instance.container_id, tail=500)
        
        return jsonify({'logs': logs})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/bulk-delete', methods=['POST'], endpoint='api_bulk_delete')
@admins_only
def api_bulk_delete():
    """Bulk delete instances"""
    try:
        data = request.get_json()
        instance_ids = data.get('instance_ids', [])
        
        if not instance_ids:
            return jsonify({'error': 'No instance IDs provided'}), 400
        
        deleted_count = 0
        for instance_id in instance_ids:
            instance = ContainerInstance.query.get(instance_id)
            if instance:
                # Stop container if running
                if instance.status == 'running' and instance.container_id:
                    container_service.stop_instance(instance, user_id=None, reason='admin_bulk_delete')
                
                db.session.delete(instance)
                deleted_count += 1
        
        db.session.commit()
        
        return jsonify({'success': True, 'deleted': deleted_count})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/stats', methods=['GET'], endpoint='api_stats')
@admins_only
def get_stats():
    """Get statistics"""
    try:
        stats = {
            'total_instances': ContainerInstance.query.count(),
            'running': ContainerInstance.query.filter_by(status='running').count(),
            'stopped': ContainerInstance.query.filter_by(status='stopped').count(),
            'solved': ContainerInstance.query.filter_by(status='solved').count(),
            'error': ContainerInstance.query.filter_by(status='error').count(),
            'total_attempts': ContainerFlagAttempt.query.count(),
            'cheat_attempts': ContainerFlagAttempt.query.filter_by(is_cheating=True).count(),
            'docker_connected': docker_service.is_connected() if docker_service else False
        }
        
        return jsonify(stats)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/cheats', methods=['GET'], endpoint='api_cheats')
@admins_only
def list_cheats():
    """List cheat attempts"""
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
        
        attempts = anticheat_service.get_cheat_attempts(limit=limit)
        
        result = []
        for attempt in attempts:
            result.append({
                'id': attempt.id,
                'challenge_id': attempt.challenge_id,
                'account_id': attempt.account_id,
                'user_id': attempt.user_id,
                'flag_owner_account_id': attempt.flag_owner_account_id,
                'timestamp': attempt.timestamp.isoformat(),
                'ip_address': attempt.ip_address
            })
        
        return jsonify({'cheats': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/config', methods=['GET'], endpoint='api_config')
@admins_only
def get_config():
    """Get plugin configuration"""
    try:
        config = ContainerConfig.get_all()
        return jsonify({'config': config})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/config', methods=['POST'], endpoint='api_config_update')
@admins_only
def update_config():
    """
    Update plugin configuration
    
    Body:
        {
            "docker_socket": "unix://var/run/docker.sock",
            "connection_host": "ctf.example.com",
            "port_range_start": 30000,
            "port_range_end": 31000
        }
    """
    try:
        data = request.get_json()
        
        # Update config
        for key, value in data.items():
            ContainerConfig.set(key, str(value))
        
        # Reconnect Docker if socket changed
        if 'docker_socket' in data:
            docker_service.base_url = data['docker_socket']
            docker_service._connect()
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/cleanup/expired', methods=['POST'], endpoint='api_cleanup_expired')
@admins_only
def cleanup_expired():
    """Manually trigger cleanup of expired instances"""
    try:
        container_service.cleanup_expired_instances()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/cleanup/old', methods=['POST'], endpoint='api_cleanup_old')
@admins_only
def cleanup_old():
    """Manually trigger cleanup of old instances"""
    try:
        container_service.cleanup_old_instances()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/images', methods=['GET'], endpoint='api_images')
@admins_only
def list_images():
    """List available Docker images"""
    try:
        if not docker_service:
            return jsonify({'error': 'Docker service not available'}), 500
        
        images = docker_service.list_images()
        # Extract image names/tags
        image_list = []
        for img in images:
            if img.tags:
                image_list.extend(img.tags)
        
        return jsonify({'images': image_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/docker/health', methods=['GET'], endpoint='api_docker_health')
@admins_only
def docker_health_check():
    """
    Check Docker connection health
    
    Returns:
        {
            "connected": bool,
            "docker_version": str,
            "api_version": str,
            "server_info": {
                "containers": int,
                "images": int,
                "memory_total": int,
                "cpus": int
            },
            "error": str (if connection failed)
        }
    """
    try:
        if not docker_service:
            return jsonify({
                'connected': False,
                'error': 'Docker service not initialized'
            }), 500
        
        # Check connection
        is_connected = docker_service.is_connected()
        
        if not is_connected:
            return jsonify({
                'connected': False,
                'error': 'Cannot connect to Docker daemon',
                'socket': ContainerConfig.get('docker_socket', 'Not configured')
            })
        
        # Get Docker info
        try:
            client = docker_service.client
            version_info = client.version()
            system_info = client.info()
            
            return jsonify({
                'connected': True,
                'docker_version': version_info.get('Version', 'Unknown'),
                'api_version': version_info.get('ApiVersion', 'Unknown'),
                'server_info': {
                    'containers': system_info.get('Containers', 0),
                    'containers_running': system_info.get('ContainersRunning', 0),
                    'containers_paused': system_info.get('ContainersPaused', 0),
                    'containers_stopped': system_info.get('ContainersStopped', 0),
                    'images': system_info.get('Images', 0),
                    'memory_total': system_info.get('MemTotal', 0),
                    'cpus': system_info.get('NCPU', 0),
                    'server_version': system_info.get('ServerVersion', 'Unknown'),
                    'operating_system': system_info.get('OperatingSystem', 'Unknown'),
                    'architecture': system_info.get('Architecture', 'Unknown')
                },
                'socket': ContainerConfig.get('docker_socket', 'Not configured')
            })
        except Exception as info_error:
            return jsonify({
                'connected': True,
                'error': f'Connected but failed to get info: {str(info_error)}',
                'socket': ContainerConfig.get('docker_socket', 'Not configured')
            })
    
    except Exception as e:
        return jsonify({
            'connected': False,
            'error': str(e)
        }), 500

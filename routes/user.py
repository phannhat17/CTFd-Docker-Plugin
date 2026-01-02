"""
User-facing Routes - Container operations for players
"""
from flask import Blueprint, request, jsonify
from CTFd.utils.decorators import (
    authed_only,
    during_ctf_time_only,
    ratelimit,
    require_verified_emails
)
from CTFd.utils.user import get_current_user
from CTFd.utils import get_config
from CTFd.models import db
from ..models.instance import ContainerInstance
from ..models.challenge import ContainerChallenge

user_bp = Blueprint('containers_user', __name__, url_prefix='/api/v1/containers')

# Global services (will be injected by plugin init)
container_service = None
flag_service = None
anticheat_service = None


def set_services(c_service, f_service, a_service):
    """Inject services"""
    global container_service, flag_service, anticheat_service
    container_service = c_service
    flag_service = f_service
    anticheat_service = a_service


def get_account_id():
    """
    Get account ID based on CTF mode
    Returns: (account_id, is_team_mode)
    """
    user = get_current_user()
    if not user:
        raise Exception("User not authenticated")
    
    mode = get_config('user_mode')
    is_team_mode = (mode == 'teams')
    
    if is_team_mode:
        if not user.team_id:
            raise Exception("You must be on a team to access this feature")
        return user.team_id, True
    else:
        return user.id, False


@user_bp.route('/request', methods=['POST'])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method='POST', limit=10, interval=60)
def request_container():
    """
    Request a new container or get existing one
    
    Body:
        {
            "challenge_id": 123
        }
    
    Response:
        {
            "status": "created" | "existing",
            "instance_uuid": "...",
            "connection": {
                "host": "...",
                "port": 12345,
                "type": "ssh",
                "info": "..."
            },
            "expires_at": "2024-01-01T00:00:00Z"
        }
    """
    try:
        data = request.get_json()
        challenge_id = data.get('challenge_id')
        
        if not challenge_id:
            return jsonify({'error': 'challenge_id is required'}), 400
        
        user = get_current_user()
        account_id, is_team_mode = get_account_id()
        
        # Check if challenge exists
        challenge = ContainerChallenge.query.get(challenge_id)
        if not challenge:
            return jsonify({'error': 'Challenge not found'}), 404
        
        # Check if already has running instance
        existing = ContainerInstance.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id
        ).filter(
            ContainerInstance.status.in_(['running', 'provisioning'])
        ).first()
        
        if existing and not existing.is_expired():
            # Return existing instance
            return jsonify({
                'status': 'existing',
                'instance_uuid': existing.uuid,
                'connection': {
                    'host': existing.connection_host,
                    'port': existing.connection_port,
                    'type': existing.connection_info.get('type') if existing.connection_info else 'ssh',
                    'info': existing.connection_info.get('info') if existing.connection_info else ''
                },
                'expires_at': existing.expires_at.isoformat(),
                'renewal_count': existing.renewal_count,
                'max_renewals': challenge.max_renewals
            })
        
        # Create new instance
        instance = container_service.create_instance(
            challenge_id=challenge_id,
            account_id=account_id,
            user_id=user.id
        )
        
        return jsonify({
            'status': 'created',
            'instance_uuid': instance.uuid,
            'connection': {
                'host': instance.connection_host,
                'port': instance.connection_port,
                'type': instance.connection_info.get('type') if instance.connection_info else 'ssh',
                'info': instance.connection_info.get('info') if instance.connection_info else ''
            },
            'expires_at': instance.expires_at.isoformat(),
            'renewal_count': instance.renewal_count,
            'max_renewals': challenge.max_renewals
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@user_bp.route('/info/<int:challenge_id>', methods=['GET'])
@authed_only
@during_ctf_time_only
@require_verified_emails
def get_container_info(challenge_id):
    """
    Get info about running container for a challenge
    
    Response:
        {
            "status": "running" | "not_found",
            "connection": {...},
            "expires_at": "..."
        }
    """
    try:
        account_id, _ = get_account_id()
        
        instance = ContainerInstance.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id
        ).filter(
            ContainerInstance.status.in_(['running', 'provisioning'])
        ).first()
        
        if not instance or instance.is_expired():
            return jsonify({'status': 'not_found'})
        
        # Update last accessed
        instance.last_accessed_at = db.func.now()
        db.session.commit()
        
        return jsonify({
            'status': instance.status,
            'instance_uuid': instance.uuid,
            'connection': {
                'host': instance.connection_host,
                'port': instance.connection_port,
                'type': instance.connection_info.get('type') if instance.connection_info else 'ssh',
                'info': instance.connection_info.get('info') if instance.connection_info else ''
            },
            'expires_at': instance.expires_at.isoformat(),
            'renewal_count': instance.renewal_count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@user_bp.route('/renew', methods=['POST'])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method='POST', limit=10, interval=60)
def renew_container():
    """
    Renew (extend) container expiration
    
    Body:
        {
            "challenge_id": 123
        }
    
    Response:
        {
            "success": true,
            "expires_at": "...",
            "renewal_count": 2
        }
    """
    try:
        data = request.get_json()
        challenge_id = data.get('challenge_id')
        
        if not challenge_id:
            return jsonify({'error': 'challenge_id is required'}), 400
        
        user = get_current_user()
        account_id, _ = get_account_id()
        
        instance = ContainerInstance.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id,
            status='running'
        ).first()
        
        if not instance:
            return jsonify({'error': 'No running container found'}), 404
        
        instance = container_service.renew_instance(instance, user.id)
        
        return jsonify({
            'success': True,
            'expires_at': instance.expires_at.isoformat(),
            'renewal_count': instance.renewal_count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@user_bp.route('/stop', methods=['POST'])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method='POST', limit=10, interval=60)
def stop_container():
    """
    Stop running container
    
    Body:
        {
            "challenge_id": 123
        }
    
    Response:
        {
            "success": true
        }
    """
    try:
        data = request.get_json()
        challenge_id = data.get('challenge_id')
        
        if not challenge_id:
            return jsonify({'error': 'challenge_id is required'}), 400
        
        user = get_current_user()
        account_id, _ = get_account_id()
        
        instance = ContainerInstance.query.filter_by(
            challenge_id=challenge_id,
            account_id=account_id,
            status='running'
        ).first()
        
        if not instance:
            return jsonify({'error': 'No running container found'}), 404
        
        success = container_service.stop_instance(instance, user.id, reason='manual')
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to stop container'}), 500
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

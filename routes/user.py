"""
User-facing Routes - Container operations for players
"""
import logging

from flask import Blueprint, jsonify, request

from CTFd.models import db
from CTFd.utils import get_config
from CTFd.utils.decorators import (
    authed_only,
    during_ctf_time_only,
    ratelimit,
    require_verified_emails,
)
from CTFd.utils.user import get_current_user

from ..models.challenge import ContainerChallenge
from ..models.config import ContainerConfig
from ..models.instance import ContainerInstance

logger = logging.getLogger(__name__)

user_bp = Blueprint('containers_user', __name__, url_prefix='/api/v1/containers')

# Injected by the plugin's load()
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
    Get account ID based on CTF mode.

    Returns: (account_id, is_team_mode)
    """
    user = get_current_user()
    if not user:
        raise ValueError("User not authenticated")

    is_team_mode = get_config('user_mode') == 'teams'
    if is_team_mode:
        if not user.team_id:
            raise ValueError("You must be on a team to access this feature")
        return user.team_id, True
    return user.id, False


def _serialize_instance(instance, challenge):
    """Build the JSON payload for an instance."""
    info = instance.connection_info or {}
    return {
        'instance_uuid': instance.uuid,
        'status': instance.status,
        'connection': {
            'host': instance.connection_host,
            'port': instance.connection_port,
            'ports': instance.connection_ports,
            'type': info.get('type'),
            'info': info.get('info'),
            'urls': info.get('urls'),
        },
        'expires_at': int(instance.expires_at.timestamp() * 1000) if instance.expires_at else None,
        'renewal_count': instance.renewal_count or 0,
        'max_renewals': challenge.get_max_renewals() if challenge else 0,
        'renew_minutes': _renew_minutes(),
    }


def _renew_minutes():
    """Minutes added by one renewal, as configured by the admin."""
    try:
        return int(ContainerConfig.get('renew_extension_minutes', 5) or 5)
    except (TypeError, ValueError):
        return 5


@user_bp.route('/request', methods=['POST'])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method='POST', limit=10, interval=60)
def request_container():
    """
    Request a new container or get the existing one.

    Body: {"challenge_id": 123}
    """
    try:
        data = request.get_json(silent=True) or {}
        challenge_id = data.get('challenge_id')
        if not challenge_id:
            return jsonify({'error': 'challenge_id is required'}), 400

        try:
            challenge_id = int(challenge_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'challenge_id must be an integer'}), 400

        user = get_current_user()
        account_id, _ = get_account_id()

        challenge = ContainerChallenge.query.get(challenge_id)
        if not challenge:
            return jsonify({'error': 'Challenge not found'}), 404

        if challenge.state != 'visible':
            return jsonify({'error': 'Challenge is not available'}), 403

        existing = container_service.get_active_instance(challenge_id, account_id)
        if existing and (not existing.is_expired() or existing.status in ('pending', 'provisioning')):
            return jsonify(dict(_serialize_instance(existing, challenge), status='existing',
                                instance_status=existing.status))

        max_containers = int(ContainerConfig.get('container_max_concurrent_count', 3) or 3)
        running_count = ContainerInstance.query.filter_by(
            account_id=account_id
        ).filter(
            ContainerInstance.status.in_(['running', 'provisioning', 'pending'])
        ).count()

        if running_count >= max_containers:
            return jsonify({
                'error': f'You have reached the maximum number of concurrent containers ({max_containers})'
            }), 403

        instance = container_service.create_instance(
            challenge_id=challenge_id,
            account_id=account_id,
            user_id=user.id,
        )

        return jsonify(dict(_serialize_instance(instance, challenge), status='created'))

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:  # noqa: BLE001
        logger.error(f"Container request failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@user_bp.route('/info/<int:challenge_id>', methods=['GET'])
@authed_only
@during_ctf_time_only
@require_verified_emails
def get_container_info(challenge_id):
    """Get info about the running container for a challenge."""
    try:
        account_id, _ = get_account_id()
        challenge = ContainerChallenge.query.get(challenge_id)
        if not challenge:
            return jsonify({'error': 'Challenge not found'}), 404

        instance = container_service.get_active_instance(challenge_id, account_id)
        if not instance or instance.is_expired():
            return jsonify({'status': 'not_found'})

        payload = _serialize_instance(instance, challenge)
        # Do not write on every poll: only touch last_accessed_at when it is
        # actually stale, otherwise a 3s poll turns into a write storm.
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        if not instance.last_accessed_at or now - instance.last_accessed_at > timedelta(seconds=60):
            instance.last_accessed_at = now
            db.session.commit()

        return jsonify(payload)

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:  # noqa: BLE001
        logger.error(f"Container info failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@user_bp.route('/renew', methods=['POST'])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method='POST', limit=10, interval=60)
def renew_container():
    """Renew (extend) the container expiration."""
    try:
        data = request.get_json(silent=True) or {}
        challenge_id = data.get('challenge_id')
        if not challenge_id:
            return jsonify({'error': 'challenge_id is required'}), 400

        user = get_current_user()
        account_id, _ = get_account_id()

        instance = ContainerInstance.query.filter_by(
            challenge_id=int(challenge_id),
            account_id=account_id,
            status='running',
        ).first()

        if not instance:
            return jsonify({'error': 'No running container found'}), 404

        instance = container_service.renew_instance(instance, user.id)
        challenge = ContainerChallenge.query.get(instance.challenge_id)

        return jsonify({
            'success': True,
            'expires_at': int(instance.expires_at.timestamp() * 1000),
            'renewal_count': instance.renewal_count,
            'max_renewals': challenge.get_max_renewals() if challenge else 0,
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:  # noqa: BLE001
        logger.error(f"Container renew failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@user_bp.route('/stop', methods=['POST'])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method='POST', limit=10, interval=60)
def stop_container():
    """Stop the running container."""
    try:
        data = request.get_json(silent=True) or {}
        challenge_id = data.get('challenge_id')
        if not challenge_id:
            return jsonify({'error': 'challenge_id is required'}), 400

        user = get_current_user()
        account_id, _ = get_account_id()

        instance = ContainerInstance.query.filter_by(
            challenge_id=int(challenge_id),
            account_id=account_id,
            status='running',
        ).first()

        if not instance:
            return jsonify({'error': 'No running container found'}), 404

        if container_service.stop_instance(instance, user.id, reason='manual'):
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to stop container'}), 500

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:  # noqa: BLE001
        logger.error(f"Container stop failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

"""
Admin Routes - Container management for admins
"""
import csv
import io
import logging
import os
import re
import traceback

from flask import Blueprint, jsonify, make_response, render_template, request

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from CTFd.models import Flags, Teams, Users, db
from CTFd.utils import get_config
from CTFd.utils.decorators import admins_only

from ..models.audit import ContainerAuditLog
from ..models.challenge import ContainerChallenge
from ..models.config import ContainerConfig
from ..models.flag import ContainerFlagAttempt
from ..models.instance import ContainerInstance
from ..utils import parse_flag_pattern

logger = logging.getLogger(__name__)

admin_bp = Blueprint('containers_admin', __name__, url_prefix='/admin/containers')

# Injected by the plugin's load()
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
# Template filters
# ============================================================================
@admin_bp.app_template_filter('get_user')
def get_user_filter(user_id):
    return Users.query.filter_by(id=user_id).first()


@admin_bp.app_template_filter('get_team')
def get_team_filter(team_id):
    return Teams.query.filter_by(id=team_id).first()


# ============================================================================
# Pages
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
                'memory_total': system_info.get('MemTotal', 0),
            }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read Docker status: {e}")

    return connected, docker_info


def _active_page_context(**extra):
    connected, docker_info = _get_docker_status()
    context = {'connected': connected, 'docker_info': docker_info}
    context.update(extra)
    return context


@admin_bp.route('/app')
@admins_only
def console():
    """
    Standalone console for the containers plugin.

    Deliberately does NOT extend CTFd's admin base template: it ships its own
    full-page design so the plugin's UI is independent of the CTFd theme
    (Bootstrap is not loaded here at all). Auth is still CTFd's admin session
    and the CSRF nonce from that session.
    """
    from flask import session
    return render_template(
        'container_console.html',
        csrf_token=session.get('nonce', ''),
        user_mode=get_config('user_mode'),
    )


@admin_bp.route('/dashboard')
@admins_only
def dashboard():
    """Admin dashboard - overview of all containers"""
    q = (request.args.get("q") or "").strip()
    challenge_id = request.args.get("challenge_id", type=int)

    status_filter = request.args.get("status")
    if status_filter is None:
        status_filter = 'running'
    else:
        status_filter = status_filter.strip()

    page = max(1, abs(request.args.get("page", 1, type=int) or 1))

    query = ContainerInstance.query

    if challenge_id:
        query = query.filter(ContainerInstance.challenge_id == challenge_id)
    if status_filter:
        query = query.filter(ContainerInstance.status == status_filter)

    is_teams_mode = get_config('user_mode') == 'teams'

    if q:
        # Account-name search: joining on the account table is what makes the
        # search usable, but only do it when a query was actually typed.
        if is_teams_mode:
            query = query.join(Teams, Teams.id == ContainerInstance.account_id)
        else:
            query = query.join(Users, Users.id == ContainerInstance.account_id)
        query = query.filter(
            or_(
                ContainerInstance.container_id.ilike(f"%{q}%"),
                (Teams.name if is_teams_mode else Users.name).ilike(f"%{q}%"),
            )
        )

    # Eager-load the challenge to avoid an N+1 query per rendered row
    instances = query.options(
        joinedload(ContainerInstance.challenge)
    ).order_by(ContainerInstance.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    all_challenges = ContainerChallenge.query.order_by(ContainerChallenge.name.asc()).all()

    stats = _instance_stats()

    return render_template(
        'container_dashboard.html',
        **_active_page_context(
            instances=instances,
            all_challenges=all_challenges,
            running_count=stats['running'],
            total_count=stats['total'],
            is_teams_mode=is_teams_mode,
            active_page='dashboard',
            filters={'q': q, 'challenge_id': challenge_id, 'status': status_filter},
        )
    )


def _instance_stats():
    """Single grouped query instead of one COUNT per status."""
    try:
        rows = db.session.query(
            ContainerInstance.status, db.func.count(ContainerInstance.id)
        ).group_by(ContainerInstance.status).all()
        counts = {status: count for status, count in rows}
    except Exception as e:  # noqa: BLE001
        logger.error(f"Could not compute instance stats: {e}")
        counts = {}

    counts.setdefault('total', sum(counts.values()))
    # Every status the dashboard/settings/stats read must exist
    for status in ('running', 'provisioning', 'pending', 'stopping', 'stopped', 'solved', 'error'):
        counts.setdefault(status, 0)
    return counts


@admin_bp.route('/settings')
@admins_only
def settings():
    """Settings page"""
    settings_data = {
        'docker_type': ContainerConfig.get('docker_type', 'local'),
        'ssh_hostname': ContainerConfig.get('ssh_hostname', ''),
        'ssh_port': ContainerConfig.get('ssh_port', '22'),
        'ssh_user': ContainerConfig.get('ssh_user', 'root'),
        'ssh_key_content': ContainerConfig.get('ssh_key_content', ''),
        'ssh_known_hosts': ContainerConfig.get('ssh_known_hosts', ''),
        'docker_base_url': ContainerConfig.get('docker_socket', ''),
        'docker_hostname': ContainerConfig.get('connection_host', ''),
        'port_bind_ip': ContainerConfig.get('port_bind_ip', ''),
        'container_expiration': ContainerConfig.get('default_timeout', '60'),
        'max_renewals': ContainerConfig.get('max_renewals', '3'),
        'renew_extension_minutes': ContainerConfig.get('renew_extension_minutes', '5'),
        'container_maxmemory': ContainerConfig.get('max_memory', '512m'),
        'container_maxcpu': ContainerConfig.get('max_cpu', '0.5'),
        'port_range_start': ContainerConfig.get('port_range_start', '30000'),
        'port_range_end': ContainerConfig.get('port_range_end', '31000'),
        'subdomain_enabled': ContainerConfig.get('subdomain_enabled', 'false'),
        'subdomain_base_domain': ContainerConfig.get('subdomain_base_domain', ''),
        'subdomain_network': ContainerConfig.get('subdomain_network', 'ctfd-challenges'),
        'subdomain_entrypoint': ContainerConfig.get('subdomain_entrypoint', 'web'),
        'subdomain_tls': ContainerConfig.get('subdomain_tls', 'false'),
        'isolated_network': ContainerConfig.get('isolated_network', 'ctfd-isolated'),
        'container_max_concurrent_count': ContainerConfig.get('container_max_concurrent_count', '3'),
        'container_discord_webhook_url': ContainerConfig.get('container_discord_webhook_url', ''),
        'anticheat_autoban_threshold': ContainerConfig.get('anticheat_autoban_threshold', '0'),
        'anticheat_log_all_attempts': ContainerConfig.get('anticheat_log_all_attempts', 'true'),
        'audit_retention_days': ContainerConfig.get('audit_retention_days', '7'),
    }

    return render_template(
        'container_settings.html',
        **_active_page_context(settings=settings_data, error_message=None, active_page='settings')
    )


@admin_bp.route('/cheats')
@admins_only
def cheats():
    """Cheat detection logs"""
    cheat_logs = ContainerFlagAttempt.query.filter(
        ContainerFlagAttempt.is_cheating == True  # noqa: E712
    ).order_by(ContainerFlagAttempt.timestamp.desc()).limit(500).all()

    # Resolve the accounts in bulk instead of 2 queries per row
    user_ids = {log.user_id for log in cheat_logs if log.user_id}
    owner_ids = {log.flag_owner_account_id for log in cheat_logs if log.flag_owner_account_id}
    is_teams_mode = get_config('user_mode') == 'teams'

    users = {u.id: u for u in Users.query.filter(Users.id.in_(user_ids)).all()} if user_ids else {}
    teams = {t.id: t for t in Teams.query.filter(Teams.id.in_(owner_ids)).all()} if owner_ids else {}

    for log in cheat_logs:
        log.submitter_user_obj = users.get(log.user_id)
        log.submitter_team = teams.get(log.submitter_user_obj.team_id) if (
            log.submitter_user_obj and log.submitter_user_obj.team_id
        ) else None

        if log.flag_owner_account_id:
            if is_teams_mode:
                log.owner_team = teams.get(log.flag_owner_account_id)
                log.owner_user_obj = None
            else:
                owner_user = users.get(log.flag_owner_account_id)
                if owner_user is None:
                    owner_user = Users.query.filter_by(id=log.flag_owner_account_id).first()
                    if owner_user:
                        users[owner_user.id] = owner_user
                log.owner_user_obj = owner_user
                log.owner_team = teams.get(owner_user.team_id) if (
                    owner_user and owner_user.team_id
                ) else None

    return render_template(
        'container_cheat.html',
        **_active_page_context(cheat_logs=cheat_logs, active_page='cheats')
    )


# ============================================================================
# Instance APIs
# ============================================================================
@admin_bp.route('/api/instances', methods=['GET'], endpoint='api_instances')
@admins_only
def api_instances():
    """List container instances"""
    try:
        query = ContainerInstance.query

        if request.args.get('status'):
            query = query.filter(ContainerInstance.status == request.args.get('status'))
        if request.args.get('challenge_id'):
            query = query.filter(ContainerInstance.challenge_id == request.args.get('challenge_id'))
        if request.args.get('account_id'):
            query = query.filter(ContainerInstance.account_id == request.args.get('account_id'))

        limit = min(int(request.args.get('limit', 100)), 500)

        instances = query.options(
            joinedload(ContainerInstance.challenge)
        ).order_by(ContainerInstance.created_at.desc()).limit(limit).all()

        return jsonify({'instances': [
            {
                'id': i.id,
                'uuid': i.uuid,
                'challenge_id': i.challenge_id,
                'challenge_name': i.challenge.name if i.challenge else 'Unknown',
                'account_id': i.account_id,
                'container_id': i.container_id,
                'port': i.connection_port,
                'status': i.status,
                'created_at': i.created_at.isoformat() if i.created_at else None,
                'expires_at': i.expires_at.isoformat() if i.expires_at else None,
                'stopped_at': i.stopped_at.isoformat() if i.stopped_at else None,
                'renewal_count': i.renewal_count,
            }
            for i in instances
        ]})

    except Exception as e:  # noqa: BLE001
        logger.error(f"api_instances failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def _delete_instance_row(instance):
    """Remove an instance row (and dependent rows) safely."""
    from ..models.flag import ContainerFlag
    ContainerFlag.query.filter_by(instance_id=instance.id).delete(synchronize_session=False)
    ContainerAuditLog.query.filter_by(instance_id=instance.id).delete(synchronize_session=False)
    db.session.delete(instance)


@admin_bp.route('/api/instances/<int:instance_id>', methods=['DELETE'], endpoint='api_delete_instance')
@admins_only
def delete_instance(instance_id):
    """Delete a specific instance"""
    try:
        instance = ContainerInstance.query.get(instance_id)
        if not instance:
            return jsonify({'error': 'Instance not found'}), 404

        if instance.status in ('running', 'provisioning', 'pending') and container_service:
            container_service.stop_instance(instance, user_id=None, reason='admin_delete')

        _delete_instance_row(instance)
        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        logger.error(f"delete_instance failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/instances/<int:instance_id>/stop', methods=['POST'], endpoint='api_stop_instance')
@admins_only
def stop_instance(instance_id):
    """Stop a specific instance"""
    try:
        instance = ContainerInstance.query.get(instance_id)
        if not instance:
            return jsonify({'error': 'Instance not found'}), 404

        if container_service.stop_instance(instance, user_id=None, reason='admin'):
            return jsonify({'success': True})
        return jsonify({'error': f'Cannot stop an instance in status {instance.status}'}), 409

    except Exception as e:  # noqa: BLE001
        logger.error(f"stop_instance failed: {e}", exc_info=True)
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
        if not docker_service:
            return jsonify({'error': 'Docker service not available'}), 500

        return jsonify({'logs': docker_service.get_container_logs(instance.container_id, tail=500)})

    except Exception as e:  # noqa: BLE001
        logger.error(f"get_instance_logs failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/bulk-delete', methods=['POST'], endpoint='api_bulk_delete')
@admins_only
def api_bulk_delete():
    """Bulk delete instances"""
    try:
        data = request.get_json(silent=True) or {}
        instance_ids = data.get('instance_ids', [])
        if not instance_ids:
            return jsonify({'error': 'No instance IDs provided'}), 400

        deleted_count = 0
        for instance_id in instance_ids:
            try:
                instance = ContainerInstance.query.get(int(instance_id))
            except (TypeError, ValueError):
                continue
            if not instance:
                continue
            if instance.status in ('running', 'provisioning', 'pending') and container_service:
                container_service.stop_instance(instance, user_id=None, reason='admin_bulk_delete')
            _delete_instance_row(instance)
            deleted_count += 1

        db.session.commit()
        return jsonify({'success': True, 'deleted': deleted_count})

    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        logger.error(f"bulk delete failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/bulk/emergency-stop', methods=['POST'], endpoint='api_emergency_stop')
@admins_only
def api_emergency_stop():
    """STOP ALL running containers immediately"""
    try:
        running = ContainerInstance.query.filter(
            ContainerInstance.status.in_(['running', 'provisioning', 'pending'])
        ).all()

        stopped = 0
        failed = 0
        for instance in running:
            try:
                if container_service.stop_instance(instance, user_id=None, reason='emergency_stop'):
                    stopped += 1
                else:
                    failed += 1
            except Exception as e:  # noqa: BLE001
                logger.error(f"Emergency stop failed for {instance.uuid}: {e}")
                failed += 1
                db.session.rollback()

        return jsonify({'success': True, 'stopped': stopped, 'failed': failed})
    except Exception as e:  # noqa: BLE001
        logger.error(f"emergency stop failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/bulk/cleanup-solved', methods=['POST'], endpoint='api_cleanup_solved')
@admins_only
def api_cleanup_solved():
    """Delete all instances with status 'solved'"""
    try:
        solved = ContainerInstance.query.filter_by(status='solved').all()
        deleted = 0
        for instance in solved:
            _delete_instance_row(instance)
            deleted += 1
        db.session.commit()
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        logger.error(f"cleanup solved failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/stats', methods=['GET'], endpoint='api_stats')
@admins_only
def get_stats():
    """Get statistics"""
    try:
        stats = dict(_instance_stats())
        stats['total_instances'] = stats.pop('total', 0)
        stats['total_attempts'] = ContainerFlagAttempt.query.count()
        stats['cheat_attempts'] = ContainerFlagAttempt.query.filter_by(is_cheating=True).count()
        stats['docker_connected'] = bool(docker_service and docker_service.is_connected())
        if container_service:
            stats['available_ports'] = container_service.port_manager.get_available_count()
        return jsonify(stats)
    except Exception as e:  # noqa: BLE001
        logger.error(f"stats failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/cheats', methods=['GET'], endpoint='api_cheats')
@admins_only
def list_cheats():
    """List cheat attempts"""
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
        attempts = anticheat_service.get_cheat_attempts(limit=limit) if anticheat_service else []
        return jsonify({'cheats': [
            {
                'id': a.id,
                'challenge_id': a.challenge_id,
                'account_id': a.account_id,
                'user_id': a.user_id,
                'flag_owner_account_id': a.flag_owner_account_id,
                'timestamp': a.timestamp.isoformat() if a.timestamp else None,
                'ip_address': a.ip_address,
            }
            for a in attempts
        ]})
    except Exception as e:  # noqa: BLE001
        logger.error(f"list_cheats failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/cheats/page', methods=['GET'], endpoint='api_cheats_page')
@admins_only
def list_cheats_page():
    """
    Paginated flag-reuse detections for the admin UI, with account names
    resolved in bulk (the old page did 2 queries per row).
    """
    try:
        page = max(1, abs(request.args.get('page', 1, type=int) or 1))
        per_page = min(max(5, abs(request.args.get('per_page', 25, type=int) or 25)), 100)

        challenge_id = request.args.get('challenge_id', type=int)
        query = ContainerFlagAttempt.query.filter(
            ContainerFlagAttempt.is_cheating == True  # noqa: E712
        )
        if challenge_id:
            query = query.filter(ContainerFlagAttempt.challenge_id == challenge_id)

        pagination = query.order_by(
            ContainerFlagAttempt.timestamp.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        rows = pagination.items
        submitter_ids = {r.user_id for r in rows if r.user_id}
        owner_ids = {r.flag_owner_account_id for r in rows if r.flag_owner_account_id}

        is_teams_mode = get_config('user_mode') == 'teams'
        users = {u.id: u for u in Users.query.filter(Users.id.in_(submitter_ids)).all()} if submitter_ids else {}
        teams = {t.id: t for t in Teams.query.filter(Teams.id.in_(owner_ids)).all()} if owner_ids else {}

        challenges = {
            c.id: c.name for c in ContainerChallenge.query.filter(
                ContainerChallenge.id.in_({r.challenge_id for r in rows})
            ).all()
        } if rows else {}

        def account_label(account_id):
            if not account_id:
                return None
            if is_teams_mode:
                team = teams.get(account_id) or Teams.query.get(account_id)
                return team.name if team else f"Team #{account_id}"
            user = users.get(account_id) or Users.query.get(account_id)
            return user.name if user else f"User #{account_id}"

        return jsonify({
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': per_page,
            'is_teams_mode': is_teams_mode,
            'cheats': [
                {
                    'id': r.id,
                    'timestamp': r.timestamp.isoformat() if r.timestamp else None,
                    'challenge_id': r.challenge_id,
                    'challenge_name': challenges.get(r.challenge_id, f"#{r.challenge_id}"),
                    'submitted_by': account_label(r.account_id),
                    'submitted_by_id': r.account_id,
                    'user_id': r.user_id,
                    'flag_owner': account_label(r.flag_owner_account_id),
                    'flag_owner_id': r.flag_owner_account_id,
                    'ip_address': r.ip_address,
                    'user_agent': r.user_agent,
                }
                for r in rows
            ],
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"list_cheats_page failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/audit', methods=['GET'], endpoint='api_audit')
@admins_only
def list_audit():
    """
    Paginated audit trail. The plugin has always written
    container_audit_logs, but there was no way to read it from the UI.
    """
    try:
        page = max(1, abs(request.args.get('page', 1, type=int) or 1))
        per_page = min(max(5, abs(request.args.get('per_page', 25, type=int) or 25)), 100)

        query = ContainerAuditLog.query

        event_type = (request.args.get('event_type') or '').strip()
        if event_type:
            query = query.filter(ContainerAuditLog.event_type == event_type)

        severity = (request.args.get('severity') or '').strip()
        if severity:
            query = query.filter(ContainerAuditLog.severity == severity)

        account_id = request.args.get('account_id', type=int)
        if account_id:
            query = query.filter(ContainerAuditLog.account_id == account_id)

        search = (request.args.get('q') or '').strip()
        if search:
            query = query.filter(
                or_(
                    ContainerAuditLog.event_type.ilike(f"%{search}%"),
                    ContainerAuditLog.ip_address.ilike(f"%{search}%"),
                )
            )

        pagination = query.order_by(
            ContainerAuditLog.timestamp.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': per_page,
            'event_types': [
                row[0] for row in
                db.session.query(ContainerAuditLog.event_type)
                .distinct().order_by(ContainerAuditLog.event_type).all()
            ],
            'entries': [
                {
                    'id': e.id,
                    'timestamp': e.timestamp.isoformat() if e.timestamp else None,
                    'event_type': e.event_type,
                    'severity': e.severity or 'info',
                    'challenge_id': e.challenge_id,
                    'account_id': e.account_id,
                    'user_id': e.user_id,
                    'instance_id': e.instance_id,
                    'ip_address': e.ip_address,
                    'details': e.details,
                }
                for e in pagination.items
            ],
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"list_audit failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500



# ============================================================================
# Configuration API
# ============================================================================
#: Keys an admin may change through the settings form. Everything else is
#: rejected, so a crafted request cannot inject arbitrary configuration
#: (or turn the SSH key handling into a file-write primitive).
ALLOWED_CONFIG_KEYS = {
    'docker_type', 'docker_socket', 'connection_host', 'port_bind_ip',
    'port_range_start', 'port_range_end',
    'default_timeout', 'max_renewals', 'renew_extension_minutes',
    'max_memory', 'max_cpu', 'container_max_concurrent_count',
    'subdomain_enabled', 'subdomain_base_domain', 'subdomain_network',
    'subdomain_entrypoint', 'subdomain_tls', 'isolated_network',
    'container_discord_webhook_url',
    'anticheat_autoban_threshold', 'anticheat_log_all_attempts',
    'audit_retention_days', 'background_jobs_enabled',
    'ssh_hostname', 'ssh_port', 'ssh_user', 'ssh_key_content', 'ssh_known_hosts',
}

#: Simple validators applied before a value is persisted.
def _validate_int(key, value, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer")
    if minimum is not None and number < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{key} must be <= {maximum}")
    return str(number)


def _validate_float(key, value, minimum=None, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")
    if minimum is not None and number < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{key} must be <= {maximum}")
    return str(number)


def _validate_bool(key, value):
    return 'true' if str(value).lower() in ('1', 'true', 'yes', 'on') else 'false'


def _validate_hostname(key, value):
    value = str(value).strip()
    if value and not re.match(r'^[A-Za-z0-9._:-]+$', value):
        raise ValueError(f"{key} contains invalid characters")
    return value


CONFIG_VALIDATORS = {
    'port_range_start': lambda k, v: _validate_int(k, v, 1, 65535),
    'port_range_end': lambda k, v: _validate_int(k, v, 1, 65535),
    'default_timeout': lambda k, v: _validate_int(k, v, 1, 60 * 24 * 30),
    'max_renewals': lambda k, v: _validate_int(k, v, 0, 1000),
    'renew_extension_minutes': lambda k, v: _validate_int(k, v, 1, 24 * 60),
    'container_max_concurrent_count': lambda k, v: _validate_int(k, v, 1, 1000),
    'anticheat_autoban_threshold': lambda k, v: _validate_int(k, v, 0, 1000),
    'audit_retention_days': lambda k, v: _validate_int(k, v, 1, 3650),
    'ssh_port': lambda k, v: _validate_int(k, v, 1, 65535),
    'max_cpu': lambda k, v: _validate_float(k, v, 0.01, 1024),
    'subdomain_enabled': _validate_bool,
    'subdomain_tls': _validate_bool,
    'anticheat_log_all_attempts': _validate_bool,
    'background_jobs_enabled': _validate_bool,
    'connection_host': _validate_hostname,
    'port_bind_ip': _validate_hostname,
    'subdomain_base_domain': _validate_hostname,
    'ssh_hostname': _validate_hostname,
    'docker_socket': lambda k, v: str(v).strip(),
    'docker_type': lambda k, v: str(v).strip() if str(v).strip() in ('local', 'ssh') else 'local',
    'max_memory': lambda k, v: str(v).strip(),
    'isolated_network': lambda k, v: str(v).strip(),
    'subdomain_network': lambda k, v: str(v).strip(),
    'subdomain_entrypoint': lambda k, v: str(v).strip(),
    'container_discord_webhook_url': lambda k, v: str(v).strip(),
}


@admin_bp.route('/api/config', methods=['GET'], endpoint='api_config')
@admins_only
def get_config_api():
    """Get plugin configuration"""
    try:
        config = {k: v for k, v in ContainerConfig.get_all().items() if k != 'flag_encryption_key'}
        return jsonify({'config': config})
    except Exception as e:  # noqa: BLE001
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/config', methods=['POST'], endpoint='api_config_update')
@admins_only
def update_config():
    """Update plugin configuration (allow-listed keys only)."""
    try:
        data = request.get_json(silent=True) or {}
        docker_type = data.get('docker_type', ContainerConfig.get('docker_type', 'local'))

        errors = []
        applied = {}

        for key, raw_value in data.items():
            if key not in ALLOWED_CONFIG_KEYS:
                errors.append(f"Ignored unknown setting '{key}'")
                continue
            try:
                validator = CONFIG_VALIDATORS.get(key, lambda k, v: str(v))
                value = validator(key, raw_value)
            except ValueError as e:
                errors.append(str(e))
                continue
            applied[key] = value

        start = int(applied.get('port_range_start', ContainerConfig.get('port_range_start', 30000)))
        end = int(applied.get('port_range_end', ContainerConfig.get('port_range_end', 31000)))
        if start > end:
            errors.append("port_range_start must be lower than port_range_end")

        if errors and any("port_range" in e for e in errors):
            return jsonify({'success': False, 'errors': errors}), 400

        for key, value in applied.items():
            ContainerConfig.set(key, value)

        # Reconnect Docker according to the connection type
        if docker_service is None:
            errors.append("Docker service is not initialised; restart CTFd after fixing the connection")
        elif docker_type == 'ssh':
            try:
                docker_socket = _configure_ssh_connection(data)
                ContainerConfig.set('docker_socket', docker_socket)
                if not docker_service.reconnect(docker_socket):
                    errors.append("Could not connect to Docker over SSH; check the key and known_hosts")
            except ValueError as e:
                errors.append(str(e))
        else:
            docker_socket = 'unix://var/run/docker.sock'
            ContainerConfig.set('docker_socket', docker_socket)
            docker_service.reconnect(docker_socket)

        return jsonify({'success': not any('Could not' in e for e in errors), 'errors': errors})
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _configure_ssh_connection(data) -> str:
    """
    Write the SSH material for a remote Docker host.

    Everything that lands in an ssh_config / known_hosts file is validated
    first: these values are interpolated into configuration files, so an
    unchecked newline would let a caller inject arbitrary ssh options.
    """
    ssh_dir = os.path.expanduser('~/.ssh')
    os.makedirs(ssh_dir, exist_ok=True)

    ssh_hostname = str(data.get('ssh_hostname', '')).strip()
    if not ssh_hostname:
        raise ValueError("SSH hostname is required")

    if not re.match(r'^[A-Za-z0-9.-]+$', ssh_hostname):
        raise ValueError("SSH hostname may only contain letters, digits, dots and dashes")

    ssh_user = str(data.get('ssh_user', 'root')).strip() or 'root'
    if not re.match(r'^[A-Za-z0-9._-]+$', ssh_user):
        raise ValueError("SSH user contains invalid characters")

    try:
        ssh_port = int(data.get('ssh_port', 22) or 22)
    except (TypeError, ValueError):
        raise ValueError("SSH port must be an integer")

    safe_hostname = re.sub(r'[^a-zA-Z0-9.-]', '_', ssh_hostname)
    host_alias = f"ctfd-docker-{safe_hostname}"
    ssh_key_content = data.get('ssh_key_content', '') or ''
    ssh_known_hosts = (data.get('ssh_known_hosts', '') or '').strip()

    key_path = os.path.join(ssh_dir, f'{host_alias}_key')
    if ssh_key_content:
        if 'PRIVATE KEY' not in ssh_key_content:
            raise ValueError("SSH private key does not look like a PEM key")
        with open(key_path, 'w') as f:
            f.write(ssh_key_content)
        os.chmod(key_path, 0o600)

    known_hosts_path = os.path.join(ssh_dir, 'known_hosts')
    if ssh_known_hosts:
        if '\n' in ssh_known_hosts:
            raise ValueError("Known hosts entry must be a single line")
        existing = []
        if os.path.exists(known_hosts_path):
            with open(known_hosts_path, 'r') as f:
                existing = [line for line in f.readlines() if ssh_hostname not in line]
        existing.append(ssh_known_hosts + '\n')
        with open(known_hosts_path, 'w') as f:
            f.writelines(existing)
        os.chmod(known_hosts_path, 0o644)

    config_path = os.path.join(ssh_dir, 'config')
    existing_config = []
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            existing_config = f.readlines()

    new_config = []
    skip_until_next_host = False
    for line in existing_config:
        stripped = line.strip()
        if stripped.startswith('Host '):
            skip_until_next_host = host_alias in stripped
        elif stripped.startswith('# CTFd Docker Plugin'):
            skip_until_next_host = False
        if not skip_until_next_host:
            new_config.append(line)

    new_config.extend([
        '\n',
        '# CTFd Docker Plugin - Auto-generated\n',
        f'Host {host_alias}\n',
        f'    HostName {ssh_hostname}\n',
        f'    User {ssh_user}\n',
        f'    Port {ssh_port}\n',
    ])
    if ssh_key_content:
        new_config.append(f'    IdentityFile {key_path}\n')
    new_config.extend([
        '    StrictHostKeyChecking yes\n',
        f'    UserKnownHostsFile {known_hosts_path}\n',
    ])

    with open(config_path, 'w') as f:
        f.writelines(new_config)
    os.chmod(config_path, 0o644)

    return f'ssh://{host_alias}'


@admin_bp.route('/api/cleanup/expired', methods=['POST'], endpoint='api_cleanup_expired')
@admins_only
def cleanup_expired():
    """Manually trigger cleanup of expired instances"""
    try:
        cleaned = container_service.cleanup_expired_instances() if container_service else 0
        return jsonify({'success': True, 'cleaned': cleaned})
    except Exception as e:  # noqa: BLE001
        logger.error(f"cleanup expired failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/cleanup/old', methods=['POST'], endpoint='api_cleanup_old')
@admins_only
def cleanup_old():
    """Manually trigger cleanup of old instances"""
    try:
        deleted = container_service.cleanup_old_instances() if container_service else 0
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:  # noqa: BLE001
        logger.error(f"cleanup old failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/images', methods=['GET'], endpoint='api_images')
@admins_only
def list_images():
    """List available Docker images"""
    try:
        if not docker_service:
            return jsonify({'error': 'Docker service not available'}), 500

        image_list = []
        for img in docker_service.list_images():
            image_list.extend(img.tags or [])
        return jsonify({'images': sorted(set(image_list))})
    except Exception as e:  # noqa: BLE001
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/docker/health', methods=['GET'], endpoint='api_docker_health')
@admins_only
def docker_health_check():
    """Check Docker connection health"""
    try:
        if not docker_service:
            return jsonify({
                'connected': False,
                'error': 'Docker service not initialized',
            }), 500

        if not docker_service.is_connected():
            return jsonify({
                'connected': False,
                'error': 'Cannot connect to Docker daemon',
                'socket': ContainerConfig.get('docker_socket', 'Not configured'),
            })

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
                    'architecture': system_info.get('Architecture', 'Unknown'),
                },
                'socket': ContainerConfig.get('docker_socket', 'Not configured'),
            })
        except Exception as info_error:  # noqa: BLE001
            return jsonify({
                'connected': True,
                'error': f'Connected but failed to get info: {info_error}',
                'socket': ContainerConfig.get('docker_socket', 'Not configured'),
            })

    except Exception as e:  # noqa: BLE001
        return jsonify({'connected': False, 'error': str(e)}), 500


@admin_bp.route('/api/notifications/test', methods=['POST'], endpoint='api_notification_test')
@admins_only
def test_notification():
    """Test webhooks"""
    try:
        from .. import notification_service
        if not notification_service:
            return jsonify({'error': 'Notification service not available'}), 500

        data = request.get_json(silent=True) or {}
        kind = data.get('type', 'connection')
        url = (data.get('url') or '').strip() or None

        handlers = {
            'connection': notification_service.send_test,
            'demo_cheat': notification_service.send_demo_cheat,
            'demo_error': notification_service.send_demo_error,
        }
        handler = handlers.get(kind)
        if handler is None:
            return jsonify({'error': f'Unknown notification type: {kind}'}), 400

        if handler(url):
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to send notification. Check the URL and server logs.'}), 400

    except Exception as e:  # noqa: BLE001
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Challenge import (CSV + Excel)
# ============================================================================
IMPORT_COLUMNS = [
    'name', 'category', 'description', 'image', 'internal_port', 'internal_ports',
    'command', 'connection_type', 'connection_info', 'flag_pattern',
    'scoring_type', 'value', 'initial', 'decay', 'minimum', 'decay_function', 'state',
]


@admin_bp.route('/import', methods=['GET'])
@admins_only
def import_challenges_page():
    """Show import page"""
    return render_template(
        'container_import.html',
        docker_connected=_get_docker_status()[0],
        docker_info=_get_docker_status()[1],
    )


def _decode_upload(file_storage):
    """Return (headers, rows) from a CSV/XLSX/XLS upload."""
    filename = (file_storage.filename or '').lower()
    raw = file_storage.read()

    if filename.endswith(('.xlsx', '.xlsm', '.xls')):
        import openpyxl
        workbook = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
        sheet = workbook['Challenges'] if 'Challenges' in workbook.sheetnames else workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return [], []
        headers = [str(c).strip().lower() if c is not None else '' for c in rows[0]]
        return headers, rows[1:]

    # CSV (the documented format)
    text = raw.decode('utf-8-sig', errors='replace')
    reader = csv.reader(io.StringIO(text))
    try:
        headers = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return [], []
    return headers, list(reader)


def _row_to_dict(headers, row):
    data = {}
    for idx, value in enumerate(row):
        if idx < len(headers) and headers[idx]:
            data[headers[idx]] = value.strip() if isinstance(value, str) else value
    return data


def _build_challenge_from_row(row_data, row_label, errors):
    """Create an unsaved ContainerChallenge from one imported row."""
    name = str(row_data.get('name') or '').strip()
    category = str(row_data.get('category') or '').strip()
    image = str(row_data.get('image') or '').strip()

    if not name:
        raise ValueError("missing 'name'")
    if not category:
        raise ValueError("missing 'category'")
    if not image:
        raise ValueError("missing 'image'")
    if ':' not in image:
        errors.append(f"{row_label}: image '{image}' has no tag (e.g. nginx:latest)")

    # Ports: accept internal_ports list, else internal_port
    ports_raw = row_data.get('internal_ports') or row_data.get('internal_port') or 80
    ports = []
    for chunk in str(ports_raw).split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            port = int(float(chunk))
        except ValueError:
            raise ValueError(f"invalid port '{chunk}'")
        if not 0 < port < 65536:
            raise ValueError(f"port out of range '{chunk}'")
        if port not in ports:
            ports.append(port)
    if not ports:
        ports = [80]

    pattern = str(row_data.get('flag_pattern') or 'CTF{flag}').strip()
    flag = parse_flag_pattern(pattern)

    scoring_type = str(row_data.get('scoring_type') or 'standard').strip().lower()
    decay_function = str(row_data.get('decay_function') or 'logarithmic').strip().lower()
    if decay_function not in ('linear', 'logarithmic'):
        decay_function = 'logarithmic'

    def _num(key, default=None):
        value = row_data.get(key)
        if value is None or value == '':
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            raise ValueError(f"'{key}' must be a number")

    container_initial = container_decay = container_minimum = None
    if scoring_type == 'dynamic':
        container_initial = _num('initial', 500)
        container_decay = _num('decay', 20)
        container_minimum = _num('minimum', 100)
        if container_initial is None or container_decay is None or container_minimum is None:
            raise ValueError("dynamic scoring needs initial/decay/minimum")
        value = container_initial
    else:
        value = _num('value', 100)

    challenge = ContainerChallenge(
        name=name,
        category=category,
        description=str(row_data.get('description') or ''),
        value=value,
        state=str(row_data.get('state') or 'visible').strip().lower() or 'visible',
        type='container',
        image=image,
        internal_port=ports[0],
        internal_ports=','.join(str(p) for p in ports),
        command=str(row_data.get('command') or ''),
        container_connection_type=str(row_data.get('connection_type') or 'http').strip().lower(),
        container_connection_info=str(row_data.get('connection_info') or ''),
        flag_mode=flag['flag_mode'],
        flag_prefix=flag['flag_prefix'],
        flag_suffix=flag['flag_suffix'],
        random_flag_length=flag['random_flag_length'],
        container_initial=container_initial,
        container_decay=container_decay,
        container_minimum=container_minimum,
        decay_function=decay_function,
    )
    return challenge


@admin_bp.route('/api/import', methods=['POST'])
@admins_only
def import_challenges():
    """
    Import challenges.

    Accepts the CSV format documented in the README as well as the legacy
    Excel workbook format.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not file.filename.lower().endswith(('.csv', '.xlsx', '.xlsm', '.xls')):
            return jsonify({
                'success': False,
                'error': 'File must be CSV (.csv) or Excel (.xlsx/.xls)',
            }), 400

        try:
            headers, rows = _decode_upload(file)
        except ImportError:
            return jsonify({
                'success': False,
                'error': 'openpyxl is not installed; use the CSV format instead',
            }), 400
        except Exception as e:  # noqa: BLE001
            return jsonify({'success': False, 'error': f'Could not read file: {e}'}), 400

        missing = [col for col in ('name', 'category', 'image') if col not in headers]
        if missing:
            return jsonify({
                'success': False,
                'error': f"Missing required column(s): {', '.join(missing)}",
            }), 400

        created = 0
        errors = []

        for row_idx, row in enumerate(rows, start=2):
            if row is None or all(v is None or str(v).strip() == '' for v in row):
                continue
            row_data = _row_to_dict(headers, row)
            try:
                challenge = _build_challenge_from_row(row_data, f"Row {row_idx}", errors)
                db.session.add(challenge)
                db.session.flush()
                Flags.query.filter_by(challenge_id=challenge.id).delete()
                db.session.add(Flags(
                    challenge_id=challenge.id,
                    type='static',
                    content='[Container flag - auto-generated per instance]',
                    data='',
                ))
                created += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"Row {row_idx}: {e}")
                db.session.rollback()
                continue

        db.session.commit()

        return jsonify({'success': True, 'created': created, 'errors': errors})

    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        logger.error(f"import failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/download-template')
@admins_only
def download_template():
    """Download the CSV template for importing challenges"""
    try:
        examples = [
            {
                'name': 'Web Challenge Example',
                'category': 'Web',
                'description': 'Find the flag',
                'image': 'nginx:latest',
                'internal_port': '80',
                'internal_ports': '80',
                'command': '',
                'connection_type': 'http',
                'connection_info': 'Access via browser',
                'flag_pattern': 'CTF{static_flag}',
                'scoring_type': 'standard',
                'value': '100',
                'initial': '',
                'decay': '',
                'minimum': '',
                'decay_function': '',
                'state': 'visible',
            },
            {
                'name': 'SSH Challenge Example',
                'category': 'Pwn',
                'description': 'SSH and find the flag',
                'image': 'ubuntu:20.04',
                'internal_port': '22',
                'internal_ports': '22',
                'command': '/usr/sbin/sshd -D',
                'connection_type': 'tcp',
                'connection_info': 'user:ctf pass:ctf',
                'flag_pattern': 'CTF{<ran_16>}',
                'scoring_type': 'dynamic',
                'value': '',
                'initial': '500',
                'decay': '20',
                'minimum': '100',
                'decay_function': 'logarithmic',
                'state': 'visible',
            },
        ]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=IMPORT_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for example in examples:
            writer.writerow(example)

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = (
            'attachment; filename=container_challenges_template.csv'
        )
        return response

    except Exception as e:  # noqa: BLE001
        return jsonify({'error': str(e)}), 500

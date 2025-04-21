import json
from flask import Blueprint, request, jsonify, render_template, url_for, redirect, Flask, flash
from CTFd.models import db
from .models import ContainerChallengeModel, ContainerInfoModel, ContainerSettingsModel, ContainerCheatLog
from .container_manager import ContainerManager, ContainerException
from CTFd.utils.decorators import admins_only
from .helpers import *

admin_bp = Blueprint("container_admin", __name__, url_prefix="/containers/admin")

container_manager = None

def set_container_manager(manager):
    global container_manager
    container_manager = manager

# Admin dashboard
@admin_bp.route("/dashboard", methods=["GET"])
@admins_only
def route_containers_dashboard():
    connected = False
    try:
        connected = container_manager.is_connected()
    except ContainerException:
        pass

    running_containers = ContainerInfoModel.query.order_by(
        ContainerInfoModel.timestamp.desc()
    ).all()

    for i, container in enumerate(running_containers):
        try:
            running_containers[i].is_running = container_manager.is_container_running(
                container.container_id
            )
        except ContainerException:
            running_containers[i].is_running = False

    return render_template(
        "container_dashboard.html",
        containers=running_containers,
        connected=connected,
    )

@admin_bp.route("/settings", methods=["GET"])
@admins_only
def route_containers_settings():
    connected = False
    try:
        connected = container_manager.is_connected()
    except ContainerException:
        pass

    return render_template(
        "container_settings.html",
        settings=container_manager.settings,
        connected=connected,
    )

@admin_bp.route("/cheat", methods=["GET"])
@admins_only
def route_containers_cheat():
    connected = False
    try:
        connected = container_manager.is_connected()
    except ContainerException:
        pass

    cheat_logs = ContainerCheatLog.query.order_by(ContainerCheatLog.timestamp.desc()).all()

    return render_template(
        "container_cheat.html",
        connected=connected,
        cheat_logs=cheat_logs
    )

# Admin API
@admin_bp.route("/api/settings", methods=["POST"])
@admins_only
def route_update_settings():

    required_fields = [
        "docker_base_url",
        "docker_hostname",
        "container_expiration",
        "container_maxmemory",
        "container_maxcpu",
        "max_containers",
        "fame_or_shame"
    ]

    # Validate required fields
    for field in required_fields:
        if request.form.get(field) is None:
            return {"error": f"{field} is required."}, 400

    # Update settings dynamically
    for key in required_fields:
        value = request.form.get(key)
        setting = ContainerSettingsModel.query.filter_by(key=key).first()

        if not setting:
            setting = ContainerSettingsModel(key=key, value=value)
            db.session.add(setting)
        else:
            setting.value = value

    db.session.commit()

    # Refresh container manager settings
    container_manager.settings = settings_to_dict(
        ContainerSettingsModel.query.all()
    )

    if container_manager.settings.get("docker_base_url") is not None:
        try:
            container_manager.initialize_connection(container_manager.settings, Flask)
        except ContainerException as err:
            flash(str(err), "error")
            return redirect(url_for(".route_containers_settings"))

    return redirect(url_for(".route_containers_dashboard"))

@admin_bp.route("/api/kill", methods=["POST"])
@admins_only
def route_admin_kill_container():
    try:
        validate_request(request.json, ["container_id"])
        return kill_container(container_manager, request.json.get("container_id"))
    except ValueError as err:
        return {"error": str(err)}, 400

@admin_bp.route("/api/purge", methods=["POST"])
@admins_only
def route_purge_containers():
    """Bulk delete multiple containers"""
    try:
        validate_request(request.json, ["container_ids"])
        container_ids = request.json.get("container_ids", [])
        if not container_ids:
            return {"error": "No containers selected"}, 400

        deleted_count = 0
        for container_id in container_ids:
            container = ContainerInfoModel.query.filter_by(container_id=container_id).first()
            if container:
                try:
                    container_manager.kill_container(container_id)
                    db.session.delete(container)
                    deleted_count += 1
                except ContainerException:
                    continue

        db.session.commit()
        return {"success": f"Deleted {deleted_count} container(s)"}
    except ValueError as err:
        return {"error": str(err)}, 400
        
@admin_bp.route("/api/images", methods=["GET"])
@admins_only
def route_get_images():
    try:
        images = container_manager.get_images()
    except ContainerException as err:
        return {"error": str(err)}

    return {"images": images}

@admin_bp.route("/api/running_containers", methods=["GET"])
@admins_only
def route_get_running_containers():
    running_containers = ContainerInfoModel.query.order_by(
        ContainerInfoModel.timestamp.desc()
    ).all()

    connected = False
    try:
        connected = container_manager.is_connected()
    except ContainerException:
        pass

    # Create lists to store unique teams and challenges
    unique_teams = set()
    unique_challenges = set()

    for i, container in enumerate(running_containers):
        try:
            running_containers[i].is_running = (
                container_manager.is_container_running(container.container_id)
            )
        except ContainerException:
            running_containers[i].is_running = False

        # Add team and challenge to the unique sets
        if is_team_mode() is True:
            unique_teams.add(f"{container.team.name} [{container.team_id}]")
        else:
            unique_teams.add(f"{container.user.name} [{container.user_id}]")
        unique_challenges.add(
            f"{container.challenge.name} [{container.challenge_id}]"
        )

    # Convert unique sets to lists
    unique_teams_list = list(unique_teams)
    unique_challenges_list = list(unique_challenges)

    # Create a list of dictionaries containing running_containers data
    running_containers_data = []
    for container in running_containers:
        if is_team_mode() is True:
            container_data = {
                "container_id": container.container_id,
                "image": container.challenge.image,
                "challenge": f"{container.challenge.name} [{container.challenge_id}]",
                "team": f"{container.team.name} [{container.team_id}]",
                "port": container.port,
                "created": container.timestamp,
                "expires": container.expires,
                "is_running": container.is_running,
            }
        else:
            container_data = {
                "container_id": container.container_id,
                "image": container.challenge.image,
                "challenge": f"{container.challenge.name} [{container.challenge_id}]",
                "user": f"{container.user.name} [{container.user_id}]",
                "port": container.port,
                "created": container.timestamp,
                "expires": container.expires,
                "is_running": container.is_running,
            }
        running_containers_data.append(container_data)

    # Create a JSON response containing running_containers_data, unique teams, and unique challenges
    response_data = {
        "containers": running_containers_data,
        "connected": connected,
        "teams": unique_teams_list,
        "challenges": unique_challenges_list,
    }

    # Return the JSON response
    return jsonify(response_data)

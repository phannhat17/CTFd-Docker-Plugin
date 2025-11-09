import json
from flask import Blueprint, request, jsonify, render_template, url_for, redirect, Flask, flash
from CTFd.models import db
from .models import ContainerChallengeModel, ContainerInfoModel, ContainerSettingsModel
from .container_manager import ContainerManager, ContainerException
from CTFd.utils.decorators import (
    authed_only,
    admins_only,
    during_ctf_time_only,
    ratelimit,
    require_verified_emails,
)
from .helpers import *
from CTFd.utils.user import get_current_user
from CTFd.utils import get_config

containers_bp = Blueprint("container_user", __name__, url_prefix="/containers")

container_manager = None

def set_container_manager(manager):
    global container_manager
    container_manager = manager


@containers_bp.route("/api/get_connect_type/<int:challenge_id>", methods=["GET"])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method="GET", limit=15, interval=60)
def get_connect_type(challenge_id):
    try:
        return connect_type(challenge_id)
    except ContainerException as err:
        return {"error": str(err)}, 500

@containers_bp.route("/api/view_info", methods=["POST"])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method="POST", limit=15, interval=60)
def route_view_info():
    try:
        validate_request(request.json, ["chal_id"])
        xid = get_current_user_or_team()
        return view_container_info(container_manager, request.json.get("chal_id"), xid, is_team_mode())
    except ValueError as err:
        return {"error": str(err)}, 400

@containers_bp.route("/api/request", methods=["POST"])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method="POST", limit=6, interval=60)
def route_request_container():
    try:
        validate_request(request.json, ["chal_id"])
        xid = get_current_user_or_team()
        return create_container(container_manager, request.json.get("chal_id"), xid, is_team_mode())
    except ValueError as err:
        return {"error": str(err)}, 400

@containers_bp.route("/api/renew", methods=["POST"])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method="POST", limit=6, interval=60)
def route_renew_container():
    try:
        validate_request(request.json, ["chal_id"])
        xid = get_current_user_or_team()
        return renew_container(container_manager, request.json.get("chal_id"), xid, is_team_mode())
    except ValueError as err:
        return {"error": str(err)}, 400

@containers_bp.route("/api/stop", methods=["POST"])
@authed_only
@during_ctf_time_only
@require_verified_emails
@ratelimit(method="POST", limit=10, interval=60)
def route_stop_container():
    try:
        validate_request(request.json, ["chal_id"])
        xid = get_current_user_or_team()
        running_container = ContainerInfoModel.query.filter_by(
            challenge_id=request.json.get("chal_id"),
            team_id=xid if is_team_mode() else None,
            user_id=None if is_team_mode() else xid
        ).first()

        if running_container and running_container.container_id:
            return kill_container(container_manager, running_container.container_id)
        return {"error": "No container found"}, 400
    except ValueError as err:
        return {"error": str(err)}, 400
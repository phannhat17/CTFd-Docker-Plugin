from __future__ import division

import time
import json
import datetime
import math

from flask import Blueprint, request, Flask, render_template, url_for, redirect, flash

from CTFd.models import db, Solves, Teams, Users
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.utils.modes import get_model
from .models import ContainerChallengeModel, ContainerInfoModel, ContainerSettingsModel, ContainerFlagModel, ContainerCheatLog  
from .container_manager import ContainerManager, ContainerException
from .admin_routes import admin_bp, set_container_manager as set_admin_manager
from .user_routes import containers_bp, set_container_manager as set_user_manager
from .helpers import *
from CTFd.utils.user import get_current_user

settings = json.load(open(get_settings_path()))

class ContainerChallenge(BaseChallenge):
    id = settings["plugin-info"]["id"]
    name = settings["plugin-info"]["name"]
    templates = settings["plugin-info"]["templates"]
    scripts = settings["plugin-info"]["scripts"]
    route = settings["plugin-info"]["base_path"]

    challenge_model = ContainerChallengeModel

    @classmethod
    def read(cls, challenge):
        """
        This method is in used to access the data of a challenge in a format processable by the front end.

        :param challenge:
        :return: Challenge object, data dictionary to be returned to the user
        """
        data = {
            "id": challenge.id,
            "name": challenge.name,
            "value": challenge.value,
            "image": challenge.image,
            "port": challenge.port,
            "command": challenge.command,
            "connection_type": challenge.connection_type,
            "ssh_username": challenge.ssh_username,
            "ssh_password": challenge.ssh_password,
            "initial": challenge.initial,
            "decay": challenge.decay,
            "minimum": challenge.minimum,
            "description": challenge.description,
            "connection_info": challenge.connection_info,
            "category": challenge.category,
            "state": challenge.state,
            "max_attempts": challenge.max_attempts,
            "type": challenge.type,
            "type_data": {
                "id": cls.id,
                "name": cls.name,
                "templates": cls.templates,
                "scripts": cls.scripts,
            },
        }
        return data

    @classmethod
    def calculate_value(cls, challenge):
        Model = get_model()

        solve_count = (
            Solves.query.join(Model, Solves.account_id == Model.id)
            .filter(
                Solves.challenge_id == challenge.id,
                Model.hidden == False,
                Model.banned == False,
            )
            .count()
        )

        # If the solve count is 0 we shouldn't manipulate the solve count to
        # let the math update back to normal
        if solve_count != 0:
            # We subtract -1 to allow the first solver to get max point value
            solve_count -= 1

        # It is important that this calculation takes into account floats.
        # Hence this file uses from __future__ import division
        value = (
            ((challenge.minimum - challenge.initial) / (challenge.decay**2))
            * (solve_count**2)
        ) + challenge.initial

        value = math.ceil(value)

        if value < challenge.minimum:
            value = challenge.minimum

        challenge.value = value
        db.session.commit()
        return challenge

    @classmethod
    def update(cls, challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.
        :param challenge:
        :param request:
        :return:
        """
        data = request.form or request.get_json()

        for attr, value in data.items():
            # We need to set these to floats so that the next operations don't operate on strings
            if attr in ("initial", "minimum", "decay"):
                value = float(value)
            setattr(challenge, attr, value)

        return ContainerChallenge.calculate_value(challenge)

    @classmethod
    def solve(cls, user, team, challenge, request):
        super().solve(user, team, challenge, request)

        cls.calculate_value(challenge)

    @classmethod
    def attempt(cls, challenge, request):
        # 1) Gather user/team & submitted_flag
        try:
            user, x_id, submitted_flag = get_xid_and_flag()
        except ValueError as e:
            return False, str(e)

        # 2) Get running container
        container_info = None
        try:
            container_info = get_active_container(challenge.id, x_id)
        except ValueError as e:
            return False, str(e)

        # 3) Check if container is actually running
        from . import container_manager
        if not container_manager or not container_manager.is_container_running(container_info.container_id):
            return False, "Your container is not running; you cannot submit yet."

        # Validate the flag belongs to the user/team
        try:
            container_flag = get_container_flag(submitted_flag, user, container_manager, container_info, challenge)
        except ValueError as e:
            return False, str(e)  # Return incorrect flag message if not cheating

        # 6) Mark used & kill container => success
        container_flag.used = True
        db.session.commit()

        # **If the challenge is static, delete both flag and container records**
        if challenge.flag_mode == "static":
            db.session.delete(container_flag)
            db.session.commit()
        
        # **If the challenge is random, keep the flag but delete only the container info**
        if challenge.flag_mode == "random":
            db.session.query(ContainerFlagModel).filter_by(container_id=container_info.container_id).update({"container_id": None})
            db.session.commit()

        # Remove container info record
        container = ContainerInfoModel.query.filter_by(container_id=container_info.container_id).first()
        if container:
            db.session.delete(container)
            db.session.commit()

        # Kill the container
        container_manager.kill_container(container_info.container_id)

        return True, "Correct"

container_manager = None  # Global

def load(app: Flask):
    # Ensure database is initialized
    app.db.create_all()

    # Register the challenge type
    CHALLENGE_CLASSES["container"] = ContainerChallenge

    register_plugin_assets_directory(
        app, base_path=settings["plugin-info"]["base_path"]
    )

    global container_manager
    container_settings = settings_to_dict(ContainerSettingsModel.query.all())
    container_manager = ContainerManager(container_settings, app)

    base_bp = Blueprint(
        "containers",
        __name__,
        template_folder=settings["blueprint"]["template_folder"],
        static_folder=settings["blueprint"]["static_folder"]
    )

    set_admin_manager(container_manager)
    set_user_manager(container_manager)

    # Register the blueprints
    app.register_blueprint(admin_bp)  # Admin APIs
    app.register_blueprint(containers_bp) # User APIs


    app.register_blueprint(base_bp)

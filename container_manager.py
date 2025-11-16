import atexit
import time
import json
import random
import string

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers import SchedulerNotRunningError
import docker
import paramiko.ssh_exception
import requests

from CTFd.models import db, Flags
from .models import ContainerInfoModel, ContainerFlagModel, ContainerFlagModel


def generate_random_flag(challenge):
    """Generate a random flag with the given length and format"""
    flag_length = challenge.random_flag_length
    random_part = "".join(
        random.choices(string.ascii_letters + string.digits, k=flag_length)
    )
    return f"{challenge.flag_prefix}{random_part}{challenge.flag_suffix}"


class ContainerException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        if args:
            self.message = args[0]
        else:
            self.message = None

    def __str__(self) -> str:
        if self.message:
            return self.message
        else:
            return "Unknown Container Exception"


class ContainerManager:
    def __init__(self, settings, app):
        self.settings = settings
        self.client = None
        self.app = app
        if (
            settings.get("docker_base_url") is None
            or settings.get("docker_base_url") == ""
        ):
            return

        # Connect to the docker daemon
        try:
            self.initialize_connection(settings, app)
        except ContainerException:
            print("Docker could not initialize or connect.")
            return

    def initialize_connection(self, settings, app) -> None:
        self.settings = settings
        self.app = app

        # Remove any leftover expiration schedulers
        try:
            self.expiration_scheduler.shutdown()
        except (SchedulerNotRunningError, AttributeError):
            # Scheduler was never running
            pass

        if settings.get("docker_base_url") is None:
            self.client = None
            return

        try:
            self.client = docker.DockerClient(base_url=settings.get("docker_base_url"))
        except docker.errors.DockerException as e:
            self.client = None
            raise ContainerException("CTFd could not connect to Docker")
        except TimeoutError as e:
            self.client = None
            raise ContainerException("CTFd timed out when connecting to Docker")
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            self.client = None
            raise ContainerException(
                "CTFd timed out when connecting to Docker: " + str(e)
            )
        except paramiko.ssh_exception.AuthenticationException as e:
            self.client = None
            raise ContainerException(
                "CTFd had an authentication error when connecting to Docker: " + str(e)
            )

        # Set up expiration scheduler
        try:
            self.expiration_seconds = int(settings.get("container_expiration", 0)) * 60
        except (ValueError, AttributeError):
            self.expiration_seconds = 0

        EXPIRATION_CHECK_INTERVAL = 5

        if self.expiration_seconds > 0:
            self.expiration_scheduler = BackgroundScheduler()
            self.expiration_scheduler.add_job(
                func=self.kill_expired_containers,
                args=(app,),
                trigger="interval",
                seconds=EXPIRATION_CHECK_INTERVAL,
            )
            self.expiration_scheduler.start()

            # Shut down the scheduler when exiting the app
            atexit.register(lambda: self.expiration_scheduler.shutdown())

    # TODO: Fix this cause it doesn't work
    def run_command(func):
        def wrapper_run_command(self, *args, **kwargs):
            if self.client is None:
                try:
                    self.__init__(self.settings, self.app)
                except:
                    raise ContainerException("Docker is not connected")
            try:
                if self.client is None:
                    raise ContainerException("Docker is not connected")
                if self.client.ping():
                    return func(self, *args, **kwargs)
            except (
                paramiko.ssh_exception.SSHException,
                ConnectionError,
                requests.exceptions.ConnectionError,
            ) as e:
                # Try to reconnect before failing
                try:
                    self.__init__(self.settings, self.app)
                except:
                    pass
                raise ContainerException(
                    "Docker connection was lost. Please try your request again later."
                )

        return wrapper_run_command

    @run_command
    def kill_expired_containers(self, app: Flask):
        # Handle both scheduled and manual calls
        if not isinstance(app, Flask):
            from CTFd import create_app
            app = create_app()

        with app.app_context():
            containers: "list[ContainerInfoModel]" = ContainerInfoModel.query.all()

            for container in containers:
                delta_seconds = container.expires - int(time.time())
                if delta_seconds < 0:
                    try:
                        self.kill_container(container.container_id)
                    except ContainerException:
                        print(
                            "[Container Expiry Job] Docker is not initialized. Please check your settings."
                        )

                    db.session.delete(container)
                    db.session.commit()

    @run_command
    def is_container_running(self, container_id: str) -> bool:
        container = self.client.containers.list(filters={"id": container_id})
        if len(container) == 0:
            return False
        return container[0].status == "running"

    @run_command
    def create_container(self, challenge, xid, is_team):
        kwargs = {}

        if challenge.flag_mode == "random":
            flag = generate_random_flag(challenge)
        else:
            # Get flag from flags table
            flag_obj = Flags.query.filter_by(challenge_id=challenge.id).first()
            if flag_obj:
                flag = challenge.flag_prefix + flag_obj.content + challenge.flag_suffix
            else:
                flag = challenge.flag_prefix + challenge.flag_suffix

        # Set the memory and CPU limits for the container
        if self.settings.get("container_maxmemory"):
            try:
                mem_limit = int(self.settings.get("container_maxmemory"))
                if mem_limit > 0:
                    kwargs["mem_limit"] = f"{mem_limit}m"
            except ValueError:
                ContainerException(
                    "Configured container memory limit must be an integer"
                )
        if self.settings.get("container_maxcpu"):
            try:
                cpu_period = float(self.settings.get("container_maxcpu"))
                if cpu_period > 0:
                    kwargs["cpu_quota"] = int(cpu_period * 100000)
                    kwargs["cpu_period"] = 100000
            except ValueError:
                ContainerException("Configured container CPU limit must be a number")

        volumes = challenge.volumes
        if volumes is not None and volumes != "":
            print("Volumes:", volumes)
            try:
                volumes_dict = json.loads(volumes)
                kwargs["volumes"] = volumes_dict
            except json.decoder.JSONDecodeError:
                raise ContainerException("Volumes JSON string is invalid")

        try:
            container = self.client.containers.run(
                challenge.image,
                ports={str(challenge.port): None},
                command=challenge.command,
                detach=True,
                auto_remove=True,
                environment={"FLAG": flag},
                **kwargs,
            )

            port = self.get_container_port(container.id)
            if port is None:
                raise ContainerException("Could not get container port")
            expires = int(time.time() + self.expiration_seconds)

            new_container_entry = ContainerInfoModel(
                container_id=container.id,
                challenge_id=challenge.id,
                team_id=xid if is_team else None,
                user_id=None if is_team else xid,
                port=port,
                ssh_username=challenge.ssh_username,
                ssh_password=challenge.ssh_password,
                flag=flag,
                timestamp=int(time.time()),
                expires=expires,
            )
            db.session.add(new_container_entry)
            db.session.commit()

            # Save the flag in the database
            new_flag_entry = ContainerFlagModel(
                challenge_id=challenge.id,
                container_id=container.id,
                flag=flag,
                team_id=xid if is_team else None,
                user_id=None if is_team else xid,
            )
            db.session.add(new_flag_entry)
            db.session.commit()

            return {
                "container": container,
                "expires": expires,
                "port": port,
                "ssh_username": challenge.ssh_username,
                "ssh_password": challenge.ssh_password,
            }
        except docker.errors.ImageNotFound:
            raise ContainerException("Docker image not found")

    @run_command
    def get_container_port(self, container_id: str) -> "str|None":
        try:
            for port in list(self.client.containers.get(container_id).ports.values()):
                if port is not None:
                    return port[0]["HostPort"]
        except (KeyError, IndexError):
            return None

    @run_command
    def get_images(self) -> "list[str]|None":
        try:
            images = self.client.images.list()
        except (KeyError, IndexError):
            return []

        images_list = []
        for image in images:
            if len(image.tags) > 0:
                images_list.append(image.tags[0])

        images_list.sort()
        return images_list

    @run_command
    def kill_container(self, container_id: str):
        try:
            container = self.client.containers.get(container_id)
            container.kill()
            container.remove()

            container_info = ContainerInfoModel.query.filter_by(
                container_id=container_id
            ).first()
            if not container_info:
                return  # No matching record => nothing else to do

            challenge = container_info.challenge

            used_flags = ContainerFlagModel.query.filter_by(
                container_id=container_id
            ).all()

            if challenge.flag_mode == "static":
                # Remove all flags for static-mode challenges (ignore used or not used)
                for f in used_flags:
                    db.session.delete(f)
            else:
                for f in used_flags:
                    if f.used:
                        # Keep this flag, but remove its container reference
                        f.container_id = None
                    else:
                        # If the flag wasn't used, delete it
                        db.session.delete(f)

        except docker.errors.NotFound:
            pass

    def is_connected(self) -> bool:
        try:
            self.client.ping()
        except:
            return False
        return True

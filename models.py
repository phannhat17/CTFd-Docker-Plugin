from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from CTFd.models import db
from CTFd.models import Challenges


class ContainerChallengeModel(Challenges):
    __mapper_args__ = {"polymorphic_identity": "container"}
    id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )
    image = db.Column(db.Text)
    port = db.Column(db.Integer)
    command = db.Column(db.Text, default="")
    volumes = db.Column(db.Text, default="")
    connection_type = db.Column(db.Text)
    password = db.Column(db.Text, default="")
    username = db.Column(db.Text, default="")
    # Dynamic challenge properties
    initial = db.Column(db.Integer, default=0)
    minimum = db.Column(db.Integer, default=0)
    decay = db.Column(db.Integer, default=0)

    # Random flag properties
    flag_mode = db.Column(db.Text, default="static")
    random_flag_length = db.Column(db.Integer, default=10)
    flag_prefix = db.Column(db.Text, default="CTF{")
    flag_suffix = db.Column(db.Text, default="}")

    def __init__(self, *args, **kwargs):
        super(ContainerChallengeModel, self).__init__(**kwargs)
        self.value = kwargs["initial"]


class ContainerInfoModel(db.Model):
    __mapper_args__ = {"polymorphic_identity": "container_info"}
    container_id = db.Column(db.String(512), primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    port = db.Column(db.Integer)
    timestamp = db.Column(db.Integer)
    expires = db.Column(db.Integer)
    flag = db.Column(db.Text, default="")
    
    team = relationship("Teams", foreign_keys=[team_id])
    user = relationship("Users", foreign_keys=[user_id])

    challenge = relationship(ContainerChallengeModel, foreign_keys=[challenge_id])


class ContainerSettingsModel(db.Model):
    __mapper_args__ = {"polymorphic_identity": "container_settings"}
    key = db.Column(db.String(512), primary_key=True)
    value = db.Column(db.Text)


class ContainerFlagModel(db.Model):
    __mapper_args__ = {"polymorphic_identity": "container_flags"}
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE")
    )
    container_id = db.Column(
        db.String(512),
        db.ForeignKey("container_info_model.container_id"),
        nullable=True,
    )
    flag = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"))
    used = db.Column(db.Boolean, default=False)

    container = relationship(ContainerInfoModel, foreign_keys=[container_id])
    challenge = relationship(ContainerChallengeModel, foreign_keys=[challenge_id])
    user = relationship("Users", foreign_keys=[user_id])
    team = relationship("Teams", foreign_keys=[team_id])


class ContainerCheatLog(db.Model):
    __mapper_args__ = {"polymorphic_identity": "container_cheat_logs"}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # The reused flag
    reused_flag = db.Column(db.Text)

    # Which challenge was it from?
    challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE")
    )
    # We'll store the relevant relationships if needed
    challenge = db.relationship("ContainerChallengeModel", foreign_keys=[challenge_id])

    # Original owners
    original_team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)
    original_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # The second submitter who tried reusing the flag
    second_team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)
    second_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Time of the cheating attempt
    timestamp = db.Column(db.Integer)

    # Relationship to help retrieve team/user if needed
    original_team = db.relationship("Teams", foreign_keys=[original_team_id])
    original_user = db.relationship("Users", foreign_keys=[original_user_id])
    second_team = db.relationship("Teams", foreign_keys=[second_team_id])
    second_user = db.relationship("Users", foreign_keys=[second_user_id])

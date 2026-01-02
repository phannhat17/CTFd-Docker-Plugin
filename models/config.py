"""
Container Plugin Configuration Model
"""
from CTFd.models import db


class ContainerConfig(db.Model):
    """
    Plugin configuration (key-value store)
    """
    __tablename__ = 'container_config'
    
    key = db.Column(db.String(255), primary_key=True)
    value = db.Column(db.Text)
    
    @staticmethod
    def get(key, default=None):
        """Get config value"""
        config = ContainerConfig.query.filter_by(key=key).first()
        return config.value if config else default
    
    @staticmethod
    def set(key, value):
        """Set config value"""
        config = ContainerConfig.query.filter_by(key=key).first()
        if not config:
            config = ContainerConfig(key=key, value=value)
            db.session.add(config)
        else:
            config.value = value
        db.session.commit()
    
    @staticmethod
    def get_all():
        """Get all config as dict"""
        configs = ContainerConfig.query.all()
        return {c.key: c.value for c in configs}

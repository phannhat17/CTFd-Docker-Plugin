"""
Container Plugin Routes
"""

from .user import user_bp
from .admin import admin_bp

__all__ = ['user_bp', 'admin_bp']

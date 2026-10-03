"""
Notification Service - Discord webhook alerts (optional)
"""
import logging

import requests

from ..models.config import ContainerConfig

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 5

DEMO_COLORS = {
    'info': 0x3498db,
    'success': 0x00ff00,
    'warning': 0xffa500,
    'error': 0xff0000,
}


class NotificationService:
    """Thin Discord webhook client. Every method degrades to a no-op."""

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _get_webhook_url(self):
        return (ContainerConfig.get('container_discord_webhook_url', '') or '').strip()

    @staticmethod
    def _valid_webhook(url: str) -> bool:
        return bool(url) and url.startswith((
            'https://discord.com/api/webhooks/',
            'https://discordapp.com/api/webhooks/',
            'https://canary.discord.com/api/webhooks/',
        ))

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def send_alert(self, title, message, color=0xff0000, fields=None, url=None):
        """Send an alert to the configured Discord webhook."""
        webhook_url = (url or self._get_webhook_url() or '').strip()
        if not webhook_url:
            return False
        return self._send_raw(webhook_url, title, message, color, fields)

    def _send_raw(self, url, title, message, color, fields=None):
        if not url:
            return False
        payload = {
            "embeds": [{
                "title": str(title)[:256],
                "description": str(message)[:4000],
                "color": color,
                "fields": (fields or [])[:25],
            }]
        }
        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            if response.status_code not in (200, 204):
                logger.warning(
                    "Discord webhook returned %s: %s",
                    response.status_code, response.text[:200],
                )
                return False
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send Discord notification: {e}")
            return False

    # ------------------------------------------------------------------
    # High level alerts
    # ------------------------------------------------------------------
    def notify_flag_reuse(self, challenge, submitter_account_id, owner_account_id,
                          flag=None, banned=False):
        """Alert admins that a flag was submitted by a different account."""
        fields = [
            {"name": "Challenge", "value": str(getattr(challenge, 'name', 'unknown')), "inline": True},
            {"name": "Submitted by account", "value": str(submitter_account_id), "inline": True},
            {"name": "Flag owner account", "value": str(owner_account_id), "inline": True},
            {"name": "Action taken", "value": "Accounts banned" if banned else "Logged only",
             "inline": False},
        ]
        if flag:
            fields.insert(3, {"name": "Flag", "value": f"||`{str(flag)[:80]}`||", "inline": False})

        return self.send_alert(
            title="🚨 Flag sharing detected",
            message="A player submitted a flag that belongs to another team/user.",
            color=DEMO_COLORS['error'],
            fields=fields,
        )

    # Backwards compatible alias
    def notify_cheat(self, user=None, challenge=None, flag=None, owner=None):
        return self.notify_flag_reuse(
            challenge=challenge,
            submitter_account_id=getattr(user, 'id', 'unknown') if user else 'unknown',
            owner_account_id=getattr(owner, 'id', 'unknown') if owner else 'unknown',
            flag=flag,
        )

    def notify_error(self, operation, error_msg):
        """Send a system error alert"""
        fields = [
            {"name": "Operation", "value": str(operation), "inline": True},
            {"name": "Error", "value": f"```{str(error_msg)[:900]}```", "inline": False},
        ]
        return self.send_alert(
            title="⚠️ Container system error",
            message="An error occurred in the container system.",
            color=DEMO_COLORS['warning'],
            fields=fields,
        )

    # ------------------------------------------------------------------
    # Admin "test webhook" helpers
    # ------------------------------------------------------------------
    def send_test(self, webhook_url=None):
        return self.send_alert(
            title="✅ Connection test",
            message="Your Discord webhook is configured correctly!",
            color=DEMO_COLORS['success'],
            url=webhook_url,
        )

    def send_demo_cheat(self, webhook_url=None):
        fields = [
            {"name": "Challenge", "value": "Demo Challenge", "inline": True},
            {"name": "Submitted by account", "value": "42", "inline": True},
            {"name": "Flag owner account", "value": "7", "inline": True},
            {"name": "Action taken", "value": "Logged only (demo)", "inline": False},
        ]
        return self.send_alert(
            title="🚨 Flag sharing detected (DEMO)",
            message="This is a demo alert. No account was affected.",
            color=DEMO_COLORS['error'],
            fields=fields,
            url=webhook_url,
        )

    def send_demo_error(self, webhook_url=None):
        fields = [
            {"name": "Operation", "value": "Container Provisioning", "inline": True},
            {"name": "Error", "value": "```DockerException: Connection refused```", "inline": False},
        ]
        return self.send_alert(
            title="⚠️ Container system error (DEMO)",
            message="This is a demo alert.",
            color=DEMO_COLORS['warning'],
            fields=fields,
            url=webhook_url,
        )

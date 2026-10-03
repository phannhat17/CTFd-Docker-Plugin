"""
Anti-Cheat Service - Flag validation and cheat detection
"""
import logging

from flask import has_request_context, request

from CTFd.models import db
from ..models.config import ContainerConfig
from ..models.flag import ContainerFlag, ContainerFlagAttempt
from ..models.audit import ContainerAuditLog
from .flag_service import FlagService

logger = logging.getLogger(__name__)

#: How many detected reuses of the same flag before accounts get auto-banned.
DEFAULT_AUTOBAN_THRESHOLD = 0

#: Cap on stored failed attempts per account+challenge (keeps the table sane).
MAX_STORED_ATTEMPTS = 200


class AntiCheatService:
    """
    Service to validate flags and detect cheating
    """

    def __init__(self, flag_service: FlagService, notification_service=None):
        self.flag_service = flag_service
        self.notification_service = notification_service

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @staticmethod
    def _autoban_threshold() -> int:
        """
        Number of flag-reuse detections before accounts are banned.

        Defaults to 0 (never auto-ban). Banning is destructive and easy to
        trigger on purpose by submitting another team's flag, so it has to be
        an explicit admin decision.
        """
        raw = ContainerConfig.get('anticheat_autoban_threshold')
        if raw is None or raw == '':
            return DEFAULT_AUTOBAN_THRESHOLD
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return DEFAULT_AUTOBAN_THRESHOLD

    @staticmethod
    def _attempt_logging_enabled() -> bool:
        raw = ContainerConfig.get('anticheat_log_all_attempts', 'true')
        return str(raw).lower() != 'false'

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_flag(self, challenge_id: int, account_id: int, user_id: int,
                      submitted_flag: str, ip_address=None) -> tuple:
        """
        Validate a submitted flag.

        Args:
            ip_address: override for the request IP (used by non-HTTP callers
                        such as notifications/tests); defaults to the request.

        Returns:
            (is_correct: bool, message: str, is_cheating: bool)
        """
        from ..models.challenge import ContainerChallenge

        challenge = ContainerChallenge.query.get(challenge_id)
        if not challenge:
            return (False, "Challenge not found", False)

        submitted_flag = (submitted_flag or '').strip()
        if not submitted_flag:
            return (False, "No flag provided", False)

        if ip_address is None and has_request_context():
            ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent') if has_request_context() else None

        if challenge.flag_mode == 'static':
            return self._validate_static(
                challenge, account_id, user_id, submitted_flag, ip_address, user_agent
            )
        return self._validate_random(
            challenge, account_id, user_id, submitted_flag, ip_address, user_agent
        )

    def _new_attempt(self, challenge_id, account_id, user_id, flag_hash, ip, ua):
        return ContainerFlagAttempt(
            challenge_id=challenge_id,
            account_id=account_id,
            user_id=user_id,
            submitted_flag_hash=flag_hash,
            ip_address=ip,
            user_agent=ua,
        )

    def _finish_attempt(self, attempt=None, audit=None):
        """Persist the attempt/audit rows, tolerating unexpected DB errors."""
        if not self._attempt_logging_enabled():
            attempt = None
        try:
            if attempt is not None:
                db.session.add(attempt)
            if audit is not None:
                db.session.add(audit)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to persist flag attempt: {e}")
            db.session.rollback()

    def _validate_static(self, challenge, account_id, user_id, submitted_flag, ip, ua):
        static_flag = f"{challenge.flag_prefix or ''}{challenge.flag_suffix or ''}"
        attempt = self._new_attempt(
            challenge.id, account_id, user_id,
            self.flag_service.hash_flag(submitted_flag), ip, ua
        )

        if self.flag_service.flags_equal(submitted_flag, static_flag):
            attempt.is_correct = True
            attempt.is_cheating = False
            audit = ContainerAuditLog(
                event_type='flag_submitted_correct',
                challenge_id=challenge.id,
                account_id=account_id,
                user_id=user_id,
                details={'flag_mode': 'static', 'ip_address': ip},
                severity='info',
                ip_address=ip,
                user_agent=ua,
            )
            self._finish_attempt(attempt, audit)
            return (True, "Correct", False)

        attempt.is_correct = False
        attempt.is_cheating = False
        self._finish_attempt(attempt)
        return (False, "Incorrect", False)

    def _validate_random(self, challenge, account_id, user_id, submitted_flag, ip, ua):
        flag_hash = self.flag_service.hash_flag(submitted_flag)

        # Scope the lookup to this challenge: a flag generated for challenge A
        # must never be accepted on challenge B.
        flag_record = ContainerFlag.query.filter_by(
            flag_hash=flag_hash,
            challenge_id=challenge.id,
        ).first()

        attempt = self._new_attempt(
            challenge.id, account_id, user_id, flag_hash, ip, ua
        )

        if flag_record is None:
            attempt.is_correct = False
            attempt.is_cheating = False
            self._finish_attempt(attempt)
            logger.info(
                "Account %s submitted non-existent flag for challenge %s",
                account_id, challenge.id,
            )
            return (False, "Incorrect", False)

        if flag_record.flag_status == 'invalidated':
            attempt.is_correct = False
            attempt.is_cheating = False
            self._finish_attempt(attempt)
            logger.info(
                "Account %s submitted invalidated flag for challenge %s",
                account_id, challenge.id,
            )
            return (False, "This flag has expired", False)

        if flag_record.account_id != account_id:
            # Somebody else's flag. Flag it, notify, but do NOT ban here: a
            # third party can submit a victim's flag and would otherwise get
            # the victim banned on purpose.
            return self._handle_flag_reuse(
                challenge, flag_record, account_id, user_id, attempt, ip, ua, submitted_flag
            )

        # Own flag
        if flag_record.flag_status == 'submitted_correct':
            attempt.is_correct = True
            attempt.is_cheating = False
            self._finish_attempt(attempt)
            return (True, "Already solved", False)

        flag_record.mark_as_submitted(user_id, ip)

        attempt.is_correct = True
        attempt.is_cheating = False
        audit = ContainerAuditLog(
            event_type='flag_submitted_correct',
            instance_id=flag_record.instance_id,
            challenge_id=challenge.id,
            account_id=account_id,
            user_id=user_id,
            details={'ip_address': ip},
            severity='info',
            ip_address=ip,
            user_agent=ua,
        )
        self._finish_attempt(attempt, audit)
        logger.info("Account %s correctly solved challenge %s", account_id, challenge.id)
        return (True, "Correct!", False)

    def _handle_flag_reuse(self, challenge, flag_record, account_id, user_id, attempt, ip, ua, submitted_flag):
        """Record a flag-reuse detection and decide whether to ban."""
        attempt.is_correct = False
        attempt.is_cheating = True
        attempt.flag_owner_account_id = flag_record.account_id

        threshold = self._autoban_threshold()
        if threshold > 0:
            prior = ContainerFlagAttempt.query.filter_by(
                challenge_id=challenge.id,
                account_id=account_id,
                is_cheating=True,
            ).count()
            ban_applied = (prior + 1) >= threshold
        else:
            ban_applied = False

        if ban_applied:
            self._ban_accounts(challenge, flag_record, account_id, threshold)

        audit = ContainerAuditLog(
            event_type='flag_reuse_detected',
            challenge_id=challenge.id,
            account_id=account_id,
            user_id=user_id,
            details={
                'submitted_flag_hash': attempt.submitted_flag_hash,
                'actual_owner_account_id': flag_record.account_id,
                'flag_status': flag_record.flag_status,
                'ip_address': ip,
                'action_taken': 'accounts_banned' if ban_applied else 'logged_only',
            },
            severity='critical' if ban_applied else 'warning',
            ip_address=ip,
            user_agent=ua,
        )
        self._finish_attempt(attempt, audit)

        logger.warning(
            "FLAG REUSE: account %s submitted the flag of account %s on challenge %s (%s)",
            account_id, flag_record.account_id, challenge.id,
            "accounts banned" if ban_applied else "logged only",
        )

        if self.notification_service:
            try:
                self.notification_service.notify_flag_reuse(
                    challenge=challenge,
                    submitter_account_id=account_id,
                    owner_account_id=flag_record.account_id,
                    flag=submitted_flag,
                    banned=ban_applied,
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to send flag-reuse notification: {e}")

        # Never tell the submitter that reuse was detected, so the message stays
        # "Incorrect". The third value reports the detection itself and is True
        # whether or not a ban was applied.
        return (False, "Incorrect", True)

    def _ban_accounts(self, challenge, flag_record, account_id, threshold):
        """Ban both accounts involved in a confirmed flag-reuse pattern."""
        from CTFd.models import Teams, Users
        from CTFd.utils import get_config

        is_team_mode = get_config('user_mode') == 'teams'

        if is_team_mode:
            for team_id in {account_id, flag_record.account_id}:
                team = Teams.query.get(team_id)
                if team:
                    team.banned = True
                for member in Users.query.filter_by(team_id=team_id).all():
                    member.banned = True
            logger.critical(
                "BANNED teams %s and %s for repeated flag reuse (threshold %s)",
                account_id, flag_record.account_id, threshold,
            )
        else:
            for uid in {account_id, flag_record.account_id}:
                user = Users.query.get(uid)
                if user:
                    user.banned = True
            logger.critical(
                "BANNED users %s and %s for repeated flag reuse (threshold %s)",
                account_id, flag_record.account_id, threshold,
            )

    # ------------------------------------------------------------------
    # Reading helpers
    # ------------------------------------------------------------------
    def get_cheat_attempts(self, limit=100):
        """Get recent cheat attempts"""
        return ContainerFlagAttempt.query.filter_by(
            is_cheating=True
        ).order_by(
            ContainerFlagAttempt.timestamp.desc()
        ).limit(limit).all()

    def get_account_attempts(self, account_id, challenge_id=None):
        """Get flag attempts for an account"""
        query = ContainerFlagAttempt.query.filter_by(account_id=account_id)
        if challenge_id:
            query = query.filter_by(challenge_id=challenge_id)
        return query.order_by(ContainerFlagAttempt.timestamp.desc()).all()

    def prune_attempts(self):
        """Drop the oldest failed attempts, keeping the table bounded."""
        try:
            total = ContainerFlagAttempt.query.count()
            if total <= MAX_STORED_ATTEMPTS * 50:
                return 0
            cutoff = ContainerFlagAttempt.query.order_by(
                ContainerFlagAttempt.timestamp.desc()
            ).offset(MAX_STORED_ATTEMPTS * 50).limit(1).first()
            if not cutoff:
                return 0
            deleted = ContainerFlagAttempt.query.filter(
                ContainerFlagAttempt.timestamp < cutoff.timestamp
            ).delete(synchronize_session=False)
            db.session.commit()
            logger.info(f"Pruned {deleted} old flag attempts")
            return deleted
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to prune flag attempts: {e}")
            db.session.rollback()
            return 0

"""
Anti-Cheat Service - Flag validation và cheat detection
"""
import logging
from datetime import datetime
from flask import request
from CTFd.models import db
from ..models.flag import ContainerFlag, ContainerFlagAttempt
from ..models.audit import ContainerAuditLog
from .flag_service import FlagService

logger = logging.getLogger(__name__)


class AntiCheatService:
    """
    Service để validate flags và detect cheating
    """
    
    def __init__(self, flag_service: FlagService):
        self.flag_service = flag_service
    
    def validate_flag(
        self,
        challenge_id: int,
        account_id: int,
        user_id: int,
        submitted_flag: str
    ) -> tuple:
        """
        Validate submitted flag
        
        Args:
            challenge_id: Challenge ID
            account_id: Team/User ID
            user_id: Actual user submitting
            submitted_flag: Submitted flag text
        
        Returns:
            (is_correct: bool, message: str, is_cheating: bool)
        """
        # 1. Hash submitted flag
        flag_hash = FlagService.hash_flag(submitted_flag)
        ip_address = request.remote_addr if request else None
        user_agent = request.headers.get('User-Agent') if request else None
        
        # 2. Find flag in database
        flag_record = ContainerFlag.query.filter_by(flag_hash=flag_hash).first()
        
        # 3. Create attempt log (always)
        attempt = ContainerFlagAttempt(
            challenge_id=challenge_id,
            account_id=account_id,
            user_id=user_id,
            submitted_flag_hash=flag_hash,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # 4. Flag không tồn tại → wrong
        if not flag_record:
            attempt.is_correct = False
            attempt.is_cheating = False
            db.session.add(attempt)
            db.session.commit()
            
            logger.info(f"Account {account_id} submitted non-existent flag for challenge {challenge_id}")
            return (False, "Incorrect", False)
        
        # 5. Flag đã invalidated → expired
        if flag_record.flag_status == 'invalidated':
            attempt.is_correct = False
            attempt.is_cheating = False
            db.session.add(attempt)
            db.session.commit()
            
            logger.info(f"Account {account_id} submitted invalidated flag for challenge {challenge_id}")
            return (False, "This flag has expired", False)
        
        # 6. Flag thuộc account khác → CHEATING
        if flag_record.account_id != account_id:
            attempt.is_correct = False
            attempt.is_cheating = True
            attempt.flag_owner_account_id = flag_record.account_id
            
            # BAN cả 2 accounts (cheater và flag owner - possible collaborator)
            from CTFd.models import Teams, Users
            from CTFd.utils import get_config
            
            mode = get_config('user_mode')
            is_team_mode = (mode == 'teams')
            
            if is_team_mode:
                # Ban cả 2 teams và TẤT CẢ members của 2 teams đó
                cheater_team = Teams.query.get(account_id)
                owner_team = Teams.query.get(flag_record.account_id)
                
                if cheater_team:
                    cheater_team.banned = True
                    # Ban tất cả users trong team
                    cheater_members = Users.query.filter_by(team_id=account_id).all()
                    for member in cheater_members:
                        member.banned = True
                    logger.critical(f"BANNED team {account_id} ({cheater_team.name}) and {len(cheater_members)} members for flag reuse")
                
                if owner_team:
                    owner_team.banned = True
                    # Ban tất cả users trong team
                    owner_members = Users.query.filter_by(team_id=flag_record.account_id).all()
                    for member in owner_members:
                        member.banned = True
                    logger.critical(f"BANNED team {flag_record.account_id} ({owner_team.name}) and {len(owner_members)} members for possible flag sharing")
            else:
                # Ban cả 2 users
                cheater_user = Users.query.get(account_id)
                owner_user = Users.query.get(flag_record.account_id)
                
                if cheater_user:
                    cheater_user.banned = True
                    logger.critical(f"BANNED user {account_id} ({cheater_user.name}) for flag reuse")
                
                if owner_user:
                    owner_user.banned = True
                    logger.critical(f"BANNED user {flag_record.account_id} ({owner_user.name}) for possible flag sharing")
            
            # Audit log với severity critical
            audit_log = ContainerAuditLog(
                event_type='flag_reuse_detected',
                challenge_id=challenge_id,
                account_id=account_id,
                user_id=user_id,
                details={
                    'submitted_flag_hash': flag_hash,
                    'actual_owner_account_id': flag_record.account_id,
                    'flag_status': flag_record.flag_status,
                    'ip_address': ip_address,
                    'action_taken': 'both_accounts_banned'
                },
                severity='critical',
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            db.session.add(attempt)
            db.session.add(audit_log)
            db.session.commit()
            
            logger.warning(
                f"CHEAT DETECTED: Account {account_id} submitted flag belonging to {flag_record.account_id} "
                f"for challenge {challenge_id} - BOTH ACCOUNTS BANNED"
            )
            
            # Không tiết lộ cho user biết flag reuse được phát hiện
            return (False, "Incorrect", True)
        
        # 7. Flag đúng và thuộc account này
        if flag_record.account_id == account_id:
            # 7.1. Đã submit rồi (duplicate)
            if flag_record.flag_status == 'submitted_correct':
                attempt.is_correct = True
                attempt.is_cheating = False
                db.session.add(attempt)
                db.session.commit()
                
                logger.info(f"Account {account_id} re-submitted already solved challenge {challenge_id}")
                return (True, "Already solved", False)
            
            # 7.2. Lần đầu submit đúng
            flag_record.mark_as_submitted(user_id, ip_address)
            
            # Note: Do NOT update instance status here
            # The ContainerService.stop_instance() will handle it when called after validation
            # This allows __init__.py to find instance with status='running' to stop it
            
            attempt.is_correct = True
            attempt.is_cheating = False
            
            # Audit log
            audit_log = ContainerAuditLog(
                event_type='flag_submitted_correct',
                instance_id=flag_record.instance_id,
                challenge_id=challenge_id,
                account_id=account_id,
                user_id=user_id,
                details={'ip_address': ip_address},
                severity='info',
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            db.session.add(attempt)
            db.session.add(audit_log)
            db.session.commit()
            
            logger.info(f"Account {account_id} correctly solved challenge {challenge_id}")
            
            return (True, "Correct!", False)
        
        # 8. Fallback
        return (False, "Unexpected error", False)
    
    def get_cheat_attempts(self, limit=100):
        """
        Get recent cheat attempts
        
        Returns:
            List of ContainerFlagAttempt records where is_cheating=True
        """
        return ContainerFlagAttempt.query.filter_by(
            is_cheating=True
        ).order_by(
            ContainerFlagAttempt.timestamp.desc()
        ).limit(limit).all()
    
    def get_account_attempts(self, account_id, challenge_id=None):
        """
        Get flag attempts for an account
        
        Args:
            account_id: Account ID
            challenge_id: Optional challenge filter
        
        Returns:
            List of attempts
        """
        query = ContainerFlagAttempt.query.filter_by(account_id=account_id)
        
        if challenge_id:
            query = query.filter_by(challenge_id=challenge_id)
        
        return query.order_by(ContainerFlagAttempt.timestamp.desc()).all()

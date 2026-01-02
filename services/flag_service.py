"""
Flag Service - Flag generation and encryption
"""
import hashlib
import random
import string
import logging
from cryptography.fernet import Fernet
from CTFd.models import db
from ..models.config import ContainerConfig

logger = logging.getLogger(__name__)


class FlagService:
    """
    Service to generate and manage flags
    """
    
    def __init__(self):
        """Initialize flag service"""
        # Get or create encryption key
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key.encode())
    
    def _get_or_create_encryption_key(self) -> str:
        """Get encryption key from config or create new one"""
        key = ContainerConfig.get('flag_encryption_key')
        if not key:
            # Generate new Fernet key
            key = Fernet.generate_key().decode()
            ContainerConfig.set('flag_encryption_key', key)
            logger.info("Generated new flag encryption key")
        return key
    
    def generate_flag(self, challenge, mode='random') -> str:
        """
        Generate flag for challenge
        
        Args:
            challenge: ContainerChallenge object
            mode: 'random' or 'static'
        
        Returns:
            Plain text flag
        """
        if mode == 'static' or challenge.flag_mode == 'static':
            # Static flag: just prefix + suffix
            flag = f"{challenge.flag_prefix}{challenge.flag_suffix}"
        else:
            # Random flag
            length = challenge.random_flag_length or 16
            random_part = ''.join(
                random.choices(string.ascii_letters + string.digits, k=length)
            )
            flag = f"{challenge.flag_prefix}{random_part}{challenge.flag_suffix}"
        
        return flag
    
    def encrypt_flag(self, flag: str) -> str:
        """
        Encrypt flag for storage
        
        Args:
            flag: Plain text flag
        
        Returns:
            Encrypted flag (base64 encoded)
        """
        encrypted = self.cipher.encrypt(flag.encode())
        return encrypted.decode()
    
    def decrypt_flag(self, encrypted_flag: str) -> str:
        """
        Decrypt flag
        
        Args:
            encrypted_flag: Encrypted flag
        
        Returns:
            Plain text flag
        """
        try:
            decrypted = self.cipher.decrypt(encrypted_flag.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Failed to decrypt flag: {e}")
            raise Exception("Failed to decrypt flag")
    
    @staticmethod
    def hash_flag(flag: str) -> str:
        """
        Hash flag using SHA256
        
        Args:
            flag: Plain text flag
        
        Returns:
            Hex digest of flag hash
        """
        return hashlib.sha256(flag.encode()).hexdigest()
    
    def create_flag_record(self, instance, challenge, account_id, flag_plaintext):
        """
        Create flag record in database
        
        Args:
            instance: ContainerInstance object
            challenge: ContainerChallenge object
            account_id: Team or user ID
            flag_plaintext: Plain text flag
        
        Returns:
            ContainerFlag object
        """
        from ..models.flag import ContainerFlag
        
        flag_hash = self.hash_flag(flag_plaintext)
        flag_encrypted = self.encrypt_flag(flag_plaintext)
        
        flag_record = ContainerFlag(
            instance_id=instance.id,
            flag_hash=flag_hash,
            challenge_id=challenge.id,
            account_id=account_id,
            flag_status='temporary'
        )
        
        db.session.add(flag_record)
        db.session.flush()  # Get the ID
        
        return flag_record

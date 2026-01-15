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
    
    def generate_flag(self, challenge, account_id=None) -> str:
        """
        Generate flag for challenge
        
        Args:
            challenge: ContainerChallenge object
            account_id: Team or User ID (optional, but recommended for uniqueness)
        
        Returns:
            Plain text flag
        """
        import secrets
        import hmac
        import hashlib
        
        if challenge.flag_mode == 'static':
            # Static flag: just prefix + suffix
            return f"{challenge.flag_prefix}{challenge.flag_suffix}"
            
        # Random flag
        length = challenge.random_flag_length or 16
        alphabet = string.ascii_letters + string.digits
        random_part = ''.join(secrets.choice(alphabet) for _ in range(length))
        
        # If account_id is provided, append a unique fingerprint based on account + challenge
        # This ensures TWO users never get the same flag even if they random the same string
        if account_id:
            # Use encryption key as salt for HMAC
            salt = self.encryption_key.encode()
            msg = f"{account_id}:{challenge.id}".encode()
            fingerprint = hmac.new(salt, msg, hashlib.sha256).hexdigest()[:8]
            
            # Combine: prefix + random + fingerprint + suffix
            # We insert the fingerprint before the suffix
            flag = f"{challenge.flag_prefix}{random_part}_{fingerprint}{challenge.flag_suffix}"
        else:
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

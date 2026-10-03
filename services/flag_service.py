"""
Flag Service - Flag generation, storage and comparison
"""
import hashlib
import hmac
import logging
import secrets

from cryptography.fernet import Fernet

from CTFd.models import db
from ..models.config import ContainerConfig

logger = logging.getLogger(__name__)

#: Characters used for the random part of a per-account flag. Ambiguous
#: glyphs (0/O, 1/l/I) are excluded so flags can be copied by hand.
FLAG_ALPHABET = (
    "abcdefghijkmnopqrstuvwxyz"
    "ABCDEFGHJKLMNPQRSTUVWXYZ"
    "23456789"
)

MIN_RANDOM_LENGTH = 8


class FlagService:
    """
    Service to generate and manage flags
    """

    def __init__(self):
        """Initialize flag service"""
        # Get or create encryption key
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key.encode())
        # Separate key used to hash stored flags so a DB leak does not let an
        # attacker recognise/replay flags. Derived from the Fernet key so no
        # additional secret has to be managed.
        self._hash_key = hashlib.sha256(
            b"ctfd-containers-flag-hash:" + self.encryption_key.encode()
        ).digest()

    def _get_or_create_encryption_key(self) -> str:
        """Get encryption key from config or create new one"""
        key = ContainerConfig.get('flag_encryption_key')
        if not key:
            # Generate new Fernet key
            key = Fernet.generate_key().decode()
            ContainerConfig.set('flag_encryption_key', key)
            logger.info("Generated new flag encryption key")
        return key

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate_flag(self, challenge, account_id=None) -> str:
        """
        Generate flag for challenge

        Args:
            challenge: ContainerChallenge object
            account_id: Team or User ID (optional, but recommended for uniqueness)

        Returns:
            Plain text flag
        """
        prefix = challenge.flag_prefix or ''
        suffix = challenge.flag_suffix or ''

        if challenge.flag_mode == 'static':
            # Static flag: just prefix + suffix
            return f"{prefix}{suffix}"

        length = int(challenge.random_flag_length or 0)
        if length < MIN_RANDOM_LENGTH:
            # A short random part is guessable; bump it to the safe minimum.
            logger.warning(
                "random_flag_length=%s is below the safe minimum (%s); using %s",
                length, MIN_RANDOM_LENGTH, MIN_RANDOM_LENGTH,
            )
            length = MIN_RANDOM_LENGTH

        random_part = ''.join(secrets.choice(FLAG_ALPHABET) for _ in range(length))
        return f"{prefix}{random_part}{suffix}"

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------
    def encrypt_flag(self, flag: str) -> str:
        """Encrypt a flag for storage"""
        return self.cipher.encrypt(flag.encode()).decode()

    def decrypt_flag(self, encrypted_flag: str) -> str:
        """Decrypt a stored flag"""
        try:
            return self.cipher.decrypt(encrypted_flag.encode()).decode()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to decrypt flag: {e}")
            raise Exception("Failed to decrypt flag")

    def hash_flag(self, flag: str) -> str:
        """
        Keyed hash of a flag (hex digest).

        Uses HMAC-SHA256 keyed with a value derived from the plugin key rather
        than a bare SHA256, so the stored digests cannot be attacked with a
        precomputed table if the database leaks.
        """
        return hmac.new(self._hash_key, flag.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def flags_equal(a: str, b: str) -> bool:
        """Constant-time comparison for flag strings."""
        return hmac.compare_digest(a or '', b or '')

    def create_flag_record(self, instance, challenge, account_id, flag_plaintext):
        """
        Create flag record in database

        Returns:
            ContainerFlag object
        """
        from ..models.flag import ContainerFlag

        flag_hash = self.hash_flag(flag_plaintext)

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

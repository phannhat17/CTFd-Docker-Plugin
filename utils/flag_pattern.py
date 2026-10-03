"""
Flag pattern helpers shared by the admin UI, the CSV/Excel importer and the
model validation.

Patterns look like ``CTF{prefix_<ran_16>_suffix}``; ``<ran_N>`` is replaced by
N random characters. Anything without ``<ran_N>`` is a static flag.
"""
import re

RANDOM_TOKEN_RE = re.compile(r'<ran_(\d+)>')

#: Smallest random part we are willing to generate.
MIN_RANDOM_LENGTH = 8
#: Largest random part we accept from a pattern (keeps flags copyable).
MAX_RANDOM_LENGTH = 128


def parse_flag_pattern(pattern: str) -> dict:
    """
    Parse an admin supplied flag pattern.

    Returns a dict with ``flag_mode``, ``flag_prefix``, ``flag_suffix`` and
    ``random_flag_length``.
    """
    pattern = pattern if pattern is not None else ''

    match = RANDOM_TOKEN_RE.search(pattern)
    if not match:
        return {
            'flag_mode': 'static',
            'flag_prefix': pattern,
            'flag_suffix': '',
            'random_flag_length': 0,
        }

    prefix, _, suffix = pattern.partition(match.group(0))
    try:
        length = int(match.group(1))
    except (TypeError, ValueError):
        length = MIN_RANDOM_LENGTH

    length = max(MIN_RANDOM_LENGTH, min(MAX_RANDOM_LENGTH, length))
    return {
        'flag_mode': 'random',
        'flag_prefix': prefix,
        'flag_suffix': suffix,
        'random_flag_length': length,
    }


def build_flag_pattern(mode, prefix, suffix, length) -> str:
    """Rebuild the editable pattern string for the update form."""
    prefix = prefix or ''
    suffix = suffix or ''
    if mode == 'random' and length:
        return f"{prefix}<ran_{length}>{suffix}"
    return f"{prefix}{suffix}"

import hashlib
import hmac
import re
import secrets
from functools import lru_cache


PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 256
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def normalize_email(value: str) -> str:
    return value.strip().lower()


def is_valid_email(value: str) -> bool:
    return len(value) <= 320 and bool(_EMAIL_PATTERN.match(value))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Used to spend the same time on unknown emails as on real ones during login."""
    return hash_password(secrets.token_urlsafe(24))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_api_key(kind: str) -> str:
    prefix = "llm_" if kind == "ingest" else "llrt_"
    return prefix + secrets.token_urlsafe(32)


def hash_token(value: str) -> str:
    """Hash for storage. Tokens are 256-bit random values, so a fast hash is sufficient and allows indexed lookup."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def display_prefix(value: str) -> str:
    return value[:8]

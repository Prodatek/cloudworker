import hashlib
import secrets

import bcrypt

_API_KEY_PREFIX = "cw_live_"
_API_KEY_DISPLAY_PREFIX_LENGTH = 12


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def generate_api_key() -> str:
    return f"{_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """API keys are already high-entropy random tokens, so a fast hash (not bcrypt) is
    sufficient and standard practice (same approach GitHub/Stripe use for tokens) — it
    lets lookup-by-hash use a plain unique index instead of scanning + per-row bcrypt checks.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def api_key_display_prefix(api_key: str) -> str:
    return api_key[:_API_KEY_DISPLAY_PREFIX_LENGTH]

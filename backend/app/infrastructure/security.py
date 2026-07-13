import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

_API_KEY_PREFIX = "cw_live_"
_API_KEY_DISPLAY_PREFIX_LENGTH = 12


class InvalidAccessTokenError(Exception):
    """Raised when a JWT is malformed, unsigned by us, or expired."""


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


def looks_like_api_key(token: str) -> bool:
    """Distinguishes an API key from a JWT in a shared Authorization: Bearer header —
    API keys always carry this prefix (see generate_api_key); JWTs never do.
    """
    return token.startswith(_API_KEY_PREFIX)


def create_access_token(
    user_id: uuid.UUID, secret_key: str, algorithm: str, expiry_minutes: int
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(token: str, secret_key: str, algorithm: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidAccessTokenError("Invalid or expired access token") from exc

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from env_settings import get_settings

SESSION_COOKIE = "wine_cellar_session"
HASH_ITERATIONS = 100_000


def validate_configuration() -> None:
    settings = get_settings()
    username = settings.cellar_username
    password = settings.cellar_password
    secret = settings.cellar_session_secret
    if not username:
        raise ValueError("CELLAR_USERNAME must be configured before starting the application.")
    if not password:
        raise ValueError("CELLAR_PASSWORD must be configured before starting the application.")
    if len(password) < 10:
        raise ValueError("CELLAR_PASSWORD must contain at least 10 characters.")
    if not secret:
        raise ValueError("CELLAR_SESSION_SECRET must be configured before starting the application.")
    if len(secret) < 32:
        raise ValueError("CELLAR_SESSION_SECRET must contain at least 32 characters.")


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a unique random salt."""
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, HASH_ITERATIONS
    )
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, hashed: Optional[str]) -> bool:
    """Verify plain password against a stored PBKDF2 hash."""
    if not hashed or not password:
        return False
    try:
        parts = hashed.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return secrets.compare_digest(derived, expected)
    except Exception:
        return False


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_credentials(username: str, password: str, db=None) -> bool:
    """
    Verify user credentials against environment admin configuration or SQLite users.
    """
    validate_configuration()
    settings = get_settings()
    configured_username = settings.cellar_username
    configured_password = settings.cellar_password

    if secrets.compare_digest(username, configured_username) and secrets.compare_digest(
        password, configured_password
    ):
        return True

    if db is not None:
        from models import User, UserStatus
        from sqlalchemy import func

        user = (
            db.query(User)
            .filter(
                (func.lower(User.username) == username.strip().lower())
                | (func.lower(User.email) == username.strip().lower())
            )
            .first()
        )
        if user and user.status == UserStatus.APPROVED and user.hashed_password:
            return verify_password(password, user.hashed_password)

    return False


def create_session_token(username: Optional[str] = None, role: str = "admin") -> str:
    """
    Generate an HMAC-signed session token for the user.
    Defaults to the root cellar admin if username is omitted.
    """
    validate_configuration()
    settings = get_settings()
    secret = settings.cellar_session_secret

    if username is None:
        username = settings.cellar_username
        role = "admin"

    expires_at = int(time.time()) + session_ttl_seconds()
    payload = json.dumps(
        [username, expires_at, secrets.token_urlsafe(16), role],
        separators=(",", ":"),
    ).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{encoded_payload}.{_sign(payload, secret)}"


def decode_session_token(token: Optional[str]) -> Optional[dict]:
    """
    Validate HMAC signature and parse payload. Returns user session dict if valid.
    """
    if not token or "." not in token:
        return None

    try:
        secret = get_settings().cellar_session_secret
        if len(secret) < 32:
            return None

        encoded_payload, supplied_signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        expected_signature = _sign(payload, secret)
        if not secrets.compare_digest(supplied_signature, expected_signature):
            return None

        data = json.loads(payload)
        if not isinstance(data, list) or len(data) < 3:
            return None

        username = data[0]
        expires_at = data[1]
        nonce = data[2]
        role = data[3] if len(data) > 3 else "user"

        if not isinstance(username, str) or not username:
            return None
        if not bool(nonce) or int(expires_at) <= int(time.time()):
            return None

        return {
            "username": username,
            "expires_at": expires_at,
            "nonce": nonce,
            "role": role,
        }
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def validate_session_token(token: Optional[str]) -> bool:
    """Boolean check for session token validity and expiration."""
    return decode_session_token(token) is not None


def secure_cookie_enabled() -> bool:
    return get_settings().cookie_secure


def session_ttl_seconds() -> int:
    return get_settings().session_ttl_hours * 60 * 60

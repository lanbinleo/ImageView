"""密码哈希与无状态会话 Cookie。"""

import hashlib
import hmac
import secrets
import time

PBKDF2_ROUNDS = 200_000
COOKIE_NAME = "ir_sess"
SESSION_TTL = 30 * 24 * 3600


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, rounds, salt, digest = stored.split("$")
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, digest)


def make_session(secret: str, ttl: int = SESSION_TTL) -> str:
    expires = str(int(time.time()) + ttl)
    sig = hmac.new(secret.encode(), expires.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def check_session(secret: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires, sig = token.split(".", 1)
    expected = hmac.new(secret.encode(), expires.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(expires) > time.time()
    except ValueError:
        return False

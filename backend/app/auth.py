"""Optional accounts: scrypt password hashes and signed (JWT) bearer tokens.

Signing in is never required to use the agent. It adds conversation sync across
devices and per-user rate limits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

from app.config import get_settings

logger = logging.getLogger(__name__)

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


@dataclass(frozen=True)
class User:
    id: int
    username: str


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), dklen=32, **_SCRYPT)
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except Exception:
        return False


@lru_cache
def _secret() -> str:
    key = get_settings().secret_key
    if not key:
        logger.warning("SECRET_KEY is not set: using a random key, so sign-ins reset on restart.")
        key = secrets.token_urlsafe(32)
    return key


def create_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": str(user.id), "name": user.username, "iat": now,
               "exp": now + get_settings().token_ttl_days * 86400}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token: str) -> User | None:
    try:
        data = jwt.decode(token, _secret(), algorithms=["HS256"])
        return User(id=int(data["sub"]), username=data["name"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def optional_user(authorization: str | None = Header(None)) -> User | None:
    """FastAPI dependency: the signed-in user, or None for anonymous use.

    A token that is present but invalid (expired, forged) is an error rather than
    silently anonymous, so the frontend can ask the user to sign in again.
    """
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    user = decode_token(token) if scheme.lower() == "bearer" else None
    if user is None:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return user


def required_user(authorization: str | None = Header(None)) -> User:
    user = optional_user(authorization)
    if user is None:
        raise HTTPException(401, "Sign in to use this feature.")
    return user

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import hashlib
import secrets

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: UUID, role: str, department_id: UUID | None, tenant_id: UUID | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "department_id": str(department_id) if department_id else None,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def create_sse_token(user_id: UUID, tenant_id: UUID, ttl_seconds: int = 120) -> str:
    """A narrowly-scoped, short-lived token for authorizing a single SSE
    connection via a URL query parameter (browser EventSource cannot set an
    Authorization header). Marked with type="sse" so get_current_user
    explicitly refuses it as a general bearer token — a short-lived value
    that still ends up in a server access log or browser history must not
    be usable to call the rest of the API."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "type": "sse",
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: UUID, session_id: UUID) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.refresh_expire_days)
    token = jwt.encode({"sub": str(user_id), "sid": str(session_id), "jti": str(uuid4()), "type": "refresh", "iat": now, "exp": expires}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)

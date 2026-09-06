from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User
from app.core.rbac import has_permission

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> User:
    try:
        payload = decode_access_token(token)
        if payload.get("type") == "sse":
            # A narrowly-scoped SSE connection token must never work as a general bearer token.
            raise _CREDENTIALS_ERROR
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _CREDENTIALS_ERROR

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


async def get_user_from_sse_token(token: str, db: AsyncSession) -> User:
    """Authorizes a single SSE connection from its query-parameter token.
    Accepts only a token minted by create_sse_token — a normal access token
    presented here is rejected, keeping the two token types non-interchangeable."""
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "sse":
            raise _CREDENTIALS_ERROR
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _CREDENTIALS_ERROR

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


def require_role(*roles: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this action",
            )
        return user

    return _check


def require_permission(permission: str):
    async def _check(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
        if not await user_has_permission(db, user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permission for this action",
            )
        return user

    return _check


async def user_has_permission(db: AsyncSession, user: User, permission: str) -> bool:
    """Resolve a permission from the persisted role grants.

    The static catalogue remains a fail-safe for installations upgrading from
    pre-RBAC schemas, while database grants permit least-privilege Admin accounts.
    """
    if not user.tenant_id:
        return False
    result = await db.scalar(text("""
        SELECT EXISTS(
          SELECT 1 FROM user_roles ur
          JOIN role_permissions rp ON rp.role_id=ur.role_id
          JOIN permissions p ON p.id=rp.permission_id
          WHERE ur.user_id=:uid AND ur.tenant_id=:tid AND p.code=:permission
        ) OR EXISTS(
          SELECT 1 FROM user_capability_bundles ucb
          JOIN capability_bundle_permissions cbp ON cbp.bundle_id=ucb.bundle_id
          JOIN permissions p ON p.id=cbp.permission_id
          JOIN capability_bundles cb ON cb.id=ucb.bundle_id
          WHERE ucb.user_id=:uid AND ucb.tenant_id=:tid AND cb.is_active=true AND p.code=:permission
        )
    """), {"uid": user.id, "tid": user.tenant_id, "permission": permission})
    return bool(result) or has_permission(user.role, permission)

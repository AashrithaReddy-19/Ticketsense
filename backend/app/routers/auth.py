from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Header, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_access_token, hash_password, hash_token, new_csrf_token, verify_password
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.platform import AuditLog, Organization
from app.schemas.auth import Token, UserCreate, UserPublic

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "ticketsense_refresh"
CSRF_COOKIE = "ticketsense_csrf"


def _set_session_cookies(response: Response, refresh_token: str, csrf: str) -> None:
    max_age = settings.refresh_expire_days * 86400
    response.set_cookie(REFRESH_COOKIE, refresh_token, max_age=max_age, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/api/auth")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=settings.cookie_secure, samesite="lax", path="/")


async def _permissions(db: AsyncSession, user: User) -> list[str]:
    rows = await db.scalars(text("""SELECT DISTINCT p.code FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id JOIN roles r ON r.id=rp.role_id JOIN user_roles ur ON ur.role_id=r.id WHERE ur.user_id=:uid AND ur.tenant_id=:tid ORDER BY p.code""").bindparams(uid=user.id, tid=user.tenant_id))
    return list(rows)


async def _create_session(db: AsyncSession, user: User, request: Request, response: Response) -> str:
    session_id = uuid4(); refresh, expires = create_refresh_token(user.id, session_id); csrf = new_csrf_token()
    await db.execute(text("""INSERT INTO auth_sessions(id,user_id,token_hash,csrf_hash,ip_address,user_agent,expires_at) VALUES(:id,:uid,:token,:csrf,:ip,:ua,:expires)"""), {"id":session_id,"uid":user.id,"token":hash_token(refresh),"csrf":hash_token(csrf),"ip":request.client.host if request.client else None,"ua":request.headers.get("user-agent","")[:512],"expires":expires})
    _set_session_cookies(response, refresh, csrf)
    return refresh


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # Self-service registration is Customer only. Elevated accounts are provisioned by admins.
    # are created via the seed/admin path, not this endpoint.
    tenant = await db.scalar(select(Organization).where(Organization.slug == "ticketsense-demo"))
    if tenant is None:
        raise HTTPException(status_code=503, detail="No registration tenant is configured")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        role="customer",
        tenant_id=tenant.id,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    await db.execute(text("""INSERT INTO user_roles(user_id,role_id,tenant_id) SELECT :uid,r.id,:tid FROM roles r WHERE r.name='customer'"""), {"uid":user.id,"tid":tenant.id})
    db.add(AuditLog(tenant_id=tenant.id,user_id=user.id,action="auth.register",resource_type="user",resource_id=str(user.id),metadata_json={}))
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    request: Request, response: Response, form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
) -> Token:
    user = await db.scalar(select(User).where(User.email == form_data.username))
    now = datetime.now(timezone.utc)
    if user is not None and user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=429, detail="Sign-in is temporarily unavailable for this account. Try again later.")
    if user is None or not user.is_active or not verify_password(form_data.password, user.hashed_password):
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            if user.tenant_id:
                db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="auth.login_failed",resource_type="user",resource_id=str(user.id),metadata_json={"locked": bool(user.locked_until),"ip":request.client.host if request.client else None}))
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.failed_login_count = 0; user.locked_until = None
    await _create_session(db, user, request, response)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="auth.login", resource_type="session", metadata_json={"ip": request.client.host if request.client else None}))
    await db.commit()
    token = create_access_token(user.id, user.role, user.department_id, user.tenant_id)
    return Token(access_token=token)


@router.post("/refresh", response_model=Token)
async def refresh(request: Request, response: Response, x_csrf_token: str | None = Header(None), db: AsyncSession = Depends(get_db)) -> Token:
    raw = request.cookies.get(REFRESH_COOKIE); csrf = request.cookies.get(CSRF_COOKIE)
    if not raw or not csrf or not x_csrf_token or csrf != x_csrf_token:
        raise HTTPException(status_code=401, detail="Refresh session is unavailable")
    try:
        payload = decode_access_token(raw)
        if payload.get("type") != "refresh": raise ValueError()
        session_id, user_id = UUID(payload["sid"]), UUID(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh session is invalid")
    row = (await db.execute(text("SELECT token_hash,csrf_hash,revoked_at,expires_at FROM auth_sessions WHERE id=:id FOR UPDATE"), {"id":session_id})).mappings().first()
    if not row or row["token_hash"] != hash_token(raw) or row["csrf_hash"] != hash_token(csrf) or row["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh session is invalid")
    if row["revoked_at"] is not None:
        await db.execute(text("UPDATE auth_sessions SET reuse_detected_at=now() WHERE id=:id"), {"id":session_id})
        await db.execute(text("UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at,now()) WHERE user_id=:uid"), {"uid":user_id})
        user = await db.get(User,user_id)
        if user and user.tenant_id: db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="auth.refresh_reuse",resource_type="session",resource_id=str(session_id),metadata_json={}))
        await db.commit()
        raise HTTPException(status_code=401, detail="Refresh-token reuse detected; session revoked")
    user = await db.get(User, user_id)
    if not user or not user.is_active: raise HTTPException(status_code=401, detail="Account is unavailable")
    new_id = uuid4(); await db.execute(text("UPDATE auth_sessions SET revoked_at=now(),replaced_by_id=:new,last_used_at=now() WHERE id=:old"), {"new":new_id,"old":session_id})
    refresh_token, expires = create_refresh_token(user.id, new_id); new_csrf = new_csrf_token()
    await db.execute(text("INSERT INTO auth_sessions(id,user_id,token_hash,csrf_hash,ip_address,user_agent,expires_at) VALUES(:id,:uid,:token,:csrf,:ip,:ua,:expires)"), {"id":new_id,"uid":user.id,"token":hash_token(refresh_token),"csrf":hash_token(new_csrf),"ip":request.client.host if request.client else None,"ua":request.headers.get("user-agent","")[:512],"expires":expires})
    db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="auth.refresh",resource_type="session",resource_id=str(new_id),metadata_json={}))
    await db.commit(); _set_session_cookies(response, refresh_token, new_csrf)
    return Token(access_token=create_access_token(user.id,user.role,user.department_id,user.tenant_id))


@router.post("/logout", status_code=204)
async def logout(request: Request, x_csrf_token: str | None = Header(None), db: AsyncSession = Depends(get_db)) -> Response:
    raw=request.cookies.get(REFRESH_COOKIE); csrf=request.cookies.get(CSRF_COOKIE)
    if raw and csrf and x_csrf_token == csrf:
        await db.execute(text("UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at,now()) WHERE token_hash=:token"), {"token":hash_token(raw)}); await db.commit()
    result=Response(status_code=204); result.delete_cookie(REFRESH_COOKIE,path="/api/auth"); result.delete_cookie(CSRF_COOKIE,path="/"); return result


@router.post("/logout-all", status_code=204)
async def logout_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Response:
    await db.execute(text("UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at,now()) WHERE user_id=:uid"), {"uid":user.id})
    db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="auth.logout_all",resource_type="session",metadata_json={}))
    await db.commit(); result=Response(status_code=204); result.delete_cookie(REFRESH_COOKIE,path="/api/auth"); result.delete_cookie(CSRF_COOKIE,path="/"); return result


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserPublic:
    return UserPublic.model_validate(user).model_copy(update={"permissions": await _permissions(db, user)})

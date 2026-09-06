"""Honest SSO configuration status. No OIDC/SAML token exchange is
implemented in this repository — only real, live detection of whether an
operator has actually configured one, so the login page can show an
accurate "not configured" state instead of a broken or fabricated button.
Never returns a client secret."""
from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api/auth/sso", tags=["sso"])


@router.get("/status")
async def sso_status():
    return {
        "oidc": {"configured": settings.oidc_configured, "issuer_url": settings.oidc_issuer_url if settings.oidc_configured else None},
        "saml": {"configured": settings.saml_configured},
    }

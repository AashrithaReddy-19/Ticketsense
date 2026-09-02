from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return HealthResponse(status="ok", database=db_status)


@router.get("/api/health/ready", response_model=HealthResponse)
async def readiness(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    try:
        extension = await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')"))
        revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
        if not extension or not revision:
            raise HTTPException(status_code=503, detail="Required database components are not ready")
        return HealthResponse(status="ready", database="ok")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database is not ready")

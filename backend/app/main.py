from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import router as auth_router
from app.api.decisions import router as decisions_router
from app.api.entities import router as entities_router
from app.api.findings import router as findings_router
from app.api.groups import router as groups_router
from app.api.imports import router as imports_router
from app.api.roles import router as roles_router
from app.core.config import get_settings
from app.db.session import engine, get_db
from app.services.storage import check_storage

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Minimalistic vulnerability management platform. SARIF-only import.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


app.include_router(auth_router)
app.include_router(entities_router)
app.include_router(imports_router)
app.include_router(findings_router)
app.include_router(decisions_router)
app.include_router(groups_router)
app.include_router(roles_router)


@app.get("/api/v1/health", tags=["health"])
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    storage_ok = check_storage()
    return {
        "status": "ok" if db_ok and storage_ok else "degraded",
        "database": "up" if db_ok else "down",
        "storage": "up" if storage_ok else "down",
        "storage_backend": settings.storage_backend,
    }

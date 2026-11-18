from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse

from greenline_api.api.v1.config import router as config_router
from greenline_api.api.v1.eta import router as eta_router
from greenline_api.api.v1.health import router as health_router
from greenline_api.core.config import get_settings
from greenline_api.db.session import dispose_engine
from greenline_api.services.routing import close_routing_client

settings = get_settings()
UI_PATH = Path(__file__).parent / "static" / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Gère le cycle de vie des ressources externes de l’application."""
    yield
    await close_routing_client()
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API de gestion de l’ETA des interventions.",
    lifespan=lifespan,
)
app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(eta_router, prefix=settings.api_v1_prefix)
app.include_router(config_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def eta_tester() -> FileResponse:
    """Sert la page HTML qui permet de tester la carte et le calcul d’ETA."""
    return FileResponse(UI_PATH)

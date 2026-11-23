import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from greenline_api.api.v1.admin import router as admin_router
from greenline_api.api.v1.config import router as config_router
from greenline_api.api.v1.eta import router as eta_router
from greenline_api.api.v1.health import router as health_router
from greenline_api.api.v1.telematics import router as telematics_router
from greenline_api.api.responses import ApiError, ApiResponse
from greenline_api.core.config import get_settings
from greenline_api.db.session import dispose_engine
from greenline_api.services.api_access import init_api_access_schema
from greenline_api.services.hiboo import close_hiboo_client, hiboo_client
from greenline_api.services.routing import close_routing_client

settings = get_settings()
if settings.google_application_credentials:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials

STATIC_PATH = Path(__file__).parent / "static"
TEMPLATE_PATH = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_PATH))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Gère le cycle de vie des ressources externes de l’application."""
    await init_api_access_schema()
    await hiboo_client.load_persisted_cache()
    if settings.hiboo_api_name and settings.hiboo_api_key:
        hiboo_client.start_background_refresh()
    yield
    await close_routing_client()
    await close_hiboo_client()
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API de gestion de l’ETA des interventions.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "La requête n’a pas pu être traitée."
    body = ApiResponse[None](
        message=message,
        errors=[ApiError(code=f"http_{exc.status_code}", message=message)],
        data=None,
        pagination=None,
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        ApiError(
            code=error["type"],
            message=error["msg"],
            field=".".join(str(part) for part in error["loc"]),
        )
        for error in exc.errors()
    ]
    body = ApiResponse[None](
        message="Les données envoyées sont invalides.",
        errors=errors,
        data=None,
        pagination=None,
    )
    return JSONResponse(status_code=422, content=body.model_dump())


@app.exception_handler(Exception)
async def unexpected_exception_handler(_: Request, __: Exception) -> JSONResponse:
    message = "Une erreur interne est survenue."
    body = ApiResponse[None](
        message=message,
        errors=[ApiError(code="internal_server_error", message=message)],
        data=None,
        pagination=None,
    )
    return JSONResponse(status_code=500, content=body.model_dump())


app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(eta_router, prefix=settings.api_v1_prefix)
app.include_router(config_router, prefix=settings.api_v1_prefix)
app.include_router(telematics_router, prefix=settings.api_v1_prefix)
app.include_router(admin_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def eta_tester(request: Request) -> Response:
    """Sert la page qui permet de tester la carte et le calcul d’ETA."""
    return templates.TemplateResponse(
        request=request,
        name="pages/index.html",
        context={"page_section": "Outil de test ETA"},
    )


@app.get("/live", include_in_schema=False)
async def live_eta_tester(request: Request) -> Response:
    """Sert la page de simulation dynamique d’un trajet."""
    return templates.TemplateResponse(
        request=request,
        name="pages/live.html",
        context={"page_section": "Simulation de trajet"},
    )


@app.get("/route-tester", include_in_schema=False)
async def route_tester(request: Request) -> Response:
    """Sert l’interface de géocodification et de test ETA dynamique."""
    return templates.TemplateResponse(
        request=request,
        name="pages/route_tester.html",
        context={"page_section": "Adresses · véhicules · ETA"},
    )


@app.get("/telematics", include_in_schema=False)
async def telematics_tester(request: Request) -> Response:
    """Sert la page de test de la télématique Hiboo."""
    return templates.TemplateResponse(
        request=request,
        name="pages/telematics.html",
        context={"page_section": "Test télématique"},
    )


@app.get("/api-reference", include_in_schema=False)
async def api_reference(request: Request) -> Response:
    """Sert la référence lisible des endpoints de l’API."""
    return templates.TemplateResponse(
        request=request,
        name="pages/api_reference.html",
        context={"page_section": "Référence API"},
    )


@app.get("/token-management", include_in_schema=False)
async def token_management(request: Request) -> Response:
    """Sert l’interface d’administration des tokens et quotas API."""
    return templates.TemplateResponse(
        request=request,
        name="pages/token_management.html",
        context={"page_section": "Gestion des accès API"},
    )

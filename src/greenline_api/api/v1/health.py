from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="État de l’API")
async def health() -> dict[str, str]:
    """Indique que le processus API répond aux requêtes HTTP."""
    return {"status": "ok"}

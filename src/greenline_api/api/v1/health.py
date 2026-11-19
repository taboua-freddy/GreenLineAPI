from fastapi import APIRouter
from pydantic import BaseModel

from greenline_api.api.responses import ApiResponse, ERROR_RESPONSE

router = APIRouter(tags=["health"])


class HealthData(BaseModel):
    status: str


@router.get("/health", summary="État de l’API", responses={500: ERROR_RESPONSE})
async def health() -> ApiResponse[HealthData]:
    """Indique que le processus API répond aux requêtes HTTP."""
    return ApiResponse(
        message="L’API est opérationnelle.",
        errors=[],
        data=HealthData(status="ok"),
        pagination=None,
    )

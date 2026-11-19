from fastapi import APIRouter
from pydantic import BaseModel

from greenline_api.api.responses import ApiResponse, ERROR_RESPONSE
from greenline_api.core.config import get_settings

router = APIRouter(tags=["configuration"])


class PublicConfigData(BaseModel):
    google_maps_api_key: str | None


@router.get(
    "/config",
    summary="Configuration publique de l’interface",
    responses={500: ERROR_RESPONSE},
)
async def public_config() -> ApiResponse[PublicConfigData]:
    """Expose la clé navigateur Maps, qui doit être limitée aux référents du site."""
    return ApiResponse(
        message="Configuration publique récupérée.",
        errors=[],
        data=PublicConfigData(google_maps_api_key=get_settings().google_maps_api_key),
        pagination=None,
    )

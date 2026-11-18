from fastapi import APIRouter

from greenline_api.core.config import get_settings

router = APIRouter(tags=["configuration"])


@router.get("/config", summary="Configuration publique de l’interface")
async def public_config() -> dict[str, str | None]:
    """Expose la clé navigateur Maps, qui doit être limitée aux référents du site."""
    return {"google_maps_api_key": get_settings().google_maps_api_key}

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from greenline_api.api.responses import ERROR_RESPONSE
from greenline_api.db.session import delete_route_map_image, load_route_map_image

router = APIRouter(prefix="/maps", tags=["route-maps"])


@router.get(
    "/{image_id}",
    summary="Télécharger une image de carte temporaire",
    responses={
        200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}},
        404: ERROR_RESPONSE,
        410: ERROR_RESPONSE,
    },
)
async def get_route_map(image_id: str) -> Response:
    """Retourne l’image associée à un lien temporaire, sans exiger de token client."""
    record = await load_route_map_image(image_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Cette image de carte n’existe pas ou a expiré.")

    image, content_type, expires_at = record
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if datetime.now(UTC) >= expires_at:
        await delete_route_map_image(image_id)
        raise HTTPException(status_code=410, detail="Le lien vers cette image de carte a expiré.")

    return Response(
        content=image,
        media_type=content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )

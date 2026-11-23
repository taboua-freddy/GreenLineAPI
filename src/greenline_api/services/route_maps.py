import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx

from greenline_api.core.config import get_settings
from greenline_api.db.session import delete_expired_route_map_images

ROUTE_MAP_TTL = timedelta(minutes=59)
ROUTE_MAP_CLEANUP_INTERVAL_SECONDS = 30
STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"
STATIC_MAPS_MAX_URL_LENGTH = 16_384
logger = logging.getLogger(__name__)


class StaticMapConfigurationError(Exception):
    """La clé d’accès à Google Maps Static API n’est pas configurée."""


class StaticMapError(Exception):
    """Google n’a pas pu produire une image de carte exploitable."""


async def render_route_map(
    *,
    encoded_polyline: str,
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> tuple[bytes, str]:
    """Génère une image PNG du trajet via Google Maps Static API."""
    api_key = get_settings().google_static_maps_api_key
    if not api_key:
        raise StaticMapConfigurationError

    params: list[tuple[str, str]] = [
        ("size", "640x400"),
        ("scale", "2"),
        ("format", "png"),
        ("maptype", "roadmap"),
        ("path", f"weight:5|color:0x147d55FF|enc:{encoded_polyline}"),
        (
            "markers",
            f"color:green|label:D|{origin_latitude},{origin_longitude}",
        ),
        (
            "markers",
            f"color:red|label:A|{destination_latitude},{destination_longitude}",
        ),
        ("key", api_key),
    ]

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            request = client.build_request("GET", STATIC_MAPS_URL, params=params)
            if len(str(request.url)) > STATIC_MAPS_MAX_URL_LENGTH:
                raise StaticMapError("La géométrie du trajet est trop longue pour Google Static Maps.")
            response = await client.send(request)
            response.raise_for_status()
    except StaticMapError:
        raise
    except httpx.HTTPStatusError as exc:
        logger.warning("Google Static Maps a répondu HTTP %s.", exc.response.status_code)
        raise StaticMapError("Google Static Maps a refusé la génération de la carte.") from exc
    except httpx.HTTPError as exc:
        raise StaticMapError("Le service Google Static Maps est indisponible.") from exc

    if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise StaticMapError("Google Static Maps n’a pas renvoyé une image PNG valide.")
    return response.content, "image/png"


async def cleanup_expired_route_maps() -> int:
    """Supprime les images dont la durée de conservation est écoulée."""
    return await delete_expired_route_map_images(datetime.now(UTC))


async def route_map_cleanup_loop() -> None:
    """Purge les images expirées à intervalles courts pendant la vie du serveur."""
    while True:
        try:
            deleted = await cleanup_expired_route_maps()
            if deleted:
                logger.info("%s image(s) de carte expirée(s) supprimée(s).", deleted)
        except Exception:
            logger.exception("La purge des images de carte expirées a échoué.")
        await asyncio.sleep(ROUTE_MAP_CLEANUP_INTERVAL_SECONDS)

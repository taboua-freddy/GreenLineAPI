from functools import lru_cache
from typing import Any

import httpx

from greenline_api.core.config import get_settings

from google.maps import routing_v2

FIELD_MASK = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"


class RouteNotFoundError(Exception):
    """Signale que Google Routes n’a trouvé aucun itinéraire entre les deux points."""


class GeocodingError(Exception):
    """Signale un échec de géocodification ou une adresse introuvable."""


class GeocodingNotFoundError(GeocodingError):
    """Aucun résultat géographique ne correspond à l’adresse demandée."""


class GeocodingConfigurationError(GeocodingError):
    """La clé Google Geocoding n’est pas configurée."""


async def geocode_address(address: str) -> dict[str, Any]:
    """Convertit une adresse en coordonnées avec l’API Google Geocoding."""
    settings = get_settings()
    api_key = settings.google_geocoding_api_key
    if not api_key:
        raise GeocodingConfigurationError("La clé Google Geocoding n’est pas configurée.")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": address, "key": api_key},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GeocodingError("Le service Google Geocoding est indisponible.") from exc

    if not isinstance(payload, dict):
        raise GeocodingError("La réponse Google Geocoding est invalide.")
    status = payload.get("status")
    if status == "ZERO_RESULTS":
        raise GeocodingNotFoundError("Aucun résultat pour cette adresse.")
    if status != "OK":
        message = payload.get("error_message")
        raise GeocodingError(
            str(message) if isinstance(message, str) else "Google Geocoding a refusé la requête."
        )
    results = payload.get("results")
    first = results[0] if isinstance(results, list) and results else None
    geometry = first.get("geometry") if isinstance(first, dict) else None
    location = geometry.get("location") if isinstance(geometry, dict) else None
    if not isinstance(location, dict) or not isinstance(first.get("formatted_address"), str):
        raise GeocodingError("Google Geocoding a renvoyé un résultat incomplet.")
    try:
        latitude, longitude = float(location["lat"]), float(location["lng"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError("Les coordonnées de l’adresse sont invalides.") from exc
    return {
        "formatted_address": first["formatted_address"],
        "latitude": latitude,
        "longitude": longitude,
    }


async def reverse_geocode_coordinates(latitude: float, longitude: float) -> str:
    """Convertit des coordonnées GPS en adresse lisible avec Google Geocoding."""
    api_key = get_settings().google_geocoding_api_key
    if not api_key:
        raise GeocodingConfigurationError("La clé Google Geocoding n’est pas configurée.")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{latitude},{longitude}", "key": api_key},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GeocodingError("Le service Google Geocoding est indisponible.") from exc

    if not isinstance(payload, dict):
        raise GeocodingError("La réponse Google Geocoding est invalide.")
    status = payload.get("status")
    if status == "ZERO_RESULTS":
        raise GeocodingNotFoundError("Aucune adresse trouvée pour ces coordonnées.")
    if status != "OK":
        raise GeocodingError("Google Geocoding a refusé la requête.")
    results = payload.get("results")
    first = results[0] if isinstance(results, list) and results else None
    address = first.get("formatted_address") if isinstance(first, dict) else None
    if not isinstance(address, str) or not address:
        raise GeocodingError("Google Geocoding n’a pas renvoyé d’adresse exploitable.")
    return address


@lru_cache(maxsize=1)
def _get_client() -> routing_v2.RoutesAsyncClient:
    """Crée une seule instance du client asynchrone Google Routes pour le processus."""
    return routing_v2.RoutesAsyncClient()


async def calculate_drive_route(
    *, origin_latitude: float, origin_longitude: float,
    destination_latitude: float, destination_longitude: float,
) -> tuple[float, int, str]:
    """Calcule avec Google la durée, la distance et la géométrie d’un trajet en voiture."""
    request = routing_v2.ComputeRoutesRequest(
        origin=routing_v2.Waypoint(
            location={"lat_lng": {"latitude": origin_latitude, "longitude": origin_longitude}}
        ),
        destination=routing_v2.Waypoint(
            location={"lat_lng": {"latitude": destination_latitude, "longitude": destination_longitude}}
        ),
        travel_mode=routing_v2.RouteTravelMode.DRIVE,
        routing_preference=routing_v2.RoutingPreference.TRAFFIC_AWARE,
    )
    response = await _get_client().compute_routes(
        request=request,
        metadata=(("x-goog-fieldmask", FIELD_MASK),),
    )
    if not response.routes:
        raise RouteNotFoundError

    route = response.routes[0]
    return route.duration.total_seconds(), route.distance_meters, route.polyline.encoded_polyline


async def close_routing_client() -> None:
    """Ferme le client Google Routes s’il a été créé pendant la vie de l’application."""
    if _get_client.cache_info().currsize:
        await _get_client().transport.close()
        _get_client.cache_clear()

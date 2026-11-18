from functools import lru_cache

from google.maps import routing_v2

FIELD_MASK = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"


class RouteNotFoundError(Exception):
    """Signale que Google Routes n’a trouvé aucun itinéraire entre les deux points."""


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

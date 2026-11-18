from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from pydantic import BaseModel, Field

from greenline_api.services.routing import RouteNotFoundError, calculate_drive_route

router = APIRouter(tags=["eta"])


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90, examples=[48.8566])
    longitude: float = Field(ge=-180, le=180, examples=[2.3522])


class EtaRequest(BaseModel):
    origin: Coordinates
    destination: Coordinates


class EtaResponse(BaseModel):
    eta_at: datetime
    duration_seconds: float
    distance_meters: int
    encoded_polyline: str


@router.post("/eta", response_model=EtaResponse, summary="Calculer une ETA routière")
async def calculate_eta(payload: EtaRequest) -> EtaResponse:
    """Calcule l’heure estimée d’arrivée à partir des coordonnées des deux points."""
    try:
        duration_seconds, distance_meters, encoded_polyline = await calculate_drive_route(
            origin_latitude=payload.origin.latitude,
            origin_longitude=payload.origin.longitude,
            destination_latitude=payload.destination.latitude,
            destination_longitude=payload.destination.longitude,
        )
    except DefaultCredentialsError as exc:
        raise HTTPException(
            status_code=503,
            detail="Les identifiants Google Cloud (ADC) ne sont pas configurés.",
        ) from exc
    except RouteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Aucun itinéraire trouvé.") from exc
    except GoogleAPICallError as exc:
        raise HTTPException(
            status_code=502,
            detail="Le calcul d’itinéraire Google a échoué.",
        ) from exc

    return EtaResponse(
        eta_at=datetime.now(UTC) + timedelta(seconds=duration_seconds),
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        encoded_polyline=encoded_polyline,
    )

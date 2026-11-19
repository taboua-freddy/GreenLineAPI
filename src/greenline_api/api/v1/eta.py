import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from pydantic import BaseModel, Field, model_validator

from greenline_api.api.responses import ApiResponse, ERROR_RESPONSE
from greenline_api.services.api_access import require_api_token
from greenline_api.services.hiboo import HibooAPIError, HibooConfigurationError, hiboo_client
from greenline_api.services.routing import (
    GeocodingConfigurationError,
    GeocodingError,
    GeocodingNotFoundError,
    RouteNotFoundError,
    calculate_drive_route,
    geocode_address,
)

router = APIRouter(tags=["eta"], dependencies=[Depends(require_api_token)])


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


class GeocodeRequest(BaseModel):
    address: str = Field(
        min_length=3,
        max_length=500,
        strip_whitespace=True,
        examples=["10 rue de Rivoli, Paris"],
    )


class ResolvedAddress(BaseModel):
    formatted_address: str
    latitude: float
    longitude: float


class LocationInput(BaseModel):
    parc_id: str | None = Field(default=None, examples=["PF-1233"])
    address: str | None = Field(
        default=None,
        min_length=3,
        max_length=500,
        strip_whitespace=True,
        examples=["10 rue de Rivoli, Paris"],
    )

    @model_validator(mode="after")
    def validate_location(self) -> "LocationInput":
        if (self.parc_id is None) == (self.address is None):
            raise ValueError("Renseignez exactement parc_id ou address.")
        if self.parc_id is not None:
            value = self.parc_id.strip().upper()
            prefix, separator, number = value.partition("-")
            if separator != "-" or prefix not in {"PF", "ST", "CO", "ME"} or not number.isdigit():
                raise ValueError("Le parc_id doit respecter le format PF-1233, ST-1233, CO-1233 ou ME-1233.")
            self.parc_id = value
        if self.address is not None:
            self.address = self.address.strip()
            if not self.address:
                raise ValueError("L’adresse ne peut pas être vide.")
        return self


class EtaLocationsRequest(BaseModel):
    origin: LocationInput
    destination: LocationInput


class ResolvedLocation(BaseModel):
    source_type: str
    source: str
    latitude: float
    longitude: float


class EtaLocationsResponse(EtaResponse):
    origin: ResolvedLocation
    destination: ResolvedLocation


async def _resolve_location(location: LocationInput) -> ResolvedLocation:
    if location.address is not None:
        result = await geocode_address(location.address)
        return ResolvedLocation(
            source_type="address",
            source=result["formatted_address"],
            latitude=result["latitude"],
            longitude=result["longitude"],
        )

    parc_id = location.parc_id or ""
    equipment = (await hiboo_client.get_equipments()).get(parc_id)
    if equipment is None:
        raise HTTPException(status_code=422, detail=f"Le véhicule {parc_id} n’est pas équipé (absent de Hiboo).")
    equipment_id = equipment.get("id")
    if not isinstance(equipment_id, int):
        raise HibooAPIError("L’identifiant d’équipement Hiboo est invalide.")
    position = await hiboo_client.get_latest_position(equipment_id)
    if position is None:
        raise HTTPException(status_code=422, detail=f"Aucune position GPS récupérable pour {parc_id}.")
    try:
        coordinates = Coordinates.model_validate(position)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"La position GPS de {parc_id} est invalide.") from exc
    return ResolvedLocation(
        source_type="parc_id",
        source=parc_id,
        latitude=coordinates.latitude,
        longitude=coordinates.longitude,
    )


@router.post(
    "/geocode",
    response_model=ApiResponse[ResolvedAddress],
    summary="Convertir une adresse en coordonnées GPS",
    responses={401: ERROR_RESPONSE, 404: ERROR_RESPONSE, 422: ERROR_RESPONSE, 429: ERROR_RESPONSE, 502: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def geocode(payload: GeocodeRequest) -> ApiResponse[ResolvedAddress]:
    try:
        result = await geocode_address(payload.address.strip())
    except GeocodingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GeocodingConfigurationError as exc:
        raise HTTPException(status_code=503, detail="La clé Google Geocoding n’est pas configurée.") from exc
    except GeocodingError as exc:
        raise HTTPException(status_code=502, detail="La géocodification Google a échoué.") from exc
    return ApiResponse(
        message="Adresse convertie en coordonnées GPS.", errors=[],
        data=ResolvedAddress(**result), pagination=None,
    )


@router.post(
    "/eta/locations",
    response_model=ApiResponse[EtaLocationsResponse],
    summary="Calculer une ETA entre adresses et/ou véhicules",
    responses={401: ERROR_RESPONSE, 404: ERROR_RESPONSE, 422: ERROR_RESPONSE, 429: ERROR_RESPONSE, 502: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def calculate_eta_from_locations(payload: EtaLocationsRequest) -> ApiResponse[EtaLocationsResponse]:
    try:
        origin, destination = await asyncio.gather(
            _resolve_location(payload.origin), _resolve_location(payload.destination)
        )
        duration, distance, polyline = await calculate_drive_route(
            origin_latitude=origin.latitude,
            origin_longitude=origin.longitude,
            destination_latitude=destination.latitude,
            destination_longitude=destination.longitude,
        )
    except DefaultCredentialsError as exc:
        raise HTTPException(status_code=503, detail="Les identifiants Google Cloud (ADC) ne sont pas configurés.") from exc
    except RouteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Aucun itinéraire trouvé.") from exc
    except GoogleAPICallError as exc:
        raise HTTPException(status_code=502, detail="Le calcul d’itinéraire Google a échoué.") from exc
    except GeocodingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GeocodingConfigurationError as exc:
        raise HTTPException(status_code=503, detail="La clé Google Geocoding n’est pas configurée.") from exc
    except GeocodingError as exc:
        raise HTTPException(status_code=502, detail="La géocodification Google a échoué.") from exc
    except (HibooConfigurationError, HibooAPIError) as exc:
        status = 503 if isinstance(exc, HibooConfigurationError) else 502
        message = "Les identifiants Hiboo ne sont pas configurés." if status == 503 else "Le service Hiboo est momentanément indisponible."
        raise HTTPException(status_code=status, detail=message) from exc

    return ApiResponse(
        message="ETA calculée à partir des deux emplacements.", errors=[],
        data=EtaLocationsResponse(
            eta_at=datetime.now(UTC) + timedelta(seconds=duration),
            duration_seconds=duration,
            distance_meters=distance,
            encoded_polyline=polyline,
            origin=origin,
            destination=destination,
        ), pagination=None,
    )


@router.post(
    "/eta",
    response_model=ApiResponse[EtaResponse],
    summary="Calculer une ETA routière",
    responses={
        401: ERROR_RESPONSE,
        404: ERROR_RESPONSE,
        422: ERROR_RESPONSE,
        429: ERROR_RESPONSE,
        500: ERROR_RESPONSE,
        502: ERROR_RESPONSE,
        503: ERROR_RESPONSE,
    },
)
async def calculate_eta(payload: EtaRequest) -> ApiResponse[EtaResponse]:
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

    return ApiResponse(
        message="ETA calculée avec succès.",
        errors=[],
        data=EtaResponse(
            eta_at=datetime.now(UTC) + timedelta(seconds=duration_seconds),
            duration_seconds=duration_seconds,
            distance_meters=distance_meters,
            encoded_polyline=encoded_polyline,
        ),
        pagination=None,
    )

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from greenline_api.api.responses import ApiResponse, ERROR_RESPONSE
from greenline_api.services.api_access import require_api_token
from greenline_api.services.hiboo import (
    HibooAPIError,
    HibooConfigurationError,
    hiboo_client,
)
from greenline_api.services.routing import (
    GeocodingConfigurationError,
    GeocodingError,
    GeocodingNotFoundError,
    reverse_geocode_coordinates,
)

router = APIRouter(
    prefix="/telematics",
    tags=["telematics"],
    dependencies=[Depends(require_api_token)],
)


class ParcIdsRequest(BaseModel):
    parc_id: str | None = Field(default=None, examples=["PF-1233"])
    parc_ids: list[str] | None = Field(
        default=None,
        max_length=100,
        examples=[["PF-1233", "ST-1233"]],
    )

    @model_validator(mode="after")
    def validate_parc_ids(self) -> "ParcIdsRequest":
        if (self.parc_id is None) == (self.parc_ids is None):
            raise ValueError("Renseignez parc_id ou parc_ids.")
        values = [self.parc_id] if self.parc_id is not None else self.parc_ids
        if not values:
            raise ValueError("La liste parc_ids ne peut pas être vide.")
        normalized = [value.strip().upper() for value in values]
        invalid = [parc_id for parc_id in normalized if not _is_valid_parc_id(parc_id)]
        if invalid:
            raise ValueError(
                "Chaque parc_id doit respecter le format PF-1233, ST-1233, CO-1233 ou ME-1233."
            )
        self.parc_id = None
        self.parc_ids = normalized
        return self


def _is_valid_parc_id(parc_id: str) -> bool:
    prefix, separator, number = parc_id.partition("-")
    return separator == "-" and prefix in {"PF", "ST", "CO", "ME"} and number.isdigit()


class TelematicsEquipment(BaseModel):
    parc_id: str
    equipped: bool
    equipment_id: int | None


class TelematicsCheckData(BaseModel):
    vehicles: list[TelematicsEquipment]


class GpsPosition(BaseModel):
    date: datetime | None = None
    latitude: float
    longitude: float
    altitude: float | None = None
    speed: float | None = None
    heading: float | None = None


class VehiclePosition(BaseModel):
    parc_id: str
    equipped: bool
    position: GpsPosition | None


class VehiclePositionsData(BaseModel):
    vehicles: list[VehiclePosition]


class ParcLocationRequest(BaseModel):
    parc_id: str = Field(examples=["PF-1233"])

    @model_validator(mode="after")
    def validate_parc_id(self) -> "ParcLocationRequest":
        self.parc_id = self.parc_id.strip().upper()
        if not _is_valid_parc_id(self.parc_id):
            raise ValueError(
                "Le parc_id doit respecter le format PF-1233, ST-1233, CO-1233 ou ME-1233."
            )
        return self


class ParcLocationData(BaseModel):
    parc_id: str
    equipped: bool
    address: str
    latitude: float
    longitude: float
    position_date: datetime | None


def _as_position(position: dict[str, Any] | None) -> GpsPosition | None:
    if position is None:
        return None
    if "latitude" not in position or "longitude" not in position:
        return None
    try:
        return GpsPosition.model_validate(position)
    except ValueError as exc:
        raise HibooAPIError("Une position Hiboo est invalide.") from exc


def _map_hiboo_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HibooConfigurationError):
        return HTTPException(
            status_code=503,
            detail="Les identifiants Hiboo ne sont pas configurés.",
        )
    return HTTPException(status_code=502, detail="Le service Hiboo est momentanément indisponible.")


@router.post(
    "/check",
    response_model=ApiResponse[TelematicsCheckData],
    summary="Vérifier l’équipement télématique des véhicules",
    responses={
        401: ERROR_RESPONSE,
        422: ERROR_RESPONSE,
        429: ERROR_RESPONSE,
        500: ERROR_RESPONSE,
        502: ERROR_RESPONSE,
        503: ERROR_RESPONSE,
    },
)
async def check_telematics(payload: ParcIdsRequest) -> ApiResponse[TelematicsCheckData]:
    """Indique quels identifiants parc existent dans le parc Hiboo."""
    try:
        equipments = await hiboo_client.get_equipments()
    except (HibooConfigurationError, HibooAPIError) as exc:
        raise _map_hiboo_error(exc) from exc

    vehicles = []
    for parc_id in payload.parc_ids or []:
        equipment = equipments.get(parc_id)
        vehicles.append(
            TelematicsEquipment(
                parc_id=parc_id,
                equipped=equipment is not None,
                equipment_id=equipment.get("id") if equipment else None,
            )
        )
    return ApiResponse(
        message="Vérification télématique effectuée.",
        errors=[],
        data=TelematicsCheckData(vehicles=vehicles),
        pagination=None,
    )


@router.post(
    "/positions",
    response_model=ApiResponse[VehiclePositionsData],
    summary="Récupérer les dernières positions GPS",
    responses={
        401: ERROR_RESPONSE,
        422: ERROR_RESPONSE,
        429: ERROR_RESPONSE,
        500: ERROR_RESPONSE,
        502: ERROR_RESPONSE,
        503: ERROR_RESPONSE,
    },
)
async def latest_positions(payload: ParcIdsRequest) -> ApiResponse[VehiclePositionsData]:
    """Récupère la position la plus récente disponible pour chaque véhicule équipé."""
    try:
        equipments = await hiboo_client.get_equipments()
        semaphore = asyncio.Semaphore(10)

        async def get_vehicle_position(parc_id: str) -> VehiclePosition:
            equipment = equipments.get(parc_id)
            if equipment is None:
                return VehiclePosition(parc_id=parc_id, equipped=False, position=None)
            equipment_id = equipment.get("id")
            if not isinstance(equipment_id, int):
                raise HibooAPIError("L’identifiant d’équipement Hiboo est invalide.")
            async with semaphore:
                raw_position = await hiboo_client.get_latest_position(equipment_id)
            return VehiclePosition(
                parc_id=parc_id,
                equipped=True,
                position=_as_position(raw_position),
            )

        vehicles = await asyncio.gather(
            *(get_vehicle_position(parc_id) for parc_id in payload.parc_ids or [])
        )
    except (HibooConfigurationError, HibooAPIError) as exc:
        raise _map_hiboo_error(exc) from exc

    return ApiResponse(
        message="Dernières positions récupérées.",
        errors=[],
        data=VehiclePositionsData(vehicles=vehicles),
        pagination=None,
    )


@router.post(
    "/location",
    response_model=ApiResponse[ParcLocationData],
    summary="Récupérer l’adresse et les coordonnées d’un véhicule",
    responses={401: ERROR_RESPONSE, 404: ERROR_RESPONSE, 422: ERROR_RESPONSE, 429: ERROR_RESPONSE, 502: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def parc_location(payload: ParcLocationRequest) -> ApiResponse[ParcLocationData]:
    """Récupère le dernier GPS Hiboo puis le convertit en adresse lisible."""
    try:
        equipment = (await hiboo_client.get_equipments()).get(payload.parc_id)
        if equipment is None:
            raise HTTPException(
                status_code=404,
                detail=f"Le véhicule {payload.parc_id} n’est pas équipé en télématique Hiboo.",
            )
        equipment_id = equipment.get("id")
        if not isinstance(equipment_id, int):
            raise HibooAPIError("L’identifiant d’équipement Hiboo est invalide.")
        raw_position = await hiboo_client.get_latest_position(equipment_id)
        position = _as_position(raw_position)
        if position is None:
            raise HTTPException(
                status_code=404,
                detail=f"Aucune position GPS disponible pour {payload.parc_id}.",
            )
        address = await reverse_geocode_coordinates(position.latitude, position.longitude)
    except HTTPException:
        raise
    except (HibooConfigurationError, HibooAPIError) as exc:
        raise _map_hiboo_error(exc) from exc
    except GeocodingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GeocodingConfigurationError as exc:
        raise HTTPException(status_code=503, detail="La clé Google Geocoding n’est pas configurée.") from exc
    except GeocodingError as exc:
        raise HTTPException(status_code=502, detail="La recherche d’adresse à partir du GPS a échoué.") from exc

    return ApiResponse(
        message="Adresse et coordonnées du véhicule récupérées.",
        errors=[],
        data=ParcLocationData(
            parc_id=payload.parc_id,
            equipped=True,
            address=address,
            latitude=position.latitude,
            longitude=position.longitude,
            position_date=position.date,
        ),
        pagination=None,
    )

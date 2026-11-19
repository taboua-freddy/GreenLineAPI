import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from greenline_api.core.config import get_settings
from greenline_api.db.session import load_hiboo_equipment_cache, save_hiboo_equipment_cache

EQUIPMENT_CACHE_TTL = timedelta(days=1)
EQUIPMENT_REFRESH_RETRY_DELAY = timedelta(minutes=5)
TOKEN_CACHE_TTL = timedelta(days=9)
EQUIPMENT_PAGE_SIZE = 50
HIBOO_REQUEST_RETRIES = 3
HIBOO_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
HIBOO_RETRY_BASE_DELAY_SECONDS = 0.5
logger = logging.getLogger(__name__)


class HibooConfigurationError(Exception):
    """Les identifiants Hiboo nécessaires ne sont pas configurés."""


class HibooAPIError(Exception):
    """Une requête vers l’API Hiboo a échoué ou renvoyé un format inattendu."""


class HibooClient:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)
        self._token_lock = asyncio.Lock()
        self._equipment_lock = asyncio.Lock()
        self._equipment_cache: dict[str, dict[str, Any]] | None = None
        self._equipment_expires_at = datetime.min.replace(tzinfo=UTC)
        self._equipment_refresh_task: asyncio.Task[None] | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            settings = get_settings()
            self._http = httpx.AsyncClient(
                base_url=settings.hiboo_api_base_url.rstrip("/"),
                timeout=httpx.Timeout(20.0),
            )
        return self._http

    async def _get_token(self, *, force_refresh: bool = False) -> str:
        settings = get_settings()
        if not settings.hiboo_api_name or not settings.hiboo_api_key:
            raise HibooConfigurationError

        async with self._token_lock:
            now = datetime.now(UTC)
            if force_refresh:
                self._token = None
            if self._token and now < self._token_expires_at:
                return self._token

            client = await self._client()
            try:
                response = await client.post(
                    "/login",
                    json={"name": settings.hiboo_api_name, "apiKey": settings.hiboo_api_key},
                )
                response.raise_for_status()
                payload = response.json()
                token = payload.get("token") if isinstance(payload, dict) else None
                if not isinstance(token, str) or not token:
                    raise HibooAPIError("Réponse de connexion Hiboo invalide.")
            except HibooAPIError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                raise HibooAPIError("La connexion à Hiboo a échoué.") from exc

            self._token = token
            self._token_expires_at = now + TOKEN_CACHE_TTL
            return token

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = await self._client()
        token_refreshed = False
        for attempt in range(HIBOO_REQUEST_RETRIES + 1):
            token = await self._get_token()
            try:
                response = await client.request(
                    method,
                    path,
                    headers={"x-access-token": token},
                    **kwargs,
                )
                if response.status_code == 401 and not token_refreshed:
                    token_refreshed = True
                    await self._get_token(force_refresh=True)
                    continue
                response.raise_for_status()
                payload = response.json()

                if not isinstance(payload, dict):
                    raise HibooAPIError("Réponse Hiboo invalide.")
                return payload
            except HibooAPIError:
                raise
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code not in HIBOO_RETRYABLE_STATUS_CODES or attempt >= HIBOO_REQUEST_RETRIES:
                    raise HibooAPIError(
                        f"Hiboo a répondu HTTP {status_code} pour {exc.request.url}."
                    ) from exc
                delay = HIBOO_RETRY_BASE_DELAY_SECONDS * (2**attempt)
                logger.warning(
                    "Réponse HTTP %s de Hiboo pour %s; nouvel essai dans %.1f s (%s/%s).",
                    status_code,
                    path,
                    delay,
                    attempt + 1,
                    HIBOO_REQUEST_RETRIES,
                )
                await asyncio.sleep(delay)
            except httpx.TransportError as exc:
                if attempt >= HIBOO_REQUEST_RETRIES:
                    raise HibooAPIError("La connexion à Hiboo a échoué après plusieurs tentatives.") from exc
                delay = HIBOO_RETRY_BASE_DELAY_SECONDS * (2**attempt)
                logger.warning(
                    "Erreur réseau vers Hiboo pour %s; nouvel essai dans %.1f s (%s/%s).",
                    path,
                    delay,
                    attempt + 1,
                    HIBOO_REQUEST_RETRIES,
                )
                await asyncio.sleep(delay)
            except ValueError as exc:
                raise HibooAPIError("Hiboo a renvoyé une réponse JSON invalide.") from exc
        raise HibooAPIError("La requête vers Hiboo a échoué après plusieurs tentatives.")

    async def get_equipments(self) -> dict[str, dict[str, Any]]:
        now = datetime.now(UTC)
        if self._equipment_cache is not None:
            settings = get_settings()
            if (
                now >= self._equipment_expires_at
                and settings.hiboo_api_name
                and settings.hiboo_api_key
            ):
                self._schedule_equipment_refresh()
            return self._equipment_cache

        # Cold start: only the first telematics request waits for the initial snapshot.
        return await self._refresh_equipments()

    async def _refresh_equipments(self) -> dict[str, dict[str, Any]]:
        async with self._equipment_lock:
            if self._equipment_cache is not None and datetime.now(UTC) < self._equipment_expires_at:
                return self._equipment_cache

            equipment_by_name: dict[str, dict[str, Any]] = {}
            offset = 0
            total: int | None = None
            while total is None or offset < total:
                print(f"Fetching Hiboo equipments, offset={offset}, total={total}")
                payload = await self._request(
                    "GET",
                    "/v2/fleet/equipments",
                    params={"limit": EQUIPMENT_PAGE_SIZE, "offset": offset},
                )
                data = payload.get("data")
                rows = data.get("rows") if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise HibooAPIError("La liste des équipements Hiboo est invalide.")
                reported_total = data.get("total")
                if not isinstance(reported_total, int) or reported_total < 0:
                    raise HibooAPIError("Le total des équipements Hiboo est invalide.")
                total = reported_total
                for item in rows:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        equipment_by_name[item["name"].strip().upper()] = item
                if not rows:
                    break
                offset += len(rows)

            # Swap the completed snapshot atomically so readers never see a partial list.
            self._equipment_cache = equipment_by_name
            cached_at = datetime.now(UTC)
            self._equipment_expires_at = cached_at + EQUIPMENT_CACHE_TTL
            try:
                await save_hiboo_equipment_cache(equipment_by_name, cached_at)
            except Exception:
                logger.exception("Impossible d’enregistrer l’instantané de la flotte Hiboo en base.")
            return equipment_by_name

    def _schedule_equipment_refresh(self) -> None:
        if self._equipment_refresh_task is None or self._equipment_refresh_task.done():
            self._equipment_refresh_task = asyncio.create_task(self._equipment_refresh_loop())

    async def _equipment_refresh_loop(self) -> None:
        while True:
            now = datetime.now(UTC)
            if self._equipment_cache is not None and now < self._equipment_expires_at:
                delay = (self._equipment_expires_at - now).total_seconds()
                await asyncio.sleep(delay)
            try:
                await self._refresh_equipments()
            except Exception:
                logger.exception("Actualisation de la liste des équipements Hiboo échouée.")
                await asyncio.sleep(EQUIPMENT_REFRESH_RETRY_DELAY.total_seconds())

    async def load_persisted_cache(self) -> None:
        """Restaure l’instantané Hiboo enregistré dans la base configurée."""
        try:
            snapshot = await load_hiboo_equipment_cache()
        except Exception:
            logger.exception("Impossible de charger l’instantané Hiboo enregistré en base.")
            return
        if snapshot is None:
            return

        equipments, cached_at = snapshot
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=UTC)
        self._equipment_cache = equipments
        self._equipment_expires_at = cached_at + EQUIPMENT_CACHE_TTL
        logger.info("Instantané Hiboo restauré depuis la base (%s équipements).", len(equipments))

    def start_background_refresh(self) -> None:
        """Démarre le rafraîchissement périodique de la flotte Hiboo."""
        self._schedule_equipment_refresh()

    async def get_latest_position(self, equipment_id: int) -> dict[str, Any] | None:
        payload = await self._request(
            "GET",
            f"/v2/fleet/equipments/{equipment_id}/positions",
            params={"limit": 1, "offset": 0},
        )
        data = payload.get("data")
        rows = data.get("rows") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise HibooAPIError("Les positions Hiboo sont dans un format inattendu.")
        if not rows or not isinstance(rows[0], dict):
            return None
        return rows[0]

    async def close(self) -> None:
        if self._equipment_refresh_task is not None:
            self._equipment_refresh_task.cancel()
            try:
                await self._equipment_refresh_task
            except asyncio.CancelledError:
                pass
            self._equipment_refresh_task = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._token = None
        self._equipment_cache = None


hiboo_client = HibooClient()


async def close_hiboo_client() -> None:
    await hiboo_client.close()

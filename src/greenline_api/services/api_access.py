import hashlib
import secrets
from datetime import UTC, date, datetime
from hmac import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from greenline_api.core.config import get_settings
from greenline_api.db.access_models import ApiQuotaRecord, ApiTokenRecord, ApiUsageRecord
from greenline_api.db.session import create_access_schema, get_session

API_QUOTA_ENDPOINTS = (
    ("POST", "/api/v1/eta"),
    ("POST", "/api/v1/eta/locations"),
    ("POST", "/api/v1/geocode"),
    ("POST", "/api/v1/telematics/check"),
    ("POST", "/api/v1/telematics/positions"),
)
client_token_header = APIKeyHeader(name="X-API-Token", auto_error=False)
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _client_token(request: Request) -> str | None:
    value = request.headers.get("x-api-token")
    if value:
        return value.strip()
    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() == "bearer" and credential.strip():
        return credential.strip()
    return None


async def require_api_token(
    request: Request,
    api_token: str | None = Depends(client_token_header),
    session: AsyncSession = Depends(get_session),
) -> None:
    token = api_token or _client_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Un token API est requis.")

    record = await session.scalar(
        select(ApiTokenRecord).where(
            ApiTokenRecord.token_hash == _token_hash(token),
            ApiTokenRecord.revoked_at.is_(None),
        )
    )
    if record is None:
        raise HTTPException(status_code=401, detail="Token API invalide ou révoqué.")

    endpoint = request.url.path
    configured_limit = await session.scalar(
        select(ApiQuotaRecord.daily_limit).where(ApiQuotaRecord.endpoint == endpoint)
    )
    if configured_limit is None:
        configured_limit = await session.scalar(
            select(ApiQuotaRecord.daily_limit).where(ApiQuotaRecord.endpoint == "*")
        )
    daily_limit = configured_limit or get_settings().api_daily_limit_default
    today = datetime.now(UTC).date()
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        insert = pg_insert
    elif dialect == "sqlite":
        insert = sqlite_insert
    else:
        raise RuntimeError(f"Dialecte de base non pris en charge pour les quotas : {dialect}.")

    usage_insert = insert(ApiUsageRecord).values(
        token_id=record.id,
        endpoint=endpoint,
        usage_date=today,
        request_count=1,
        rejected_count=0,
    )
    usage_upsert = (
        usage_insert.on_conflict_do_update(
            index_elements=[
                ApiUsageRecord.token_id,
                ApiUsageRecord.endpoint,
                ApiUsageRecord.usage_date,
            ],
            set_={"request_count": ApiUsageRecord.request_count + 1},
            where=ApiUsageRecord.request_count < daily_limit,
        )
        .returning(ApiUsageRecord.request_count)
    )
    accepted = await session.scalar(usage_upsert)
    if accepted is None:
        await session.execute(
            update(ApiUsageRecord)
            .where(
                ApiUsageRecord.token_id == record.id,
                ApiUsageRecord.endpoint == endpoint,
                ApiUsageRecord.usage_date == today,
            )
            .values(rejected_count=ApiUsageRecord.rejected_count + 1)
        )
        await session.commit()
        raise HTTPException(status_code=429, detail="Le quota journalier de cet endpoint est atteint.")

    record.last_used_at = datetime.now(UTC)
    await session.commit()


async def require_admin_token(
    request: Request,
    admin_token: str | None = Depends(admin_token_header),
) -> None:
    expected = get_settings().api_admin_token
    supplied = admin_token or request.headers.get("x-admin-token", "")
    if not expected:
        raise HTTPException(status_code=503, detail="API_ADMIN_TOKEN n’est pas configuré.")
    if not supplied or not compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Token administrateur invalide.")


def create_api_token() -> str:
    return f"gl_{secrets.token_urlsafe(36)}"


def hash_api_token(token: str) -> str:
    return _token_hash(token)


def api_prefix_path(endpoint: str) -> str:
    prefix = get_settings().api_v1_prefix.rstrip("/")
    default_prefix = "/api/v1"
    return f"{prefix}{endpoint.removeprefix(default_prefix)}"


def configured_quota_endpoints() -> list[tuple[str, str]]:
    return [(method, api_prefix_path(endpoint)) for method, endpoint in API_QUOTA_ENDPOINTS]


async def init_api_access_schema() -> None:
    """Crée les tables d’accès API si elles n’existent pas encore."""
    await create_access_schema()


async def summarize_usage(session: AsyncSession, usage_date: date) -> list[dict[str, object]]:
    rows = await session.execute(
        select(
            ApiUsageRecord.token_id,
            ApiTokenRecord.name,
            ApiTokenRecord.token_prefix,
            ApiUsageRecord.endpoint,
            ApiUsageRecord.request_count,
            ApiUsageRecord.rejected_count,
        )
        .join(ApiTokenRecord, ApiTokenRecord.id == ApiUsageRecord.token_id)
        .where(ApiUsageRecord.usage_date == usage_date)
        .order_by(ApiUsageRecord.token_id, ApiUsageRecord.endpoint)
    )
    return [dict(row._mapping) for row in rows]


async def token_usage_today(session: AsyncSession, token_id: int) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(ApiUsageRecord.request_count), 0)).where(
                ApiUsageRecord.token_id == token_id,
                ApiUsageRecord.usage_date == datetime.now(UTC).date(),
            )
        )
        or 0
    )

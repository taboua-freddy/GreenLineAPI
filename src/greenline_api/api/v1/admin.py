from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from greenline_api.api.responses import ApiResponse, ERROR_RESPONSE
from greenline_api.core.config import get_settings
from greenline_api.db.access_models import ApiQuotaRecord, ApiTokenRecord
from greenline_api.db.session import get_session
from greenline_api.services.api_access import (
    configured_quota_endpoints,
    create_api_token,
    hash_api_token,
    require_admin_token,
    summarize_usage,
    token_usage_today,
)

router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    dependencies=[Depends(require_admin_token)],
)


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TokenSummary(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    requests_today: int


class TokenCreated(TokenSummary):
    token: str


class TokenListData(BaseModel):
    tokens: list[TokenSummary]


class CreateTokenData(BaseModel):
    token: TokenCreated


class UsageRow(BaseModel):
    token_id: int
    token_name: str
    token_prefix: str
    endpoint: str
    request_count: int
    rejected_count: int


class UsageData(BaseModel):
    date: date
    rows: list[UsageRow]


class EndpointLimit(BaseModel):
    method: str
    endpoint: str
    limit_override: int | None
    effective_daily_limit: int


class LimitsData(BaseModel):
    default_daily_limit: int
    endpoints: list[EndpointLimit]


class UpdateLimitsRequest(BaseModel):
    default_daily_limit: int = Field(ge=1, le=10_000_000)
    endpoint_limits: dict[str, int | None] = Field(default_factory=dict)


class UpdateLimitsData(BaseModel):
    limits: LimitsData


@router.get(
    "/tokens",
    response_model=ApiResponse[TokenListData],
    summary="Lister les tokens API",
    responses={401: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def list_tokens(
    session: AsyncSession = Depends(get_session),
) -> ApiResponse[TokenListData]:
    records = await session.scalars(select(ApiTokenRecord).order_by(ApiTokenRecord.created_at.desc()))
    tokens = [
        TokenSummary(
            id=record.id,
            name=record.name,
            prefix=record.token_prefix,
            created_at=record.created_at,
            revoked_at=record.revoked_at,
            last_used_at=record.last_used_at,
            requests_today=await token_usage_today(session, record.id),
        )
        for record in records
    ]
    return ApiResponse(
        message="Tokens API récupérés.", errors=[], data=TokenListData(tokens=tokens), pagination=None
    )


@router.post(
    "/tokens",
    response_model=ApiResponse[CreateTokenData],
    summary="Créer un token API",
    status_code=201,
    responses={401: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def create_token(
    payload: CreateTokenRequest,
    session: AsyncSession = Depends(get_session),
) -> ApiResponse[CreateTokenData]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Le nom du token ne peut pas être vide.")
    token_value = create_api_token()
    record = ApiTokenRecord(
        name=name,
        token_prefix=token_value[:12],
        token_hash=hash_api_token(token_value),
        created_at=datetime.now(UTC),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    token = TokenCreated(
        id=record.id,
        name=record.name,
        prefix=record.token_prefix,
        created_at=record.created_at,
        revoked_at=record.revoked_at,
        last_used_at=record.last_used_at,
        requests_today=0,
        token=token_value,
    )
    return ApiResponse(
        message="Token créé. Copiez-le maintenant : il ne sera plus affiché ensuite.",
        errors=[],
        data=CreateTokenData(token=token),
        pagination=None,
    )


@router.post(
    "/tokens/{token_id}/revoke",
    response_model=ApiResponse[TokenSummary],
    summary="Révoquer un token API",
    responses={401: ERROR_RESPONSE, 404: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def revoke_token(
    token_id: int,
    session: AsyncSession = Depends(get_session),
) -> ApiResponse[TokenSummary]:
    record = await session.get(ApiTokenRecord, token_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Token introuvable.")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(record)
    summary = TokenSummary(
        id=record.id,
        name=record.name,
        prefix=record.token_prefix,
        created_at=record.created_at,
        revoked_at=record.revoked_at,
        last_used_at=record.last_used_at,
        requests_today=await token_usage_today(session, record.id),
    )
    return ApiResponse(
        message="Token révoqué.", errors=[], data=summary, pagination=None
    )


@router.get(
    "/usage",
    response_model=ApiResponse[UsageData],
    summary="Consulter l’utilisation journalière",
    responses={401: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def get_usage(
    usage_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse[UsageData]:
    usage_date = usage_date or datetime.now(UTC).date()
    raw_rows = await summarize_usage(session, usage_date)
    rows = [
        UsageRow(
            token_id=int(row["token_id"]),
            token_name=str(row["name"]),
            token_prefix=str(row["token_prefix"]),
            endpoint=str(row["endpoint"]),
            request_count=int(row["request_count"]),
            rejected_count=int(row["rejected_count"]),
        )
        for row in raw_rows
    ]
    return ApiResponse(
        message="Utilisation récupérée.",
        errors=[],
        data=UsageData(date=usage_date, rows=rows),
        pagination=None,
    )


async def _limits_data(session: AsyncSession) -> LimitsData:
    default_limit = await session.scalar(
        select(ApiQuotaRecord.daily_limit).where(ApiQuotaRecord.endpoint == "*")
    )
    default_limit = default_limit or get_settings().api_daily_limit_default
    endpoint_limits = await session.scalars(
        select(ApiQuotaRecord).where(ApiQuotaRecord.endpoint != "*")
    )
    overrides = {row.endpoint: row.daily_limit for row in endpoint_limits}
    endpoints = [
        EndpointLimit(
            method=method,
            endpoint=path,
            limit_override=overrides.get(path),
            effective_daily_limit=overrides.get(path, default_limit),
        )
        for method, path in configured_quota_endpoints()
    ]
    return LimitsData(default_daily_limit=default_limit, endpoints=endpoints)


@router.get(
    "/limits",
    response_model=ApiResponse[LimitsData],
    summary="Consulter les quotas journaliers",
    responses={401: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def get_limits(
    session: AsyncSession = Depends(get_session),
) -> ApiResponse[LimitsData]:
    limits = await _limits_data(session)
    return ApiResponse(message="Quotas récupérés.", errors=[], data=limits, pagination=None)


@router.put(
    "/limits",
    response_model=ApiResponse[UpdateLimitsData],
    summary="Configurer les quotas journaliers",
    responses={401: ERROR_RESPONSE, 422: ERROR_RESPONSE, 503: ERROR_RESPONSE},
)
async def update_limits(
    payload: UpdateLimitsRequest,
    session: AsyncSession = Depends(get_session),
) -> ApiResponse[UpdateLimitsData]:
    allowed_endpoints = {path for _, path in configured_quota_endpoints()}
    unknown = set(payload.endpoint_limits) - allowed_endpoints
    if unknown:
        raise HTTPException(status_code=422, detail=f"Endpoint(s) inconnu(s) : {', '.join(sorted(unknown))}.")
    if any(limit is not None and not 1 <= limit <= 10_000_000 for limit in payload.endpoint_limits.values()):
        raise HTTPException(status_code=422, detail="Chaque quota doit être compris entre 1 et 10 000 000.")

    now = datetime.now(UTC)
    default_record = await session.get(ApiQuotaRecord, "*")
    if default_record is None:
        session.add(ApiQuotaRecord(endpoint="*", daily_limit=payload.default_daily_limit, updated_at=now))
    else:
        default_record.daily_limit = payload.default_daily_limit
        default_record.updated_at = now

    for endpoint, daily_limit in payload.endpoint_limits.items():
        existing = await session.get(ApiQuotaRecord, endpoint)
        if daily_limit is None:
            if existing is not None:
                await session.delete(existing)
        elif existing is None:
            session.add(ApiQuotaRecord(endpoint=endpoint, daily_limit=daily_limit, updated_at=now))
        else:
            existing.daily_limit = daily_limit
            existing.updated_at = now
    await session.commit()
    limits = await _limits_data(session)
    return ApiResponse(
        message="Quotas journaliers mis à jour.",
        errors=[],
        data=UpdateLimitsData(limits=limits),
        pagination=None,
    )



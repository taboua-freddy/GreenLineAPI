from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from greenline_api.db.base import Base


class ApiTokenRecord(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiQuotaRecord(Base):
    __tablename__ = "api_quotas"

    endpoint: Mapped[str] = mapped_column(String(200), primary_key=True)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiUsageRecord(Base):
    __tablename__ = "api_usage"

    token_id: Mapped[int] = mapped_column(ForeignKey("api_tokens.id"), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(200), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class HibooEquipmentCacheRecord(Base):
    __tablename__ = "hiboo_equipment_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipments: Mapped[dict[str, dict[str, Any]]] = mapped_column(JSON, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HibooEquipmentRefreshRecord(Base):
    __tablename__ = "hiboo_equipment_refresh"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipments: Mapped[dict[str, dict[str, Any]]] = mapped_column(JSON, nullable=False)
    next_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

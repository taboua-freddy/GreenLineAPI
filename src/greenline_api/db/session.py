from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from greenline_api.core.config import get_settings

_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Fournit une session asynchrone et la ferme à la fin de la requête."""
    async with _session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Libère les connexions SQLAlchemy à l’arrêt de l’application."""
    await _engine.dispose()


async def create_access_schema() -> None:
    """Crée les tables de gestion des accès API si elles n’existent pas encore."""
    from greenline_api.db.base import Base

    async with _engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def load_hiboo_equipment_cache() -> tuple[dict[str, dict[str, Any]], datetime] | None:
    from greenline_api.db.access_models import HibooEquipmentCacheRecord

    async with _session_factory() as session:
        record = await session.get(HibooEquipmentCacheRecord, 1)
        if record is None:
            return None
        return record.equipments, record.cached_at


async def save_hiboo_equipment_cache(
    equipments: dict[str, dict[str, Any]],
    cached_at: datetime,
) -> None:
    from greenline_api.db.access_models import HibooEquipmentCacheRecord

    async with _session_factory() as session:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            insert = pg_insert
        elif dialect == "sqlite":
            insert = sqlite_insert
        else:
            raise RuntimeError(f"Dialecte de base non pris en charge pour le cache Hiboo : {dialect}.")

        statement = insert(HibooEquipmentCacheRecord).values(
            id=1,
            equipments=equipments,
            cached_at=cached_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[HibooEquipmentCacheRecord.id],
            set_={
                "equipments": statement.excluded.equipments,
                "cached_at": statement.excluded.cached_at,
            },
        )
        await session.execute(statement)
        await session.commit()

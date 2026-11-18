from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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

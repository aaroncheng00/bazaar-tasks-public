from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bazaar_api.config import settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Lazily create the engine on first use, in the running event loop.

    Module-level construction binds the pool to whatever loop is current at
    import time, which breaks when tests run each case on its own loop."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.app_database_url)
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)

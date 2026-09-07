"""SQLAlchemy 2.x engine and session composition over psycopg 3."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from businessos.config import Settings


class Database:
    """Own the process engine/pool and provide operation-scoped sessions."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_pre_ping=True,
        )
        self.sessions = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

    async def readiness(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()

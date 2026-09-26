"""SQLAlchemy 2.x engine and session composition over psycopg 3."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from businessos.config import Settings
from businessos.errors import ConfigurationError


class Database:
    """Own the process engine/pool and provide operation-scoped sessions."""

    def __init__(self, settings: Settings) -> None:
        self._connection_budget = settings.database_connection_budget
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=0,
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

    async def check_connection_budget(self) -> None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT current_setting('max_connections')::int")
            )
            if self._connection_budget > result.scalar_one():
                raise ConfigurationError(
                    "Installation connection budget exceeds PostgreSQL capacity"
                )

    async def close(self) -> None:
        await self.engine.dispose()

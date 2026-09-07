"""SQLAlchemy 2.x engine and session composition over psycopg 3."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from businessos.config import Settings
from businessos.context import TenantContext
from businessos.errors import ConfigurationError


class Database:
    """Own the process engine/pool and provide operation-scoped sessions."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tenant_databases: dict[UUID, Database] = {}
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

    def sessions_for_tenant(self, context: TenantContext) -> async_sessionmaker[AsyncSession]:
        tenant_id = context.tenant_id
        if tenant_id not in self._tenant_databases:
            url = self._settings.tenant_database_urls.get(tenant_id)
            if url is None:
                raise ConfigurationError("No database login configured for trusted tenant")
            if len(self._tenant_databases) >= self._settings.maximum_tenant_pools:
                raise ConfigurationError("Tenant database pool capacity exceeded")
            role = make_url(url).username
            if role is None or role in {"businessos_app", "businessos_ops", "businessos_migrator"}:
                raise ConfigurationError("Tenant database requires a dedicated login")
            settings = self._settings.model_copy(
                update={"database_url": url, "tenant_database_urls": {}}
            )
            self._tenant_databases[tenant_id] = Database(settings)
        return self._tenant_databases[tenant_id].sessions

    async def readiness(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        try:
            for database in self._tenant_databases.values():
                await database.close()
        finally:
            self._tenant_databases.clear()
            await self.engine.dispose()

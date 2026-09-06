"""Framework-owned Alembic discovery and upgrade coordination."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from businessos.modules import ModuleRegistry


class MigrationCoordinator:
    """Combine protected and module-owned revision locations in dependency order."""

    def __init__(
        self,
        modules: ModuleRegistry,
        *,
        config_path: str | Path = "alembic.ini",
        platform_versions: str | Path = "platform/migrations/versions",
    ) -> None:
        self._modules = modules
        self._config_path = Path(config_path)
        self._platform_versions = Path(platform_versions)

    def version_locations(self) -> tuple[Path, ...]:
        locations = [self._platform_versions]
        for registered in self._modules.ordered():
            locations.extend(Path(item) for item in registered.module.manifest.migrations)
        return tuple(locations)

    def configuration(self, database_url: str) -> Config:
        config = Config(str(self._config_path))
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        config.set_main_option(
            "version_locations",
            os.pathsep.join(str(location) for location in self.version_locations()),
        )
        return config

    def upgrade(self, database_url: str, revision: str = "head") -> None:
        command.upgrade(self.configuration(database_url), revision)

    def downgrade(self, database_url: str, revision: str = "base") -> None:
        command.downgrade(self.configuration(database_url), revision)

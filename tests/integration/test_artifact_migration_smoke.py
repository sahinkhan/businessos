import pytest
from scripts import migration_database_smoke as smoke

from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.version import runtime_version


@pytest.mark.integration
@pytest.mark.postgres
def test_complete_artifact_graph_upgrade_and_replay(postgres_migration_database_url: str) -> None:
    modules = tuple(discover_modules())
    registry = ModuleRegistry(
        platform_version=runtime_version(),
        sdk_version="0.1.0",
        approved_artifacts=approved_artifacts_from_operator_inventory(modules),
    )
    for module in modules:
        registry.add(module)
    coordinator = MigrationCoordinator(registry)
    plan = smoke._expected_plan()
    raw_url = postgres_migration_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    coordinator.upgrade(postgres_migration_database_url)
    smoke._verify(raw_url, plan)
    coordinator.plan(postgres_migration_database_url)
    coordinator.downgrade(postgres_migration_database_url, "geography_0002")
    coordinator.upgrade(postgres_migration_database_url)
    smoke._verify(raw_url, plan)
    coordinator.plan(postgres_migration_database_url)
    with pytest.raises(Exception, match="gov_0004 downgrade refused"):
        coordinator.downgrade(postgres_migration_database_url)
    smoke._verify(raw_url, plan)
    coordinator.upgrade(postgres_migration_database_url)
    smoke._verify(raw_url, plan)

"""ADR-024 exact admitted compatibility capture, without caller-selected subsets."""

from dataclasses import replace

import pytest
from businessos_metadata.ui_provenance import CompatibilityMember, capture_members

from businessos.activation import ContributionGeneration
from businessos.config import Settings
from tests.unit.test_phase5d_ui import extension, sources


def test_capture_complete_sources_and_dependencies_not_every_locked_module() -> None:
    base = tuple(
        replace(
            source,
            dependency_generations=(ContributionGeneration("foundation.audit", 3),),
        )
        for source in sources()
    )
    partner = replace(
        extension(),
        dependency_generations=(ContributionGeneration("foundation.party", 1),),
    )
    locked = (
        CompatibilityMember("unrelated.module", "ignored", 1),
        CompatibilityMember("foundation.party", "Opaque/É", 4),
        CompatibilityMember("example.partner", "exact-identity", 2),
        CompatibilityMember("foundation.audit", "audit-identity", 7),
    )
    expected = (locked[2], locked[3], locked[1])
    assert capture_members((*base, partner), locked) == expected
    assert capture_members((partner, *reversed(base)), tuple(reversed(locked))) == expected


@pytest.mark.parametrize("generation", [0, -1, 2**63, True, 1.0])
def test_capture_rejects_non_bigint_generation(generation: int) -> None:
    with pytest.raises(ValueError, match="durable compatibility identity"):
        capture_members(sources(), (CompatibilityMember("foundation.party", "exact", generation),))


@pytest.mark.parametrize("module_id", [" Foundation.party", "Foundation.party", "x", "a/party"])
def test_capture_rejects_noncanonical_ids(module_id: str) -> None:
    with pytest.raises(ValueError, match="durable compatibility identity"):
        capture_members(sources(), (CompatibilityMember(module_id, "exact", 1),))


def test_capture_rejects_missing_dependency_and_duplicate_rows() -> None:
    member = CompatibilityMember("foundation.party", "exact", 1)
    base = replace(
        sources()[0], dependency_generations=(ContributionGeneration("foundation.audit", 2),)
    )
    with pytest.raises(ValueError, match="Missing admitted"):
        capture_members((base,), (member,))
    with pytest.raises(ValueError, match="durable compatibility identity"):
        capture_members(sources(), (member, member))


def test_capture_rejects_conflicting_admission_generations() -> None:
    base = sources()[0]
    conflicting = replace(base, generation=ContributionGeneration("foundation.party", 2))
    with pytest.raises(ValueError, match="Conflicting admitted"):
        capture_members((base, conflicting), (CompatibilityMember("foundation.party", "exact", 1),))


def test_capture_rejects_over_budget_union() -> None:
    base = replace(
        sources()[0],
        dependency_generations=tuple(
            ContributionGeneration(f"example.m{x}", 1) for x in range(128)
        ),
    )
    with pytest.raises(ValueError, match="budget"):
        capture_members((base,), ())


def test_private_profile_configuration_is_separate_redacted_and_budgeted() -> None:
    ordinary = "postgresql+psycopg://businessos_app:ordinary@localhost:5432/test"
    private = "postgresql+psycopg://businessos_ui_publication:secret-canary@localhost:5432/test"
    settings = Settings(database_url=ordinary, ui_publication_database_url=private)
    assert "secret-canary" not in repr(settings)
    assert "ui_publication_database_url" not in settings.model_dump()
    assert Settings(database_url=ordinary).ui_publication_database_url is None
    with pytest.raises(ValueError, match="connection budget"):
        Settings(
            database_url=ordinary,
            ui_publication_database_url=private,
            database_connection_budget=23,
        )
    for invalid in (
        private.replace("businessos_ui_publication", "businessos_metadata"),
        private.replace("localhost", "other-host"),
        private.replace("/test", "/other"),
        private + "?options=-c%20role%3Dbusinessos_migrator",
    ):
        with pytest.raises(ValueError, match="dedicated same-database profile"):
            Settings(database_url=ordinary, ui_publication_database_url=invalid)

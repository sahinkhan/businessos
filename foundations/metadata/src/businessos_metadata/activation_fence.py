"""Metadata-owned PostgreSQL fence for module and publication compatibility."""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from businessos.sdk import ConfigurationError, UnitOfWork

from .models import MODULE_FENCE

InstallationTransaction = Callable[[], AbstractAsyncContextManager[UnitOfWork]]


class MetadataActivationFence:
    """Module activation and Metadata publish lock the same authoritative rows.

    A changed artifact cannot activate while any published definition pins its
    old generation. This deliberately conservative Phase 5A compatibility rule
    permits a later certified upgrade preflight without allowing an unchecked
    activation today.
    """

    def __init__(self, factory: InstallationTransaction) -> None:
        self._factory = factory

    @asynccontextmanager
    async def activation(self, module_id: str, artifact_identity: str) -> AsyncGenerator[None]:
        if not module_id or not artifact_identity:
            raise ConfigurationError("Module activation identity is required")
        async with self._factory() as uow:
            persistence = uow.persistence
            await persistence.execute(
                insert(MODULE_FENCE)
                .values(
                    module_id=module_id,
                    artifact_identity=artifact_identity,
                    generation=1,
                    active_bindings=0,
                )
                .on_conflict_do_nothing(index_elements=["module_id"])
            )
            row = (
                (
                    await persistence.execute(
                        select(MODULE_FENCE)
                        .where(MODULE_FENCE.c.module_id == module_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            if row["artifact_identity"] != artifact_identity:
                if row["active_bindings"]:
                    raise ConfigurationError(
                        "Module artifact change conflicts with active Metadata revisions"
                    )
                await persistence.execute(
                    update(MODULE_FENCE)
                    .where(MODULE_FENCE.c.module_id == module_id)
                    .values(
                        artifact_identity=artifact_identity,
                        generation=row["generation"] + 1,
                    )
                )
            yield
            await uow.commit()

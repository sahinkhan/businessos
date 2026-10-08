"""Metadata-owned PostgreSQL fence for module and publication compatibility."""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy import select, text, update
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

    def __init__(
        self,
        factory: InstallationTransaction,
        read_factory: InstallationTransaction | None = None,
    ) -> None:
        self._factory = factory
        self._read_factory = read_factory

    @asynccontextmanager
    async def activation(self, module_id: str, artifact_identity: str) -> AsyncGenerator[int]:
        if not module_id or not artifact_identity:
            raise ConfigurationError("Module activation identity is required")
        # A restart at an already admitted artifact needs no issuance credential.
        # Retain the compatibility key through activation. A missing/changed
        # identity takes the private lifecycle writer below and rechecks it there.
        if self._read_factory is not None:
            async with self._read_factory() as existing:
                await existing.persistence.execute(text("SET LOCAL lock_timeout = '5s'"))
                current = (
                    await existing.persistence.execute(
                        select(MODULE_FENCE.c.artifact_identity, MODULE_FENCE.c.generation)
                        .where(MODULE_FENCE.c.module_id == module_id)
                        .with_for_update(read=True, key_share=True)
                    )
                ).one_or_none()
                if current is not None and current.artifact_identity == artifact_identity:
                    yield current.generation
                    await existing.commit()
                    return
        async with self._factory() as uow:
            persistence = uow.persistence
            await persistence.execute(text("SET LOCAL lock_timeout = '5s'"))
            await persistence.execute(
                insert(MODULE_FENCE)
                .values(
                    module_id=module_id,
                    artifact_identity=artifact_identity,
                    generation=1,
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
                durable_generation = row["generation"] + 1
            else:
                durable_generation = row["generation"]
            yield durable_generation
            await uow.commit()

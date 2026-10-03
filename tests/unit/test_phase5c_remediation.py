"""Frozen-consumer coexistence and bounded admission cancellation proofs."""

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_metadata import CustomEntityDefinitionSnapshot
from businessos_metadata.contracts import (
    DefinitionKind,
    DefinitionSnapshot,
    FieldDefinition,
    FieldType,
)
from businessos_metadata.module import CreateCustomEntityDefinition, CreateDefinition
from pydantic import ValidationError

from businessos.database_admission import internal_database_admission
from businessos.errors import ConfigurationError, ProtectedDatabaseCapacityError
from tests.fixtures import phase5a_v1_contracts as frozen


def test_frozen_v1_consumer_and_dedicated_surface() -> None:
    assert [v.value for v in DefinitionKind] == ["field_set", "reference_set"]
    assert [v.value for v in frozen.DefinitionKind] == [v.value for v in DefinitionKind]
    assert (
        Path("foundations/metadata/src/businessos_metadata/contracts.py").read_bytes()
        == Path("tests/fixtures/phase5a_v1_contracts.py").read_bytes()
    )
    field = FieldDefinition(field_id=uuid4(), name="label", value_type=FieldType.TEXT)
    for kind in DefinitionKind:
        current = DefinitionSnapshot(kind=kind, fields=(field,))
        assert (
            frozen.DefinitionSnapshot.model_validate_json(current.model_dump_json()).digest()
            == current.digest()
        )
    custom = CustomEntityDefinitionSnapshot(fields=(field,))
    assert custom.fields[0] is field
    with pytest.raises(ValidationError):
        frozen.DefinitionSnapshot.model_validate_json(custom.model_dump_json())
    with pytest.raises(ValidationError):
        CreateDefinition.model_validate(
            dict(
                resource_namespace="foundation.metadata.custom_entity",
                owner_contract_version="1",
                kind="custom_entity",
                snapshot=custom.model_dump(),
            )
        )
    assert CreateCustomEntityDefinition(snapshot=custom).snapshot == custom
    with pytest.raises(ValidationError):
        CreateCustomEntityDefinition(contract_version="2.0", snapshot=custom)


@pytest.mark.asyncio
async def test_admission_fifo_cancellation_independence_and_cleanup() -> None:
    gate = cast(Any, internal_database_admission(timeout=1))
    gate._limit = 4
    entered, release = asyncio.Event(), asyncio.Event()
    order: list[int] = []

    async def first() -> None:
        async with gate.admit(frozenset({"tenant-a:row-x"})):
            entered.set()
            await release.wait()

    async def waiter(index: int) -> None:
        async with gate.admit(frozenset({"tenant-a:row-x"})):
            order.append(index)

    holder = asyncio.create_task(first())
    await entered.wait()
    waiters = [asyncio.create_task(waiter(i)) for i in range(3)]
    async with gate._condition:
        await gate._condition.wait_for(lambda: len(gate._tickets) == 4)
    with pytest.raises(ProtectedDatabaseCapacityError):
        async with gate.admit(frozenset({"tenant-b:row-y"})):
            pytest.fail("Bounded queue must reject excess admission")
    waiters[1].cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiters[1]
    async with gate.admit(frozenset({"tenant-a:row-y", "tenant-b:row-x"})):
        assert not order
    release.set()
    await asyncio.wait_for(asyncio.gather(holder, waiters[0], waiters[2]), 1)
    assert order == [0, 2]
    assert not gate._tickets
    with pytest.raises(RuntimeError):
        async with gate.admit(frozenset({"tenant-a:row-x"})):
            raise RuntimeError("transaction failed")
    assert not gate._tickets


@pytest.mark.asyncio
async def test_admission_timeout_recovers_and_close_wakes_waiters() -> None:
    gate = cast(Any, internal_database_admission(timeout=0.01))
    async with gate.admit(frozenset({"x"})):
        with pytest.raises(ProtectedDatabaseCapacityError):
            async with gate.admit(frozenset({"x"})):
                pytest.fail("Contended admission entered")
        async with gate.admit(frozenset({"unrelated"})):
            pass
    assert not gate._tickets
    async with gate.admit(frozenset({"x"})):
        gate._timeout = 10
        waiter = asyncio.create_task(_enter(gate))
        async with gate._condition:
            await gate._condition.wait_for(lambda: len(gate._tickets) == 2)
        await gate.close()
        with pytest.raises(ConfigurationError):
            await asyncio.wait_for(waiter, 1)
    assert not gate._tickets


async def _enter(gate: Any) -> None:
    async with gate.admit(frozenset({"x"})):
        pass

"""Atomic owner-generation admission for runtime contributions."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum

from businessos.errors import ConfigurationError, NotFoundError


class ContributionState(StrEnum):
    STAGED = "staged"
    ACTIVE = "active"
    DRAINING = "draining"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class ContributionGeneration:
    """Opaque identity for one module activation attempt."""

    owner: str
    number: int


@dataclass(slots=True)
class _GenerationState:
    lifecycle: ContributionState
    in_flight: int
    drained: asyncio.Event


class ContributionGate:
    """Publish a complete module generation with one event-loop-atomic state change."""

    def __init__(self) -> None:
        self._next_generation: dict[str, int] = {}
        self._states: dict[ContributionGeneration, _GenerationState] = {}
        self._retired: set[str] = set()

    def reserve(self, owner: str) -> ContributionGeneration:
        if owner in self._retired:
            raise ConfigurationError(f"Retired module cannot be activated: {owner}")
        number = self._next_generation.get(owner, 0) + 1
        self._next_generation[owner] = number
        generation = ContributionGeneration(owner, number)
        drained = asyncio.Event()
        drained.set()
        self._states[generation] = _GenerationState(
            lifecycle=ContributionState.STAGED,
            in_flight=0,
            drained=drained,
        )
        return generation

    def publish(self, generation: ContributionGeneration) -> None:
        state = self._state(generation)
        if generation.owner in self._retired:
            raise ConfigurationError(
                f"Retired module cannot publish contributions: {generation.owner}"
            )
        state.lifecycle = ContributionState.ACTIVE

    def is_active(self, generation: ContributionGeneration | None) -> bool:
        if generation is None:
            return True
        state = self._states.get(generation)
        return bool(state is not None and state.lifecycle is ContributionState.ACTIVE)

    def state(self, generation: ContributionGeneration) -> ContributionState:
        return self._state(generation).lifecycle

    @asynccontextmanager
    async def admit(self, generation: ContributionGeneration | None) -> AsyncGenerator[None]:
        if generation is None:
            yield
            return
        state = self._states.get(generation)
        if state is None or state.lifecycle is not ContributionState.ACTIVE:
            raise NotFoundError("Module contribution is not active")
        state.in_flight += 1
        state.drained.clear()
        try:
            yield
        finally:
            state.in_flight -= 1
            if state.in_flight == 0:
                state.drained.set()

    async def close_and_drain(
        self,
        generation: ContributionGeneration,
        *,
        timeout_seconds: float,
    ) -> None:
        state = self._state(generation)
        state.lifecycle = ContributionState.DRAINING
        async with asyncio.timeout(timeout_seconds):
            await state.drained.wait()
        state.lifecycle = ContributionState.INACTIVE

    def discard(self, generation: ContributionGeneration) -> None:
        state = self._states.get(generation)
        if state is not None and state.in_flight:
            raise ConfigurationError(
                f"Cannot discard in-flight module generation: {generation.owner}"
            )
        self._states.pop(generation, None)

    def retire(self, owner: str) -> None:
        if any(
            generation.owner == owner and state.in_flight
            for generation, state in self._states.items()
        ):
            raise ConfigurationError(f"Cannot retire module with in-flight work: {owner}")
        self._retired.add(owner)

    def in_flight(self, generation: ContributionGeneration) -> int:
        return self._state(generation).in_flight

    def _state(self, generation: ContributionGeneration) -> _GenerationState:
        state = self._states.get(generation)
        if state is None:
            raise ConfigurationError(
                f"Unknown module contribution generation: {generation.owner}/{generation.number}"
            )
        return state

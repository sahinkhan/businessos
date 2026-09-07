"""Public application contract registry."""

from typing import Protocol

from businessos.activation import ContributionGate
from businessos.registry import OwnedRegistry


class PublicContract(Protocol):
    @property
    def version(self) -> str: ...


class ContractRegistry(OwnedRegistry[PublicContract]):
    def __init__(self, gate: ContributionGate | None = None) -> None:
        super().__init__("contract", gate)
